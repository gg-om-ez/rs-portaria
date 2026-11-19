from app import db as dbmod


def _conn(tmp_path):
    return dbmod.get_conn(tmp_path / "app.db")


def _nova(client, tipo="continuo"):
    r = client.post("/propostas/nova", data={"tipo": tipo}, follow_redirects=False)
    return int(r.headers["location"].split("/")[2])


def test_etapa_cliente_criar_e_vincular(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/cliente/novo", data={
        "razao_social": "Cliente Exemplo Ltda", "cnpj": "11.222.333/0001-81",
        "endereco": "Av. Exemplo, 1000", "email": "x@y.com", "telefone": "",
    }, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/local")
    conn = _conn(tmp_path)
    assert conn.execute("SELECT cliente_id FROM propostas WHERE id=?", (pid,)).fetchone()[0]


def test_etapa_cliente_cnpj_invalido_reexibe_erro(client):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/cliente/novo", data={
        "razao_social": "X", "cnpj": "11.111.111/0001-00",
        "endereco": "E", "email": "", "telefone": "",
    })
    assert r.status_code == 200 and "CNPJ inválido" in r.text


def test_etapa_cliente_selecionar_existente(client, tmp_path):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/cliente/novo", data={
        "razao_social": "A", "cnpj": "11.444.777/0001-61",
        "endereco": "E", "email": "", "telefone": "",
    })
    pid2 = _nova(client)
    conn = _conn(tmp_path)
    cid = conn.execute("SELECT id FROM clientes").fetchone()["id"]
    r = client.post(f"/propostas/{pid2}/cliente", data={"cliente_id": cid},
                    follow_redirects=False)
    assert r.status_code == 303


def test_etapa_local_botao_endereco_cliente(client):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/cliente/novo", data={
        "razao_social": "A", "cnpj": "11.444.777/0001-61",
        "endereco": "Av. Exemplo, 1000", "email": "", "telefone": "",
    })
    r = client.get(f"/propostas/{pid}/local")
    # atributo onclick com aspas simples - tojson emite aspas duplas reais,
    # que quebrariam um atributo delimitado por aspas duplas
    assert r.status_code == 200
    assert "onclick='document.getElementById" in r.text


def test_etapa_local_continuo(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Empresa", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "12", "data_inicio": "2026-08-01",
    }, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/servicos")
    import json
    dados = json.loads(_conn(tmp_path).execute(
        "SELECT dados_json FROM propostas WHERE id=?", (pid,)).fetchone()[0])
    assert dados["duracao_meses"] == "12"


def test_etapa_local_data_invalida_reexibe_com_erro(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Empresa", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "12", "data_inicio": "banana",
    })
    assert r.status_code == 200
    assert "inválid" in r.text.lower()
    import json
    dados = json.loads(_conn(tmp_path).execute(
        "SELECT dados_json FROM propostas WHERE id=?", (pid,)).fetchone()[0])
    assert dados == {}  # dados_json não foi atualizado


def test_etapa_local_duracao_nao_numerica_reexibe_com_erro(client):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Empresa", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "abc", "data_inicio": "2026-08-01",
    })
    assert r.status_code == 200
    assert "inválid" in r.text.lower()


def test_etapa_local_evento_hora_invalida_reexibe_com_erro(client):
    pid = _nova(client, tipo="evento")
    r = client.post(f"/propostas/{pid}/local", data={
        "nome_evento": "Show", "endereco_servico": "Rua X, 1",
        "data_evento": "2026-08-01", "hora_inicio": "25:99", "hora_fim": "22:00",
    })
    assert r.status_code == 200
    assert "inválid" in r.text.lower()








def _linha_manual(conn, pid):
    return conn.execute(
        "SELECT * FROM linhas_custo WHERE proposta_id=? AND categoria='manual'",
        (pid,)).fetchall()


def test_adicionar_linha_manual(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/linhas/nova",
                    data={"descricao": "Operacional", "valor": "208,00"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/custos")
    linhas = _linha_manual(_conn(tmp_path), pid)
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha["descricao"] == "Operacional"
    assert linha["quantidade"] == 1
    assert linha["valor_final_centavos"] == 20800
    assert linha["valor_sugerido_centavos"] == 20800


def test_adicionar_linha_manual_htmx_devolve_parcial(client):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/linhas/nova",
                    data={"descricao": "Operacional", "valor": "208,00"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Operacional" in r.text
    assert "<html" not in r.text  # parcial, não a página inteira


def test_linha_manual_descricao_vazia_reexibe_erro(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/linhas/nova",
                    data={"descricao": "   ", "valor": "208,00"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Descrição é obrigatória" in r.text
    assert _linha_manual(_conn(tmp_path), pid) == []


def test_linha_manual_valor_ilegivel_reexibe_erro(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/linhas/nova",
                    data={"descricao": "Operacional", "valor": "banana"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Valor inválido" in r.text
    assert _linha_manual(_conn(tmp_path), pid) == []


def test_remover_linha_manual(client, tmp_path):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/linhas/nova",
                data={"descricao": "Operacional", "valor": "208,00"})
    conn = _conn(tmp_path)
    lid = _linha_manual(conn, pid)[0]["id"]
    r = client.post(f"/propostas/{pid}/linhas/{lid}/remover", follow_redirects=False)
    assert r.status_code == 303
    assert _linha_manual(conn, pid) == []


def test_remover_linha_nao_manual_eh_bloqueado(client, tmp_path):
    pid = _nova(client)
    conn = _conn(tmp_path)
    conn.execute(
        "INSERT INTO linhas_custo (proposta_id, descricao, categoria, quantidade,"
        " valor_sugerido_centavos, valor_final_centavos) VALUES (?, ?, ?, ?, ?, ?)",
        (pid, "Portaria diurna", "mao_de_obra", 1, 160000, 160000))
    conn.commit()
    lid = conn.execute("SELECT id FROM linhas_custo WHERE proposta_id=?", (pid,)).fetchone()["id"]
    r = client.post(f"/propostas/{pid}/linhas/{lid}/remover", follow_redirects=False)
    assert r.status_code == 404
    assert conn.execute(
        "SELECT COUNT(*) FROM linhas_custo WHERE proposta_id=?", (pid,)).fetchone()[0] == 1


def test_linha_manual_bloqueada_em_proposta_emitida(client, tmp_path):
    pid = _nova(client)
    conn = _conn(tmp_path)
    conn.execute("UPDATE propostas SET status='emitida' WHERE id=?", (pid,))
    conn.commit()
    r = client.post(f"/propostas/{pid}/linhas/nova",
                    data={"descricao": "Operacional", "valor": "208,00"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/emitida")
    assert _linha_manual(conn, pid) == []


def _dados(tmp_path, pid):
    import json
    return json.loads(_conn(tmp_path).execute(
        "SELECT dados_json FROM propostas WHERE id=?", (pid,)).fetchone()[0])


def test_local_aceita_data_br(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Empresa", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "12", "data_inicio": "01/08/2026",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert _dados(tmp_path, pid)["data_inicio"] == "2026-08-01"


def test_local_data_invalida(client):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Empresa", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "12", "data_inicio": "31/02/2026",
    })
    assert r.status_code == 200
    assert "Data de início inválida - use dd/mm/aaaa." in r.text




def test_pagamento_data_limite_br(client, tmp_path):
    pid = _nova(client, tipo="evento")
    r = client.post(f"/propostas/{pid}/pagamento", data={
        "formas_pagamento": "PIX", "data_limite_pagamento": "09/09/2026",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert _dados(tmp_path, pid)["data_limite_pagamento"] == "2026-09-09"


def test_pagamento_data_limite_invalida(client):
    pid = _nova(client, tipo="evento")
    r = client.post(f"/propostas/{pid}/pagamento", data={
        "formas_pagamento": "PIX", "data_limite_pagamento": "banana",
    })
    assert r.status_code == 200
    assert "Data-limite inválida - use dd/mm/aaaa." in r.text


def test_preview_mostra_data_br(client):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "Empresa", "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "12", "data_inicio": "2026-08-01",
    })
    r = client.get(f"/propostas/{pid}/preview")
    assert "01/08/2026" in r.text and "2026-08-01" not in r.text


def test_inputs_de_data_marcados_para_mascara(client):
    pid = _nova(client)
    r = client.get(f"/propostas/{pid}/local")
    assert 'data-campo="data"' in r.text and 'type="date"' in r.text


def test_base_carrega_campos_js(client):
    assert "/static/campos.js" in client.get("/").text


def test_adicionar_linha_percentual(client, tmp_path):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "Operacional", "valor": "1.000,00"})
    r = client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "ISS", "valor": "5%"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200 and "ISS (5%)" in r.text
    linha = [l for l in _linha_manual(_conn(tmp_path), pid) if l["descricao"] == "ISS"][0]
    assert linha["percentual"] == "0.05" and linha["valor_final_centavos"] == 5000


def test_remover_fixa_recalcula_percentual(client, tmp_path):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "Operacional", "valor": "1.000,00"})
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "ISS", "valor": "5%"})
    linhas = {l["descricao"]: l for l in _linha_manual(_conn(tmp_path), pid)}
    client.post(f"/propostas/{pid}/linhas/{linhas['Operacional']['id']}/remover")
    iss = [l for l in _linha_manual(_conn(tmp_path), pid) if l["descricao"] == "ISS"][0]
    assert iss["valor_final_centavos"] == 0


def test_linha_valor_invalido_mensagem(client):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "X", "valor": "abc"},
                    headers={"HX-Request": "true"})
    assert "Valor inválido - use 1.234,56 ou 5%." in r.text


# ---- menu de escalas ----
def _escala_id(tmp_path, nome):
    return _conn(tmp_path).execute("SELECT id FROM escalas WHERE nome = ?", (nome,)).fetchone()["id"]


def _funcao_id(tmp_path, prefixo):
    return _conn(tmp_path).execute(
        "SELECT id FROM funcoes WHERE nome LIKE ?", (prefixo + "%",)).fetchone()["id"]


def _form_exemplo(tmp_path):
    form = {"escala_id": _escala_id(tmp_path, "Personalizado"),
            "trajes": "Fardamento padrão da empresa prestadora", "observacoes": "",
            f"qtd_{_funcao_id(tmp_path, 'Portaria diurna')}": "1"}
    for d in ("qua", "qui", "sex"):
        form.update({f"dia_{d}_ativo": "on", f"dia_{d}_inicio": "09:00",
                     f"dia_{d}_fim": "18:15", f"dia_{d}_valor": "200,00"})
    form.update({"dia_sab_ativo": "on", "dia_sab_inicio": "08:30",
                 "dia_sab_fim": "14:00", "dia_sab_valor": "150,00"})
    return form


def _linhas(tmp_path, pid):
    return _conn(tmp_path).execute(
        "SELECT * FROM linhas_custo WHERE proposta_id=? ORDER BY ordem, id", (pid,)).fetchall()






















# ---- wizard em colunas ----
def _com_cliente(client):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/cliente/novo", data={
        "razao_social": "Cliente Exemplo Ltda", "cnpj": "11.222.333/0001-81",
        "endereco": "Av. Exemplo, 1000", "email": "", "telefone": ""})
    return pid


def test_etapas_verticais_com_estado(client):
    pid = _com_cliente(client)
    r = client.get(f"/propostas/{pid}/servicos")
    assert 'aria-label="Etapas"' in r.text and 'aria-current="step"' in r.text
    assert 'data-estado="ok"' in r.text and f'href="/propostas/{pid}/cliente"' in r.text


def test_resumo_lateral_mostra_total(client, tmp_path):
    pid = _com_cliente(client)
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "Operacional", "valor": "1.000,00"})
    r = client.get(f"/propostas/{pid}/local")
    assert "Resumo da proposta" in r.text and "1.000,00" in r.text and "Cliente Exemplo Ltda" in r.text


# ---- lista de propostas ----
def test_lista_mostra_colunas_e_aviso(client, tmp_path):
    pid = _com_cliente(client)
    conn = _conn(tmp_path)
    conn.execute("UPDATE propostas SET status = 'emitida', numero = 'RS-2026-0001', pdf_arquivado = 0"
                 " WHERE id = ?", (pid,))
    conn.commit()
    r = client.get("/propostas")
    for t in ["Total (R$)", "Escala", "Criada em", "12x36", "RS-2026-0001"]:
        assert t in r.text, t
    assert r.text.count("Regravar cópias não arquivadas") == 1


def test_lista_filtros_na_query(client):
    _com_cliente(client)
    r = client.get("/propostas?status=emitida")
    assert "Nada encontrado." in r.text and '<option value="emitida" selected' in r.text


# ---- Custos e Revisão no layout de desktop ----
def test_custos_colunas_origem_e_sugerido(client):
    pid = _com_cliente(client)
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "Operacional", "valor": "1.000,00"})
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "ISS", "valor": "5%"})
    r = client.get(f"/propostas/{pid}/custos")
    for t in ["Origem", "Sugerido", "Percentual", "Manual", "ISS (5%)"]:
        assert t in r.text, t


def test_htmx_atualiza_tabela_e_total(client):
    pid = _com_cliente(client)
    r = client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "Operacional", "valor": "100,00"},
                    headers={"HX-Request": "true"})
    assert "Total da proposta" in r.text and "Adicionar linha" in r.text and "100,00" in r.text
    assert "<html" not in r.text  # parcial, não a página


def test_revisao_lado_a_lado(client):
    pid = _com_cliente(client)
    r = client.get(f"/propostas/{pid}/revisao")
    assert 'class="revisao-colunas"' in r.text and 'target="_blank"' in r.text
    assert 'class="wizard-lateral"' not in r.text  # revisão usa a largura toda


# ---- minors das telas ----


def test_ok_sem_mudar_valor_nao_congela_percentual(client, tmp_path):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "Operacional", "valor": "1.000,00"})
    client.post(f"/propostas/{pid}/linhas/nova", data={"descricao": "ISS", "valor": "5%"})
    iss = [l for l in _linha_manual(_conn(tmp_path), pid) if l["descricao"] == "ISS"][0]
    client.post(f"/propostas/{pid}/linhas/{iss['id']}/valor", data={"valor": "50,00"})
    iss = [l for l in _linha_manual(_conn(tmp_path), pid) if l["descricao"] == "ISS"][0]
    assert iss["sobrescrito"] == 0


# ---- A informar / A combinar ----
def test_local_a_informar(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/local", data={
        "descricao_local": "", "endereco_servico": "", "duracao_meses": "", "data_inicio": "banana",
        "endereco_servico_sentinela": "on", "duracao_meses_sentinela": "on", "data_inicio_sentinela": "on",
    }, follow_redirects=False)
    assert r.status_code == 303
    d = _dados(tmp_path, pid)
    assert (d["endereco_servico"], d["duracao_meses"], d["data_inicio"]) == ("A informar",) * 3
    html = client.get(f"/propostas/{pid}/local").text
    assert 'name="data_inicio_sentinela" data-sentinela-de="data_inicio" checked' in html


def test_pagamento_a_combinar_continuo(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/pagamento", data={
        "formas_pagamento": "PIX", "formas_pagamento_sentinela": "on",
        "vencimento": "dia 5", "vencimento_sentinela": "on"}, follow_redirects=False)
    assert r.status_code == 303
    d = _dados(tmp_path, pid)
    assert (d["formas_pagamento"], d["vencimento"]) == ("A combinar", "A combinar")


def test_pagamento_a_combinar_evento(client, tmp_path):
    pid = _nova(client, tipo="evento")
    r = client.post(f"/propostas/{pid}/pagamento", data={
        "formas_pagamento": "PIX", "data_limite_pagamento": "banana",
        "data_limite_pagamento_sentinela": "on"}, follow_redirects=False)
    assert r.status_code == 303
    d = _dados(tmp_path, pid)
    assert (d["formas_pagamento"], d["data_limite_pagamento"]) == ("PIX", "A combinar")


# ---- excluir rascunho ----
def test_rota_excluir_confirma_e_redireciona(client, tmp_path):
    pid = _nova(client)
    r = client.get(f"/propostas/{pid}/excluir")
    assert r.status_code == 200 and "Esta ação não pode ser desfeita." in r.text
    r = client.post(f"/propostas/{pid}/excluir", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/propostas"
    assert _conn(tmp_path).execute("SELECT COUNT(*) FROM propostas WHERE id=?", (pid,)).fetchone()[0] == 0


def test_rota_excluir_emitida_nao_exclui(client, tmp_path):
    pid = _nova(client)
    conn = _conn(tmp_path)
    conn.execute("UPDATE propostas SET status='emitida', numero='RS-2026-0009' WHERE id=?", (pid,))
    conn.commit()
    r = client.post(f"/propostas/{pid}/excluir", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/emitida")
    assert conn.execute("SELECT COUNT(*) FROM propostas WHERE id=?", (pid,)).fetchone()[0] == 1


def test_etapas_tem_lixeira_so_em_rascunho(client, tmp_path):
    pid = _nova(client)
    html = client.get(f"/propostas/{pid}/cliente").text
    assert 'aria-label="Excluir rascunho"' in html and "<dialog" in html
    conn = _conn(tmp_path)
    conn.execute("UPDATE propostas SET status='emitida', numero='RS-2026-0010' WHERE id=?", (pid,))
    conn.commit()
    assert 'aria-label="Excluir rascunho"' not in client.get(f"/propostas/{pid}/cliente").text
