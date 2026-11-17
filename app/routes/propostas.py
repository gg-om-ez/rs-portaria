import os
import secrets
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
from app.moeda import format_brl, parse_brl, parse_percentual
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
        "escala_nome": " + ".join(dict.fromkeys(
            f.get("escala_nome") or "12x36" for f in escalas.funcoes_da_proposta(dados, linhas)))
            if prop["tipo"] == "continuo" else "",
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


def _txt(form, nome: str) -> str:
    return str(form.get(nome) or "").strip()


def _escala_por_id(conn, bruto) -> sqlite3.Row:
    """Escala pelo id do formulário; vazio é a 12x36 padrão (rascunho antigo)."""
    if bruto in (None, ""):
        return rcat.escala_padrao(conn)
    try:
        escala = rcat.obter_escala(conn, int(bruto))
    except ValueError:
        escala = None
    if escala is None:
        raise HTTPException(422, "Escala inválida")
    return escala


def _cartao(conn, chave: str, catalogo: list, cfg: dict | None = None, form=None,
            erro: str | None = None) -> dict:
    """Contexto de um cartão de função: do que está gravado (`cfg`), do formulário
    enviado (`form`, re-exibição e troca de escala) ou um cartão novo (nenhum dos dois)."""
    p = f"f_{chave}_"
    primeira = str(catalogo[0]["id"]) if catalogo else "personalizada"
    if form is not None:
        escala = _escala_por_id(conn, form.get(p + "escala_id"))
        cartao = {
            "funcao_sel": _txt(form, p + "funcao") or primeira,
            "nome": _txt(form, p + "nome"), "qtd": _txt(form, p + "qtd"), "piso": _txt(form, p + "piso"),
            "valores": {c: _txt(form, p + c) for c in
                        ("hora_inicio_turno", "hora_fim_turno", "valor_diaria")},
            "dias": escalas.dias_para_form(form=form, prefixo=p),
            # dias/mês digitado vale; trocar de escala sem digitar sugere o da nova
            "dias_mes": _txt(form, p + "plantoes_mes") if p + "plantoes_mes" in form
                        else (escala["dias_mes"] or ""),
        }
    else:
        cfg = cfg or {}
        escala = _escala_por_id(conn, cfg.get("escala_id"))
        padrao = str(rcat.escala_padrao(conn)["id"])
        mesma = bool(cfg) and str(cfg.get("escala_id") or padrao) == str(escala["id"])
        cartao = {
            "funcao_sel": (str(cfg["funcao_id"]) if cfg.get("funcao_id")
                           else "personalizada" if cfg else primeira),
            "nome": "" if cfg.get("funcao_id") else cfg.get("nome", ""),
            "qtd": cfg.get("quantidade", 1),
            "piso": format_brl(cfg["piso_centavos"]) if cfg.get("piso_centavos") else "",
            "valores": {"hora_inicio_turno": cfg.get("hora_inicio_turno") or "",
                        "hora_fim_turno": cfg.get("hora_fim_turno") or "",
                        "valor_diaria": (format_brl(cfg["valor_diaria_centavos"])
                                         if cfg.get("valor_diaria_centavos") else "")},
            "dias": escalas.dias_para_form(dados=cfg),
            "dias_mes": (cfg.get("plantoes_mes") if mesma else None) or escala["dias_mes"] or "",
        }
    cartao.update({"chave": chave, "p": p, "escala": escala, "erro": erro})
    return cartao


def _ctx_servicos(conn, prop, dados: dict, cartoes: list | None = None) -> dict:
    ctx = _ctx_wizard(conn, prop, "servicos")
    ctx["dados"] = dados
    ctx["funcoes"] = rcat.listar_funcoes(conn, tipo=prop["tipo"])
    ctx["escalas"] = rcat.listar_escalas(conn)
    ctx["dias_semana"] = escalas.DIAS_SEMANA
    ctx["cartoes"] = cartoes or []
    ctx["escala"] = None
    ctx["qtd_atuais"] = {}
    ctx["erro"] = None
    return ctx


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


@router.get("/propostas/{pid}/servicos")
def etapa_servicos(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    dados = rp.dados_de(prop)
    ctx = _ctx_servicos(conn, prop, dados)
    linhas = rp.linhas_da_proposta(conn, pid)
    if prop["tipo"] == "continuo":
        cfgs = escalas.funcoes_da_proposta(dados, linhas)
        ctx["cartoes"] = [_cartao(conn, f["chave"], ctx["funcoes"], cfg=f) for f in cfgs] \
            or [_cartao(conn, secrets.token_hex(3), ctx["funcoes"])]
    else:
        ctx["qtd_atuais"] = {l["funcao_id"]: l["quantidade"] for l in linhas
                             if l["categoria"] == "mao_de_obra" and l["funcao_id"]}
    return templates.TemplateResponse(request, "etapa_servicos.html", ctx)


@router.get("/propostas/{pid}/servicos/funcao")
def cartao_funcao(request: Request, pid: int, chave: str = "", conn=Depends(conn_dep)):
    """Parcial de um cartão: novo (sem chave) ou o mesmo cartão refeito com a escala
    ou a função trocada (campos dele vêm na query via hx-include)."""
    prop = _proposta_ou_404(conn, pid)
    catalogo = rcat.listar_funcoes(conn, tipo="continuo")
    q = request.query_params
    if chave and any(k.startswith(f"f_{chave}_") for k in q.keys()):
        cartao = _cartao(conn, chave, catalogo, form=q)
    else:
        cartao = _cartao(conn, secrets.token_hex(3), catalogo)
    return templates.TemplateResponse(request, "_funcao_card.html", {
        "c": cartao, "prop": prop, "funcoes": catalogo,
        "escalas": rcat.listar_escalas(conn), "dias_semana": escalas.DIAS_SEMANA})


def _ler_cartoes(conn, form, catalogo: list) -> tuple[list[dict], list[dict], str | None]:
    """Lê os cartões do POST: configurações válidas (quantidade > 0), contexto de
    cada cartão para re-exibir e a primeira mensagem de erro."""
    cfgs, cartoes, erro = [], [], None
    for chave in form.getlist("funcao"):
        p = f"f_{chave}_"
        sel = _txt(form, p + "funcao")
        funcao = None
        if sel != "personalizada":
            try:
                funcao = rcat.obter_funcao(conn, int(sel))
            except ValueError:
                funcao = None
            if funcao is None:
                raise HTTPException(422, "Função inválida")
        nome = funcao["nome"] if funcao else _txt(form, p + "nome")
        erro_c, qtd = None, 0
        try:
            qtd = int(_txt(form, p + "qtd") or "0")
            if qtd < 0:
                raise ValueError
        except ValueError:
            erro_c = f"Quantidade inválida para {nome or 'a função'}."
        escala = _escala_por_id(conn, form.get(p + "escala_id"))
        if erro_c is None and qtd > 0:  # quantidade 0: cartão ignorado
            if not nome:
                erro_c = "Informe o nome da função personalizada."
            else:
                dados_escala, e = escalas.ler_form_escala(escala, form, p)
                if e:
                    erro_c = f"{nome}: {e}"
                piso = None
                if erro_c is None and funcao is None and escala["modo"] == "piso_mensal":
                    try:
                        piso = parse_brl(_txt(form, p + "piso"))
                    except ValueError:
                        piso = 0
                    if piso <= 0:
                        erro_c = "Informe o piso mensal da função personalizada."
                if erro_c is None:
                    cfgs.append({"chave": chave, "funcao_id": funcao["id"] if funcao else None,
                                 "nome": nome, "quantidade": qtd, "piso_centavos": piso,
                                 "aplica_noturno": False, **dados_escala})
        cartoes.append(_cartao(conn, chave, catalogo, form=form, erro=erro_c))
        erro = erro or erro_c
    return cfgs, cartoes, erro


def _salvar_linhas_continuo(conn, pid: int, cfgs: list[dict], anteriores: dict, params) -> None:
    """Upsert das linhas de mão de obra por cartão (chave_funcao), preservando
    override; troca de escala ou de modo no cartão volta a linha ao sugerido."""
    linhas_mo = [l for l in rp.linhas_da_proposta(conn, pid) if l["categoria"] == "mao_de_obra"]
    # linha antiga sem chave casa com o cartão derivado "l<id>"
    por_chave = {(l["chave_funcao"] or f"l{l['id']}"): l for l in linhas_mo}
    padrao = str(rcat.escala_padrao(conn)["id"])
    for cfg in cfgs:
        catalogo = rcat.obter_funcao(conn, cfg["funcao_id"]) if cfg["funcao_id"] else None
        sugerido = escalas.sugerido_mensal(cfg, params, catalogo)
        descricao = f"{cfg['nome']} - {cfg['escala_nome']}"
        linha = por_chave.get(cfg["chave"])
        if linha is None:
            rp.inserir_linha(conn, pid, descricao, "mao_de_obra", cfg["quantidade"], sugerido,
                             funcao_id=cfg["funcao_id"], chave_funcao=cfg["chave"],
                             modo_preco=cfg["modo_preco"])
            continue
        ant = anteriores.get(cfg["chave"])
        mudou = (ant is None or str(ant.get("escala_id") or padrao) != cfg["escala_id"]
                 or escalas.modo_de(ant) != cfg["modo_preco"])
        if mudou and linha["sobrescrito"]:
            rp.restaurar_linha(conn, linha["id"])
        rp.atualizar_linha_mao_de_obra(conn, linha["id"], cfg["quantidade"], sugerido,
                                       descricao=descricao, modo_preco=cfg["modo_preco"],
                                       chave_funcao=cfg["chave"])
    vistas = {cfg["chave"] for cfg in cfgs}
    for chave, linha in por_chave.items():
        if chave not in vistas:
            rp.remover_linha(conn, linha["id"])


def _salvar_linhas_evento(conn, pid: int, form) -> None:
    """Evento: quantidade por função do catálogo, valor-base como diária."""
    linhas_mo = [l for l in rp.linhas_da_proposta(conn, pid) if l["categoria"] == "mao_de_obra"]
    existentes = {l["funcao_id"]: l for l in linhas_mo if l["funcao_id"] is not None}
    vistos = set()
    for funcao in rcat.listar_funcoes(conn, tipo="evento"):
        qtd = int(form.get(f"qtd_{funcao['id']}") or 0)
        if qtd > 0:
            vistos.add(funcao["id"])
            if funcao["id"] in existentes:
                rp.atualizar_linha_mao_de_obra(conn, existentes[funcao["id"]]["id"], qtd,
                                               funcao["valor_base_centavos"])
            else:
                rp.inserir_linha(conn, pid, funcao["nome"], "mao_de_obra", qtd,
                                 funcao["valor_base_centavos"], funcao_id=funcao["id"])
    for linha in linhas_mo:
        if linha["funcao_id"] not in vistos:
            rp.remover_linha(conn, linha["id"])


@router.post("/propostas/{pid}/servicos")
async def salvar_servicos(request: Request, pid: int, conn=Depends(conn_dep)):
    prop = _proposta_ou_404(conn, pid)
    form = await request.form()
    tipo = prop["tipo"]
    dados_anteriores = rp.dados_de(prop)
    dados_form = {c: _txt(form, c) for c in _campos_servicos(tipo)}
    if tipo == "continuo":
        catalogo = rcat.listar_funcoes(conn, tipo="continuo")
        cfgs, cartoes, erro = _ler_cartoes(conn, form, catalogo)
    else:
        erro = _erro_validacao_qtds(conn, tipo, form)
    if erro:
        ctx = _ctx_servicos(conn, prop, {**dados_anteriores, **dados_form},
                            cartoes if tipo == "continuo" else None)
        if tipo != "continuo":
            ctx["qtd_atuais"] = {f["id"]: form.get(f"qtd_{f['id']}") for f in ctx["funcoes"]
                                 if form.get(f"qtd_{f['id']}") is not None}
        ctx["erro"] = erro
        return templates.TemplateResponse(request, "etapa_servicos.html", ctx)

    params = rcat.params_vigentes(conn)
    if tipo == "continuo":
        linhas_ant = rp.linhas_da_proposta(conn, pid)
        anteriores = {f["chave"]: f for f in escalas.funcoes_da_proposta(dados_anteriores, linhas_ant)}
        dados_form["funcoes"] = cfgs
        # escala no nível da proposta é do formato antigo: limpa para não confundir
        dados_form.update({c: None for c in escalas.CAMPOS_ESCALA_PROPOSTA})
        rp.atualizar_dados(conn, pid, dados_form)
        _salvar_linhas_continuo(conn, pid, cfgs, anteriores, params)
    else:
        rp.atualizar_dados(conn, pid, dados_form)
        _salvar_linhas_evento(conn, pid, form)

    rp.sincronizar_acessorios(
        conn, pid,
        valor_alimentacao=rcat.param_int(conn, f"valor_alimentacao_{tipo}"),
        valor_transporte=rcat.param_int(conn, f"valor_transporte_{tipo}"),
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
