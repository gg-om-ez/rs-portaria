import json

from app import db as dbmod
from tests.conftest import form_servicos


def _conn(tmp_path):
    return dbmod.get_conn(tmp_path / "app.db")


def _fluxo_ate_custos(client, tmp_path):
    r = client.post("/propostas/nova", data={"tipo": "continuo"}, follow_redirects=False)
    pid = int(r.headers["location"].split("/")[2])
    client.post(f"/propostas/{pid}/cliente/novo", data={
        "razao_social": "Cliente Exemplo Ltda", "cnpj": "11.222.333/0001-81",
        "endereco": "Av. Exemplo, 1000", "email": "", "telefone": "",
    })
    client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Empresa", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "12", "data_inicio": "2026-08-01",
    })
    conn = _conn(tmp_path)
    client.post(f"/propostas/{pid}/servicos", data=form_servicos(conn, [{
        "funcao": "Portaria noturna", "qtd": 2, "hora_inicio_turno": "18:00",
        "hora_fim_turno": "06:00", "plantoes_mes": "15"}]))
    return pid, conn


def test_custos_override_e_restauracao(client, tmp_path):
    pid, conn = _fluxo_ate_custos(client, tmp_path)
    r = client.get(f"/propostas/{pid}/custos")
    assert r.status_code == 200 and "Portaria noturna" in r.text

    linha = conn.execute(
        "SELECT id FROM linhas_custo WHERE proposta_id=? AND categoria='mao_de_obra'",
        (pid,)).fetchone()["id"]
    r = client.post(f"/propostas/{pid}/linhas/{linha}/valor",
                    data={"valor": "1.853,00"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "sobrescrita" in r.text  # linha destacada
    row = conn.execute("SELECT * FROM linhas_custo WHERE id=?", (linha,)).fetchone()
    assert row["valor_final_centavos"] == 185300 and row["sobrescrito"] == 1

    client.post(f"/propostas/{pid}/linhas/{linha}/restaurar", headers={"HX-Request": "true"})
    row = conn.execute("SELECT * FROM linhas_custo WHERE id=?", (linha,)).fetchone()
    assert row["sobrescrito"] == 0


def test_emissao_bloqueada_sem_pagamento(client, tmp_path):
    pid, _ = _fluxo_ate_custos(client, tmp_path)
    r = client.get(f"/propostas/{pid}/revisao")
    assert "check-falha" in r.text
    r = client.post(f"/propostas/{pid}/emitir", follow_redirects=False)
    assert r.status_code == 200 and "pendências" in r.text.lower()


def test_fluxo_completo_ate_pdf(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.pdf.gerar_pdf", lambda s: b"%PDF-fake")
    pid, conn = _fluxo_ate_custos(client, tmp_path)
    client.post(f"/propostas/{pid}/pagamento", data={
        "formas_pagamento": ["PIX", "Transferência bancária"],
        "vencimento": "todo dia 05", "parcela_ingresso": "on",
    })
    r = client.get(f"/propostas/{pid}/revisao")
    assert "Emitir PDF" in r.text  # críticos todos ok -> botão liberado

    r = client.post(f"/propostas/{pid}/emitir", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/emitida")

    row = conn.execute("SELECT * FROM propostas WHERE id=?", (pid,)).fetchone()
    assert row["status"] == "emitida" and row["numero"].startswith("RS-")
    assert row["pdf_arquivado"] == 1
    snap = json.loads(row["snapshot_json"])
    assert snap["dados"]["parcela_ingresso"] == "sim"

    r = client.get(f"/propostas/{pid}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content == b"%PDF-fake"

    import pathlib, os
    arquivos = list(pathlib.Path(os.environ["RSP_ARQUIVO_DIR"]).glob("*.pdf"))
    assert len(arquivos) == 1 and arquivos[0].name.startswith(row["numero"])


def test_preview_rascunho(client, tmp_path):
    pid, _ = _fluxo_ate_custos(client, tmp_path)
    r = client.get(f"/propostas/{pid}/preview")
    assert r.status_code == 200 and "RASCUNHO" in r.text


def test_valor_com_linha_de_outra_proposta_da_404(client, tmp_path):
    pid_a, conn = _fluxo_ate_custos(client, tmp_path)
    pid_b, _ = _fluxo_ate_custos(client, tmp_path)
    linha_b = conn.execute(
        "SELECT id FROM linhas_custo WHERE proposta_id=? AND categoria='mao_de_obra'",
        (pid_b,)).fetchone()["id"]
    antes = conn.execute(
        "SELECT valor_final_centavos, sobrescrito FROM linhas_custo WHERE id=?",
        (linha_b,)).fetchone()

    # tenta mutar a linha da proposta B através da proposta A
    r = client.post(f"/propostas/{pid_a}/linhas/{linha_b}/valor",
                    data={"valor": "9.999,00"}, headers={"HX-Request": "true"})
    assert r.status_code == 404

    depois = conn.execute(
        "SELECT valor_final_centavos, sobrescrito FROM linhas_custo WHERE id=?",
        (linha_b,)).fetchone()
    assert depois["valor_final_centavos"] == antes["valor_final_centavos"]
    assert depois["sobrescrito"] == antes["sobrescrito"]

    r = client.post(f"/propostas/{pid_a}/linhas/{linha_b}/restaurar",
                    headers={"HX-Request": "true"})
    assert r.status_code == 404


def _emitir_proposta(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.pdf.gerar_pdf", lambda s: b"%PDF-fake")
    pid, conn = _fluxo_ate_custos(client, tmp_path)
    client.post(f"/propostas/{pid}/pagamento", data={
        "formas_pagamento": ["PIX"], "vencimento": "todo dia 05",
    })
    client.post(f"/propostas/{pid}/emitir", follow_redirects=False)
    return pid, conn


def test_mutacao_de_linha_em_proposta_emitida_redireciona(client, tmp_path, monkeypatch):
    pid, conn = _emitir_proposta(client, tmp_path, monkeypatch)
    linha = conn.execute(
        "SELECT id FROM linhas_custo WHERE proposta_id=? AND categoria='mao_de_obra'",
        (pid,)).fetchone()["id"]
    antes = conn.execute(
        "SELECT valor_final_centavos, sobrescrito FROM linhas_custo WHERE id=?",
        (linha,)).fetchone()

    r = client.post(f"/propostas/{pid}/linhas/{linha}/valor",
                    data={"valor": "9.999,00"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/emitida")

    r = client.post(f"/propostas/{pid}/linhas/{linha}/restaurar", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/emitida")

    depois = conn.execute(
        "SELECT valor_final_centavos, sobrescrito FROM linhas_custo WHERE id=?",
        (linha,)).fetchone()
    assert depois["valor_final_centavos"] == antes["valor_final_centavos"]
    assert depois["sobrescrito"] == antes["sobrescrito"]


def test_fluxo_escala_personalizada_ate_pdf(client, tmp_path, monkeypatch):
    """Caso que motivou as escalas: Qua-Sex 09:00-18:15 a R$ 200,00/dia e
    Sáb 08:30-14:00 a R$ 150,00/dia, 1 profissional, mais ISS de 5%."""
    monkeypatch.setattr("app.pdf.gerar_pdf", lambda s: b"%PDF-fake")
    r = client.post("/propostas/nova", data={"tipo": "continuo"}, follow_redirects=False)
    pid = int(r.headers["location"].split("/")[2])
    client.post(f"/propostas/{pid}/cliente/novo", data={
        "razao_social": "Cliente Exemplo Ltda", "cnpj": "11.222.333/0001-81",
        "endereco": "Av. Exemplo, 1000", "email": "", "telefone": "",
    })
    client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Loja", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "6", "data_inicio": "01/12/2026",
    })
    conn = _conn(tmp_path)
    dias = {d: ("09:00", "18:15", "200,00") for d in ("qua", "qui", "sex")}
    dias["sab"] = ("08:30", "14:00", "150,00")
    form = form_servicos(conn, [{"funcao": "Portaria diurna", "escala": "Personalizado", "dias": dias}])
    assert client.post(f"/propostas/{pid}/servicos", data=form,
                       follow_redirects=False).status_code == 303
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "ISS", "valor": "5%"})
    client.post(f"/propostas/{pid}/pagamento", data={
        "formas_pagamento": ["PIX"], "vencimento": "todo dia 05"})

    r = client.post(f"/propostas/{pid}/emitir", follow_redirects=False)
    assert r.status_code == 303

    snap = json.loads(conn.execute(
        "SELECT snapshot_json FROM propostas WHERE id=?", (pid,)).fetchone()[0])
    assert snap["total_centavos"] == 341250 and snap["total_fmt"] == "3.412,50"
    assert snap["dados"]["data_inicio"] == "2026-12-01"
    assert {l["categoria"] for l in snap["linhas"]} == {"mao_de_obra", "manual"}
    # escalas por função no snapshot: conferidas na Task 6 (formato "escalas")


def test_emitir_bloqueado_com_dados_de_exemplo(client, tmp_path):
    from app import repo_catalogo as rcat
    pid, conn = _fluxo_ate_custos(client, tmp_path)
    client.post(f"/propostas/{pid}/pagamento", data={"formas_pagamento": ["PIX"], "vencimento": "dia 05"})
    # volta um campo ao valor de exemplo do seed
    rcat.definir_parametro(conn, "pagamento_pix", "chave-pix@exemplo.com.br", "2026-01-03")
    r = client.post(f"/propostas/{pid}/emitir", follow_redirects=False)
    assert r.status_code == 200 and "Dados da empresa configurados" in r.text
