import pytest

from app.admin_secoes import SECOES, Campo, converter, exibir, secao

CHAVES_EDITAVEIS = {
    "pct_encargos", "pct_noturno", "pct_margem", "divisor_horas", "validade_dias",
    "valor_alimentacao_continuo", "valor_transporte_continuo", "valor_alimentacao_evento",
    "valor_transporte_evento", "empresa_nome", "empresa_cnpj", "empresa_endereco",
    "empresa_telefone", "empresa_email", "pagamento_pix", "pagamento_banco",
    "condicoes_continuo", "condicoes_evento", "condicoes_composicao_mensal",
    "obs_finais_continuo", "obs_finais_evento",
}


def test_toda_chave_editavel_esta_em_uma_secao():
    chaves = [c.chave for s in SECOES for c in s.campos]
    assert sorted(chaves) == sorted(CHAVES_EDITAVEIS)  # cada uma exatamente uma vez


def test_secao_desconhecida_cai_na_primeira():
    assert secao("nao-existe") is SECOES[0]
    assert secao("evento-calculo").titulo == "Cálculo por diária"


def test_exibir_e_converter_pct():
    c = Campo("pct_encargos", "Encargos", "pct")
    assert exibir(c, "0.58") == "58%" and converter(c, "60%") == "0.6"
    with pytest.raises(ValueError):
        converter(c, "0.58")


def test_converter_brl_e_int():
    assert converter(Campo("valor_alimentacao_continuo", "A", "brl"), "610,00") == "61000"
    assert exibir(Campo("valor_alimentacao_continuo", "A", "brl"), "58000") == "580,00"
    assert converter(Campo("validade_dias", "V", "int"), "45") == "45"
    for ruim in ["0", "-1", "abc"]:
        with pytest.raises(ValueError):
            converter(Campo("validade_dias", "V", "int"), ruim)


def test_converter_texto_preserva_e_rejeita_vazio():
    c = Campo("condicoes_evento", "C", "texto_longo")
    assert converter(c, "  Linha 1\nLinha 2  ") == "Linha 1\nLinha 2"
