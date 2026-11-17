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


def test_usa_motor_completo():
    assert escalas.usa_motor_completo("evento", {"modo_preco": "semanal"}) is True
    assert escalas.usa_motor_completo("continuo", {}) is True
    assert escalas.usa_motor_completo("continuo", {"modo_preco": "diaria"}) is False
    assert escalas.usa_motor_completo("continuo", {"modo_preco": "semanal"}) is False


def test_valor_semanal():
    assert escalas.valor_semanal({"escala_semanal": SEMANA}) == 75000
    assert escalas.valor_semanal({}) == 0


def test_sugerido_piso_sem_noturno():
    dados = {"modo_preco": "piso_mensal", "hora_inicio_turno": "07:00",
             "hora_fim_turno": "19:00", "plantoes_mes": "15"}
    assert escalas.sugerido_mensal(SEM_NOTURNO, dados, P) == 160000


def test_sugerido_piso_noturno_igual_ao_calculo_original():
    noturna = {"valor_base_centavos": 160000, "aplica_noturno": 1}
    dados = {"hora_inicio_turno": "18:00", "hora_fim_turno": "06:00", "plantoes_mes": "15"}
    assert escalas.sugerido_mensal(noturna, dados, P) == 177455
    sem_plantoes = {"hora_inicio_turno": "18:00", "hora_fim_turno": "06:00"}
    assert escalas.sugerido_mensal(noturna, sem_plantoes, P) == 177455


def test_sugerido_semanal():
    assert escalas.sugerido_mensal(SEM_NOTURNO, {"modo_preco": "semanal", "escala_semanal": SEMANA}, P) == 325000


def test_sugerido_diaria():
    dados = {"modo_preco": "diaria", "valor_diaria_centavos": 20000, "plantoes_mes": "21.67"}
    assert escalas.sugerido_mensal(SEM_NOTURNO, dados, P) == 433400
