"""Conversão entre texto pt-BR e números: reais <-> centavos inteiros, percentuais."""
import re
from decimal import Decimal


def parse_brl(texto: str) -> int:
    """'1.853,00' -> 185300. Sem vírgula, assume valor inteiro em reais."""
    limpo = texto.strip().replace("R$", "").strip()
    # Exige ao menos um dígito - rejeita entradas só de pontuação (".", ",", "..")
    if not re.fullmatch(r"(?=.*\d)[\d.,]+", limpo):
        raise ValueError(f"Valor monetário inválido: {texto!r}")
    # Mais de uma vírgula é ambíguo (ex.: "1,853,00") - rejeita em vez de misparsear
    if limpo.count(",") > 1:
        raise ValueError(f"Valor monetário inválido: {texto!r}")
    if "," in limpo:
        inteiro, _, decimal = limpo.partition(",")
        decimal = (decimal + "00")[:2]
        inteiro = inteiro.replace(".", "")
    else:
        n_pontos = limpo.count(".")
        if n_pontos == 0:
            inteiro, decimal = limpo, "00"
        else:
            ultimo_grupo = limpo.rsplit(".", 1)[1]
            if n_pontos == 1 and len(ultimo_grupo) in (1, 2):
                # teclado numérico móvel: único ponto seguido de 1-2 dígitos no
                # fim é decimal ("1853.00" -> R$1.853,00; "1.50" -> R$1,50)
                inteiro, _, decimal = limpo.rpartition(".")
            elif len(ultimo_grupo) in (1, 2):
                # múltiplos pontos sem vírgula com grupo final não-milhar: ambíguo
                raise ValueError(f"Valor monetário inválido: {texto!r}")
            else:
                inteiro, decimal = limpo, "00"
            inteiro = inteiro.replace(".", "")
            decimal = (decimal + "00")[:2]
    if not (inteiro.isdigit() and decimal.isdigit()):
        raise ValueError(f"Valor monetário inválido: {texto!r}")
    return int(inteiro) * 100 + int(decimal)


def format_brl(centavos: int) -> str:
    """185300 -> '1.853,00' (sem prefixo R$)."""
    negativo = centavos < 0
    centavos = abs(centavos)
    reais, cents = divmod(centavos, 100)
    milhar = f"{reais:,}".replace(",", ".")
    return f"{'-' if negativo else ''}{milhar},{cents:02d}"


def parse_percentual(texto: str) -> Decimal:
    """'5%' -> Decimal('0.05'); '5,5 %' -> Decimal('0.055'). Exige o sinal de %."""
    limpo = texto.strip()
    if not limpo.endswith("%"):
        raise ValueError("Valor inválido - use 1.234,56 ou 5%.")
    numero = limpo[:-1].strip().replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", numero):
        raise ValueError("Valor inválido - use 1.234,56 ou 5%.")
    fracao = Decimal(numero) / 100
    if fracao <= 0 or fracao > 1:
        raise ValueError("Percentual deve ficar entre 0% e 100%.")
    return fracao


def format_percentual(fracao: Decimal | str) -> str:
    """Decimal('0.055') -> '5,5%'."""
    valor = (Decimal(fracao) * 100).normalize()
    return format(valor, "f").replace(".", ",") + "%"


def parse_decimal_br(texto: str) -> Decimal:
    """'21,67' ou '21.67' -> Decimal('21.67'). Sem separador de milhar (uso em
    quantidades pequenas, como dias trabalhados por mês)."""
    limpo = texto.strip()
    if not re.fullmatch(r"\d+([.,]\d+)?", limpo):
        raise ValueError(f"Número inválido: {texto!r}")
    return Decimal(limpo.replace(",", "."))


def parse_percentual_campo(texto: str) -> Decimal:
    """Campo de percentual do admin: '58', '58%' ou '58,5' -> fração (Decimal('0.58')).
    Sem '%', número abaixo de 1 é recusado: '0.58' quase sempre é a fração digitada
    por engano e viraria 0,58%."""
    limpo = texto.strip()
    com_sinal = limpo.endswith("%")
    numero = limpo.rstrip("%").strip().replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", numero):
        raise ValueError("Percentual inválido. Use 58 ou 58%.")
    valor = Decimal(numero)
    if not com_sinal and valor < 1:
        raise ValueError("Valor ambíguo. Use 58 ou 58% (não 0.58).")
    return valor / 100
