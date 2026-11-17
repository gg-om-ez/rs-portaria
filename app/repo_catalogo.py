"""Parâmetros globais com histórico de vigência e catálogo de funções."""
import sqlite3
from datetime import date
from decimal import Decimal

from app.calc import Params


def definir_parametro(conn: sqlite3.Connection, chave: str, valor: str, vigencia_inicio: str) -> None:
    conn.execute(
        "INSERT INTO parametros (chave, valor, vigencia_inicio) VALUES (?, ?, ?)",
        (chave, str(valor), vigencia_inicio),
    )
    conn.commit()


def parametro_vigente(conn: sqlite3.Connection, chave: str, em: str | None = None) -> str | None:
    em = em or date.today().isoformat()
    row = conn.execute(
        "SELECT valor FROM parametros WHERE chave = ? AND vigencia_inicio <= ?"
        " ORDER BY vigencia_inicio DESC, id DESC LIMIT 1",
        (chave, em),
    ).fetchone()
    return row["valor"] if row else None


def historico_parametro(conn: sqlite3.Connection, chave: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM parametros WHERE chave = ? ORDER BY vigencia_inicio DESC, id DESC",
        (chave,),
    ).fetchall()


def param_int(conn: sqlite3.Connection, chave: str) -> int:
    valor = parametro_vigente(conn, chave)
    if valor is None:
        raise ValueError(f"Parâmetro obrigatório ausente: {chave}")
    return int(valor)


def params_vigentes(conn: sqlite3.Connection) -> Params:
    def _dec(chave: str) -> Decimal:
        valor = parametro_vigente(conn, chave)
        if valor is None:
            raise ValueError(f"Parâmetro obrigatório ausente: {chave}")
        return Decimal(valor)

    return Params(
        pct_encargos=_dec("pct_encargos"),
        pct_noturno=_dec("pct_noturno"),
        pct_margem=_dec("pct_margem"),
        divisor_horas=param_int(conn, "divisor_horas"),
    )


def criar_funcao(
    conn: sqlite3.Connection, nome: str, tipo: str, valor_base_centavos: int, aplica_noturno: bool = False
) -> int:
    cur = conn.execute(
        "INSERT INTO funcoes (nome, tipo, valor_base_centavos, aplica_noturno) VALUES (?, ?, ?, ?)",
        (nome.strip(), tipo, valor_base_centavos, int(aplica_noturno)),
    )
    conn.commit()
    return cur.lastrowid


def listar_funcoes(conn: sqlite3.Connection, tipo: str | None = None, apenas_ativas: bool = True) -> list[sqlite3.Row]:
    sql, args = "SELECT * FROM funcoes WHERE 1=1", []
    if tipo:
        sql += " AND tipo = ?"
        args.append(tipo)
    if apenas_ativas:
        sql += " AND ativa = 1"
    return conn.execute(sql + " ORDER BY tipo, nome", args).fetchall()


def obter_funcao(conn: sqlite3.Connection, funcao_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM funcoes WHERE id = ?", (funcao_id,)).fetchone()


def atualizar_funcao(conn: sqlite3.Connection, funcao_id: int, **campos) -> None:
    permitidos = {"nome", "valor_base_centavos", "aplica_noturno", "ativa"}
    invalidos = set(campos) - permitidos
    if invalidos:
        raise ValueError(f"Campos não editáveis: {invalidos}")
    sets = ", ".join(f"{c} = ?" for c in campos)
    conn.execute(f"UPDATE funcoes SET {sets} WHERE id = ?", (*campos.values(), funcao_id))
    conn.commit()


MODOS_EDITAVEIS = ("piso_mensal", "diaria")


def listar_escalas(conn: sqlite3.Connection, apenas_ativas: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM escalas" + (" WHERE ativa = 1" if apenas_ativas else "")
    return conn.execute(sql + " ORDER BY ordem, id").fetchall()


def obter_escala(conn: sqlite3.Connection, escala_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM escalas WHERE id = ?", (escala_id,)).fetchone()


def escala_padrao(conn: sqlite3.Connection) -> sqlite3.Row:
    """12x36: escala de rascunhos anteriores ao menu de escalas."""
    row = conn.execute("SELECT * FROM escalas WHERE nome = '12x36'").fetchone()
    if row is None:
        raise ValueError("Escala padrão 12x36 ausente")
    return row


def atualizar_escala(conn: sqlite3.Connection, escala_id: int, modo: str,
                     dias_mes: Decimal | None) -> None:
    atual = obter_escala(conn, escala_id)
    if atual is None:
        raise ValueError(f"Escala {escala_id} não existe")
    # Personalizado (semanal) tem preço por dia da semana; não troca de modo,
    # e nenhuma outra escala vira semanal
    if atual["modo"] == "semanal" or modo not in MODOS_EDITAVEIS:
        raise ValueError(f"Modo de preço não editável para {atual['nome']}")
    if dias_mes is not None and dias_mes <= 0:
        raise ValueError("Dias trabalhados por mês inválido.")
    conn.execute(
        "UPDATE escalas SET modo = ?, dias_mes = ? WHERE id = ?",
        (modo, None if dias_mes is None else str(dias_mes), escala_id),
    )
    conn.commit()


_SEED_PARAMETROS = {
    "pct_encargos": "0.58",
    "pct_noturno": "0.20",
    "pct_margem": "0.10",
    "divisor_horas": "220",
    "validade_dias": "30",
    "valor_alimentacao_continuo": "58000",
    "valor_transporte_continuo": "18000",
    "valor_alimentacao_evento": "2000",
    "valor_transporte_evento": "4000",
    "empresa_nome": "RS PORTARIA E SERVICOS",
    "empresa_cnpj": "11.444.777/0001-61",
    "empresa_endereco": "Rua Exemplo, 123, Bairro, Cidade - UF, CEP 00000-000",
    "empresa_telefone": "(00) 00000-0000",
    "empresa_email": "contato@exemplo.com.br",
    "pagamento_pix": "chave-pix@exemplo.com.br",
    "pagamento_banco": "Banco Exemplo - Agência 0000, Conta Corrente 00000-0",
    "condicoes_continuo": (
        "Os profissionais alocados exercerão suas funções devidamente uniformizados, em conformidade "
        "com o padrão de apresentação e conduta estabelecido pela CONTRATADA, durante toda a jornada.\n"
        "A CONTRATADA compromete-se a garantir a cobertura integral de todos os plantões contratados, "
        "providenciando a substituição imediata de qualquer profissional que apresente impedimento. "
        "A ausência de cobertura não justificada sujeitará a CONTRATADA ao desconto proporcional do valor "
        "do plantão descoberto, acrescido de multa equivalente a 150% (cento e cinquenta por cento) do valor "
        "base do plantão, a ser abatida na fatura do mês em questão.\n"
        "Alterações de escopo, horário ou local de prestação de serviço solicitadas pela CONTRATANTE deverão "
        "ser comunicadas com antecedência mínima de 48 (quarenta e oito) horas. Solicitações que impliquem "
        "ampliação de jornada, inclusão de plantões ou mudança de escala poderão ensejar revisão dos valores "
        "contratados, mediante acordo entre as partes antes da execução."
    ),
    "condicoes_evento": (
        "Os profissionais contratados estarão devidamente trajados, em conformidade de etiqueta prevista em contrato.\n"
        "O prestador compromete-se a substituir, se necessário, qualquer profissional que apresente impedimento "
        "de última hora, sem prejuízo da prestação do serviço, quando possível.\n"
        "Alterações de horário, local ou escopo solicitadas pela CONTRATANTE devem ser comunicadas com no mínimo "
        "12 horas de antecedência; ajustes de preço podem ocorrer caso haja alteração do escopo.\n"
        "Em caso de cancelamento pelo CONTRATANTE após a confirmação do pagamento, será aplicada uma retenção de "
        "20% (vinte por cento) do valor total para cobertura de custos operacionais já incorridos.\n"
        "O prestador não se responsabiliza por bens pessoais dos participantes."
    ),
    "condicoes_composicao_mensal": (
        "Os valores mensais deste orçamento são estimativas pela média de 52 semanas por ano "
        "(52/12 semanas por mês). A fatura de cada mês considera os dias efetivamente previstos "
        "na escala naquele mês.\n"
        "Feriados que coincidam com dias da escala são faturados conforme a prestação efetiva do "
        "serviço; a prestação em feriado e eventual acréscimo de valor devem ser acordados "
        "previamente entre as partes."
    ),
    "obs_finais_continuo": (
        "Este documento funciona como orçamento e tem validade limitada. Tanto a proposta definitiva para o "
        "período em questão quanto a formalização contratual (contrato de prestação de serviços) serão emitidas "
        "após a confirmação da contratante, com cláusulas detalhadas (responsabilidades, seguros) de acordo com "
        "a necessidade da CONTRATANTE."
    ),
    "obs_finais_evento": (
        "Este documento funciona como orçamento e proposta. A formalização contratual (contrato de prestação de "
        "serviços) será emitida após a confirmação do pagamento, com cláusulas detalhadas (responsabilidades, "
        "seguros, confidencialidade, quando aplicável) de acordo com a necessidade da CONTRATANTE."
    ),
}

_SEED_FUNCOES = [
    ("Portaria diurna (12x36)", "continuo", 160000, False),
    ("Portaria noturna (12x36)", "continuo", 160000, True),
    ("Auxiliar de serviços gerais", "continuo", 151800, False),
    ("Segurança de evento (12h)", "evento", 22000, False),
    ("Serviços gerais de evento (12h)", "evento", 22000, False),
]


# (nome, modo, dias_mes): dias = semanas médias (52/12) x dias trabalhados na semana;
# 12x36 mantém os 15 plantões/mês do cálculo original
_SEED_ESCALAS = [
    ("12x36", "piso_mensal", "15"),
    ("6x1", "piso_mensal", "26"),
    ("5x2", "piso_mensal", "21.67"),
    ("4x3", "piso_mensal", "17.33"),
    ("Diárias por escala", "diaria", None),
    ("Personalizado", "semanal", None),
]


def seed_inicial(conn: sqlite3.Connection) -> None:
    """Popula parâmetros e funções apenas se ainda não existirem (idempotente)."""
    for chave, valor in _SEED_PARAMETROS.items():
        existe = conn.execute(
            "SELECT 1 FROM parametros WHERE chave = ? LIMIT 1", (chave,)
        ).fetchone()
        if not existe:
            conn.execute(
                "INSERT INTO parametros (chave, valor, vigencia_inicio) VALUES (?, ?, '2026-01-01')",
                (chave, valor),
            )
    if not conn.execute("SELECT 1 FROM funcoes LIMIT 1").fetchone():
        for nome, tipo, valor, noturno in _SEED_FUNCOES:
            conn.execute(
                "INSERT INTO funcoes (nome, tipo, valor_base_centavos, aplica_noturno) VALUES (?, ?, ?, ?)",
                (nome, tipo, valor, int(noturno)),
            )
    if not conn.execute("SELECT 1 FROM escalas LIMIT 1").fetchone():
        for ordem, (nome, modo, dias) in enumerate(_SEED_ESCALAS, start=1):
            conn.execute(
                "INSERT INTO escalas (nome, modo, dias_mes, ordem) VALUES (?, ?, ?, ?)",
                (nome, modo, dias, ordem),
            )
    conn.commit()
