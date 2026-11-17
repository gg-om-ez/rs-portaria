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


def test_etapa_servicos_gera_linhas(client, tmp_path):
    pid = _nova(client)
    conn = _conn(tmp_path)
    noturna = conn.execute(
        "SELECT id FROM funcoes WHERE nome LIKE 'Portaria noturna%'").fetchone()["id"]
    r = client.post(f"/propostas/{pid}/servicos", data={
        "hora_inicio_turno": "18:00", "hora_fim_turno": "06:00",
        "plantoes_mes": "15", "trajes": "Fardamento padrão da empresa prestadora",
        "observacoes": "", f"qtd_{noturna}": "2",
    }, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/custos")

    linhas = conn.execute(
        "SELECT * FROM linhas_custo WHERE proposta_id=? ORDER BY ordem", (pid,)).fetchall()
    categorias = [l["categoria"] for l in linhas]
    assert categorias.count("mao_de_obra") == 1
    assert "acessorio" in categorias and "derivada" in categorias
    mo = [l for l in linhas if l["categoria"] == "mao_de_obra"][0]
    assert mo["quantidade"] == 2
    # noturna 18h-06h com seed (piso 1.600,00, divisor 220, 20%, 15 plantões):
    # 120h x (160000/220) x 0.20 = 17.454,54... -> 17455 + 160000
    assert mo["valor_sugerido_centavos"] == 177455


def test_etapa_servicos_qtd_invalida_reexibe_com_erro(client, tmp_path):
    pid = _nova(client)
    conn = _conn(tmp_path)
    noturna = conn.execute(
        "SELECT id FROM funcoes WHERE nome LIKE 'Portaria noturna%'").fetchone()["id"]
    r = client.post(f"/propostas/{pid}/servicos", data={
        "hora_inicio_turno": "18:00", "hora_fim_turno": "06:00",
        "plantoes_mes": "15", "trajes": "Fardamento padrão da empresa prestadora",
        "observacoes": "", f"qtd_{noturna}": "abc",
    })
    assert r.status_code == 200
    assert "inválid" in r.text.lower()
    linhas = conn.execute(
        "SELECT * FROM linhas_custo WHERE proposta_id=?", (pid,)).fetchall()
    assert linhas == []  # nenhuma linha criada


def test_etapa_servicos_resubmissao_preserva_override(client, tmp_path):
    pid = _nova(client)
    conn = _conn(tmp_path)
    noturna = conn.execute(
        "SELECT id FROM funcoes WHERE nome LIKE 'Portaria noturna%'").fetchone()["id"]
    dados_form = {
        "hora_inicio_turno": "18:00", "hora_fim_turno": "06:00",
        "plantoes_mes": "15", "trajes": "Fardamento padrão da empresa prestadora",
        "observacoes": "", f"qtd_{noturna}": "2",
    }
    client.post(f"/propostas/{pid}/servicos", data=dados_form, follow_redirects=False)

    linha = conn.execute(
        "SELECT * FROM linhas_custo WHERE proposta_id=? AND categoria='mao_de_obra'",
        (pid,)).fetchone()
    client.post(f"/propostas/{pid}/linhas/{linha['id']}/valor", data={"valor": "1.900,00"})

    # re-submete a mesma etapa com a mesma função, mudando a quantidade
    dados_form[f"qtd_{noturna}"] = "3"
    r = client.post(f"/propostas/{pid}/servicos", data=dados_form, follow_redirects=False)
    assert r.status_code == 303

    linhas_mo = conn.execute(
        "SELECT * FROM linhas_custo WHERE proposta_id=? AND categoria='mao_de_obra'",
        (pid,)).fetchall()
    assert len(linhas_mo) == 1  # não duplicou a linha
    linha = linhas_mo[0]
    assert linha["quantidade"] == 3
    assert linha["sobrescrito"] == 1
    assert linha["valor_final_centavos"] == 190000  # override preservado
    assert linha["valor_sugerido_centavos"] == 177455  # sugerido recalculado


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


def test_servicos_normaliza_hora(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/servicos", data={
        "hora_inicio_turno": "6:00", "hora_fim_turno": "18h00",
        "plantoes_mes": "15", "trajes": "Fardamento padrão da empresa prestadora",
        "observacoes": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    dados = _dados(tmp_path, pid)
    assert dados["hora_inicio_turno"] == "06:00" and dados["hora_fim_turno"] == "18:00"


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


def test_servicos_personalizado_exemplo(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/servicos", data=_form_exemplo(tmp_path), follow_redirects=False)
    assert r.status_code == 303
    linhas = _linhas(tmp_path, pid)
    assert [l["categoria"] for l in linhas] == ["mao_de_obra"]
    assert (linhas[0]["valor_final_centavos"], linhas[0]["quantidade"]) == (325000, 1)
    dados = _dados(tmp_path, pid)
    assert len(dados["escala_semanal"]) == 4
    assert dados["escala_semanal"][0] == {"dia": "qua", "inicio": "09:00", "fim": "18:15", "valor_centavos": 20000}


def test_servicos_personalizado_sem_dia(client, tmp_path):
    pid = _nova(client)
    form = {k: v for k, v in _form_exemplo(tmp_path).items() if not k.endswith("_ativo")}
    r = client.post(f"/propostas/{pid}/servicos", data=form)
    assert r.status_code == 200 and "Ative pelo menos um dia da semana." in r.text
    assert 'name="dia_qua_inicio"' in r.text  # re-exibe com a escala submetida
    assert _linhas(tmp_path, pid) == []


def test_servicos_diaria_usa_dias_da_escala(client, tmp_path):
    e5x2 = _escala_id(tmp_path, "5x2")
    client.post(f"/admin/escalas/{e5x2}", data={"modo": "diaria", "dias_mes": "21,67"})
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/servicos", data={
        "escala_id": e5x2, "hora_inicio_turno": "09:00", "hora_fim_turno": "18:00",
        "valor_diaria": "200,00", "trajes": "Fardamento padrão da empresa prestadora",
        "observacoes": "", f"qtd_{_funcao_id(tmp_path, 'Portaria diurna')}": "1",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert [l["valor_final_centavos"] for l in _linhas(tmp_path, pid)] == [433400]


def test_servicos_diarias_por_escala_exige_dias(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/servicos", data={
        "escala_id": _escala_id(tmp_path, "Diárias por escala"), "hora_inicio_turno": "09:00",
        "hora_fim_turno": "18:00", "valor_diaria": "200,00", "plantoes_mes": "",
        "trajes": "Fardamento padrão da empresa prestadora", "observacoes": "",
    })
    assert r.status_code == 200 and "Dias trabalhados por mês inválido." in r.text


def test_trocar_modo_descarta_override(client, tmp_path):
    pid = _nova(client)
    diurna = _funcao_id(tmp_path, "Portaria diurna")
    client.post(f"/propostas/{pid}/servicos", data={
        "hora_inicio_turno": "07:00", "hora_fim_turno": "19:00", "plantoes_mes": "15",
        "trajes": "Fardamento padrão da empresa prestadora", "observacoes": "",
        f"qtd_{diurna}": "1"})
    mo = [l for l in _linhas(tmp_path, pid) if l["categoria"] == "mao_de_obra"][0]
    client.post(f"/propostas/{pid}/linhas/{mo['id']}/valor", data={"valor": "9.999,99"})
    client.post(f"/propostas/{pid}/servicos", data=_form_exemplo(tmp_path))
    mo = [l for l in _linhas(tmp_path, pid) if l["categoria"] == "mao_de_obra"][0]
    assert (mo["valor_final_centavos"], mo["sobrescrito"]) == (325000, 0)


def test_get_servicos_escala_por_query(client, tmp_path):
    pid = _nova(client)
    r = client.get(f"/propostas/{pid}/servicos?escala_id={_escala_id(tmp_path, 'Personalizado')}")
    assert 'name="dia_qua_ativo"' in r.text and 'id="campos-escala"' in r.text
    assert 'hx-select="#campos-escala"' in r.text
    padrao = client.get(f"/propostas/{pid}/servicos").text
    assert 'name="dia_qua_ativo"' not in padrao and 'name="hora_inicio_turno"' in padrao


def test_servicos_reabre_com_escala_salva(client, tmp_path):
    pid = _nova(client)
    client.post(f"/propostas/{pid}/servicos", data=_form_exemplo(tmp_path))
    r = client.get(f"/propostas/{pid}/servicos")
    assert 'name="dia_qua_ativo" style="width:auto" checked' in r.text
    assert 'value="200,00"' in r.text


def test_servicos_erro_reexibe_valores_digitados(client, tmp_path):
    pid = _nova(client)
    r = client.post(f"/propostas/{pid}/servicos", data={
        "escala_id": _escala_id(tmp_path, "Diárias por escala"), "hora_inicio_turno": "25:00",
        "hora_fim_turno": "18:00", "valor_diaria": "210,50", "plantoes_mes": "13",
        "trajes": "Fardamento padrão da empresa prestadora", "observacoes": "",
    })
    assert r.status_code == 200
    assert 'value="25:00"' in r.text and 'value="210,50"' in r.text and 'value="13"' in r.text
