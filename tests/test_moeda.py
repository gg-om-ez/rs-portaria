import pytest

from app.moeda import format_brl, parse_brl


def test_parse_brl_formatos_comuns():
    assert parse_brl("1.853,00") == 185300
    assert parse_brl("R$ 1.140,50") == 114050
    assert parse_brl("580") == 58000
    assert parse_brl("12.000") == 1200000
    assert parse_brl("0,50") == 50


def test_parse_brl_invalido():
    with pytest.raises(ValueError):
        parse_brl("abc")
    with pytest.raises(ValueError):
        parse_brl("")


def test_parse_brl_so_pontuacao():
    # Entrada só de pontuação não pode parsear como 0
    with pytest.raises(ValueError):
        parse_brl(".")
    with pytest.raises(ValueError):
        parse_brl(",")
    with pytest.raises(ValueError):
        parse_brl("..")


def test_parse_brl_multiplas_virgulas():
    # Mais de uma vírgula é ambíguo - rejeitar em vez de misparsear
    with pytest.raises(ValueError):
        parse_brl("1,853,00")


def test_parse_brl_ponto_decimal_teclado_movel():
    # Teclado numérico móvel usa "." como separador decimal - um único ponto
    # seguido de 1-2 dígitos no fim, sem vírgula, deve ser tratado como decimal
    assert parse_brl("1853.00") == 185300
    assert parse_brl("1.50") == 150
    assert parse_brl("0.5") == 50
    # grupos de 3 dígitos continuam sendo interpretados como milhar (inalterado)
    assert parse_brl("12.000") == 1200000
    # com vírgula presente, o comportamento não muda
    assert parse_brl("1.853,00") == 185300


def test_parse_brl_ponto_ambiguo_invalido():
    with pytest.raises(ValueError):
        parse_brl(".50")
    with pytest.raises(ValueError):
        parse_brl("1.2.50")


def test_format_brl():
    assert format_brl(185300) == "1.853,00"
    assert format_brl(50) == "0,50"
    assert format_brl(1200000) == "12.000,00"
    assert format_brl(0) == "0,00"
    assert format_brl(-185300) == "-1.853,00"


def test_ida_e_volta():
    assert parse_brl(format_brl(999999999)) == 999999999


from decimal import Decimal

from app.moeda import format_percentual, parse_percentual


@pytest.mark.parametrize("entrada,esperado", [
    ("5%", Decimal("0.05")), (" 5,5 % ", Decimal("0.055")), ("0%", Decimal("0")),
    ("12.5%", Decimal("0.125"))])
def test_parse_percentual(entrada, esperado):
    assert parse_percentual(entrada) == esperado


@pytest.mark.parametrize("entrada", ["5", "", "%", "-5%", "abc%", "1,2,3%"])
def test_parse_percentual_rejeita(entrada):
    with pytest.raises(ValueError):
        parse_percentual(entrada)


@pytest.mark.parametrize("entrada,esperado", [
    (Decimal("0.05"), "5%"), (Decimal("0.055"), "5,5%"), (Decimal("0.10"), "10%")])
def test_format_percentual(entrada, esperado):
    assert format_percentual(entrada) == esperado


from app.moeda import parse_decimal_br


@pytest.mark.parametrize("entrada,esperado", [
    ("21,67", Decimal("21.67")), ("21.67", Decimal("21.67")), (" 15 ", Decimal("15"))])
def test_parse_decimal_br(entrada, esperado):
    assert parse_decimal_br(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "abc", "1,2,3", "-1"])
def test_parse_decimal_br_rejeita(entrada):
    with pytest.raises(ValueError):
        parse_decimal_br(entrada)


from app.moeda import parse_percentual_campo


@pytest.mark.parametrize("e,v", [("58", "0.58"), ("58%", "0.58"), ("58,5", "0.585"),
                                 ("0,5%", "0.005"), (" 20 % ", "0.2")])
def test_parse_percentual_campo(e, v):
    assert parse_percentual_campo(e) == Decimal(v)


@pytest.mark.parametrize("e", ["", "0.58", "0,58", "-5", "abc", "%"])
def test_parse_percentual_campo_rejeita(e):
    with pytest.raises(ValueError):
        parse_percentual_campo(e)
