import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import checklist, emissao, escalas
from app import pdf as pdf_mod
from app import repo_catalogo as rcat
from app import repo_clientes as rcli
from app import repo_propostas as rp
from app.datas import parse_data, parse_hora_24
from app.sentinelas import A_COMBINAR, A_INFORMAR, marcado
from app.db import conn_dep
from app.moeda import parse_brl, parse_percentual
from app.web import templates

router = APIRouter()


def _proposta_ou_404(conn: sqlite3.Connection, pid: int) -> sqlite3.Row:
    prop = rp.obter_proposta(conn, pid)
    if prop is None:
        raise HTTPException(404, "Proposta não encontrada")
    return prop


ETAPAS = ["cliente", "local", "servicos", "custos", "pagamento", "revisao"]


def _resumo(conn, prop, dados: dict) -> dict:
    cliente = rcli.obter_cliente(conn, prop["cliente_id"]) if prop["cliente_id"] else None
    linhas = rp.linhas_da_proposta(conn, prop["id"])
    return {
        "cliente": cliente["razao_social"] if cliente else "",
        "data": dados.get("data_inicio") or dados.get("data_evento") or "",
        "duracao_meses": dados.get("duracao_meses") or "",
        # rascunho anterior ao menu de escalas é 12x36
        "escala_nome": (dados.get("escala_nome") or "12x36") if prop["tipo"] == "continuo" else "",
        "profissionais": sum(l["quantidade"] for l in linhas if l["categoria"] == "mao_de_obra"),
        "total_centavos": rp.total_proposta(conn, prop["id"]),
    }


def _ctx_wizard(conn, prop, etapa: str) -> dict:
    dados = rp.dados_de(prop)
    return {"prop": prop, "dados": dados, "etapas": ETAPAS, "etapa": etapa,
            "estados": checklist.estado_etapas(checklist.avaliar(conn, prop["id"]), ETAPAS, etapa),
            "resumo": _resumo(conn, prop, dados),
            # Custos e Revisão usam a largura toda (painel e prévia próprios)
            "sem_lateral": etapa in ("custos", "revisao")}


@router.get("/")
def home(request: Request, conn=Depends(conn_dep)):
    recentes = rp.listar_propostas(conn)[:5]
    return templates.TemplateResponse(request, "home.html", {"recentes": recentes})


@router.get("/propostas")
def lista(request: Request, q: str = "", status: str = "", tipo: str = "",
          conn=Depends(conn_dep)):
    return templates.TemplateResponse(request, "propostas_lista.html", {
        "propostas": rp.listar_propostas(conn, q, status, tipo),
        "q": q, "status": status, "tipo": tipo,
        "nao_arquivadas": rp.contar_nao_arquivadas(conn),
    })


@router.post("/propostas/nova")
def nova(tipo: str = Form(...), conn=Depends(conn_dep)):
    if tipo not in ("continuo", "evento"):
        raise HTTPException(422, "Tipo inválido")
    pid = rp.criar_proposta(conn, tipo)
    return RedirectResponse(f"/propostas/{pid}/cliente", status_code=303)


@router.post("/propostas/{pid}/duplicar")
def duplicar(pid: int, conn=Depends(conn_dep)):
    _proposta_ou_404(conn, pid)
    novo = rp.duplicar_proposta(conn, pid)
    return RedirectResponse(f"/propostas/{novo}/cliente", status_code=303)


@router.get("/propostas/{pid}/cliente")
def etapa_cliente(request: Request, pid: int, q: str = "", conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    ctx = _ctx_wizard(conn, prop, "cliente")
    ctx.update({"clientes": rcli.buscar_clientes(conn, q), "q": q, "erro": None})
    return templates.TemplateResponse(request, "etapa_cliente.html", ctx)


@router.post("/propostas/{pid}/cliente")
def escolher_cliente(pid: int, cliente_id: int = Form(...), conn=Depends(conn_dep)):
    _proposta_ou_404(conn, pid)
    rp.definir_cliente(conn, pid, cliente_id)
    return RedirectResponse(f"/propostas/{pid}/local", status_code=303)


@router.post("/propostas/{pid}/cliente/novo")
def criar_cliente_e_vincular(
    request: Request, pid: int,
    razao_social: str = Form(...), cnpj: str = Form(...), endereco: str = Form(...),
    email: str = Form(""), telefone: str = Form(""), conn=Depends(conn_dep),
):
    prop = _proposta_ou_404(conn, pid)
    try:
        cid = rcli.criar_cliente(conn, razao_social, cnpj, endereco, email, telefone)
    except ValueError as exc:
        ctx = _ctx_wizard(conn, prop, "cliente")
        ctx.update({"clientes": rcli.buscar_clientes(conn), "q": "", "erro": str(exc)})
        return templates.TemplateResponse(request, "etapa_cliente.html", ctx)
    rp.definir_cliente(conn, pid, cid)
    return RedirectResponse(f"/propostas/{pid}/local", status_code=303)


@router.get("/propostas/{pid}/local")
def etapa_local(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    ctx = _ctx_wizard(conn, prop, "local")
    ctx["cliente"] = rcli.obter_cliente(conn, prop["cliente_id"]) if prop["cliente_id"] else None
    ctx["erro"] = None
    return templates.TemplateResponse(request, "etapa_local.html", ctx)


def _campos_local(tipo: str) -> list[str]:
    if tipo == "continuo":
        return ["descricao_local", "endereco_servico", "duracao_meses", "data_inicio"]
    return ["nome_evento", "endereco_servico", "data_evento", "hora_inicio", "hora_fim"]


def _erro_validacao_local(tipo: str, dados: dict) -> str | None:
    """Valida e normaliza datas/horas para ISO em `dados` (in-place)."""
    if not dados.get("endereco_servico"):
        return "Endereço é obrigatório."
    if tipo == "continuo":
        if dados.get("duracao_meses") != A_INFORMAR:
            try:
                if int(dados.get("duracao_meses") or "") <= 0:
                    return "Duração em meses inválida."
            except ValueError:
                return "Duração em meses inválida."
        if dados.get("data_inicio") != A_INFORMAR:
            try:
                dados["data_inicio"] = parse_data(dados.get("data_inicio", ""))
            except ValueError:
                return "Data de início inválida - use dd/mm/aaaa."
    else:
        try:
            dados["data_evento"] = parse_data(dados.get("data_evento", ""))
        except ValueError:
            return "Data do evento inválida - use dd/mm/aaaa."
        for campo, rotulo in [("hora_inicio", "Horário de início"), ("hora_fim", "Horário de término")]:
            try:
                dados[campo] = parse_hora_24(dados.get(campo, ""))
            except ValueError:
                return f"{rotulo} inválido - use HH:MM (24h)."
    return None


@router.post("/propostas/{pid}/local")
async def salvar_local(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    form = await request.form()
    campos = _campos_local(prop["tipo"])
    dados = {c: str(form.get(c, "")).strip() for c in campos}
    for campo in ("endereco_servico", "duracao_meses", "data_inicio"):
        if campo in dados and marcado(form, campo):
            dados[campo] = A_INFORMAR  # marcado vale mais que o texto digitado
    erro = _erro_validacao_local(prop["tipo"], dados)
    if erro:
        ctx = _ctx_wizard(conn, prop, "local")
        ctx["dados"] = {**ctx["dados"], **dados}
        ctx["cliente"] = rcli.obter_cliente(conn, prop["cliente_id"]) if prop["cliente_id"] else None
        ctx["erro"] = erro
        return templates.TemplateResponse(request, "etapa_local.html", ctx)
    rp.atualizar_dados(conn, pid, dados)
    return RedirectResponse(f"/propostas/{pid}/servicos", status_code=303)


def _campos_servicos(tipo: str) -> list[str]:
    """Campos livres da etapa; os da escala (contínuo) vêm de escalas.ler_form_escala."""
    if tipo == "continuo":
        return ["trajes", "observacoes"]
    return ["trajes", "comunicacao", "observacoes"]


def _escala_escolhida(conn, bruto, dados: dict) -> sqlite3.Row:
    """Escala do formulário/query; senão a gravada na proposta; senão 12x36 (legado)."""
    for candidato in (bruto, dados.get("escala_id")):
        if candidato in (None, ""):
            continue
        try:
            escala = rcat.obter_escala(conn, int(candidato))
        except ValueError:
            escala = None
        if escala is None:
            raise HTTPException(422, "Escala inválida")
        return escala
    return rcat.escala_padrao(conn)


def _erro_validacao_qtds(conn, tipo: str, form) -> str | None:
    for funcao in rcat.listar_funcoes(conn, tipo=tipo):
        valor = str(form.get(f"qtd_{funcao['id']}", "")).strip()
        if not valor:
            continue
        try:
            if int(valor) < 0:
                raise ValueError
        except ValueError:
            return f"Quantidade inválida para {funcao['nome']}."
    return None


def _escala_id_gravada(conn, dados: dict) -> str:
    """Escala em vigor no rascunho; sem escala_id (legado) é a 12x36 padrão."""
    return str(dados.get("escala_id") or rcat.escala_padrao(conn)["id"])


def _ctx_servicos(conn, prop, escala, dados: dict, form=None) -> dict:
    ctx = _ctx_wizard(conn, prop, "servicos")
    ctx["dados"] = dados
    ctx["funcoes"] = rcat.listar_funcoes(conn, tipo=prop["tipo"])
    ctx["escalas"] = rcat.listar_escalas(conn)
    ctx["escala"] = escala
    ctx["dias_semana"] = escalas.DIAS_SEMANA
    ctx["dias"] = escalas.dias_para_form(dados=dados, form=form)
    # Dias/mês: o gravado vale só para a mesma escala; ao trocar, sugere o da nova
    mesma = escala is not None and _escala_id_gravada(conn, dados) == str(escala["id"])
    ctx["dias_mes"] = (dados.get("plantoes_mes") if mesma or form is not None else None) \
        or (escala["dias_mes"] if escala is not None else "") or ""
    ctx["erro"] = None
    return ctx


@router.get("/propostas/{pid}/servicos")
def etapa_servicos(request: Request, pid: int, escala_id: str = "", conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    dados = rp.dados_de(prop)
    escala = _escala_escolhida(conn, escala_id, dados) if prop["tipo"] == "continuo" else None
    ctx = _ctx_servicos(conn, prop, escala, dados)
    ctx["qtd_atuais"] = {
        l["funcao_id"]: l["quantidade"]
        for l in rp.linhas_da_proposta(conn, pid)
        if l["categoria"] == "mao_de_obra" and l["funcao_id"]
    }
    # Troca de escala via hx-get manda as quantidades digitadas (hx-include)
    for nome, valor in request.query_params.items():
        if nome.startswith("qtd_") and nome[4:].isdigit():
            ctx["qtd_atuais"][int(nome[4:])] = valor
    return templates.TemplateResponse(request, "etapa_servicos.html", ctx)


@router.post("/propostas/{pid}/servicos")
async def salvar_servicos(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    form = await request.form()
    tipo = prop["tipo"]
    dados_anteriores = rp.dados_de(prop)
    dados_form = {c: str(form.get(c, "")).strip() for c in _campos_servicos(tipo)}
    erro, escala = None, None
    if tipo == "continuo":
        escala = _escala_escolhida(conn, form.get("escala_id"), dados_anteriores)
        dados_escala, erro = escalas.ler_form_escala(escala, form)
        dados_form.update(dados_escala)
    erro = erro or _erro_validacao_qtds(conn, tipo, form)
    if erro:
        # Re-exibe o texto digitado, inclusive o que não passou na validação
        brutos = {c: str(form.get(c, "")).strip() for c in
                  ("hora_inicio_turno", "hora_fim_turno", "plantoes_mes", "valor_diaria")}
        ctx = _ctx_servicos(conn, prop, escala,
                            {**dados_anteriores, **dados_form, **brutos,
                             "valor_diaria_centavos": None},
                            form=form)
        ctx["qtd_atuais"] = {}
        for funcao in ctx["funcoes"]:
            bruto = form.get(f"qtd_{funcao['id']}")
            if bruto is not None:
                ctx["qtd_atuais"][funcao["id"]] = bruto
        ctx["erro"] = erro
        return templates.TemplateResponse(request, "etapa_servicos.html", ctx)
    rp.atualizar_dados(conn, pid, dados_form)
    prop = rp.obter_proposta(conn, pid)
    dados = rp.dados_de(prop)
    params = rcat.params_vigentes(conn)

    linhas_mo = [l for l in rp.linhas_da_proposta(conn, pid) if l["categoria"] == "mao_de_obra"]
    # Override feito sob outra escala ou outro modo de preço não vale no novo
    # (seria preço de outra cobertura, silencioso): a troca volta as linhas ao sugerido
    trocou = tipo == "continuo" and (
        _escala_id_gravada(conn, dados) != _escala_id_gravada(conn, dados_anteriores)
        or escalas.modo_de(dados) != escalas.modo_de(dados_anteriores))
    if trocou:
        for linha in linhas_mo:
            if linha["sobrescrito"]:
                rp.restaurar_linha(conn, linha["id"])
        linhas_mo = [l for l in rp.linhas_da_proposta(conn, pid) if l["categoria"] == "mao_de_obra"]

    # upsert por funcao_id: preserva override de linhas já existentes em vez de
    # apagar e recriar (o que perderia silenciosamente qualquer valor sobrescrito)
    existentes = {l["funcao_id"]: l for l in linhas_mo if l["funcao_id"] is not None}
    orfas = [l for l in linhas_mo if l["funcao_id"] is None]  # duplicatas antigas sem função
    vistos = set()
    for funcao in rcat.listar_funcoes(conn, tipo=tipo):
        qtd = int(form.get(f"qtd_{funcao['id']}") or 0)
        if qtd > 0:
            vistos.add(funcao["id"])
            if tipo == "evento":
                sugerido = funcao["valor_base_centavos"]
            else:
                sugerido = escalas.sugerido_mensal(dados, params, funcao)
            if funcao["id"] in existentes:
                rp.atualizar_linha_mao_de_obra(conn, existentes[funcao["id"]]["id"], qtd, sugerido)
            else:
                rp.inserir_linha(conn, pid, funcao["nome"], "mao_de_obra", qtd, sugerido,
                                 funcao_id=funcao["id"])
    for funcao_id, linha in existentes.items():
        if funcao_id not in vistos:
            rp.remover_linha(conn, linha["id"])
    for linha in orfas:
        rp.remover_linha(conn, linha["id"])

    sufixo = tipo  # 'continuo' | 'evento'
    rp.sincronizar_acessorios(
        conn, pid,
        valor_alimentacao=rcat.param_int(conn, f"valor_alimentacao_{sufixo}"),
        valor_transporte=rcat.param_int(conn, f"valor_transporte_{sufixo}"),
    )
    rp.recalcular_derivadas(conn, pid, params)
    return RedirectResponse(f"/propostas/{pid}/custos", status_code=303)


def _arquivo_dir() -> Path:
    return Path(os.environ.get("RSP_ARQUIVO_DIR", "data/propostas-enviadas"))


def _ctx_custos(conn, prop) -> dict:
    return {
        "prop": prop,
        "linhas": rp.linhas_da_proposta(conn, prop["id"]),
        "total": rp.total_proposta(conn, prop["id"]),
        "totais": rp.totais_por_origem(conn, prop["id"]),
    }


@router.get("/propostas/{pid}/custos")
def etapa_custos(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    ctx = _ctx_wizard(conn, prop, "custos")
    ctx.update(_ctx_custos(conn, prop))
    return templates.TemplateResponse(request, "etapa_custos.html", ctx)


def _responder_tabela(request: Request, conn, pid: int, erro: str | None = None):
    prop = _proposta_ou_404(conn, pid)
    if request.headers.get("HX-Request"):
        ctx = _ctx_custos(conn, prop)
        ctx["erro"] = erro
        return templates.TemplateResponse(request, "_tabela_custos.html", ctx)
    return RedirectResponse(f"/propostas/{pid}/custos", status_code=303)


def _linha_da_proposta_ou_404(conn: sqlite3.Connection, pid: int, lid: int) -> None:
    """Garante que a linha existe e pertence à proposta indicada."""
    row = conn.execute(
        "SELECT proposta_id FROM linhas_custo WHERE id = ?", (lid,)).fetchone()
    if row is None or row["proposta_id"] != pid:
        raise HTTPException(404, "Linha não encontrada nesta proposta")


@router.post("/propostas/{pid}/linhas/{lid}/valor")
def alterar_valor(request: Request, pid: int, lid: int,
                  valor: str = Form(...), conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    if prop["status"] != "rascunho":
        return RedirectResponse(f"/propostas/{pid}/emitida", status_code=303)
    _linha_da_proposta_ou_404(conn, pid, lid)
    try:
        centavos = parse_brl(valor)
    except ValueError:
        centavos = None  # valor ilegível: mantém como está; tabela devolvida mostra o atual
    atual = conn.execute(
        "SELECT valor_final_centavos FROM linhas_custo WHERE id = ?", (lid,)).fetchone()[0]
    # OK sem mudar o valor não vira override (congelaria uma linha percentual)
    if centavos is not None and centavos != atual:
        rp.sobrescrever_linha(conn, lid, centavos)
    rp.recalcular_derivadas(conn, pid, rcat.params_vigentes(conn))
    return _responder_tabela(request, conn, pid)


@router.post("/propostas/{pid}/linhas/{lid}/restaurar")
def restaurar_valor(request: Request, pid: int, lid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    if prop["status"] != "rascunho":
        return RedirectResponse(f"/propostas/{pid}/emitida", status_code=303)
    _linha_da_proposta_ou_404(conn, pid, lid)
    rp.restaurar_linha(conn, lid)
    rp.recalcular_derivadas(conn, pid, rcat.params_vigentes(conn))
    return _responder_tabela(request, conn, pid)


@router.post("/propostas/{pid}/linhas/nova")
def adicionar_linha_manual(request: Request, pid: int,
                           descricao: str = Form(""), valor: str = Form(""),
                           conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    if prop["status"] != "rascunho":
        return RedirectResponse(f"/propostas/{pid}/emitida", status_code=303)
    descricao = descricao.strip()
    if not descricao:
        return _responder_tabela(request, conn, pid, erro="Descrição é obrigatória.")
    try:
        if valor.strip().endswith("%"):
            # Linha percentual: o valor sai de recalcular_derivadas, sobre as linhas fixas
            pct, centavos = parse_percentual(valor), 0
        else:
            pct, centavos = None, parse_brl(valor)
    except ValueError as exc:
        erro = str(exc) if valor.strip().endswith("%") else "Valor inválido - use 1.234,56 ou 5%."
        return _responder_tabela(request, conn, pid, erro=erro)
    rp.inserir_linha(conn, pid, descricao, "manual", 1, centavos, percentual=pct)
    rp.recalcular_derivadas(conn, pid, rcat.params_vigentes(conn))
    return _responder_tabela(request, conn, pid)


@router.post("/propostas/{pid}/linhas/{lid}/remover")
def remover_linha_manual(request: Request, pid: int, lid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    if prop["status"] != "rascunho":
        return RedirectResponse(f"/propostas/{pid}/emitida", status_code=303)
    linha = conn.execute(
        "SELECT proposta_id, categoria FROM linhas_custo WHERE id = ?", (lid,)).fetchone()
    # Só linhas manuais são removíveis aqui: mão de obra sai pela etapa Serviços;
    # acessórios e derivadas são geridas pelo motor
    if linha is None or linha["proposta_id"] != pid or linha["categoria"] != "manual":
        raise HTTPException(404, "Linha não encontrada nesta proposta")
    rp.remover_linha(conn, lid)
    rp.recalcular_derivadas(conn, pid, rcat.params_vigentes(conn))
    return _responder_tabela(request, conn, pid)


@router.get("/propostas/{pid}/pagamento")
def etapa_pagamento(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    return templates.TemplateResponse(request, "etapa_pagamento.html",
                                      _ctx_wizard(conn, prop, "pagamento"))


@router.post("/propostas/{pid}/pagamento")
async def salvar_pagamento(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    form = await request.form()
    novos = {"formas_pagamento": A_COMBINAR if marcado(form, "formas_pagamento")
             else ", ".join(form.getlist("formas_pagamento"))}
    if prop["tipo"] == "continuo":
        novos["vencimento"] = (A_COMBINAR if marcado(form, "vencimento")
                               else str(form.get("vencimento", "")).strip())
        novos["parcela_ingresso"] = "sim" if form.get("parcela_ingresso") else ""
    else:
        bruto = str(form.get("data_limite_pagamento", "")).strip()
        try:
            novos["data_limite_pagamento"] = (A_COMBINAR if marcado(form, "data_limite_pagamento")
                                              else parse_data(bruto))
        except ValueError:
            ctx = _ctx_wizard(conn, prop, "pagamento")
            ctx["dados"] = {**ctx["dados"], **novos, "data_limite_pagamento": bruto}
            ctx["erro"] = "Data-limite inválida - use dd/mm/aaaa."
            return templates.TemplateResponse(request, "etapa_pagamento.html", ctx)
    rp.atualizar_dados(conn, pid, novos)
    return RedirectResponse(f"/propostas/{pid}/revisao", status_code=303)


@router.get("/propostas/{pid}/revisao")
def etapa_revisao(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    itens = checklist.avaliar(conn, pid)
    ctx = _ctx_wizard(conn, prop, "revisao")
    ctx.update({"itens": itens, "pode": checklist.pode_emitir(itens),
                "total": rp.total_proposta(conn, pid), "erro": None})
    return templates.TemplateResponse(request, "etapa_revisao.html", ctx)


@router.get("/propostas/{pid}/preview")
def preview(pid: int, conn=Depends(conn_dep)):
    _proposta_ou_404(conn, pid)
    return HTMLResponse(pdf_mod.render_documento_html(emissao.montar_snapshot(conn, pid)))


@router.post("/propostas/{pid}/emitir")
def emitir(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    try:
        emissao.emitir(conn, pid, _arquivo_dir())
    except ValueError as exc:  # checklist pendente
        itens = checklist.avaliar(conn, pid)
        ctx = _ctx_wizard(conn, prop, "revisao")
        ctx.update({"itens": itens, "pode": False,
                    "total": rp.total_proposta(conn, pid), "erro": str(exc)})
        return templates.TemplateResponse(request, "etapa_revisao.html", ctx)
    except Exception:
        itens = checklist.avaliar(conn, pid)
        ctx = _ctx_wizard(conn, prop, "revisao")
        ctx.update({"itens": itens, "pode": checklist.pode_emitir(itens),
                    "total": rp.total_proposta(conn, pid),
                    "erro": "Falha ao gerar o PDF. O rascunho foi preservado - tente novamente."})
        return templates.TemplateResponse(request, "etapa_revisao.html", ctx)
    return RedirectResponse(f"/propostas/{pid}/emitida", status_code=303)


@router.get("/propostas/{pid}/emitida")
def emitida(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    return templates.TemplateResponse(request, "emitida.html", {"prop": prop})


@router.get("/propostas/{pid}/pdf")
def baixar_pdf(pid: int, conn=Depends(conn_dep)):
    import json as _json

    prop = _proposta_ou_404(conn, pid)
    if prop["snapshot_json"]:
        snapshot = _json.loads(prop["snapshot_json"])
    else:
        snapshot = emissao.montar_snapshot(conn, pid)
    corpo = pdf_mod.gerar_pdf(snapshot)
    nome = pdf_mod.nome_arquivo(snapshot)
    return Response(corpo, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@router.post("/rearquivar")
def rearquivar(conn=Depends(conn_dep)):
    emissao.rearquivar_pendentes(conn, _arquivo_dir())
    return RedirectResponse("/propostas", status_code=303)
