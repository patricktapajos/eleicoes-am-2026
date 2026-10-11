"""Consultas SQL sobre a tabela agregada de votos."""
from __future__ import annotations

import sqlite3

from .db import LOCAL_TABLE, META_TABLE, TABLE, ZONA_TABLE

CATEGORIAS = ["Candidato", "Legenda", "Branco", "Nulo"]


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def meta(con: sqlite3.Connection) -> dict[str, str]:
    return {r["chave"]: r["valor"] for r in con.execute(f"SELECT chave, valor FROM {META_TABLE}")}


def kpis(con: sqlite3.Connection) -> dict:
    """Números grandes exibidos no topo do painel (tabelas-resumo)."""
    votos = con.execute(
        f"""
        SELECT
            SUM(qt_votos)                                                       AS total_votos,
            COUNT(DISTINCT CASE WHEN categoria='Candidato'
                                THEN nm_votavel END)                            AS total_candidatos,
            SUM(CASE WHEN categoria IN ('Candidato','Legenda')
                     THEN qt_votos ELSE 0 END)                                  AS votos_validos,
            SUM(CASE WHEN categoria='Legenda' THEN qt_votos ELSE 0 END)         AS votos_legenda,
            SUM(CASE WHEN categoria='Branco' THEN qt_votos ELSE 0 END)          AS votos_branco,
            SUM(CASE WHEN categoria='Nulo'   THEN qt_votos ELSE 0 END)          AS votos_nulo
        FROM {LOCAL_TABLE}
        """
    ).fetchone()
    # As seções e os locais são partições por zona, então somar por zona dá o total.
    zonas = con.execute(
        f"""
        SELECT COUNT(*)              AS total_zonas,
               COALESCE(SUM(secoes), 0) AS total_secoes,
               COALESCE(SUM(locais), 0) AS total_locais
        FROM {ZONA_TABLE}
        """
    ).fetchone()
    retorno = dict(votos)
    retorno.update(dict(zonas))
    return retorno


def votos_por_categoria(con: sqlite3.Connection) -> list[dict]:
    return _rows(
        con.execute(
            f"SELECT categoria AS rotulo, SUM(qt_votos) AS total "
            f"FROM {LOCAL_TABLE} GROUP BY categoria ORDER BY total DESC"
        )
    )


def votos_por_partido(con: sqlite3.Connection) -> list[dict]:
    return _rows(
        con.execute(
            f"""
            SELECT COALESCE(sg_partido, nm_votavel) AS rotulo,
                   nm_partido                      AS nome,
                   SUM(qt_votos)                   AS total
            FROM {LOCAL_TABLE}
            WHERE nr_partido IS NOT NULL
            GROUP BY nr_partido
            ORDER BY total DESC
            """
        )
    )


def top_candidatos(con: sqlite3.Connection, limite: int = 15) -> list[dict]:
    return _rows(
        con.execute(
            f"""
            SELECT nr_votavel, nm_votavel AS rotulo, sg_partido,
                   nm_partido, SUM(qt_votos) AS total
            FROM {LOCAL_TABLE}
            WHERE categoria='Candidato'
            GROUP BY nr_votavel
            ORDER BY total DESC
            LIMIT ?
            """,
            (limite,),
        )
    )


def votos_por_zona(con: sqlite3.Connection) -> list[dict]:
    return _rows(
        con.execute(
            f"""
            SELECT nr_zona AS rotulo, qt_votos AS total, locais, secoes
            FROM {ZONA_TABLE}
            ORDER BY nr_zona
            """
        )
    )


def top_locais(con: sqlite3.Connection, limite: int = 10) -> list[dict]:
    return _rows(
        con.execute(
            f"""
            SELECT nm_local_votacao AS rotulo, nr_zona,
                   SUM(qt_votos) AS total
            FROM {LOCAL_TABLE}
            GROUP BY nr_zona, nm_local_votacao
            ORDER BY total DESC
            LIMIT ?
            """,
            (limite,),
        )
    )


def partidos(con: sqlite3.Connection) -> list[dict]:
    """Lista de partidos distintos (opções do filtro)."""
    return _rows(
        con.execute(
            f"""
            SELECT DISTINCT nr_partido, COALESCE(sg_partido, '-') AS rotulo
            FROM {LOCAL_TABLE}
            WHERE nr_partido IS NOT NULL
            ORDER BY rotulo
            """
        )
    )


def zonas(con: sqlite3.Connection) -> list[int]:
    return [r["nr_zona"] for r in con.execute(f"SELECT DISTINCT nr_zona FROM {LOCAL_TABLE} ORDER BY nr_zona")]


def locais(con: sqlite3.Connection) -> list[str]:
    return [
        r["nm_local_votacao"]
        for r in con.execute(
            f"SELECT DISTINCT nm_local_votacao FROM {LOCAL_TABLE} ORDER BY nm_local_votacao"
        )
    ]


def candidatos_lista(con: sqlite3.Connection) -> list[dict]:
    """Todos os candidatos distintos (nº, nome e partido), por ordem alfabética."""
    return _rows(
        con.execute(
            f"""
            SELECT DISTINCT nr_votavel, nm_votavel, COALESCE(sg_partido, '-') AS sg_partido
            FROM {LOCAL_TABLE}
            WHERE categoria = 'Candidato'
            ORDER BY nm_votavel
            """
        )
    )


# --------------------------------------------------------------------------- #
# Tabela agregada paginada com filtros
# --------------------------------------------------------------------------- #
def _as_lista(valor) -> list[str]:
    """Normaliza um filtro que pode ser string única ou lista (multi-seleção)."""
    if not valor:
        return []
    if isinstance(valor, str):
        return [valor] if valor.strip() else []
    return [v.strip() for v in valor if v and v.strip()]


def _filtros(filtros: dict) -> tuple[str, list]:
    clausulas, params = [], []
    if filtros.get("zona"):
        clausulas.append("nr_zona = ?")
        params.append(int(filtros["zona"]))

    locais = _as_lista(filtros.get("local"))
    if locais:
        clausulas.append(f"nm_local_votacao IN ({','.join('?' * len(locais))})")
        params.extend(locais)

    candidatos = _as_lista(filtros.get("candidato"))
    if candidatos:
        clausulas.append(f"nr_votavel IN ({','.join('?' * len(candidatos))})")
        params.extend(candidatos)

    if filtros.get("partido"):
        clausulas.append("nr_partido = ?")
        params.append(filtros["partido"])
    if filtros.get("categoria"):
        clausulas.append("categoria = ?")
        params.append(filtros["categoria"])
    if filtros.get("q"):
        clausulas.append("(nm_votavel LIKE ? OR nr_votavel LIKE ? OR nm_local_votacao LIKE ?)")
        termo = f"%{filtros['q']}%"
        params.extend([termo, termo, termo])
    where = (" WHERE " + " AND ".join(clausulas)) if clausulas else ""
    return where, params


def _tabela_e_campos(por_secao: bool) -> tuple[str, str, str, str]:
    """Tabela e colunas da visualização.

    Por padrão usa a tabela-resumo sem seção (``votos_local``); com
    ``por_secao=True`` usa a base detalhada por seção (``votos_agregados``).
    Retorna (tabela, coluna_secao, ordem_secao, coluna_secoes).
    """
    if por_secao:
        return TABLE, "nr_secao,", ", nr_secao", ""
    return LOCAL_TABLE, "", "", ", secoes"


def tabela_agregada(
    con: sqlite3.Connection, filtros: dict, pagina: int, por_pagina: int,
    por_secao: bool = False,
) -> dict:
    where, params = _filtros(filtros)
    tabela, col_secao, ord_secao, col_secoes = _tabela_e_campos(por_secao)
    total = con.execute(f"SELECT COUNT(*) AS n FROM {tabela}{where}", params).fetchone()[0]
    offset = (pagina - 1) * por_pagina
    linhas = _rows(
        con.execute(
            f"""
            SELECT nr_zona, nm_local_votacao, nr_votavel, nm_votavel,
                   {col_secao}
                   categoria, COALESCE(sg_partido, '-') AS sg_partido,
                   qt_votos
                   {col_secoes}
            FROM {tabela}{where}
            ORDER BY qt_votos DESC, nr_zona{ord_secao}
            LIMIT ? OFFSET ?
            """,
            [*params, por_pagina, offset],
        )
    )
    return {"linhas": linhas, "total": total}


def candidatos_ranking(con: sqlite3.Connection, busca: str, pagina: int, por_pagina: int) -> dict:
    cond = "categoria='Candidato'"
    params: list = []
    if busca:
        cond += " AND nm_votavel LIKE ?"
        params.append(f"%{busca}%")

    total = con.execute(
        f"SELECT COUNT(DISTINCT nr_votavel) AS n FROM {LOCAL_TABLE} WHERE {cond}", params
    ).fetchone()["n"]

    offset = (pagina - 1) * por_pagina
    linhas = _rows(
        con.execute(
            f"""
            SELECT nr_votavel, nm_votavel, COALESCE(sg_partido,'-') AS sg_partido,
                   nm_partido, SUM(qt_votos) AS total
            FROM {LOCAL_TABLE}
            WHERE {cond}
            GROUP BY nr_votavel
            ORDER BY total DESC
            LIMIT ? OFFSET ?
            """,
            [*params, por_pagina, offset],
        )
    )
    return {"linhas": linhas, "total": total}


def exportar_filtrado(con: sqlite3.Connection, filtros: dict, por_secao: bool = False):
    """Gera as linhas (tuplas) da tabela agregada para exportação em CSV."""
    where, params = _filtros(filtros)
    tabela, col_secao, ord_secao, col_secoes = _tabela_e_campos(por_secao)
    cur = con.execute(
        f"""
        SELECT nr_zona, nm_local_votacao, nr_votavel, nm_votavel,
               {col_secao}
               categoria, COALESCE(sg_partido, '') AS sg_partido,
               qt_votos
               {col_secoes}
        FROM {tabela}{where}
        ORDER BY nr_zona{ord_secao}, qt_votos DESC
        """,
        params,
    )
    cabecalho = [c[0] for c in cur.description]
    return cabecalho, cur
