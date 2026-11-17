"""Seções do painel de configurações, agrupadas por modalidade.

Cada campo é um parâmetro com vigência (tabela `parametros`); `converter` leva o
texto digitado ao valor gravado e `exibir` faz o caminho inverso. Seções sem
campos (catálogo) têm formulários próprios no template.
"""
from dataclasses import dataclass

from app.moeda import format_brl, format_percentual, parse_brl, parse_percentual_campo


@dataclass(frozen=True)
class Campo:
    chave: str
    rotulo: str
    tipo: str  # pct | brl | int | texto | texto_longo
    ajuda: str = ""


@dataclass(frozen=True)
class Secao:
    id: str
    grupo: str
    titulo: str
    descricao: str
    campos: tuple[Campo, ...] = ()


SECOES: list[Secao] = [
    Secao("continuo-piso", "Serviço contínuo", "Cálculo por piso mensal",
          "Vale para as escalas 12x36, 6x1, 5x2 e 4x3. Encargos e margem também se aplicam a eventos.", (
              Campo("pct_encargos", "Encargos sociais", "pct", "Sobre a soma da mão de obra"),
              Campo("pct_noturno", "Adicional noturno", "pct", "Sobre as horas entre 22h e 06h"),
              Campo("pct_margem", "Margem administrativa", "pct", "Sobre mão de obra, acessórios e encargos"),
              Campo("divisor_horas", "Divisor de horas mensal", "int", "CLT: 220"),
              Campo("valor_alimentacao_continuo", "Alimentação mensal", "brl", "Por profissional (R$)"),
              Campo("valor_transporte_continuo", "Transporte mensal", "brl", "Por profissional (R$)"),
          )),
    Secao("continuo-diaria", "Serviço contínuo", "Diária e personalizado",
          "Escalas de diária fechada: sem encargos, margem e acessórios automáticos.", (
              Campo("condicoes_composicao_mensal", "Composição mensal e feriados", "texto_longo",
                    "Entra nas condições do PDF. Um parágrafo por linha."),
          )),
    Secao("continuo-textos", "Serviço contínuo", "Textos do documento", "Textos fixos do PDF de serviço contínuo.", (
        Campo("condicoes_continuo", "Condições gerais", "texto_longo", "Um parágrafo por linha."),
        Campo("obs_finais_continuo", "Observações finais", "texto_longo"),
    )),
    Secao("evento-calculo", "Evento único", "Cálculo por diária", "Acessórios automáticos de eventos.", (
        Campo("valor_alimentacao_evento", "Alimentação por evento", "brl", "Por profissional (R$)"),
        Campo("valor_transporte_evento", "Transporte por evento", "brl", "Por profissional (R$)"),
    )),
    Secao("evento-textos", "Evento único", "Textos do documento", "Textos fixos do PDF de evento.", (
        Campo("condicoes_evento", "Condições gerais", "texto_longo", "Um parágrafo por linha."),
        Campo("obs_finais_evento", "Observações finais", "texto_longo"),
    )),
    Secao("catalogo-funcoes", "Catálogo", "Funções", "Funções e valores-base usados na etapa Serviços."),
    Secao("catalogo-escalas", "Catálogo", "Escalas", "Modo de preço e dias trabalhados por mês de cada escala."),
    Secao("empresa-dados", "Empresa", "Dados e pagamento", "Cabeçalho e dados de pagamento do PDF.", (
        Campo("empresa_nome", "Razão social", "texto"),
        Campo("empresa_cnpj", "CNPJ", "texto"),
        Campo("empresa_endereco", "Endereço", "texto"),
        Campo("empresa_telefone", "Telefone/WhatsApp", "texto"),
        Campo("empresa_email", "E-mail", "texto"),
        Campo("pagamento_pix", "Chave PIX", "texto"),
        Campo("pagamento_banco", "Dados bancários", "texto"),
    )),
    Secao("empresa-validade", "Empresa", "Validade da proposta", "Prazo impresso nas observações finais.", (
        Campo("validade_dias", "Validade da proposta", "int", "Em dias"),
    )),
]


def secao(id_secao: str) -> Secao:
    """Seção pelo id; desconhecido cai na primeira."""
    return next((s for s in SECOES if s.id == id_secao), SECOES[0])


def converter(campo: Campo, texto: str) -> str:
    """Texto digitado -> valor gravado em `parametros`. ValueError com mensagem pt-BR."""
    limpo = texto.replace("\r\n", "\n").strip()
    if campo.tipo == "pct":
        return str(parse_percentual_campo(limpo))
    if campo.tipo == "brl":
        try:
            return str(parse_brl(limpo))
        except ValueError:
            raise ValueError("Valor inválido - use 1.234,56.")
    if campo.tipo == "int":
        if not limpo.isdigit() or int(limpo) <= 0:
            raise ValueError("Use um número inteiro maior que zero.")
        return str(int(limpo))
    return limpo


def exibir(campo: Campo, valor: str) -> str:
    """Valor gravado -> texto para a tela."""
    if not valor:
        return ""
    if campo.tipo == "pct":
        return format_percentual(valor)
    if campo.tipo == "brl":
        return format_brl(int(valor))
    return valor
