"""Camada de acesso ao banco SQLite (somente leitura) + migração do esquema."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

import esquema

# Nomes compartilhados com o ETL (ver esquema.py).
TABLE = esquema.TABELA_BASE
LOCAL_TABLE = esquema.TABELA_RESUMO
ZONA_TABLE = esquema.TABELA_ZONA
META_TABLE = "metadados"

_MENSAGEM_ESQUEMA = (
    "Banco de dados desatualizado em '{db}': {problemas}. "
    "Rode o ETL para regerar a base: `python -m etl.etl` "
    "(no Docker: `FORCE_ETL=1 docker compose up -d`)."
)


def connect_ro(db_path: str | Path) -> sqlite3.Connection:
    """Abre uma conexão independente (somente leitura) para o banco."""
    path = Path(db_path)
    if not path.exists():
        raise RuntimeError(
            f"Banco não encontrado em '{path}'. "
            "Execute o ETL primeiro: python -m etl.etl"
        )
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def migrar_esquema(db_path: str | Path) -> list[str]:
    """Cria as tabelas-resumo que faltarem (para bancos de versões antigas).

    Abre uma conexão de escrita pontual; retorna as tabelas criadas.
    """
    path = Path(db_path)
    if not path.exists():
        return []
    con = sqlite3.connect(path)
    try:
        if not esquema.problemas_de_esquema(con):
            return []
        if esquema._tem_tabela(con, esquema.TABELA_BASE):
            criadas = esquema.criar_resumos(con)
            if criadas:
                print(f"[db] esquema atualizado: criadas {', '.join(criadas)}", flush=True)
            return criadas
        return []
    finally:
        con.close()


def _validar_esquema(con: sqlite3.Connection, db_path) -> None:
    faltas = esquema.problemas_de_esquema(con)
    if faltas:
        raise RuntimeError(
            _MENSAGEM_ESQUEMA.format(db=db_path, problemas="; ".join(faltas))
        )


def get_db() -> sqlite3.Connection:
    """Retorna a conexão do request atual (somente leitura)."""
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        con = connect_ro(db_path)
        _validar_esquema(con, db_path)
        g.db = con
    return g.db


def close_db(_exc=None) -> None:
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    # Migra bancos gerados por versões antigas do ETL (ex.: antes de existir
    # a tabela-resumo `votos_local`). Ignora silenciosamente se o arquivo não
    # existir — o get_db() devolve uma mensagem clara nesse caso.
    try:
        migrar_esquema(app.config["DATABASE"])
    except Exception as exc:  # noqa: BLE001 - nunca impedir o boot por isso
        print(f"[db] atenção: não foi possível migrar o esquema: {exc}", flush=True)
