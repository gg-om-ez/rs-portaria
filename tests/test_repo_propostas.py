from decimal import Decimal

import pytest

from app import repo_propostas as rp
from app.calc import Params

PARAMS = Params(Decimal("0.50"), Decimal("0.20"), Decimal("0.10"))


def _proposta_com_linhas(conn):
    pid = rp.criar_proposta(conn, "continuo")
    rp.inserir_linha(conn, pid, "Portaria noturna (12x36)", "mao_de_obra", 2, 100000)
    rp.inserir_linha(conn, pid, "Portaria diurna (12x36)", "mao_de_obra", 1, 80000)
    return pid


def test_criar_e_atualizar_dados(conn):
    pid = rp.criar_proposta(conn, "continuo")
    rp.atualizar_dados(conn, pid, {"endereco_servico": "Av. X, 100"})
    rp.atualizar_dados(conn, pid, {"duracao_meses": "12"})
    dados = rp.dados_de(rp.obter_proposta(conn, pid))
    assert dados == {"endereco_servico": "Av. X, 100", "duracao_meses": "12"}


def test_linhas_override_e_total(conn):
    pid = _proposta_com_linhas(conn)
    linhas = rp.linhas_da_proposta(conn, pid)
    assert rp.total_proposta(conn, pid) == 2 * 100000 + 80000

    alvo = linhas[0]["id"]
    rp.sobrescrever_linha(conn, alvo, 90000)
    linha = [r for r in rp.linhas_da_proposta(conn, pid) if r["id"] == alvo][0]
    assert linha["sobrescrito"] == 1 and linha["valor_final_centavos"] == 90000
    assert linha["valor_sugerido_centavos"] == 100000  # sugerido preservado
    assert rp.total_proposta(conn, pid) == 2 * 90000 + 80000

    rp.restaurar_linha(conn, alvo)
    linha = [r for r in rp.linhas_da_proposta(conn, pid) if r["id"] == alvo][0]
    assert linha["sobrescrito"] == 0 and linha["valor_final_centavos"] == 100000


def test_sincronizar_acessorios(conn):
    pid = _proposta_com_linhas(conn)  # 3 profissionais
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    acess = {r["descricao"]: r for r in rp.linhas_da_proposta(conn, pid) if r["categoria"] == "acessorio"}
    assert acess["Alimentação"]["quantidade"] == 3
    assert acess["Transporte"]["valor_final_centavos"] == 18000

    # sobrescreve alimentação e adiciona mais um profissional: quantidade muda, valor mantido
    rp.sobrescrever_linha(conn, acess["Alimentação"]["id"], 60000)
    rp.inserir_linha(conn, pid, "Auxiliar", "mao_de_obra", 1, 70000)
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    acess = {r["descricao"]: r for r in rp.linhas_da_proposta(conn, pid) if r["categoria"] == "acessorio"}
    assert acess["Alimentação"]["quantidade"] == 4
    assert acess["Alimentação"]["valor_final_centavos"] == 60000  # override respeitado


def test_recalcular_derivadas(conn):
    pid = _proposta_com_linhas(conn)  # mão de obra = 280.000
    rp.recalcular_derivadas(conn, pid, PARAMS)
    deriv = {r["descricao"]: r for r in rp.linhas_da_proposta(conn, pid) if r["categoria"] == "derivada"}
    assert deriv["Encargos sociais"]["valor_final_centavos"] == 140000        # 50% de 280.000
    assert deriv["Margem administrativa"]["valor_final_centavos"] == 42000    # 10% de 420.000

    # override na margem sobrevive a novo recálculo; encargos acompanham a base
    rp.sobrescrever_linha(conn, deriv["Margem administrativa"]["id"], 114000)
    rp.inserir_linha(conn, pid, "Extra", "mao_de_obra", 1, 20000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    deriv = {r["descricao"]: r for r in rp.linhas_da_proposta(conn, pid) if r["categoria"] == "derivada"}
    assert deriv["Encargos sociais"]["valor_final_centavos"] == 150000        # 50% de 300.000
    assert deriv["Margem administrativa"]["valor_final_centavos"] == 114000
    assert deriv["Margem administrativa"]["sobrescrito"] == 1


def test_duplicar_proposta(conn):
    pid = _proposta_com_linhas(conn)
    rp.atualizar_dados(conn, pid, {"endereco_servico": "Av. X"})
    novo = rp.duplicar_proposta(conn, pid)
    assert novo != pid
    nova_row = rp.obter_proposta(conn, novo)
    assert nova_row["status"] == "rascunho" and nova_row["numero"] is None
    assert rp.dados_de(nova_row)["endereco_servico"] == "Av. X"
    assert len(rp.linhas_da_proposta(conn, novo)) == 2


def test_nao_edita_proposta_emitida(conn):
    pid = rp.criar_proposta(conn, "evento")
    conn.execute("UPDATE propostas SET status = 'emitida' WHERE id = ?", (pid,))
    with pytest.raises(RuntimeError):
        rp.atualizar_dados(conn, pid, {"x": "1"})


def test_nao_muta_linhas_de_proposta_emitida(conn):
    pid = _proposta_com_linhas(conn)
    linha_id = rp.linhas_da_proposta(conn, pid)[0]["id"]
    conn.execute("UPDATE propostas SET status = 'emitida' WHERE id = ?", (pid,))
    with pytest.raises(RuntimeError):
        rp.sobrescrever_linha(conn, linha_id, 90000)
    with pytest.raises(RuntimeError):
        rp.restaurar_linha(conn, linha_id)
    with pytest.raises(RuntimeError):
        rp.remover_linha(conn, linha_id)


def test_linha_inexistente_levanta_valueerror(conn):
    with pytest.raises(ValueError):
        rp.sobrescrever_linha(conn, 9999, 100)
    with pytest.raises(ValueError):
        rp.restaurar_linha(conn, 9999)
    with pytest.raises(ValueError):
        rp.remover_linha(conn, 9999)


def test_atualizar_linha_mao_de_obra_preserva_override(conn):
    pid = _proposta_com_linhas(conn)
    linha_id = rp.linhas_da_proposta(conn, pid)[0]["id"]  # noturna, qtd 2, 100000

    rp.sobrescrever_linha(conn, linha_id, 90000)
    rp.atualizar_linha_mao_de_obra(conn, linha_id, 3, 105000)
    linha = [r for r in rp.linhas_da_proposta(conn, pid) if r["id"] == linha_id][0]
    assert linha["quantidade"] == 3
    assert linha["valor_sugerido_centavos"] == 105000  # sugerido sempre atualiza
    assert linha["valor_final_centavos"] == 90000       # override preservado
    assert linha["sobrescrito"] == 1

    rp.restaurar_linha(conn, linha_id)
    rp.atualizar_linha_mao_de_obra(conn, linha_id, 4, 110000)
    linha = [r for r in rp.linhas_da_proposta(conn, pid) if r["id"] == linha_id][0]
    assert linha["valor_final_centavos"] == 110000  # sem override, final acompanha sugerido


def test_linha_manual_fica_fora_das_bases_e_entra_no_total(conn):
    pid = _proposta_com_linhas(conn)  # mão de obra = 280.000
    rp.recalcular_derivadas(conn, pid, PARAMS)
    rp.inserir_linha(conn, pid, "Operacional", "manual", 1, 20800)
    rp.recalcular_derivadas(conn, pid, PARAMS)

    deriv = {r["descricao"]: r for r in rp.linhas_da_proposta(conn, pid) if r["categoria"] == "derivada"}
    assert deriv["Encargos sociais"]["valor_final_centavos"] == 140000     # base só mão de obra
    assert deriv["Margem administrativa"]["valor_final_centavos"] == 42000  # manual fora da base
    assert rp.total_proposta(conn, pid) == 280000 + 140000 + 42000 + 20800
    assert rp.linhas_da_proposta(conn, pid)[-1]["descricao"] == "Operacional"  # após derivadas


def test_linha_manual_sobrevive_a_sincronizacoes_sem_mao_de_obra(conn):
    pid = _proposta_com_linhas(conn)
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    rp.inserir_linha(conn, pid, "EPIs, trajes e material", "manual", 1, 16000)

    for r in rp.linhas_da_proposta(conn, pid):
        if r["categoria"] == "mao_de_obra":
            rp.remover_linha(conn, r["id"])
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)

    restantes = rp.linhas_da_proposta(conn, pid)
    assert [r["categoria"] for r in restantes] == ["manual"]
    assert rp.total_proposta(conn, pid) == 16000


def test_linha_manual_copiada_na_duplicacao(conn):
    pid = _proposta_com_linhas(conn)
    rp.inserir_linha(conn, pid, "Operacional", "manual", 1, 20800)
    novo = rp.duplicar_proposta(conn, pid)
    copiada = [r for r in rp.linhas_da_proposta(conn, novo) if r["categoria"] == "manual"]
    assert len(copiada) == 1
    assert copiada[0]["descricao"] == "Operacional"
    assert copiada[0]["valor_final_centavos"] == 20800


def test_derivadas_e_acessorios_somem_sem_mao_de_obra(conn):
    pid = _proposta_com_linhas(conn)
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    assert any(r["categoria"] == "acessorio" for r in rp.linhas_da_proposta(conn, pid))
    assert any(r["categoria"] == "derivada" for r in rp.linhas_da_proposta(conn, pid))

    for r in rp.linhas_da_proposta(conn, pid):
        if r["categoria"] == "mao_de_obra":
            rp.remover_linha(conn, r["id"])
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    assert rp.linhas_da_proposta(conn, pid) == []
    assert rp.total_proposta(conn, pid) == 0


# ---- linha manual percentual ----
from app import repo_catalogo as rcat


def _linha(conn, lid):
    return conn.execute("SELECT * FROM linhas_custo WHERE id = ?", (lid,)).fetchone()


def test_percentual_incide_sobre_linhas_fixas(conn):
    rcat.seed_inicial(conn)  # encargos 0.58, margem 0.10
    params = rcat.params_vigentes(conn)
    pid = rp.criar_proposta(conn, "continuo")
    rp.inserir_linha(conn, pid, "Portaria", "mao_de_obra", 1, 100000)
    rp.inserir_linha(conn, pid, "Operacional", "manual", 1, 10000)
    lid = rp.inserir_linha(conn, pid, "Taxa", "manual", 1, 0, percentual=Decimal("0.10"))
    rp.recalcular_derivadas(conn, pid, params)
    # 1.000,00 + encargos 580,00 + margem 158,00 + manual 100,00 = 1.838,00 -> 10% = 183,80
    assert _linha(conn, lid)["valor_final_centavos"] == 18380
    assert rp.total_proposta(conn, pid) == 202180


def test_percentuais_nao_se_compoem(conn):
    pid = rp.criar_proposta(conn, "continuo")
    rp.inserir_linha(conn, pid, "Fixa", "manual", 1, 325000)
    a = rp.inserir_linha(conn, pid, "ISS", "manual", 1, 0, percentual=Decimal("0.05"))
    b = rp.inserir_linha(conn, pid, "Outra", "manual", 1, 0, percentual=Decimal("0.02"))
    rp.recalcular_derivadas(conn, pid, PARAMS)
    assert [_linha(conn, a)["valor_final_centavos"], _linha(conn, b)["valor_final_centavos"]] == [16250, 6500]


def test_override_de_percentual_preservado(conn):
    pid = rp.criar_proposta(conn, "continuo")
    rp.inserir_linha(conn, pid, "Fixa", "manual", 1, 325000)
    lid = rp.inserir_linha(conn, pid, "ISS", "manual", 1, 0, percentual=Decimal("0.05"))
    rp.recalcular_derivadas(conn, pid, PARAMS)
    rp.sobrescrever_linha(conn, lid, 20000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    linha = _linha(conn, lid)
    assert linha["valor_final_centavos"] == 20000 and linha["sobrescrito"] == 1
    assert linha["valor_sugerido_centavos"] == 16250


def test_duplicar_preserva_percentual(conn):
    pid = rp.criar_proposta(conn, "continuo")
    rp.inserir_linha(conn, pid, "Fixa", "manual", 1, 325000)
    rp.inserir_linha(conn, pid, "ISS", "manual", 1, 0, percentual=Decimal("0.05"))
    rp.recalcular_derivadas(conn, pid, PARAMS)
    novo = rp.duplicar_proposta(conn, pid)
    linhas = {l["descricao"]: l for l in rp.linhas_da_proposta(conn, novo)}
    assert linhas["ISS"]["percentual"] == "0.05"
    rp.sobrescrever_linha(conn, linhas["Fixa"]["id"], 100000)
    rp.recalcular_derivadas(conn, novo, PARAMS)
    assert _linha(conn, linhas["ISS"]["id"])["valor_final_centavos"] == 5000


def test_modo_semanal_sem_acessorios_nem_derivadas(conn):
    pid = rp.criar_proposta(conn, "continuo")
    rp.atualizar_dados(conn, pid, {"modo_preco": "semanal"})
    rp.inserir_linha(conn, pid, "Portaria", "mao_de_obra", 1, 325000)
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    rp.inserir_linha(conn, pid, "ISS", "manual", 1, 0, percentual=Decimal("0.05"))
    rp.recalcular_derivadas(conn, pid, PARAMS)
    categorias = {l["categoria"] for l in rp.linhas_da_proposta(conn, pid)}
    assert categorias == {"mao_de_obra", "manual"}
    assert rp.total_proposta(conn, pid) == 341250


def test_trocar_para_semanal_remove_e_voltar_para_piso_recria(conn):
    pid = rp.criar_proposta(conn, "continuo")
    rp.inserir_linha(conn, pid, "Portaria", "mao_de_obra", 1, 160000)
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    rp.atualizar_dados(conn, pid, {"modo_preco": "semanal"})
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    assert {l["categoria"] for l in rp.linhas_da_proposta(conn, pid)} == {"mao_de_obra"}
    rp.atualizar_dados(conn, pid, {"modo_preco": "piso_mensal"})
    rp.sincronizar_acessorios(conn, pid, valor_alimentacao=58000, valor_transporte=18000)
    rp.recalcular_derivadas(conn, pid, PARAMS)
    descricoes = {l["descricao"] for l in rp.linhas_da_proposta(conn, pid)}
    assert {"Alimentação", "Transporte", "Encargos sociais", "Margem administrativa"} <= descricoes


# ---- lista com total, escala e filtros ----
from app import repo_clientes as rc


def _duas_propostas(conn):
    c1 = rc.criar_cliente(conn, "Cliente Exemplo Ltda", "11.222.333/0001-81", "Av. Exemplo, 1000")
    c2 = rc.criar_cliente(conn, "Empresa XYZ", "11.444.777/0001-61", "Rua X, 1")
    a = rp.criar_proposta(conn, "continuo")
    rp.definir_cliente(conn, a, c1)
    rp.atualizar_dados(conn, a, {"escala_nome": "5x2"})
    rp.inserir_linha(conn, a, "Portaria", "mao_de_obra", 2, 100000)
    b = rp.criar_proposta(conn, "evento")
    rp.definir_cliente(conn, b, c2)
    conn.execute("UPDATE propostas SET status = 'emitida', pdf_arquivado = 0 WHERE id = ?", (b,))
    conn.commit()
    return a, b


def test_listar_traz_total_e_escala(conn):
    a, b = _duas_propostas(conn)
    rows = {r["id"]: r for r in rp.listar_propostas(conn)}
    assert rows[a]["total_centavos"] == 200000 and rows[a]["escala_nome"] == "5x2"
    assert rows[b]["total_centavos"] == 0 and rows[b]["escala_nome"] is None


def test_listar_filtra_status_tipo_e_busca_juntos(conn):
    a, b = _duas_propostas(conn)
    assert [r["id"] for r in rp.listar_propostas(conn, "exemplo", status="rascunho", tipo="continuo")] == [a]
    assert rp.listar_propostas(conn, "exemplo", status="emitida") == []
    assert [r["id"] for r in rp.listar_propostas(conn, tipo="evento")] == [b]
    assert len(rp.listar_propostas(conn, status="invalido", tipo="xyz")) == 2


def test_contar_nao_arquivadas(conn):
    _duas_propostas(conn)
    assert rp.contar_nao_arquivadas(conn) == 1
