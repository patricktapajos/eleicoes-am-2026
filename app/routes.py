"""Rotas da aplicação: páginas HTML, API JSON e exportação CSV."""
from __future__ import annotations

import csv
import io
import math

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from . import queries as q
from .db import connect_ro, get_db

bp = Blueprint("main", __name__)

POR_PAGINA_TABELA = 25
POR_PAGINA_RANKING = 20


def _pagina() -> int:
    try:
        return max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        return 1


def _multi(nome: str) -> list[str]:
    """Parâmetro repetido na query string (?local=A&local=B) — multi-seleção."""
    return [v.strip() for v in request.args.getlist(nome) if v.strip()]


def _paginar(total: int, pagina: int, por_pagina: int) -> dict:
    paginas = max(1, math.ceil(total / por_pagina))
    return {
        "pagina": pagina,
        "por_pagina": por_pagina,
        "total": total,
        "paginas": paginas,
        "tem_anterior": pagina > 1,
        "tem_proxima": pagina < paginas,
        "inicio": (pagina - 1) * por_pagina + 1 if total else 0,
        "fim": min(pagina * por_pagina, total),
    }


# --------------------------------------------------------------------------- #
# Páginas
# --------------------------------------------------------------------------- #
@bp.route("/")
def dashboard():
    con = get_db()
    kpis = q.kpis(con)
    total = kpis["total_votos"] or 1
    contexto = {
        "pagina_atual": "dashboard",
        "meta": q.meta(con),
        "kpis": kpis,
        "share": {k: (kpis[k] or 0) / total * 100 for k in ("votos_validos", "votos_branco", "votos_nulo", "votos_legenda")},
        "por_categoria": q.votos_por_categoria(con),
        "por_partido": q.votos_por_partido(con),
        "top_candidatos": q.top_candidatos(con, 10),
        "por_zona": q.votos_por_zona(con),
        "top_locais": q.top_locais(con, 8),
    }
    return render_template("dashboard.html", **contexto)


@bp.route("/candidatos")
def candidatos():
    con = get_db()
    busca = request.args.get("busca", "").strip()
    pagina = _pagina()
    dados = q.candidatos_ranking(con, busca, pagina, POR_PAGINA_RANKING)
    contexto = {
        "pagina_atual": "candidatos",
        "meta": q.meta(con),
        "ranking": dados["linhas"],
        "paginacao": _paginar(dados["total"], pagina, POR_PAGINA_RANKING),
        "busca": busca,
        "top_candidatos": q.top_candidatos(con, 15),
        "por_partido": q.votos_por_partido(con),
        "total_validos": q.kpis(con)["votos_validos"] or 1,
    }
    return render_template("candidatos.html", **contexto)


@bp.route("/zonas")
def zonas():
    con = get_db()
    dados = q.votos_por_zona(con)
    contexto = {
        "pagina_atual": "zonas",
        "meta": q.meta(con),
        "zonas": dados,
        "total_geral": sum(z["total"] for z in dados) or 1,
    }
    return render_template("zonas.html", **contexto)


@bp.route("/dados")
def dados():
    con = get_db()
    por_secao = request.args.get("por_secao", "").strip() == "1"
    filtros = {
        "zona": request.args.get("zona", "").strip(),
        "local": _multi("local"),
        "candidato": _multi("candidato"),
        "partido": request.args.get("partido", "").strip(),
        "categoria": request.args.get("categoria", "").strip(),
        "q": request.args.get("q", "").strip(),
        # "1"/"" apenas para propagar o link (ignorado pelo filtro SQL).
        "por_secao": "1" if por_secao else "",
    }
    pagina = _pagina()
    resultado = q.tabela_agregada(con, filtros, pagina, POR_PAGINA_TABELA, por_secao)
    contexto = {
        "pagina_atual": "dados",
        "meta": q.meta(con),
        "linhas": resultado["linhas"],
        "paginacao": _paginar(resultado["total"], pagina, POR_PAGINA_TABELA),
        "filtros": filtros,
        "por_secao": por_secao,
        "zonas": q.zonas(con),
        "locais": q.locais(con),
        "candidatos_lista": q.candidatos_lista(con),
        "partidos": q.partidos(con),
        "categorias": q.CATEGORIAS,
    }
    return render_template("dados.html", **contexto)


# --------------------------------------------------------------------------- #
# API JSON (usada pelos gráficos e integrável por terceiros)
# --------------------------------------------------------------------------- #
@bp.route("/api/resumo")
def api_resumo():
    con = get_db()
    return jsonify({"meta": q.meta(con), "kpis": q.kpis(con)})


@bp.route("/api/votos-por-categoria")
def api_categoria():
    return jsonify(q.votos_por_categoria(get_db()))


@bp.route("/api/votos-por-partido")
def api_partido():
    return jsonify(q.votos_por_partido(get_db()))


@bp.route("/api/top-candidatos")
def api_top_candidatos():
    limite = min(int(request.args.get("limite", 15)), 100)
    return jsonify(q.top_candidatos(get_db(), limite))


@bp.route("/api/votos-por-zona")
def api_zona():
    return jsonify(q.votos_por_zona(get_db()))


@bp.route("/api/top-locais")
def api_top_locais():
    limite = min(int(request.args.get("limite", 10)), 100)
    return jsonify(q.top_locais(get_db(), limite))


# --------------------------------------------------------------------------- #
# Exportação CSV da tabela agregada (com filtros aplicados)
# --------------------------------------------------------------------------- #
@bp.route("/dados/export.csv")
def export_csv():
    filtros = {
        "zona": request.args.get("zona", "").strip(),
        "local": _multi("local"),
        "candidato": _multi("candidato"),
        "partido": request.args.get("partido", "").strip(),
        "categoria": request.args.get("categoria", "").strip(),
        "q": request.args.get("q", "").strip(),
    }
    por_secao = request.args.get("por_secao", "").strip() == "1"
    db_path = current_app.config["DATABASE"]

    def gerar():
        # Conexão própria: o streaming ocorre após o fim do request context.
        con = connect_ro(db_path)
        try:
            cabecalho, cur = q.exportar_filtrado(con, filtros, por_secao)
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
            writer.writerow(cabecalho)
            yield "\ufeff" + buffer.getvalue()  # BOM p/ Excel
            for linha in cur:
                buffer.seek(0)
                buffer.truncate(0)
                writer.writerow(list(linha))
                yield buffer.getvalue()
        finally:
            con.close()

    return Response(
        stream_with_context(gerar()),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=votos_agregados.csv"},
    )
