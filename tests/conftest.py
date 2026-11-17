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
