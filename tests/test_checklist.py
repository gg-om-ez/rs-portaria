import pytest

from app import checklist, repo_clientes as rc, repo_propostas as rp


def _completa_continuo(conn):
    cid = rc.criar_cliente(conn, "Cliente Exemplo", "11.222.333/0001-81", "Av. Exemplo, 1000")
    pid = rp.criar_proposta(conn, "continuo")
    rp.definir_cliente(conn, pid, cid)
    rp.atualizar_dados(conn, pid, {
        "endereco_servico": "Av. Exemplo, 1000",
        "duracao_meses": "12",
        "data_inicio": "2026-08-01",
        "hora_inicio_turno": "18:00",
        "hora_fim_turno": "06:00",
        "formas_pagamento": "PIX",
        "vencimento": "todo dia 05",
    })
    rp.inserir_linha(conn, pid, "Portaria noturna", "mao_de_obra", 2, 100000)
    return pid


def test_proposta_completa_pode_emitir(conn):
    pid = _completa_continuo(conn)
    itens = checklist.avaliar(conn, pid)
    assert checklist.pode_emitir(itens) is True
    assert all(i.ok for i in itens if i.critico)


def test_sem_cliente_bloqueia(conn):
    pid = rp.criar_proposta(conn, "continuo")
    itens = checklist.avaliar(conn, pid)
    assert checklist.pode_emitir(itens) is False


def test_sem_linha_de_mao_de_obra_bloqueia(conn):
    pid = _completa_continuo(conn)
    for linha in rp.linhas_da_proposta(conn, pid):
        rp.remover_linha(conn, linha["id"])
    assert checklist.pode_emitir(checklist.avaliar(conn, pid)) is False


def test_evento_exige_data_limite(conn):
    cid = rc.criar_cliente(conn, "XYZ", "11.444.777/0001-61", "End.")
    pid = rp.criar_proposta(conn, "evento")
    rp.definir_cliente(conn, pid, cid)
    rp.atualizar_dados(conn, pid, {
        "endereco_servico": "Local do evento",
        "data_evento": "2026-09-10",
        "hora_inicio": "18:00",
        "hora_fim": "02:00",
        "formas_pagamento": "PIX",
    })
    rp.inserir_linha(conn, pid, "Segurança", "mao_de_obra", 6, 22000)
    assert checklist.pode_emitir(checklist.avaliar(conn, pid)) is False  # falta data_limite_pagamento

    rp.atualizar_dados(conn, pid, {"data_limite_pagamento": "2026-09-09"})
    assert checklist.pode_emitir(checklist.avaliar(conn, pid)) is True


def test_observacoes_nao_critico(conn):
    pid = _completa_continuo(conn)
    itens = {i.rotulo: i for i in checklist.avaliar(conn, pid)}
    obs = itens["Observações preenchidas"]
    assert obs.ok is False and obs.critico is False


def test_campo_none_conta_como_vazio(conn):
    # Campo explicitamente limpo (None no dados_json) não pode passar no checklist
    pid = _completa_continuo(conn)
    rp.atualizar_dados(conn, pid, {"endereco_servico": None})
    itens = {i.rotulo: i for i in checklist.avaliar(conn, pid)}
    assert itens["Endereço do serviço informado"].ok is False
    assert checklist.pode_emitir(list(itens.values())) is False


def test_avaliar_proposta_inexistente(conn):
    with pytest.raises(ValueError):
        checklist.avaliar(conn, 99999)


# ---- por modo de escala ----
SEMANA = [{"dia": "qua", "inicio": "09:00", "fim": "18:15", "valor_centavos": 20000}]


def _rotulos(conn, pid):
    return {i.rotulo: i for i in checklist.avaliar(conn, pid)}


def test_semanal_exige_dia_ativo(conn):
    pid = _completa_continuo(conn)
    rp.atualizar_dados(conn, pid, {"modo_preco": "semanal", "escala_semanal": [],
                                   "hora_inicio_turno": "", "hora_fim_turno": ""})
    itens = _rotulos(conn, pid)
    item = itens["Pelo menos um dia ativo na escala"]
    assert item.critico and not item.ok
    assert "Horários do turno definidos" not in itens
    rp.atualizar_dados(conn, pid, {"escala_semanal": SEMANA})
    assert checklist.pode_emitir(checklist.avaliar(conn, pid)) is True


def test_diaria_exige_valor_e_dias(conn):
    pid = _completa_continuo(conn)
    rp.atualizar_dados(conn, pid, {"modo_preco": "diaria"})
    item = _rotulos(conn, pid)["Valor da diária e dias por mês"]
    assert item.critico and not item.ok
    rp.atualizar_dados(conn, pid, {"valor_diaria_centavos": 20000, "plantoes_mes": "21.67"})
    assert _rotulos(conn, pid)["Valor da diária e dias por mês"].ok


def test_piso_e_legado_mantem_turno(conn):
    pid = _completa_continuo(conn)
    itens = _rotulos(conn, pid)
    assert "Horários do turno definidos" in itens
    assert "Pelo menos um dia ativo na escala" not in itens


# ---- estado por etapa (navegação vertical) ----
from app.routes.propostas import ETAPAS


def test_estado_etapas_nova_proposta_sem_pendencia_futura(conn):
    pid = rp.criar_proposta(conn, "continuo")
    est = checklist.estado_etapas(checklist.avaliar(conn, pid), ETAPAS, "cliente")
    assert set(est.values()) == {""}


def test_estado_etapas_marca_pendencia_anterior(conn):
    pid = _completa_continuo(conn)
    rp.atualizar_dados(conn, pid, {"formas_pagamento": ""})
    est = checklist.estado_etapas(checklist.avaliar(conn, pid), ETAPAS, "revisao")
    assert est["pagamento"] == "pendente" and est["cliente"] == "ok" and est["custos"] == ""


def test_estado_etapas_futura_nao_ok_fica_vazia(conn):
    pid = _completa_continuo(conn)
    rp.atualizar_dados(conn, pid, {"formas_pagamento": ""})
    est = checklist.estado_etapas(checklist.avaliar(conn, pid), ETAPAS, "servicos")
    assert est["pagamento"] == "" and est["local"] == "ok"


def test_todo_item_tem_etapa(conn):
    pid = _completa_continuo(conn)
    assert all(i.etapa in ETAPAS for i in checklist.avaliar(conn, pid))


def test_checklist_aceita_sentinelas(conn):
    pid = _completa_continuo(conn)
    rp.atualizar_dados(conn, pid, {
        "endereco_servico": "A informar", "duracao_meses": "A informar", "data_inicio": "A informar",
        "formas_pagamento": "A combinar", "vencimento": "A combinar"})
    assert checklist.pode_emitir(checklist.avaliar(conn, pid)) is True


# ---- dados de exemplo da empresa ----
from app import repo_catalogo as rcat
from tests.conftest import configurar_empresa

ROTULO_EMPRESA = "Dados da empresa configurados (Configurações > Empresa)"


def test_bloqueia_emissao_com_dados_de_exemplo(conn):
    rcat.seed_inicial(conn)
    pid = _completa_continuo(conn)
    item = _rotulos(conn, pid)[ROTULO_EMPRESA]
    assert item.critico and not item.ok and item.etapa == "revisao"
    assert checklist.pode_emitir(checklist.avaliar(conn, pid)) is False


def test_nome_igual_ao_seed_nao_bloqueia(conn):
    rcat.seed_inicial(conn)
    configurar_empresa(conn)  # não mexe no nome
    assert rcat.parametro_vigente(conn, "empresa_nome") == "RS PORTARIA E SERVICOS"
    pid = _completa_continuo(conn)
    assert _rotulos(conn, pid)[ROTULO_EMPRESA].ok
    assert rcat.empresa_com_dados_de_exemplo(conn) == []
