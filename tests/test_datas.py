import pytest

from app.datas import format_data_br, parse_data, parse_hora_24


@pytest.mark.parametrize("entrada,esperado", [
    ("2026-11-17", "2026-11-17"), ("17/11/2026", "2026-11-17"), ("1/8/2026", "2026-08-01"),
    ("17112026", "2026-11-17"), (" 17/11/2026 ", "2026-11-17")])
def test_parse_data(entrada, esperado):
    assert parse_data(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "31/02/2026", "2026-02-31", "17/11/26", "banana"])
def test_parse_data_rejeita(entrada):
    with pytest.raises(ValueError):
        parse_data(entrada)


@pytest.mark.parametrize("entrada,esperado", [
    ("2026-11-17", "17/11/2026"), ("2026-11-17 14:03:00", "17/11/2026"),
    ("", ""), (None, ""), ("17/11/2026", "17/11/2026"), ("lixo", "lixo")])
def test_format_data_br(entrada, esperado):
    assert format_data_br(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("09:00", "09:00"), ("09:00:00", "09:00"), ("9:00", "09:00"), ("18h15", "18:15"),
    ("0915", "09:15"), ("00:00", "00:00")])
def test_parse_hora_24(entrada, esperado):
    assert parse_hora_24(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "24:00", "9:60", "6 PM", "915"])
def test_parse_hora_24_rejeita(entrada):
    with pytest.raises(ValueError):
        parse_hora_24(entrada)
