"""Regras de preço por modo de escala (contínuo). Sem acesso a banco.

Modos: `piso_mensal` (piso CLT + noturno; motor soma encargos, margem e
acessórios), `diaria` (diária fechada x dias/mês) e `semanal` (Personalizado:
valor por dia da semana, mensal = semana x 52/12). Diária e semanal são preço
fechado: o motor não gera encargos, margem nem acessórios.
"""
from collections.abc import Mapping
from datetime import time
from decimal import Decimal

from app.calc import Params, custo_profissional_continuo, mensal_de_semanal, mensal_por_diaria
from app.datas import parse_hora_24
from app.moeda import format_brl, parse_brl, parse_decimal_br

DIAS_SEMANA: list[tuple[str, str]] = [
    ("seg", "Seg"), ("ter", "Ter"), ("qua", "Qua"), ("qui", "Qui"),
    ("sex", "Sex"), ("sab", "Sáb"), ("dom", "Dom"),
]

# Rascunhos anteriores ao menu de escalas são 12x36 (15 plantões/mês)
_DIAS_MES_PADRAO = "15"


def modo_de(dados: dict) -> str:
    return dados.get("modo_preco") or "piso_mensal"


def modo_da_linha(linha: Mapping, tipo: str, dados: dict) -> str:
    """Modo de preço efetivo de uma linha de mão de obra. Evento é sempre piso
    (motor completo). Linha antiga sem modo herda o da proposta (formato de
    antes da escala por função)."""
    if tipo == "evento":
        return "piso_mensal"
    return linha["modo_preco"] or modo_de(dados)


# Campos de escala que, antes da escala por função, ficavam no nível da proposta
_CAMPOS_ESCALA = ("escala_id", "escala_nome", "modo_preco", "hora_inicio_turno", "hora_fim_turno",
                  "plantoes_mes", "valor_diaria_centavos", "escala_semanal")


def funcoes_da_proposta(dados: dict, linhas: list) -> list[dict]:
    """Cartões de função da proposta. Rascunho antigo (sem "funcoes") é derivado:
    um cartão por linha de mão de obra, com a escala que era da proposta."""
    if "funcoes" in dados:
        return dados["funcoes"]
    escala = {"escala_nome": "12x36", "modo_preco": "piso_mensal", "plantoes_mes": _DIAS_MES_PADRAO}
    escala.update({c: dados[c] for c in _CAMPOS_ESCALA if dados.get(c) not in (None, "")})
    return [{"chave": f"l{l['id']}", "funcao_id": l["funcao_id"], "nome": l["descricao"],
             "quantidade": l["quantidade"], "piso_centavos": None, "aplica_noturno": False, **escala}
            for l in linhas if l["categoria"] == "mao_de_obra"]


def valor_semanal(dados: dict) -> int:
    return sum(int(d["valor_centavos"]) for d in dados.get("escala_semanal") or [])


def sugerido_mensal(cfg: Mapping, params: Params, catalogo: Mapping | None = None) -> int:
    """Valor mensal sugerido por profissional de um cartão de função. Em piso
    mensal usa o piso do catálogo (com o noturno dele) ou, para função
    personalizada, o `piso_centavos` digitado, sem noturno."""
    modo = modo_de(cfg)
    if modo == "semanal":
        return mensal_de_semanal(valor_semanal(cfg))
    if modo == "diaria":
        return mensal_por_diaria(int(cfg["valor_diaria_centavos"]), Decimal(cfg["plantoes_mes"]))
    if catalogo is not None:
        piso, noturno = catalogo["valor_base_centavos"], catalogo["aplica_noturno"]
    else:
        piso, noturno = int(cfg["piso_centavos"]), bool(cfg.get("aplica_noturno"))
    if not noturno:
        return piso
    ini = time.fromisoformat(cfg.get("hora_inicio_turno") or "18:00")
    fim = time.fromisoformat(cfg.get("hora_fim_turno") or "06:00")
    dias = Decimal(cfg.get("plantoes_mes") or _DIAS_MES_PADRAO)
    return custo_profissional_continuo(piso, ini, fim, dias, params)

def _campo(form: Mapping, nome: str) -> str:
    return str(form.get(nome) or "").strip()


def _ler_semana(form: Mapping) -> tuple[list[dict], str | None]:
    semana = []
    for chave, rotulo in DIAS_SEMANA:
        if not form.get(f"dia_{chave}_ativo"):
            continue  # dia inativo: horário e valor digitados são ignorados
        try:
            inicio = parse_hora_24(_campo(form, f"dia_{chave}_inicio"))
            fim = parse_hora_24(_campo(form, f"dia_{chave}_fim"))
        except ValueError:
            return [], f"Horário inválido em {rotulo}."
        try:
            valor = parse_brl(_campo(form, f"dia_{chave}_valor"))
        except ValueError:
            valor = 0
        if valor <= 0:
            return [], f"Valor inválido em {rotulo}."
        semana.append({"dia": chave, "inicio": inicio, "fim": fim, "valor_centavos": valor})
    if not semana:
        return [], "Ative pelo menos um dia da semana."
    return semana, None


def ler_form_escala(escala: Mapping, form: Mapping) -> tuple[dict, str | None]:
    """Campos da escala escolhida, normalizados para dados_json, ou a mensagem de erro."""
    modo = escala["modo"]
    dados = {"escala_id": str(escala["id"]), "escala_nome": escala["nome"], "modo_preco": modo}
    if modo == "semanal":
        semana, erro = _ler_semana(form)
        dados["escala_semanal"] = semana
        return dados, erro

    for campo, rotulo in [("hora_inicio_turno", "início"), ("hora_fim_turno", "término")]:
        try:
            dados[campo] = parse_hora_24(_campo(form, campo))
        except ValueError:
            return dados, f"Horário de {rotulo} do turno inválido - use HH:MM (24h)."

    # Vazio = dias da escala; escala sem dias (ex.: Diárias por escala) exige o campo
    bruto = _campo(form, "plantoes_mes")
    try:
        dias = parse_decimal_br(bruto) if bruto else Decimal(escala["dias_mes"] or "0")
    except ValueError:
        dias = Decimal("0")
    if dias <= 0 or dias > 31:  # teto evita erro de digitação virar preço
        return dados, "Dias trabalhados por mês inválido."
    dados["plantoes_mes"] = str(dias)

    if modo == "diaria":
        try:
            valor = parse_brl(_campo(form, "valor_diaria"))
        except ValueError:
            valor = 0
        if valor <= 0:
            return dados, "Valor da diária inválido."
        dados["valor_diaria_centavos"] = valor
    return dados, None


def dias_para_form(dados: dict | None = None, form: Mapping | None = None) -> dict[str, dict]:
    """Estado dos 7 dias para o template: do formulário submetido (re-exibição
    com erro) ou da escala semanal gravada."""
    if form is not None:
        return {k: {"ativo": bool(form.get(f"dia_{k}_ativo")),
                    "inicio": _campo(form, f"dia_{k}_inicio"),
                    "fim": _campo(form, f"dia_{k}_fim"),
                    "valor": _campo(form, f"dia_{k}_valor")} for k, _ in DIAS_SEMANA}
    gravados = {d["dia"]: d for d in (dados or {}).get("escala_semanal") or []}
    estado = {}
    for k, _ in DIAS_SEMANA:
        d = gravados.get(k)
        estado[k] = {"ativo": d is not None, "inicio": d["inicio"] if d else "",
                     "fim": d["fim"] if d else "",
                     "valor": format_brl(d["valor_centavos"]) if d else ""}
    return estado
