"""Emissão: numeração sequencial, snapshot imutável e arquivamento duplo."""
import json
import sqlite3
from datetime import date
from pathlib import Path

from app import checklist, escalas
from app import repo_catalogo as rcat
from app import repo_clientes as rc
from app import repo_propostas as rp
from app.calc import mensal_de_semanal
from app.moeda import format_brl, format_percentual
from app.pdf import nome_arquivo as _nome_arquivo


def proximo_numero(conn: sqlite3.Connection, ano: int) -> str:
    seq = conn.execute(
        "INSERT INTO sequencia_numeracao (ano, ultimo) VALUES (?, 1)"
        " ON CONFLICT (ano) DO UPDATE SET ultimo = ultimo + 1 RETURNING ultimo",
        (ano,),
    ).fetchone()["ultimo"]
    return f"RS-{ano}-{seq:04d}"


def _dias_fmt(dias: str) -> str:
    return str(dias).replace(".", ",")


def _nota_metodologica(conn: sqlite3.Connection, tipo: str, funcoes: list[dict]) -> str:
    """Uma frase por modo de preço presente nas funções da proposta."""
    if tipo != "continuo":
        return "Valores por diária conforme catálogo vigente; alimentação e transporte por profissional."
    frases = []
    piso = [f for f in funcoes if escalas.modo_de(f) == "piso_mensal"]
    if piso:
        p = rcat.params_vigentes(conn)
        padrao = rcat.escala_padrao(conn)["dias_mes"]
        bases = ", ".join(dict.fromkeys(
            f"{_dias_fmt(f.get('plantoes_mes') or padrao)} dias trabalhados/mês, escala "
            f"{f.get('escala_nome') or '12x36'}" for f in piso))
        frases.append(
            f"Base estimada: piso mensal por função + adicional noturno de "
            f"{format_percentual(p.pct_noturno)} sobre horas entre 22h-06h ({bases}); "
            f"encargos sociais de {format_percentual(p.pct_encargos)} sobre a mão de obra; "
            f"margem administrativa de {format_percentual(p.pct_margem)}.")
    for f in funcoes:
        if escalas.modo_de(f) == "diaria":
            frases.append(f"Diária fechada de R$ {format_brl(int(f['valor_diaria_centavos']))} por "
                          f"profissional x {_dias_fmt(f['plantoes_mes'])} dias/mês; "
                          "demais valores conforme linhas listadas.")
    if any(escalas.modo_de(f) == "semanal" for f in funcoes):
        frases.append("Valor semanal pela soma das diárias dos dias ativos; "
                      "mensal estimado = semanal x 52/12.")
    return " ".join(frases)


def _escala_snapshot(f: dict) -> dict:
    """Escala de uma função congelada no snapshot (rótulos e valores prontos)."""
    modo = escalas.modo_de(f)
    rotulos = dict(escalas.DIAS_SEMANA)
    ini, fim = f.get("hora_inicio_turno"), f.get("hora_fim_turno")
    snap = {"funcao": f.get("nome", ""), "quantidade": f.get("quantidade", 0),
            "nome": f.get("escala_nome") or "12x36", "modo": modo,
            "turno": f"{ini} às {fim}" if modo != "semanal" and ini and fim else None,
            "diaria_centavos": f.get("valor_diaria_centavos") if modo == "diaria" else None,
            "dias_mes": _dias_fmt(f["plantoes_mes"]) if f.get("plantoes_mes") else None,
            "semanal_centavos": None, "mensal_centavos": None, "dias": []}
    if modo == "semanal":
        semanal = escalas.valor_semanal(f)
        snap.update({
            "semanal_centavos": semanal, "mensal_centavos": mensal_de_semanal(semanal),
            "dias": [{"rotulo": rotulos[d["dia"]], "inicio": d["inicio"], "fim": d["fim"],
                      "valor_centavos": d["valor_centavos"]} for d in f.get("escala_semanal") or []],
        })
    return snap


def montar_snapshot(conn: sqlite3.Connection, pid: int) -> dict:
    prop = rp.obter_proposta(conn, pid)
    if prop is None:
        raise ValueError(f"Proposta {pid} não existe")
    cliente = rc.obter_cliente(conn, prop["cliente_id"]) if prop["cliente_id"] else None
    par = lambda chave: rcat.parametro_vigente(conn, chave) or ""

    linhas = []
    linhas_db = rp.linhas_da_proposta(conn, pid)
    for l in linhas_db:
        subtotal = l["valor_final_centavos"] * l["quantidade"]
        linhas.append({
            "descricao": l["descricao"], "categoria": l["categoria"],
            "quantidade": l["quantidade"], "sobrescrito": l["sobrescrito"],
            "percentual_fmt": format_percentual(l["percentual"]) if l["percentual"] else "",
            "valor_unitario_centavos": l["valor_final_centavos"],
            "valor_unitario_fmt": format_brl(l["valor_final_centavos"]),
            "subtotal_centavos": subtotal, "subtotal_fmt": format_brl(subtotal),
        })
    total = rp.total_proposta(conn, pid)
    tipo = prop["tipo"]
    dados = rp.dados_de(prop)
    funcoes = escalas.funcoes_da_proposta(dados, linhas_db) if tipo == "continuo" else []
    condicoes = [p for p in par(f"condicoes_{tipo}").split("\n") if p.strip()]
    if any(escalas.modo_de(f) in ("diaria", "semanal") for f in funcoes):
        condicoes += [p for p in par("condicoes_composicao_mensal").split("\n") if p.strip()]
    snapshot = {
        "numero": prop["numero"] or "RASCUNHO",
        "tipo": tipo,
        "emitida_em": (prop["emitida_em"] or date.today().isoformat())[:10],
        "validade_dias": rcat.param_int(conn, "validade_dias"),
        "empresa": {
            "nome": par("empresa_nome"), "cnpj": par("empresa_cnpj"),
            "endereco": par("empresa_endereco"), "telefone": par("empresa_telefone"),
            "email": par("empresa_email"), "pix": par("pagamento_pix"),
            "banco": par("pagamento_banco"),
        },
        "cliente": {
            "razao_social": cliente["razao_social"] if cliente else "",
            "cnpj": cliente["cnpj"] if cliente else "",
            "endereco": cliente["endereco"] if cliente else "",
            "email": cliente["email"] if cliente else "",
            "telefone": cliente["telefone"] if cliente else "",
        },
        "dados": dados,
        "linhas": linhas,
        "total_centavos": total,
        "total_fmt": format_brl(total),
        "condicoes": condicoes,
        "obs_finais": par(f"obs_finais_{tipo}"),
        "nota_metodologica": _nota_metodologica(conn, tipo, funcoes),
    }
    if tipo == "continuo":
        snapshot["escalas"] = [_escala_snapshot(f) for f in funcoes]
    return snapshot


def _arquivar(pdf_bytes: bytes, arquivo_dir: Path, nome: str) -> bool:
    try:
        arquivo_dir.mkdir(parents=True, exist_ok=True)
        (arquivo_dir / nome).write_bytes(pdf_bytes)
        return True
    except OSError:
        return False


def emitir(conn: sqlite3.Connection, pid: int, arquivo_dir: Path, gerador_pdf=None) -> dict:
    """Numera, congela e arquiva. Transacional: falha de PDF preserva o rascunho."""
    if gerador_pdf is None:
        from app.pdf import gerar_pdf as gerador_pdf
    prop = rp.obter_proposta(conn, pid)
    if prop is not None and prop["status"] != "rascunho":
        raise ValueError("Proposta já emitida - duplique para gerar nova versão")
    itens = checklist.avaliar(conn, pid)
    if not checklist.pode_emitir(itens):
        pendentes = ", ".join(i.rotulo for i in itens if i.critico and not i.ok)
        raise ValueError(f"Checklist com pendências críticas: {pendentes}")
    try:
        numero = proximo_numero(conn, date.today().year)
        conn.execute(
            "UPDATE propostas SET numero = ?, status = 'emitida',"
            " emitida_em = datetime('now') WHERE id = ?",
            (numero, pid),
        )
        snapshot = montar_snapshot(conn, pid)
        pdf_bytes = gerador_pdf(snapshot)  # pode levantar exceção -> rollback
        arquivado = _arquivar(pdf_bytes, Path(arquivo_dir), _nome_arquivo(snapshot))
        conn.execute(
            "UPDATE propostas SET snapshot_json = ?, pdf_arquivado = ? WHERE id = ?",
            (json.dumps(snapshot, ensure_ascii=False), int(arquivado), pid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return snapshot


def rearquivar_pendentes(conn: sqlite3.Connection, arquivo_dir: Path, gerador_pdf=None) -> int:
    if gerador_pdf is None:
        from app.pdf import gerar_pdf as gerador_pdf
    pendentes = conn.execute(
        "SELECT id, snapshot_json FROM propostas"
        " WHERE status = 'emitida' AND pdf_arquivado = 0"
    ).fetchall()
    regravadas = 0
    for row in pendentes:
        snapshot = json.loads(row["snapshot_json"])
        try:
            pdf_bytes = gerador_pdf(snapshot)
        except Exception:
            # Falha de uma pendente não interrompe as demais nem perde progresso
            continue
        if _arquivar(pdf_bytes, Path(arquivo_dir), _nome_arquivo(snapshot)):
            conn.execute("UPDATE propostas SET pdf_arquivado = 1 WHERE id = ?", (row["id"],))
            conn.commit()  # garante o progresso de cada sucesso imediatamente
            regravadas += 1
    return regravadas
