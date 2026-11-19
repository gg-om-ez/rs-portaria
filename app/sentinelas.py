"""Valores-sentinela de campos que podem ficar em aberto na proposta.

Marcada a opção ao lado do campo, grava-se o texto da sentinela no lugar do
valor: o checklist o aceita como preenchido e o PDF o imprime como está.
"""
from collections.abc import Mapping

A_INFORMAR = "A informar"
A_COMBINAR = "A combinar"
SENTINELAS = (A_INFORMAR, A_COMBINAR)


def marcado(form: Mapping, campo: str) -> bool:
    return form.get(f"{campo}_sentinela") is not None
