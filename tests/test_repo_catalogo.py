from decimal import Decimal

from app import repo_catalogo as rcat


def test_parametro_vigente_respeita_vigencia(conn):
    rcat.definir_parametro(conn, "pct_noturno", "0.20", "2025-01-01")
    rcat.definir_parametro(conn, "pct_noturno", "0.25", "2026-01-01")
    rcat.definir_parametro(conn, "pct_noturno", "0.30", "2099-01-01")  # futura

    assert rcat.parametro_vigente(conn, "pct_noturno", em="2025-06-01") == "0.20"
    assert rcat.parametro_vigente(conn, "pct_noturno", em="2026-07-15") == "0.25"
    assert rcat.parametro_vigente(conn, "inexistente") is None
    assert len(rcat.historico_parametro(conn, "pct_noturno")) == 3


def test_params_vigentes_monta_dataclass(conn):
    rcat.seed_inicial(conn)
    p = rcat.params_vigentes(conn)
    assert p.pct_noturno == Decimal("0.20")
    assert p.divisor_horas == 220
    assert rcat.param_int(conn, "valor_alimentacao_continuo") == 58000


def test_funcoes_crud(conn):
    fid = rcat.criar_funcao(conn, "Portaria noturna (12x36)", "continuo", 160000, aplica_noturno=True)
    f = rcat.obter_funcao(conn, fid)
    assert f["aplica_noturno"] == 1
    assert [r["id"] for r in rcat.listar_funcoes(conn, tipo="continuo")] == [fid]

    rcat.atualizar_funcao(conn, fid, valor_base_centavos=170000, ativa=0)
    assert rcat.listar_funcoes(conn, tipo="continuo") == []
    assert rcat.obter_funcao(conn, fid)["valor_base_centavos"] == 170000


def test_seed_idempotente(conn):
    rcat.seed_inicial(conn)
    rcat.seed_inicial(conn)
    assert rcat.parametro_vigente(conn, "empresa_nome") == "RS PORTARIA E SERVICOS"
    assert len(rcat.listar_funcoes(conn)) == 5
    assert len(rcat.historico_parametro(conn, "empresa_nome")) == 1


# ---- escalas ----
import pytest


def _escala(conn, nome):
    return [e for e in rcat.listar_escalas(conn) if e["nome"] == nome][0]


def test_seed_escalas(conn):
    rcat.seed_inicial(conn)
    esc = rcat.listar_escalas(conn)
    assert [e["nome"] for e in esc] == ["12x36", "6x1", "5x2", "4x3", "Diárias por escala", "Personalizado"]
    assert [e["modo"] for e in esc] == ["piso_mensal"] * 4 + ["diaria", "semanal"]
    assert [e["dias_mes"] for e in esc] == ["15", "26", "21.67", "17.33", None, None]
    assert rcat.escala_padrao(conn)["nome"] == "12x36"
    assert rcat.obter_escala(conn, esc[2]["id"])["nome"] == "5x2"


def test_seed_escalas_idempotente(conn):
    rcat.seed_inicial(conn)
    rcat.seed_inicial(conn)
    assert len(rcat.listar_escalas(conn)) == 6


def test_atualizar_escala(conn):
    rcat.seed_inicial(conn)
    eid = _escala(conn, "5x2")["id"]
    rcat.atualizar_escala(conn, eid, "diaria", Decimal("22"))
    e = rcat.obter_escala(conn, eid)
    assert (e["modo"], e["dias_mes"]) == ("diaria", "22")
    rcat.atualizar_escala(conn, eid, "diaria", None)
    assert rcat.obter_escala(conn, eid)["dias_mes"] is None


def test_atualizar_escala_rejeita(conn):
    rcat.seed_inicial(conn)
    with pytest.raises(ValueError):
        rcat.atualizar_escala(conn, _escala(conn, "Personalizado")["id"], "diaria", None)
    with pytest.raises(ValueError):
        rcat.atualizar_escala(conn, _escala(conn, "5x2")["id"], "semanal", None)
    with pytest.raises(ValueError):
        rcat.atualizar_escala(conn, _escala(conn, "5x2")["id"], "piso_mensal", Decimal("0"))


import sqlite3


def test_definir_parametros_transacional(conn):
    rcat.seed_inicial(conn)
    with pytest.raises(sqlite3.IntegrityError):
        rcat.definir_parametros(conn, {"pct_encargos": "0.6", None: "x"}, "2026-12-01")
    assert rcat.parametro_vigente(conn, "pct_encargos", em="2026-12-02") == "0.58"


def test_definir_parametros_mesma_vigencia(conn):
    rcat.seed_inicial(conn)
    rcat.definir_parametros(conn, {"pct_encargos": "0.6", "pct_margem": "0.12"}, "2026-12-01")
    for chave, valor in [("pct_encargos", "0.6"), ("pct_margem", "0.12")]:
        row = rcat.vigencia_atual(conn, chave, em="2026-12-01")
        assert (row["valor"], row["vigencia_inicio"]) == (valor, "2026-12-01")
