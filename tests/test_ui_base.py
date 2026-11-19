from app import db as dbmod


def _conn_do_client(tmp_path):
    c = dbmod.get_conn(tmp_path / "app.db")
    return c


def test_home_renderiza(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Nova proposta" in r.text


def test_criar_proposta_redireciona_para_wizard(client, tmp_path):
    r = client.post("/propostas/nova", data={"tipo": "continuo"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("/cliente")
    conn = _conn_do_client(tmp_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM propostas").fetchone()["n"] == 1


def test_lista_e_busca(client, tmp_path):
    client.post("/propostas/nova", data={"tipo": "evento"})
    r = client.get("/propostas")
    assert r.status_code == 200 and "evento" in r.text.lower()
    assert client.get("/propostas?q=zzz-inexistente").status_code == 200


def test_duplicar(client, tmp_path):
    client.post("/propostas/nova", data={"tipo": "continuo"})
    conn = _conn_do_client(tmp_path)
    pid = conn.execute("SELECT id FROM propostas").fetchone()["id"]
    r = client.post(f"/propostas/{pid}/duplicar", follow_redirects=False)
    assert r.status_code == 303
    assert conn.execute("SELECT COUNT(*) AS n FROM propostas").fetchone()["n"] == 2


# ---- cores só em tokens (rebranding troca o bloco :root) ----
import re
from pathlib import Path

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")


def _sem_root(css: str) -> str:
    return re.sub(r":root\s*\{[^}]*\}", "", css)


def test_style_css_so_usa_tokens():
    css = Path("app/static/style.css").read_text()
    assert _HEX.findall(_sem_root(css)) == []


def test_templates_sem_cor_literal():
    for t in Path("app/templates").rglob("*.html"):
        assert _HEX.findall(_sem_root(t.read_text())) == [], t


# ---- placeholders ----
_INPUT = re.compile(r"<input\b[^>]*>", re.S)
_TIPOS_COM_TEXTO = {"", "text", "search", "email"}


def _inputs_de_texto_sem_placeholder(html: str) -> list[str]:
    faltando = []
    for tag in _INPUT.findall(html):
        tipo = re.search(r'type="([^"]*)"', tag)
        if (tipo.group(1) if tipo else "") in _TIPOS_COM_TEXTO and "placeholder=" not in tag:
            faltando.append(tag)
    return faltando


def test_campos_de_texto_tem_placeholder(client):
    for tipo, etapas in [("continuo", ["cliente", "local", "pagamento"]), ("evento", ["local", "pagamento"])]:
        r = client.post("/propostas/nova", data={"tipo": tipo}, follow_redirects=False)
        pid = int(r.headers["location"].split("/")[2])
        for etapa in etapas:
            html = client.get(f"/propostas/{pid}/{etapa}").text
            assert _inputs_de_texto_sem_placeholder(html) == [], (tipo, etapa)


def test_local_nao_preenche_duracao(client):
    r = client.post("/propostas/nova", data={"tipo": "continuo"}, follow_redirects=False)
    pid = int(r.headers["location"].split("/")[2])
    html = client.get(f"/propostas/{pid}/local").text
    assert 'name="duracao_meses"' in html and 'value="12"' not in html
