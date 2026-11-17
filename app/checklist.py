"""Checklist de revisão. Item crítico não-ok bloqueia a emissão."""
import sqlite3
from dataclasses import dataclass

from app import escalas
from app import repo_catalogo as rcat
from app import repo_clientes as rc
from app import repo_propostas as rp


@dataclass(frozen=True)
class ItemChecklist:
    rotulo: str
    ok: bool
    critico: bool
    etapa: str  # etapa do wizard onde o item se resolve (navegação vertical)


def _tem(dados: dict, chave: str) -> bool:
    # `or ""` cobre chave presente com valor None (senão str(None) vira "None", truthy)
    return bool(str(dados.get(chave) or "").strip())


def avaliar(conn: sqlite3.Connection, pid: int) -> list[ItemChecklist]:
    prop = rp.obter_proposta(conn, pid)
    if prop is None:
        raise ValueError(f"Proposta {pid} não existe")
    dados = rp.dados_de(prop)
    cliente = rc.obter_cliente(conn, prop["cliente_id"]) if prop["cliente_id"] else None
    linhas = rp.linhas_da_proposta(conn, pid)
    tem_mao_de_obra = any(l["categoria"] == "mao_de_obra" for l in linhas)

    itens = [
        ItemChecklist("Cliente definido com CNPJ válido",
                      cliente is not None and rc.validar_cnpj(cliente["cnpj"]), True, "cliente"),
        ItemChecklist("Endereço do serviço informado", _tem(dados, "endereco_servico"), True, "local"),
        ItemChecklist("Pelo menos uma função de mão de obra", tem_mao_de_obra, True, "servicos"),
        ItemChecklist("Forma de pagamento definida", _tem(dados, "formas_pagamento"), True, "pagamento"),
    ]
    if prop["tipo"] == "continuo":
        modo = escalas.modo_de(dados)
        itens.append(ItemChecklist("Duração do contrato e data de início",
                                   _tem(dados, "duracao_meses") and _tem(dados, "data_inicio"), True,
                                   "local"))
        if modo == "semanal":
            # Personalizado: horários ficam em cada dia ativo, não num turno único
            itens.append(ItemChecklist("Pelo menos um dia ativo na escala",
                                       bool(dados.get("escala_semanal")), True, "servicos"))
        else:
            itens.append(ItemChecklist(
                "Horários do turno definidos",
                _tem(dados, "hora_inicio_turno") and _tem(dados, "hora_fim_turno"), True, "servicos"))
        if modo == "diaria":
            itens.append(ItemChecklist(
                "Valor da diária e dias por mês",
                bool(dados.get("valor_diaria_centavos")) and _tem(dados, "plantoes_mes"), True,
                "servicos"))
        itens.append(ItemChecklist("Vencimento acordado", _tem(dados, "vencimento"), True, "pagamento"))
    else:
        itens += [
            ItemChecklist("Data do evento definida", _tem(dados, "data_evento"), True, "local"),
            ItemChecklist("Horários de início e término",
                          _tem(dados, "hora_inicio") and _tem(dados, "hora_fim"), True, "local"),
            ItemChecklist("Data-limite do pagamento antecipado",
                          _tem(dados, "data_limite_pagamento"), True, "pagamento"),
        ]
    itens.append(ItemChecklist("Observações preenchidas", _tem(dados, "observacoes"), False, "servicos"))
    # Bloqueia PDF com CNPJ, PIX etc. de exemplo (instância nunca configurada)
    itens.append(ItemChecklist("Dados da empresa configurados (Configurações > Empresa)",
                               not rcat.empresa_com_dados_de_exemplo(conn), True, "revisao"))
    return itens


def pode_emitir(itens: list[ItemChecklist]) -> bool:
    return all(i.ok for i in itens if i.critico)


def estado_etapas(itens: list[ItemChecklist], etapas: list[str], atual: str) -> dict[str, str]:
    """Estado de cada etapa para a navegação: "ok" quando todos os itens críticos
    dela passam; "pendente" quando algum falha numa etapa já percorrida (ou na
    revisão, que mostra tudo); "" sem itens ou etapa futura ainda incompleta, para
    uma proposta nova não aparecer toda pendente."""
    idx_atual = etapas.index(atual)
    estados = {}
    for idx, etapa in enumerate(etapas):
        criticos = [i for i in itens if i.critico and i.etapa == etapa]
        # a Revisão já mostra o checklist inteiro; marca própria só confundiria
        if not criticos or etapa == "revisao":
            estados[etapa] = ""
        elif all(i.ok for i in criticos):
            estados[etapa] = "ok"
        elif idx < idx_atual or atual == "revisao":
            estados[etapa] = "pendente"
        else:
            estados[etapa] = ""
    return estados
