"""Jinja compartilhado entre rotas (Jinja2Templates) e renderização fora de request."""
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.datas import format_data_br
from app.moeda import format_brl, format_percentual

_DIR = Path(__file__).parent / "templates"

env = Environment(loader=FileSystemLoader(_DIR), autoescape=select_autoescape(["html"]))
env.filters["brl"] = format_brl
env.filters["data_br"] = format_data_br
env.filters["pct"] = format_percentual


def origem_linha(linha) -> str:
    """Quem controla o valor da linha de custo, para a coluna Origem."""
    if linha["percentual"] is not None:
        return "Percentual"
    return {"mao_de_obra": "Mão de obra", "acessorio": "Acessório",
            "derivada": "Calculado", "manual": "Manual"}[linha["categoria"]]


env.filters["origem"] = origem_linha

templates = Jinja2Templates(env=env)
