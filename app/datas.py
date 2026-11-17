"""Conversão entre texto de data/hora (pt-BR ou ISO do input nativo) e ISO.

Armazenamento é sempre ISO (`AAAA-MM-DD`, `HH:MM`); pt-BR só na borda.
"""
import re
from datetime import date

# ISO vem do <input type="date"> nativo; BR vem do campo mascarado no desktop
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_BR = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_BR_DIGITOS = re.compile(r"(\d{2})(\d{2})(\d{4})")  # máscara incompleta: só dígitos
_HORA = re.compile(r"(\d{1,2})[:hH](\d{2})(?::\d{2})?")  # segundos do input nativo descartados
_HORA_DIGITOS = re.compile(r"(\d{2})(\d{2})")


def parse_data(texto: str) -> str:
    """'17/11/2026', '17112026' ou '2026-11-17' -> '2026-11-17'."""
    limpo = (texto or "").strip()
    m = _ISO.fullmatch(limpo)
    if m:
        ano, mes, dia = m.groups()
    else:
        m = _BR.fullmatch(limpo) or _BR_DIGITOS.fullmatch(limpo)
        if not m:
            raise ValueError(f"Data inválida: {texto!r}")
        dia, mes, ano = m.groups()
    # date() valida o calendário (31/02 levanta ValueError)
    return date(int(ano), int(mes), int(dia)).isoformat()


def format_data_br(valor: str | None) -> str:
    """'2026-11-17' (ou datetime ISO) -> '17/11/2026'. Fora de ISO devolve inalterado,
    para re-exibir o texto digitado quando o formulário volta com erro."""
    if not valor:
        return ""
    m = _ISO.match(valor)
    if not m:
        return valor
    ano, mes, dia = m.groups()
    return f"{dia}/{mes}/{ano}"


def parse_hora_24(texto: str) -> str:
    """'9:00', '18h15', '0915' ou '09:00:00' -> 'HH:MM' (24h)."""
    limpo = (texto or "").strip()
    m = _HORA.fullmatch(limpo) or _HORA_DIGITOS.fullmatch(limpo)
    if not m:
        raise ValueError(f"Hora inválida: {texto!r}")
    hora, minuto = int(m.group(1)), int(m.group(2))
    if hora > 23 or minuto > 59:
        raise ValueError(f"Hora inválida: {texto!r}")
    return f"{hora:02d}:{minuto:02d}"
