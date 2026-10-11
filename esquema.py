"""Esquema das tabelas-resumo derivadas da base de votos.

O banco é gerado por ``python -m etl.etl``. Este módulo guarda o DDL das
tabelas derivadas (``votos_local`` e ``zona_stats``) para que o ETL e a
aplicação usem exatamente a mesma definição, e oferece uma migração
idempotente para bancos criados por versões anteriores do ETL.

Uso:
    from esquema import criar_resumos, problemas_de_esquema
"""
from __future__ import annotations

import sqlite3

TABELA_BASE = "votos_agregados"
TABELA_RESUMO = "votos_local"
TABELA_ZONA = "zona_stats"

# Colunas mínimas que cada tabela precisa ter para a aplicação funcionar.
COLUNAS_RESUMO = {
    "nr_zona", "nm_local_votacao", "nr_votavel", "nm_votavel",
    "nr_partido", "sg_partido", "nm_partido", "categoria", "qt_votos", "secoes",
}
COLUNAS_ZONA = {"nr_zona", "qt_votos", "locais", "secoes"}

_DDL_RESUMO = f"""
    CREATE TABLE {TABELA_RESUMO} AS
    SELECT nr_zona, nm_local_votacao, nr_votavel, nm_votavel,
           nr_partido, sg_partido, nm_partido, categoria,
           SUM(qt_votos) AS qt_votos,
           COUNT(DISTINCT nr_secao) AS secoes
    FROM {TABELA_BASE}
    GROUP BY nr_zona, nm_local_votacao, nr_votavel, nm_votavel
"""

_DDL_ZONA = f"""
    CREATE TABLE {TABELA_ZONA} AS
    SELECT nr_zona,
           SUM(qt_votos) AS qt_votos,
           COUNT(DISTINCT nm_local_votacao) AS locais,
           COUNT(DISTINCT nr_secao) AS secoes
    FROM {TABELA_BASE}
    GROUP BY nr_zona
"""

_INDICES_RESUMO = [
    f"idx_local_votos ON {TABELA_RESUMO}(qt_votos)",
    f"idx_local_zona ON {TABELA_RESUMO}(nr_zona)",
    f"idx_local_votavel ON {TABELA_RESUMO}(nr_votavel)",
    f"idx_local_partido ON {TABELA_RESUMO}(nr_partido)",
    f"idx_local_categoria ON {TABELA_RESUMO}(categoria)",
]
_INDICE_ZONA = f"idx_zona_stats ON {TABELA_ZONA}(nr_zona)"


def _tem_tabela(con: sqlite3.Connection, nome: str) -> bool:
    return con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (nome,)
    ).fetchone()[0] == 1


def _colunas(con: sqlite3.Connection, nome: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({nome})")}


def problemas_de_esquema(con: sqlite3.Connection) -> list[str]:
    """Lista o que falta no banco (vazio = esquema completo)."""
    faltas: list[str] = []
    if not _tem_tabela(con, TABELA_BASE):
        faltas.append(
            f"a tabela principal '{TABELA_BASE}' não existe — rode o ETL: "
            "python -m etl.etl (ou FORCE_ETL=1 no Docker)"
        )
        return faltas
    if not _tem_tabela(con, TABELA_RESUMO) or not COLUNAS_RESUMO <= _colunas(con, TABELA_RESUMO):
        faltas.append(f"a tabela-resumo '{TABELA_RESUMO}' está ausente ou desatualizada")
    if not _tem_tabela(con, TABELA_ZONA) or not COLUNAS_ZONA <= _colunas(con, TABELA_ZONA):
        faltas.append(f"a tabela-resumo '{TABELA_ZONA}' está ausente ou desatualizada")
    return faltas


def criar_resumos(con: sqlite3.Connection, forcar: bool = False) -> list[str]:
    """Cria/atualiza as tabelas-resumo a partir da base (idempotente).

    Usa ``BEGIN IMMEDIATE`` para serializar escritores concorrentes (ex.: dois
    workers do gunicorn subindo ao mesmo tempo) e tolera a corrida em que
    outra conexão já criou a tabela.

    Retorna a lista de tabelas que foram (re)criadas.
    """
    definicoes = (
        (TABELA_RESUMO, COLUNAS_RESUMO, _DDL_RESUMO, _INDICES_RESUMO),
        (TABELA_ZONA, COLUNAS_ZONA, _DDL_ZONA, [_INDICE_ZONA]),
    )
    criadas: list[str] = []

    # Se o chamador já tem uma transação aberta (ex.: o ETL), usamos a dele;
    # caso contrário iniciamos uma própria para serializar escritores.
    transacao_propria = not con.in_transaction
    if transacao_propria:
        con.execute("BEGIN IMMEDIATE")
    try:
        for tabela, colunas, ddl, indices in definicoes:
            desatualizada = (
                not _tem_tabela(con, tabela)
                or not colunas <= _colunas(con, tabela)
            )
            if not (forcar or desatualizada):
                continue
            con.execute(f"DROP TABLE IF EXISTS {tabela}")
            try:
                con.execute(ddl)
            except sqlite3.OperationalError as exc:
                if "already exists" not in str(exc).lower():
                    raise
                continue  # outra conexão criou a tabela primeiro
            for indice in indices:
                con.execute(f"CREATE INDEX IF NOT EXISTS {indice}")
            criadas.append(tabela)
        if transacao_propria:
            con.commit()
    except Exception:
        if transacao_propria:
            con.rollback()
        raise
    return criadas
