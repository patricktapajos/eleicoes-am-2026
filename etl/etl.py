"""ETL: extrai o CSV da votação, agrupa e carrega em SQLite.

Pipeline:
  1. Extrai o arquivo .zip de ``data/raw`` (se ainda não estiver extraído).
  2. Lê o CSV (ISO-8859-1, separador ``;``).
  3. Agrupa por ``nr_zona, nm_local_votacao, nr_votavel, nm_votavel, nr_secao``
     e totaliza ``qt_votos``.
  4. Enriquece com partido/categoria derivados do número votável.
  5. Grava tudo no banco SQLite consumido pela aplicação Flask.

Uso:
    python -m etl.etl
"""
from __future__ import annotations

import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import esquema

# --------------------------------------------------------------------------- #
# Configuração (sobrescrevível por variáveis de ambiente)
# --------------------------------------------------------------------------- #
ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = Path(os.getenv("RAW_DIR", ROOT_DIR / "data" / "raw"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", ROOT_DIR / "data" / "processed"))
ZIP_PATH = Path(
    os.getenv(
        "ZIP_PATH",
        RAW_DIR / "votacao_secao-deputado_estadual_t1_2026_am.csv.zip",
    )
)
DB_PATH = Path(os.getenv("DB_PATH", PROCESSED_DIR / "eleicao.db"))

# Nomes compartilhados com a aplicação (ver esquema.py).
TABLE = esquema.TABELA_BASE
LOCAL_TABLE = esquema.TABELA_RESUMO
ZONA_TABLE = esquema.TABELA_ZONA
META_TABLE = "metadados"

# Colunas do agrupamento definido para a análise.
GROUP_COLS = ["nr_zona", "nm_local_votacao", "nr_votavel", "nm_votavel", "nr_secao"]
MEASURE = "qt_votos"

# Siglas por número de partido (prefixo de 2 dígitos do número votável).
SIGLAS = {
    "10": "REPUBLICANOS",
    "11": "PP",
    "12": "PDT",
    "13": "PT",
    "14": "PTB",
    "15": "MDB",
    "16": "PSTU",
    "17": "PSL",
    "18": "REDE",
    "19": "PODE",
    "20": "PODE",
    "21": "PCB",
    "22": "PL",
    "23": "CIDADANIA",
    "25": "DEM",
    "27": "DC",
    "28": "PRTB",
    "29": "PCO",
    "30": "NOVO",
    "33": "PMN",
    "35": "PMB",
    "36": "AGIR",
    "40": "PSB",
    "43": "PV",
    "44": "UNIÃO",
    "45": "PSDB",
    "50": "PSOL",
    "51": "PATRIOTA",
    "55": "PSD",
    "65": "PCdoB",
    "70": "AVANTE",
    "77": "SOLIDARIEDADE",
    "90": "PROS",
}
BRANCO, NULO = "95", "96"


def log(msg: str) -> None:
    print(f"[etl] {msg}", flush=True)


def extract_zip(zip_path: Path = ZIP_PATH) -> Path:
    """Extrai o CSV contido em ``zip_path`` para ``RAW_DIR``."""
    if not zip_path.exists():
        raise FileNotFoundError(f"Arquivo .zip não encontrado: {zip_path}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"Nenhum CSV dentro de {zip_path}")
        member = csv_names[0]
        target = RAW_DIR / Path(member).name
        if target.exists() and target.stat().st_size > 0:
            log(f"CSV já extraído: {target.name}")
        else:
            zf.extract(member, RAW_DIR)
            log(f"Extraído: {member} -> {target.name}")
    return target


def classify(nr: str) -> str:
    """Classifica o número votável."""
    if nr == BRANCO:
        return "Branco"
    if nr == NULO:
        return "Nulo"
    if len(nr) == 2:
        return "Legenda"
    return "Candidato"


def load_csv(csv_path: Path) -> pd.DataFrame:
    log(f"Lendo CSV: {csv_path.name} ({csv_path.stat().st_size / 1e6:.1f} MB)")
    return pd.read_csv(
        csv_path,
        sep=";",
        encoding="latin-1",
        dtype=str,
        keep_default_na=False,
        low_memory=False,
    )


def build_party_map(df: pd.DataFrame) -> dict[str, str]:
    """Constrói ``{nr_partido: nome}`` a partir das linhas de legenda."""
    legendas = df[(df["nr_votavel"].str.len() == 2) & (~df["nr_votavel"].isin([BRANCO, NULO]))]
    return dict(zip(legendas["nr_votavel"], legendas["nm_votavel"]))


def transform(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    df = df.copy()
    df[MEASURE] = pd.to_numeric(df[MEASURE], errors="coerce").fillna(0).astype("int64")
    df["nr_zona"] = pd.to_numeric(df["nr_zona"], errors="coerce").fillna(0).astype("int64")
    df["nr_secao"] = pd.to_numeric(df["nr_secao"], errors="coerce").fillna(0).astype("int64")

    party_map = build_party_map(df)

    log(f"Agrupando {len(df):,} linhas por {GROUP_COLS}...")
    agg = (
        df.groupby(GROUP_COLS, as_index=False, sort=False)[MEASURE]
        .sum()
        .reset_index(drop=True)
    )
    log(f"Grupos resultantes: {len(agg):,}")

    # Colunas derivadas (dependentes apenas de nr_votavel).
    categorias = agg["nr_votavel"].map(classify)
    nr_partido = agg["nr_votavel"].where(
        categorias == "Legenda", agg["nr_votavel"].str[:2]
    )
    nr_partido = nr_partido.where(categorias.isin(["Candidato", "Legenda"]), None)
    sg_partido = nr_partido.map(SIGLAS)
    nm_partido = nr_partido.map(party_map)
    # Fallback: legenda sem entrada no mapa usa o próprio nome votável.
    nm_partido = nm_partido.where(
        ~(categorias == "Legenda"), nm_partido
    ).fillna(agg["nm_votavel"])

    agg["categoria"] = categorias
    agg["nr_partido"] = nr_partido
    agg["sg_partido"] = sg_partido.fillna(pd.Series([None] * len(agg)))
    agg["nm_partido"] = nm_partido

    # Metadados constantes do arquivo.
    for src, dst in [
        ("nm_municipio", "nm_municipio"),
        ("sg_uf", "sg_uf"),
        ("ds_cargo", "ds_cargo"),
        ("ds_eleicao", "ds_eleicao"),
        ("nr_turno", "nr_turno"),
    ]:
        agg[dst] = df[src].iloc[0] if src in df.columns and len(df) else None

    agg = agg[
        GROUP_COLS
        + [
            MEASURE,
            "categoria",
            "nr_partido",
            "sg_partido",
            "nm_partido",
            "nm_municipio",
            "sg_uf",
            "ds_cargo",
            "ds_eleicao",
            "nr_turno",
        ]
    ]
    return agg, party_map


def write_sqlite(agg: pd.DataFrame, meta: dict[str, str], db_path: Path = DB_PATH) -> None:
    import sqlite3

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    log(f"Gravando SQLite: {db_path}")

    with sqlite3.connect(db_path) as con:
        agg.to_sql(TABLE, con, index=False, if_exists="replace")
        con.execute(f"CREATE INDEX idx_zona ON {TABLE}(nr_zona)")
        con.execute(f"CREATE INDEX idx_votavel ON {TABLE}(nr_votavel)")
        con.execute(f"CREATE INDEX idx_partido ON {TABLE}(nr_partido)")
        con.execute(f"CREATE INDEX idx_categoria ON {TABLE}(categoria)")
        con.execute(
            f"CREATE INDEX idx_secao ON {TABLE}(nr_zona, nr_secao)"
        )

        # Tabelas-resumo (definição compartilhada em esquema.py): o painel
        # padrão consulta elas em vez de agregar os 345k registros por requisição.
        esquema.criar_resumos(con)

        con.execute(
            f"CREATE TABLE {META_TABLE} (chave TEXT PRIMARY KEY, valor TEXT)"
        )
        con.executemany(
            f"INSERT OR REPLACE INTO {META_TABLE} (chave, valor) VALUES (?, ?)",
            list(meta.items()),
        )
        con.commit()
        total = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        resumo = con.execute(f"SELECT COUNT(*) FROM {LOCAL_TABLE}").fetchone()[0]
    log(f"OK: {total:,} linhas em '{TABLE}' + {resumo:,} em '{LOCAL_TABLE}'")


def run() -> None:
    started = datetime.now(timezone.utc)
    csv_path = extract_zip()
    df = load_csv(csv_path)
    agg, _ = transform(df)

    meta = {
        "arquivo_origem": csv_path.name,
        "linhas_origem": f"{len(df):,}".replace(",", "."),
        "linhas_agregadas": f"{len(agg):,}".replace(",", "."),
        "total_votos": str(int(agg[MEASURE].sum())),
        "nm_municipio": str(df["nm_municipio"].iloc[0]),
        "sg_uf": str(df["sg_uf"].iloc[0]),
        "ds_cargo": str(df["ds_cargo"].iloc[0]),
        "ds_eleicao": str(df["ds_eleicao"].iloc[0]),
        "dt_eleicao": str(df["dt_eleicao"].iloc[0]),
        "nr_turno": str(df["nr_turno"].iloc[0]),
        "processado_em": started.astimezone().strftime("%d/%m/%Y %H:%M:%S"),
    }
    write_sqlite(agg, meta)
    log(f"Concluído em {(datetime.now(timezone.utc) - started).total_seconds():.1f}s")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        log(f"ERRO: {exc}")
        sys.exit(1)
