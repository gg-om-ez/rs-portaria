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

DIAS_SEMANA: list[tuple[str, str]] = [
    ("seg", "Seg"), ("ter", "Ter"), ("qua", "Qua"), ("qui", "Qui"),
    ("sex", "Sex"), ("sab", "Sáb"), ("dom", "Dom"),
]

# Rascunhos anteriores ao menu de escalas são 12x36 (15 plantões/mês)
_DIAS_MES_PADRAO = "15"


def modo_de(dados: dict) -> str:
    return dados.get("modo_preco") or "piso_mensal"


def usa_motor_completo(tipo: str, dados: dict) -> bool:
    """Encargos, margem e acessórios automáticos: evento e contínuo por piso mensal."""
    return tipo == "evento" or modo_de(dados) == "piso_mensal"


def valor_semanal(dados: dict) -> int:
    return sum(int(d["valor_centavos"]) for d in dados.get("escala_semanal") or [])


def sugerido_mensal(funcao: Mapping, dados: dict, params: Params) -> int:
    """Valor mensal sugerido por profissional de uma função, conforme o modo."""
    modo = modo_de(dados)
    if modo == "semanal":
        return mensal_de_semanal(valor_semanal(dados))
    if modo == "diaria":
        return mensal_por_diaria(int(dados["valor_diaria_centavos"]), Decimal(dados["plantoes_mes"]))
    if not funcao["aplica_noturno"]:
        return funcao["valor_base_centavos"]
    ini = time.fromisoformat(dados.get("hora_inicio_turno") or "18:00")
    fim = time.fromisoformat(dados.get("hora_fim_turno") or "06:00")
    dias = Decimal(dados.get("plantoes_mes") or _DIAS_MES_PADRAO)
    return custo_profissional_continuo(funcao["valor_base_centavos"], ini, fim, dias, params)
