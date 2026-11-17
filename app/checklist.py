"""Checklist de revisão. Item crítico não-ok bloqueia a emissão."""
import sqlite3
from dataclasses import dataclass

from app import escalas
from app import repo_clientes as rc
from app import repo_propostas as rp


@dataclass(frozen=True)
class ItemChecklist:
    rotulo: str
    ok: bool
    critico: bool


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
                      cliente is not None and rc.validar_cnpj(cliente["cnpj"]), True),
        ItemChecklist("Endereço do serviço informado", _tem(dados, "endereco_servico"), True),
        ItemChecklist("Pelo menos uma função de mão de obra", tem_mao_de_obra, True),
        ItemChecklist("Forma de pagamento definida", _tem(dados, "formas_pagamento"), True),
    ]
    if prop["tipo"] == "continuo":
        modo = escalas.modo_de(dados)
        itens.append(ItemChecklist("Duração do contrato e data de início",
                                   _tem(dados, "duracao_meses") and _tem(dados, "data_inicio"), True))
        if modo == "semanal":
            # Personalizado: horários ficam em cada dia ativo, não num turno único
            itens.append(ItemChecklist("Pelo menos um dia ativo na escala",
                                       bool(dados.get("escala_semanal")), True))
        else:
            itens.append(ItemChecklist(
                "Horários do turno definidos",
                _tem(dados, "hora_inicio_turno") and _tem(dados, "hora_fim_turno"), True))
        if modo == "diaria":
            itens.append(ItemChecklist(
                "Valor da diária e dias por mês",
                bool(dados.get("valor_diaria_centavos")) and _tem(dados, "plantoes_mes"), True))
        itens.append(ItemChecklist("Vencimento acordado", _tem(dados, "vencimento"), True))
    else:
        itens += [
            ItemChecklist("Data do evento definida", _tem(dados, "data_evento"), True),
            ItemChecklist("Horários de início e término",
                          _tem(dados, "hora_inicio") and _tem(dados, "hora_fim"), True),
            ItemChecklist("Data-limite do pagamento antecipado",
                          _tem(dados, "data_limite_pagamento"), True),
        ]
    itens.append(ItemChecklist("Observações preenchidas", _tem(dados, "observacoes"), False))
    return itens


def pode_emitir(itens: list[ItemChecklist]) -> bool:
    return all(i.ok for i in itens if i.critico)
