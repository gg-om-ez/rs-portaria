from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import repo_catalogo as rcat
from app.datas import parse_data
from app.db import conn_dep
from app.admin_secoes import SECOES, Secao, converter, exibir
from app.admin_secoes import secao as secao_por_id
from app.moeda import parse_brl, parse_decimal_br
from app.web import templates

router = APIRouter(prefix="/admin")

def _render(request: Request, conn, sec: Secao, erro: str | None = None,
            erros: dict | None = None, digitados: dict | None = None, vigencia: str = ""):
    campos = []
    for c in sec.campos:
        row = rcat.vigencia_atual(conn, c.chave)
        vigente = row["valor"] if row else ""
        # numéricos vêm vazios (vigente fica ao lado); textos vêm preenchidos para editar no lugar
        original = vigente if c.tipo in ("texto", "texto_longo") else ""
        campos.append({
            "campo": c, "vigente": exibir(c, vigente), "desde": row["vigencia_inicio"] if row else "",
            "original": original,
            "novo": digitados[c.chave] if digitados is not None else original,
            "erro": (erros or {}).get(c.chave),
            "historico": rcat.historico_parametro(conn, c.chave),
        })
    return templates.TemplateResponse(request, "admin.html", {
        "secoes": SECOES, "sec": sec, "campos": campos,
        "vigencia": vigencia or date.today().isoformat(),
        "funcoes": rcat.listar_funcoes(conn, apenas_ativas=False),
        "escalas": rcat.listar_escalas(conn, apenas_ativas=False),
        "exibir": exibir, "erro": erro,
    })


@router.get("")
def painel(request: Request, secao: str = "", conn=Depends(conn_dep)):
    return _render(request, conn, secao_por_id(secao))


@router.post("/parametros/lote")
async def salvar_lote(request: Request, conn=Depends(conn_dep)):
    form = await request.form()
    sec = secao_por_id(str(form.get("secao", "")))
    bruto_vigencia = str(form.get("vigencia_inicio", "")).strip()
    digitados = {c.chave: str(form.get(f"novo_{c.chave}", "")) for c in sec.campos}
    try:
        vigencia = parse_data(bruto_vigencia)
    except ValueError:
        vigencia = None
    erros, valores = {}, {}
    for c in sec.campos:
        texto = c.tipo in ("texto", "texto_longo")
        # numérico em branco: não altera. Texto vem preenchido, então vazio enviado
        # é limpar; campo que nem veio no formulário não muda
        if not digitados[c.chave].strip() and (not texto or f"novo_{c.chave}" not in form):
            continue
        try:
            valor = converter(c, digitados[c.chave])
        except ValueError as exc:
            erros[c.chave] = str(exc)
            continue
        # igual ao que já vale na data escolhida: não cria vigência repetida
        vigente = rcat.parametro_vigente(conn, c.chave, em=vigencia) or ""
        if texto:
            vigente = vigente.replace("\r\n", "\n").strip()  # legado gravado com CRLF
        if valor != vigente:
            valores[c.chave] = valor
    erro = None
    if vigencia is None:
        erro = "Data de vigência inválida - use dd/mm/aaaa."
    elif erros:
        erro = "Corrija os campos marcados. Nada foi gravado."
    elif not valores:
        erro = "Nenhuma alteração para salvar."
    if erro:
        return _render(request, conn, sec, erro=erro, erros=erros, digitados=digitados,
                       vigencia=vigencia or bruto_vigencia)
    rcat.definir_parametros(conn, valores, vigencia)
    return RedirectResponse(f"/admin?secao={sec.id}", status_code=303)


@router.post("/funcoes")
def criar_funcao(request: Request, nome: str = Form(...), tipo: str = Form(...),
                 valor_base: str = Form(""), aplica_noturno: str = Form(""),
                 conn=Depends(conn_dep)):
    try:
        rcat.criar_funcao(conn, nome, tipo, parse_brl(valor_base),
                          aplica_noturno=bool(aplica_noturno))
    except ValueError as exc:
        return _render(request, conn, secao_por_id("catalogo-funcoes"), erro=str(exc))
    return RedirectResponse("/admin?secao=catalogo-funcoes", status_code=303)


@router.post("/funcoes/{fid}")
def atualizar_funcao(request: Request, fid: int, valor_base: str = Form(""),
                     ativa: str = Form(""), nome: str = Form(""), conn=Depends(conn_dep)):
    try:
        campos = {"valor_base_centavos": parse_brl(valor_base), "ativa": int(bool(ativa))}
        if nome.strip():
            campos["nome"] = nome.strip()
        rcat.atualizar_funcao(conn, fid, **campos)
    except ValueError as exc:
        return _render(request, conn, secao_por_id("catalogo-funcoes"), erro=str(exc))
    return RedirectResponse("/admin?secao=catalogo-funcoes", status_code=303)


@router.post("/escalas/{eid}")
def atualizar_escala(request: Request, eid: int, modo: str = Form(...),
                     dias_mes: str = Form(""), conn=Depends(conn_dep)):
    try:
        try:
            dias = parse_decimal_br(dias_mes) if dias_mes.strip() else None
        except ValueError:
            raise ValueError("Dias trabalhados por mês inválido.")
        rcat.atualizar_escala(conn, eid, modo, dias)
    except ValueError as exc:
        return _render(request, conn, secao_por_id("catalogo-escalas"), erro=str(exc))
    return RedirectResponse("/admin?secao=catalogo-escalas", status_code=303)
