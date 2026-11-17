"""Etapa Serviços do contínuo: um cartão de função, cada um com sua escala."""
import json

from app import db as dbmod
from app import repo_propostas as rp
from tests.conftest import form_servicos

SEMANA_EXEMPLO = {d: ("09:00", "18:15", "200,00") for d in ("qua", "qui", "sex")}
SEMANA_EXEMPLO["sab"] = ("08:30", "14:00", "150,00")


def _conn(tmp_path):
    return dbmod.get_conn(tmp_path / "app.db")


def _nova(client):
    r = client.post("/propostas/nova", data={"tipo": "continuo"}, follow_redirects=False)
    return int(r.headers["location"].split("/")[2])


def _mo(conn, pid):
    return conn.execute("SELECT * FROM linhas_custo WHERE proposta_id=? AND categoria='mao_de_obra'"
                        " ORDER BY id", (pid,)).fetchall()


def _dados(conn, pid):
    return json.loads(conn.execute("SELECT dados_json FROM propostas WHERE id=?", (pid,)).fetchone()[0])


def _post(client, pid, data):
    return client.post(f"/propostas/{pid}/servicos", data=data, follow_redirects=False)


def test_gera_linhas_com_noturno(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    r = _post(client, pid, form_servicos(conn, [{"funcao": "Portaria noturna", "qtd": 2,
        "hora_inicio_turno": "18:00", "hora_fim_turno": "06:00", "plantoes_mes": "15"}]))
    assert r.status_code == 303 and r.headers["location"].endswith("/custos")
    cats = [l["categoria"] for l in conn.execute(
        "SELECT categoria FROM linhas_custo WHERE proposta_id=?", (pid,))]
    assert "acessorio" in cats and "derivada" in cats
    mo = _mo(conn, pid)
    assert len(mo) == 1 and mo[0]["quantidade"] == 2
    assert mo[0]["valor_sugerido_centavos"] == 177455  # 160000 + noturno 18h-06h, 15 plantões
    assert mo[0]["descricao"] == "Portaria noturna (12x36) - 12x36" and mo[0]["modo_preco"] == "piso_mensal"


def test_quantidade_invalida(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    r = _post(client, pid, form_servicos(conn, [{"qtd": "abc"}]))
    assert r.status_code == 200 and "Quantidade inválida" in r.text
    assert _mo(conn, pid) == []


def test_reenvio_preserva_override(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    cartao = {"funcao": "Portaria noturna", "qtd": 2, "hora_inicio_turno": "18:00",
              "hora_fim_turno": "06:00", "plantoes_mes": "15"}
    _post(client, pid, form_servicos(conn, [cartao]))
    client.post(f"/propostas/{pid}/linhas/{_mo(conn, pid)[0]['id']}/valor", data={"valor": "1.900,00"})
    _post(client, pid, form_servicos(conn, [{**cartao, "qtd": 3}]))
    mo = _mo(conn, pid)
    assert len(mo) == 1
    assert (mo[0]["quantidade"], mo[0]["sobrescrito"], mo[0]["valor_final_centavos"],
            mo[0]["valor_sugerido_centavos"]) == (3, 1, 190000, 177455)


def test_normaliza_hora(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    assert _post(client, pid, form_servicos(conn, [{"hora_inicio_turno": "6:00",
                                                   "hora_fim_turno": "18h00"}])).status_code == 303
    f = _dados(conn, pid)["funcoes"][0]
    assert (f["hora_inicio_turno"], f["hora_fim_turno"]) == ("06:00", "18:00")


def test_personalizado_exemplo(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{"escala": "Personalizado", "dias": SEMANA_EXEMPLO}]))
    cats = {l["categoria"] for l in conn.execute("SELECT categoria FROM linhas_custo WHERE proposta_id=?", (pid,))}
    assert cats == {"mao_de_obra"}
    assert _mo(conn, pid)[0]["valor_final_centavos"] == 325000
    f = _dados(conn, pid)["funcoes"][0]
    assert f["escala_semanal"][0] == {"dia": "qua", "inicio": "09:00", "fim": "18:15", "valor_centavos": 20000}
    assert "escala_id" not in _dados(conn, pid) or _dados(conn, pid)["escala_id"] is None


def test_personalizado_sem_dia(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    r = _post(client, pid, form_servicos(conn, [{"escala": "Personalizado", "dias": {}}]))
    assert r.status_code == 200 and "Ative pelo menos um dia da semana." in r.text
    assert 'name="f_c0_dia_qua_inicio"' in r.text and _mo(conn, pid) == []


def test_diaria_usa_dias_da_escala(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    e5x2 = conn.execute("SELECT id FROM escalas WHERE nome='5x2'").fetchone()[0]
    client.post(f"/admin/escalas/{e5x2}", data={"modo": "diaria", "dias_mes": "21,67"})
    _post(client, pid, form_servicos(conn, [{"escala": "5x2", "valor_diaria": "200,00"}]))
    mo = _mo(conn, pid)[0]
    assert (mo["valor_final_centavos"], mo["modo_preco"]) == (433400, "diaria")


def test_diarias_por_escala_exige_dias(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    r = _post(client, pid, form_servicos(conn, [{"escala": "Diárias por escala", "valor_diaria": "200,00",
                                                 "plantoes_mes": ""}]))
    assert r.status_code == 200 and "Dias trabalhados por mês inválido." in r.text


def test_trocar_modo_descarta_override(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{}]))
    client.post(f"/propostas/{pid}/linhas/{_mo(conn, pid)[0]['id']}/valor", data={"valor": "9.999,99"})
    _post(client, pid, form_servicos(conn, [{"escala": "Personalizado", "dias": SEMANA_EXEMPLO}]))
    mo = _mo(conn, pid)[0]
    assert (mo["valor_final_centavos"], mo["sobrescrito"]) == (325000, 0)


def test_trocar_escala_no_mesmo_modo_descarta_override(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{}]))
    client.post(f"/propostas/{pid}/linhas/{_mo(conn, pid)[0]['id']}/valor", data={"valor": "3.000,00"})
    _post(client, pid, form_servicos(conn, [{"escala": "6x1"}]))
    mo = _mo(conn, pid)[0]
    assert (mo["sobrescrito"], mo["valor_final_centavos"]) == (0, 160000)


def test_dois_cartoes_escalas_diferentes(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [
        {"funcao": "Portaria diurna"},
        {"funcao": "personalizada", "nome": "Jardineiro", "escala": "Personalizado",
         "dias": {"sab": ("08:00", "12:00", "150,00")}}]))
    mo = {l["descricao"]: l for l in _mo(conn, pid)}
    assert mo["Portaria diurna (12x36) - 12x36"]["valor_final_centavos"] == 160000
    assert mo["Jardineiro - Personalizado"]["valor_final_centavos"] == 65000
    assert mo["Jardineiro - Personalizado"]["funcao_id"] is None
    alim = conn.execute("SELECT quantidade FROM linhas_custo WHERE proposta_id=? AND descricao='Alimentação'",
                        (pid,)).fetchone()
    assert alim["quantidade"] == 1  # só a portaria (piso) conta


def test_mesma_funcao_duas_vezes(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    form = form_servicos(conn, [{}, {"escala": "Personalizado", "dias": {"sab": ("08:00", "12:00", "150,00")}}])
    _post(client, pid, form)
    mo = _mo(conn, pid)
    assert len(mo) == 2
    client.post(f"/propostas/{pid}/linhas/{mo[0]['id']}/valor", data={"valor": "1.700,00"})
    _post(client, pid, form)
    mo = _mo(conn, pid)
    assert len(mo) == 2 and (mo[0]["sobrescrito"], mo[0]["valor_final_centavos"]) == (1, 170000)


def test_cartao_com_quantidade_zero_e_ignorado(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{}, {"funcao": "Auxiliar", "qtd": 0}]))
    assert len(_mo(conn, pid)) == 1


def test_personalizada_sem_nome(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    r = _post(client, pid, form_servicos(conn, [{"funcao": "personalizada", "nome": "  "}]))
    assert r.status_code == 200 and "Informe o nome da função personalizada." in r.text


def test_personalizada_piso_sem_valor(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    r = _post(client, pid, form_servicos(conn, [{"funcao": "personalizada", "nome": "Jardineiro"}]))
    assert r.status_code == 200 and "Informe o piso mensal da função personalizada." in r.text


def test_personalizada_piso_com_valor(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{"funcao": "personalizada", "nome": "Jardineiro",
                                             "piso": "1.500,00"}]))
    mo = _mo(conn, pid)[0]
    assert (mo["descricao"], mo["valor_final_centavos"]) == ("Jardineiro - 12x36", 150000)


def test_get_cartao_novo(client, tmp_path):
    pid = _nova(client)
    r = client.get(f"/propostas/{pid}/servicos/funcao")
    assert r.status_code == 200 and 'class="cartao funcao-card"' in r.text
    assert 'name="funcao"' in r.text and "<html" not in r.text


def test_get_cartao_troca_escala_preserva_quantidade(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    form = form_servicos(conn, [{"escala": "Personalizado", "qtd": 3, "dias": {}}])
    form.pop("funcao"), form.pop("trajes"), form.pop("observacoes")
    r = client.get(f"/propostas/{pid}/servicos/funcao", params={"chave": "c0", **form})
    assert 'name="f_c0_dia_qua_ativo"' in r.text and 'name="f_c0_qtd" inputmode="numeric" value="3"' in r.text


def test_reabre_com_escala_salva(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{"escala": "Personalizado", "dias": SEMANA_EXEMPLO}]))
    html = client.get(f"/propostas/{pid}/servicos").text
    assert 'name="f_c0_dia_qua_ativo" style="width:auto" checked' in html and 'value="200,00"' in html


def test_erro_reexibe_valores_digitados(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    r = _post(client, pid, form_servicos(conn, [{"escala": "Diárias por escala", "hora_inicio_turno": "25:00",
                                                 "valor_diaria": "210,50", "plantoes_mes": "13"}]))
    assert r.status_code == 200
    assert 'value="25:00"' in r.text and 'value="210,50"' in r.text and 'value="13"' in r.text


def test_rascunho_legado_reexibe_dias_gravados(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    rp.atualizar_dados(conn, pid, {"hora_inicio_turno": "18:00", "hora_fim_turno": "06:00", "plantoes_mes": "16"})
    lid = rp.inserir_linha(conn, pid, "Portaria noturna (12x36)", "mao_de_obra", 1, 160000,
                           funcao_id=conn.execute("SELECT id FROM funcoes WHERE nome LIKE 'Portaria noturna%'").fetchone()[0])
    html = client.get(f"/propostas/{pid}/servicos").text
    assert f'name="f_l{lid}_plantoes_mes" inputmode="decimal" value="16"' in html


def test_rascunho_legado_reenvia_igual(client, tmp_path):
    """Review Focus 1: rascunho do formato antigo, com override, reenviado sem mudanças."""
    pid, conn = _nova(client), _conn(tmp_path)
    pers = conn.execute("SELECT id FROM escalas WHERE nome='Personalizado'").fetchone()[0]
    semana = [{"dia": "sab", "inicio": "08:00", "fim": "12:00", "valor_centavos": 15000}]
    rp.atualizar_dados(conn, pid, {"escala_id": str(pers), "escala_nome": "Personalizado",
                                   "modo_preco": "semanal", "escala_semanal": semana})
    diurna = conn.execute("SELECT id FROM funcoes WHERE nome LIKE 'Portaria diurna%'").fetchone()[0]
    lid = rp.inserir_linha(conn, pid, "Portaria diurna (12x36)", "mao_de_obra", 1, 65000, funcao_id=diurna)
    rp.sobrescrever_linha(conn, lid, 70000)
    form = form_servicos(conn, [{"chave": f"l{lid}", "escala": "Personalizado",
                                 "dias": {"sab": ("08:00", "12:00", "150,00")}}])
    assert _post(client, pid, form).status_code == 303
    mo = _mo(conn, pid)
    assert len(mo) == 1 and mo[0]["id"] == lid
    assert (mo[0]["sobrescrito"], mo[0]["valor_final_centavos"], mo[0]["chave_funcao"]) == (1, 70000, f"l{lid}")


# ---- correções da revisão final ----
def test_trocar_funcao_no_cartao_descarta_override(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{"funcao": "Portaria diurna"}]))
    client.post(f"/propostas/{pid}/linhas/{_mo(conn, pid)[0]['id']}/valor", data={"valor": "1.900,00"})
    _post(client, pid, form_servicos(conn, [{"funcao": "Auxiliar"}]))
    mo = _mo(conn, pid)[0]
    aux = conn.execute("SELECT id FROM funcoes WHERE nome LIKE 'Auxiliar%'").fetchone()[0]
    assert (mo["funcao_id"], mo["sobrescrito"], mo["valor_final_centavos"]) == (aux, 0, 151800)


def test_funcao_inativa_continua_selecionada(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    _post(client, pid, form_servicos(conn, [{"funcao": "Auxiliar"}]))
    aux = conn.execute("SELECT id FROM funcoes WHERE nome LIKE 'Auxiliar%'").fetchone()[0]
    conn.execute("UPDATE funcoes SET ativa = 0 WHERE id = ?", (aux,))
    conn.commit()
    html = client.get(f"/propostas/{pid}/servicos").text
    assert f'<option value="{aux}" selected' in html


def test_chave_maliciosa_nao_vira_html(client, tmp_path):
    pid = _nova(client)
    ruim = 'x" onfocus=alert(1) autofocus x="'
    r = client.get(f"/propostas/{pid}/servicos/funcao", params={"chave": ruim, f"f_{ruim}_qtd": "1"})
    assert r.status_code == 200 and "onfocus=alert(1)" not in r.text


def test_post_com_chave_invalida_e_recusado(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    form = form_servicos(conn, [{"chave": 'x"y'}])
    assert _post(client, pid, form).status_code == 422
    assert _mo(conn, pid) == []


def test_trocar_escala_sugere_dias_da_nova(client, tmp_path):
    pid, conn = _nova(client), _conn(tmp_path)
    form = form_servicos(conn, [{"escala": "6x1", "plantoes_mes": "15"}])
    form.pop("funcao"), form.pop("trajes"), form.pop("observacoes")
    r = client.get(f"/propostas/{pid}/servicos/funcao", params={"chave": "c0", "troca_escala": "1", **form})
    assert 'name="f_c0_plantoes_mes" inputmode="decimal" value="26"' in r.text
    r = client.get(f"/propostas/{pid}/servicos/funcao", params={"chave": "c0", **form})
    assert 'name="f_c0_plantoes_mes" inputmode="decimal" value="15"' in r.text  # sem troca, vale o digitado
