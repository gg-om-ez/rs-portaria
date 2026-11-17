from decimal import Decimal

from app import escalas
from app.calc import Params

P = Params(Decimal("0.58"), Decimal("0.20"), Decimal("0.10"))
SEMANA = [{"dia": d, "inicio": "09:00", "fim": "18:15", "valor_centavos": 20000}
          for d in ("qua", "qui", "sex")] + \
         [{"dia": "sab", "inicio": "08:30", "fim": "14:00", "valor_centavos": 15000}]
SEM_NOTURNO = {"valor_base_centavos": 160000, "aplica_noturno": 0}


def test_dias_semana_ordem():
    assert [k for k, _ in escalas.DIAS_SEMANA] == ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def test_modo_de_padrao_piso():
    assert escalas.modo_de({}) == "piso_mensal"
    assert escalas.modo_de({"modo_preco": "semanal"}) == "semanal"


def test_modo_da_linha():
    linha = lambda m: {"modo_preco": m}
    assert escalas.modo_da_linha(linha("diaria"), "continuo", {"modo_preco": "semanal"}) == "diaria"
    assert escalas.modo_da_linha(linha(None), "continuo", {"modo_preco": "semanal"}) == "semanal"
    assert escalas.modo_da_linha(linha(None), "continuo", {}) == "piso_mensal"
    assert escalas.modo_da_linha(linha(None), "evento", {"modo_preco": "semanal"}) == "piso_mensal"


def test_valor_semanal():
    assert escalas.valor_semanal({"escala_semanal": SEMANA}) == 75000
    assert escalas.valor_semanal({}) == 0


def test_sugerido_piso_sem_noturno():
    dados = {"modo_preco": "piso_mensal", "hora_inicio_turno": "07:00",
             "hora_fim_turno": "19:00", "plantoes_mes": "15"}
    assert escalas.sugerido_mensal(dados, P, SEM_NOTURNO) == 160000


def test_sugerido_piso_noturno_igual_ao_calculo_original():
    noturna = {"valor_base_centavos": 160000, "aplica_noturno": 1}
    dados = {"hora_inicio_turno": "18:00", "hora_fim_turno": "06:00", "plantoes_mes": "15"}
    assert escalas.sugerido_mensal(dados, P, noturna) == 177455
    sem_plantoes = {"hora_inicio_turno": "18:00", "hora_fim_turno": "06:00"}
    assert escalas.sugerido_mensal(sem_plantoes, P, noturna) == 177455


def test_sugerido_semanal():
    assert escalas.sugerido_mensal({"modo_preco": "semanal", "escala_semanal": SEMANA}, P, SEM_NOTURNO) == 325000


def test_sugerido_diaria():
    dados = {"modo_preco": "diaria", "valor_diaria_centavos": 20000, "plantoes_mes": "21.67"}
    assert escalas.sugerido_mensal(dados, P, SEM_NOTURNO) == 433400


# ---- ler_form_escala ----
import pytest

PERSONALIZADO = {"id": 6, "nome": "Personalizado", "modo": "semanal", "dias_mes": None}
E12X36 = {"id": 1, "nome": "12x36", "modo": "piso_mensal", "dias_mes": "15"}
DIARIAS = {"id": 5, "nome": "Diárias por escala", "modo": "diaria", "dias_mes": None}
E5X2_DIARIA = {"id": 3, "nome": "5x2", "modo": "diaria", "dias_mes": "21.67"}

FORM_EXEMPLO = {
    **{f"dia_{d}_{c}": v for d in ("qua", "qui", "sex")
       for c, v in (("ativo", "on"), ("inicio", "09:00"), ("fim", "18:15"), ("valor", "200,00"))},
    "dia_sab_ativo": "on", "dia_sab_inicio": "08:30", "dia_sab_fim": "14:00", "dia_sab_valor": "150,00",
    "dia_seg_inicio": "07:00",  # dia inativo: campos ignorados
}


def test_ler_form_personalizado():
    dados, erro = escalas.ler_form_escala(PERSONALIZADO, FORM_EXEMPLO)
    assert erro is None
    assert (dados["escala_id"], dados["escala_nome"], dados["modo_preco"]) == ("6", "Personalizado", "semanal")
    assert dados["escala_semanal"] == SEMANA


@pytest.mark.parametrize("ajuste,mensagem", [
    ({k: v for k, v in FORM_EXEMPLO.items() if not k.endswith("_ativo")}, "Ative pelo menos um dia da semana."),
    ({**FORM_EXEMPLO, "dia_sab_fim": "25:00"}, "Horário inválido em Sáb."),
    ({**FORM_EXEMPLO, "dia_qua_valor": "0"}, "Valor inválido em Qua."),
    ({**FORM_EXEMPLO, "dia_qui_valor": "abc"}, "Valor inválido em Qui."),
])
def test_ler_form_personalizado_erros(ajuste, mensagem):
    assert escalas.ler_form_escala(PERSONALIZADO, ajuste)[1] == mensagem


def test_ler_form_piso_usa_dias_da_escala():
    dados, erro = escalas.ler_form_escala(E12X36, {"hora_inicio_turno": "6:00", "hora_fim_turno": "18:00"})
    assert erro is None
    assert dados["plantoes_mes"] == "15" and dados["hora_inicio_turno"] == "06:00"


def test_ler_form_diaria():
    dados, erro = escalas.ler_form_escala(E5X2_DIARIA, {
        "hora_inicio_turno": "09:00", "hora_fim_turno": "18:00", "valor_diaria": "200,00"})
    assert erro is None
    assert (dados["valor_diaria_centavos"], dados["plantoes_mes"]) == (20000, "21.67")


@pytest.mark.parametrize("escala,form,mensagem", [
    (E12X36, {"hora_inicio_turno": "x", "hora_fim_turno": "18:00"},
     "Horário de início do turno inválido - use HH:MM (24h)."),
    (E12X36, {"hora_inicio_turno": "06:00", "hora_fim_turno": ""},
     "Horário de término do turno inválido - use HH:MM (24h)."),
    (E12X36, {"hora_inicio_turno": "06:00", "hora_fim_turno": "18:00", "plantoes_mes": "0"},
     "Dias trabalhados por mês inválido."),
    (DIARIAS, {"hora_inicio_turno": "06:00", "hora_fim_turno": "18:00", "valor_diaria": "200,00"},
     "Dias trabalhados por mês inválido."),
    (E5X2_DIARIA, {"hora_inicio_turno": "06:00", "hora_fim_turno": "18:00", "valor_diaria": ""},
     "Valor da diária inválido."),
])
def test_ler_form_erros_turno(escala, form, mensagem):
    assert escalas.ler_form_escala(escala, form)[1] == mensagem


def test_ler_form_dias_acima_de_31():
    form = {"hora_inicio_turno": "06:00", "hora_fim_turno": "18:00", "plantoes_mes": "32"}
    assert escalas.ler_form_escala(E12X36, form)[1] == "Dias trabalhados por mês inválido."



def test_sugerido_personalizada_piso():
    cfg = {"modo_preco": "piso_mensal", "piso_centavos": 150000, "hora_inicio_turno": "08:00",
           "hora_fim_turno": "17:00", "plantoes_mes": "21.67"}
    assert escalas.sugerido_mensal(cfg, P, None) == 150000


def test_funcoes_da_proposta_deriva_legado():
    dados = {"escala_id": "6", "escala_nome": "Personalizado", "modo_preco": "semanal", "escala_semanal": SEMANA}
    linhas = [{"id": 7, "categoria": "mao_de_obra", "funcao_id": 1, "descricao": "Portaria", "quantidade": 2},
              {"id": 8, "categoria": "manual", "funcao_id": None, "descricao": "ISS", "quantidade": 1}]
    fs = escalas.funcoes_da_proposta(dados, linhas)
    assert len(fs) == 1
    f = fs[0]
    assert (f["chave"], f["funcao_id"], f["nome"], f["quantidade"]) == ("l7", 1, "Portaria", 2)
    assert (f["modo_preco"], f["escala_nome"], f["escala_semanal"]) == ("semanal", "Personalizado", SEMANA)


def test_funcoes_da_proposta_legado_sem_escala_e_12x36():
    linhas = [{"id": 3, "categoria": "mao_de_obra", "funcao_id": 2, "descricao": "Portaria", "quantidade": 1}]
    f = escalas.funcoes_da_proposta({}, linhas)[0]
    assert (f["modo_preco"], f["escala_nome"], f["plantoes_mes"]) == ("piso_mensal", "12x36", "15")


def test_funcoes_da_proposta_usa_lista_quando_existe():
    lista = [{"chave": "a1", "nome": "Jardineiro"}]
    assert escalas.funcoes_da_proposta({"funcoes": lista, "modo_preco": "semanal"}, []) == lista
