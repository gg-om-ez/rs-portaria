from app import db as dbmod


def _conn(tmp_path):
    return dbmod.get_conn(tmp_path / "app.db")


def test_admin_renderiza(client):
    r = client.get("/admin")
    assert r.status_code == 200 and "pct_encargos" in r.text


def _n_parametros(tmp_path):
    return _conn(tmp_path).execute("SELECT COUNT(*) FROM parametros").fetchone()[0]


def _vig(tmp_path, chave):
    return _conn(tmp_path).execute(
        "SELECT valor, vigencia_inicio FROM parametros WHERE chave = ? ORDER BY id DESC LIMIT 1",
        (chave,)).fetchone()


def test_lote_grava_todos_com_mesma_vigencia(client, tmp_path):
    antes = _n_parametros(tmp_path)
    r = client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "01/12/2026",
        "novo_pct_encargos": "60%", "novo_valor_alimentacao_continuo": "610,00",
        "novo_pct_noturno": ""}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin?secao=continuo-piso"
    assert tuple(_vig(tmp_path, "pct_encargos")) == ("0.6", "2026-12-01")
    assert tuple(_vig(tmp_path, "valor_alimentacao_continuo")) == ("61000", "2026-12-01")
    assert _n_parametros(tmp_path) == antes + 2  # noturno em branco não gera linha


def test_lote_ignora_valor_igual_ao_vigente(client, tmp_path):
    antes = _n_parametros(tmp_path)
    client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "01/12/2026",
        "novo_pct_encargos": "58%", "novo_pct_margem": "12"})
    assert _n_parametros(tmp_path) == antes + 1


def test_lote_com_campo_invalido_nao_grava_nada(client, tmp_path):
    antes = _n_parametros(tmp_path)
    r = client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "01/12/2026",
        "novo_pct_encargos": "60%", "novo_valor_alimentacao_continuo": "abc"})
    assert r.status_code == 200
    assert 'value="60%"' in r.text and 'value="abc"' in r.text and "Valor inválido" in r.text
    assert _n_parametros(tmp_path) == antes


def test_lote_rejeita_fracao_sem_porcento(client, tmp_path):
    antes = _n_parametros(tmp_path)
    r = client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "01/12/2026", "novo_pct_encargos": "0.58"})
    assert r.status_code == 200 and "Use 58 ou 58%" in r.text
    assert _n_parametros(tmp_path) == antes


def test_lote_sem_alteracao(client):
    r = client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "01/12/2026", "novo_pct_encargos": ""})
    assert r.status_code == 200 and "Nenhuma alteração para salvar." in r.text


def test_lote_vigencia_invalida(client, tmp_path):
    antes = _n_parametros(tmp_path)
    r = client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "2027-13-01", "novo_pct_encargos": "60%"})
    assert r.status_code == 200 and "Data de vigência inválida" in r.text
    assert _n_parametros(tmp_path) == antes


def test_lote_texto_preenchido_so_grava_se_mudou(client, tmp_path):
    antes = _n_parametros(tmp_path)
    client.post("/admin/parametros/lote", data={
        "secao": "empresa-dados", "vigencia_inicio": "01/12/2026",
        "novo_empresa_nome": "RS PORTARIA E SERVICOS", "novo_empresa_email": "novo@exemplo.com.br"})
    assert _n_parametros(tmp_path) == antes + 1
    assert _vig(tmp_path, "empresa_email")[0] == "novo@exemplo.com.br"


def test_admin_secao_mostra_vigente_e_desde(client):
    r = client.get("/admin?secao=continuo-piso")
    assert "Cálculo por piso mensal" in r.text and "58%" in r.text and "01/01/2026" in r.text
    assert 'name="novo_pct_encargos"' in r.text and "/static/admin.js" in r.text


def test_admin_menu_agrupa_por_modalidade(client):
    r = client.get("/admin")
    for t in ["Serviço contínuo", "Evento único", "Catálogo", "Empresa"]:
        assert t in r.text


def test_admin_catalogo_escalas_e_funcoes(client):
    assert "Personalizado" in client.get("/admin?secao=catalogo-escalas").text
    assert "Nova função" in client.get("/admin?secao=catalogo-funcoes").text


def test_criar_e_desativar_funcao(client, tmp_path):
    r = client.post("/admin/funcoes", data={
        "nome": "Recepcionista de evento (6h)", "tipo": "evento",
        "valor_base": "150,00",
    }, follow_redirects=False)
    assert r.status_code == 303
    conn = _conn(tmp_path)
    f = conn.execute("SELECT * FROM funcoes WHERE nome LIKE 'Recepcionista%'").fetchone()
    assert f["valor_base_centavos"] == 15000 and f["aplica_noturno"] == 0

    client.post(f"/admin/funcoes/{f['id']}", data={"valor_base": "180,00", "ativa": ""})
    f = conn.execute("SELECT * FROM funcoes WHERE id=?", (f["id"],)).fetchone()
    assert f["valor_base_centavos"] == 18000 and f["ativa"] == 0


def test_parametro_monetario_malformado_reexibe_erro(client, tmp_path):
    r = client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "01/07/2026",
        "novo_valor_alimentacao_continuo": "1,853,00",
    })
    assert r.status_code == 200 and "inválido" in r.text
    conn = _conn(tmp_path)
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM parametros WHERE chave='valor_alimentacao_continuo'"
    ).fetchone()["n"]
    assert n == 1  # só o seed; nada gravado


def test_parametro_chave_desconhecida_ignorada(client, tmp_path):
    # o lote só lê os campos da seção: chave fora dela nunca é gravada
    r = client.post("/admin/parametros/lote", data={
        "secao": "continuo-piso", "vigencia_inicio": "01/07/2026", "novo_chave_inexistente": "1",
    })
    assert r.status_code == 200 and "Nenhuma alteração para salvar." in r.text
    conn = _conn(tmp_path)
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM parametros WHERE chave='chave_inexistente'"
    ).fetchone()["n"]
    assert n == 0


def test_criar_funcao_valor_vazio_reexibe_erro(client, tmp_path):
    r = client.post("/admin/funcoes", data={
        "nome": "Vigia temporário", "tipo": "evento", "valor_base": "",
    })
    assert r.status_code == 200 and "inválido" in r.text
    conn = _conn(tmp_path)
    f = conn.execute("SELECT * FROM funcoes WHERE nome LIKE 'Vigia%'").fetchone()
    assert f is None


def _id_escala(tmp_path, nome):
    return _conn(tmp_path).execute("SELECT id FROM escalas WHERE nome = ?", (nome,)).fetchone()["id"]


def test_admin_atualiza_escala(client, tmp_path):
    eid = _id_escala(tmp_path, "5x2")
    r = client.post(f"/admin/escalas/{eid}", data={"modo": "diaria", "dias_mes": "21,67"},
                    follow_redirects=False)
    assert r.status_code == 303
    row = _conn(tmp_path).execute("SELECT modo, dias_mes FROM escalas WHERE id = ?", (eid,)).fetchone()
    assert (row["modo"], row["dias_mes"]) == ("diaria", "21.67")


def test_admin_escala_dias_invalidos(client, tmp_path):
    eid = _id_escala(tmp_path, "5x2")
    r = client.post(f"/admin/escalas/{eid}", data={"modo": "diaria", "dias_mes": "abc"})
    assert r.status_code == 200 and "Dias trabalhados por mês inválido." in r.text


def test_admin_lista_escalas(client):
    r = client.get("/admin?secao=catalogo-escalas")
    assert "Escalas" in r.text and "Personalizado" in r.text and "Diária fechada" in r.text
