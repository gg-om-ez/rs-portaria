import os

os.environ.setdefault("APP_PIN", "1234")
os.environ.setdefault("APP_SECRET", "segredo-de-teste")

import pytest

from app import db as dbmod

# Dados fictícios de empresa diferentes do seed: o checklist bloqueia a emissão
# enquanto os do seed estiverem vigentes
EMPRESA_FICTICIA = {
    "empresa_cnpj": "45.723.174/0001-10",
    "empresa_endereco": "Av. Fictícia, 500 - Centro, Cidade Teste - UF, 00000-000",
    "empresa_telefone": "(11) 90000-0000",
    "empresa_email": "contato@empresa-ficticia.com.br",
    "pagamento_pix": "pix@empresa-ficticia.com.br",
    "pagamento_banco": "Banco Fictício - Agência 1111, Conta 22222-3",
}


def configurar_empresa(conn) -> None:
    from app import repo_catalogo as rcat
    rcat.definir_parametros(conn, EMPRESA_FICTICIA, "2026-01-02")


@pytest.fixture
def conn(tmp_path):
    c = dbmod.get_conn(tmp_path / "teste.db")
    dbmod.init_db(c)
    yield c
    c.close()


def _novo_client(tmp_path, monkeypatch):
    monkeypatch.setenv("RSP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("RSP_ARQUIVO_DIR", str(tmp_path / "arquivo"))
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def client_sem_login(tmp_path, monkeypatch):
    return _novo_client(tmp_path, monkeypatch)


@pytest.fixture
def client(tmp_path, monkeypatch):
    tc = _novo_client(tmp_path, monkeypatch)
    tc.post("/login", data={"pin": "1234"})
    c = dbmod.get_conn(tmp_path / "app.db")
    configurar_empresa(c)
    c.close()
    return tc


def form_servicos(conn, cartoes: list[dict], trajes: str = "Fardamento padrão da empresa prestadora",
                  observacoes: str = "") -> dict:
    """Monta o POST da etapa Serviços (contínuo) com um cartão por função.

    Cada cartão: funcao (prefixo do nome no catálogo, ou "personalizada" com nome),
    qtd, escala (nome), e os campos da escala: hora_inicio_turno, hora_fim_turno,
    plantoes_mes, valor_diaria, piso, dias={"qua": ("09:00", "18:15", "200,00")}.
    """
    data = {"funcao": [], "trajes": trajes, "observacoes": observacoes}
    for i, c in enumerate(cartoes):
        chave = c.get("chave", f"c{i}")
        p = f"f_{chave}_"
        data["funcao"].append(chave)
        funcao = c.get("funcao", "Portaria diurna")
        if funcao == "personalizada":
            data[p + "funcao"] = "personalizada"
            data[p + "nome"] = c.get("nome", "")
        else:
            data[p + "funcao"] = str(conn.execute(
                "SELECT id FROM funcoes WHERE nome LIKE ?", (funcao + "%",)).fetchone()[0])
        data[p + "qtd"] = str(c.get("qtd", 1))
        data[p + "escala_id"] = str(conn.execute(
            "SELECT id FROM escalas WHERE nome = ?", (c.get("escala", "12x36"),)).fetchone()[0])
        if "dias" not in c:
            data[p + "hora_inicio_turno"] = c.get("hora_inicio_turno", "07:00")
            data[p + "hora_fim_turno"] = c.get("hora_fim_turno", "19:00")
        for campo in ("plantoes_mes", "valor_diaria", "piso"):
            if campo in c:
                data[p + campo] = c[campo]
        for dia, (ini, fim, valor) in c.get("dias", {}).items():
            data.update({p + f"dia_{dia}_ativo": "on", p + f"dia_{dia}_inicio": ini,
                         p + f"dia_{dia}_fim": fim, p + f"dia_{dia}_valor": valor})
    return data
