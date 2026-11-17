import pytest

from app import emissao, repo_catalogo as rcat, repo_clientes as rc, repo_propostas as rp
from app.pdf import render_documento_html


@pytest.fixture
def snapshot(conn):
    rcat.seed_inicial(conn)
    cid = rc.criar_cliente(conn, "Cliente Exemplo Ltda", "11.222.333/0001-81", "Av. Exemplo, 1000")
    pid = rp.criar_proposta(conn, "continuo")
    rp.definir_cliente(conn, pid, cid)
    rp.atualizar_dados(conn, pid, {
        "endereco_servico": "Av. Exemplo, 1000", "duracao_meses": "12",
        "data_inicio": "2026-08-01", "hora_inicio_turno": "18:00",
        "hora_fim_turno": "06:00", "formas_pagamento": "PIX", "vencimento": "dia 05",
    })
    rp.inserir_linha(conn, pid, "Portaria noturna (12x36)", "mao_de_obra", 2, 185300)
    rp.recalcular_derivadas(conn, pid, rcat.params_vigentes(conn))
    return emissao.montar_snapshot(conn, pid)


def test_html_contem_campos_criticos(snapshot):
    html = render_documento_html(snapshot)
    for trecho in [
        "RS PORTARIA E SERVICOS", "11.444.777/0001-61",
        "Cliente Exemplo Ltda", "11.222.333/0001-81",
        "Portaria noturna (12x36)", "1.853,00",
        "COMPOSIÇÃO DE CUSTOS", "CONDIÇÕES GERAIS", snapshot["total_fmt"],
    ]:
        assert trecho in html, f"faltando no documento: {trecho}"


def test_pdf_smoke(snapshot):
    pytest.importorskip("weasyprint")
    from app.pdf import gerar_pdf

    pdf = gerar_pdf(snapshot)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_html_escala_semanal(conn, snapshot):
    snapshot["escala"] = {
        "nome": "Personalizado", "modo": "semanal", "semanal_centavos": 75000, "mensal_centavos": 325000,
        "dias": [{"rotulo": "Qua", "inicio": "09:00", "fim": "18:15", "valor_centavos": 20000},
                 {"rotulo": "Sáb", "inicio": "08:30", "fim": "14:00", "valor_centavos": 15000}]}
    html = render_documento_html(snapshot)
    for trecho in ["Escala:", "Personalizado", "Qua", "09:00 às 18:15", "200,00", "750,00", "3.250,00",
                   "Mensal estimado"]:
        assert trecho in html, f"faltando no documento: {trecho}"
    assert "Turno de trabalho" not in html


def test_snapshot_legado_renderiza(snapshot):
    # snapshot congelado antes das escalas: sem "escala" e linhas sem percentual_fmt
    snapshot.pop("escala", None)
    for l in snapshot["linhas"]:
        l.pop("percentual_fmt", None)
    html = render_documento_html(snapshot)
    assert "Turno de trabalho" in html and "Escala:" not in html
