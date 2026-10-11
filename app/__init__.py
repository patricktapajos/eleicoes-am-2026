"""Fábrica da aplicação Flask para visualização dos dados da eleição."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from . import db
from .routes import bp

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT_DIR / "data" / "processed" / "eleicao.db"


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    # FLASK_DEBUG=1 habilita recarga de templates/estáticos (útil no Docker
    # com o código montado por bind mount). Em produção fica desligado.
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.config.from_mapping(
        DATABASE=os.getenv("DB_PATH", str(DEFAULT_DB)),
        SECRET_KEY=os.getenv("SECRET_KEY", "eleicoes-2026"),
        JSON_SORT_KEYS=False,
        DEBUG=debug,
        TEMPLATES_AUTO_RELOAD=debug,
        SEND_FILE_MAX_AGE_DEFAULT=0 if debug else None,
    )
    if config:
        app.config.update(config)

    # Preserva acentuação na saída JSON.
    app.json.ensure_ascii = False

    db.init_app(app)
    app.register_blueprint(bp)

    @app.template_filter("num")
    def format_number(value) -> str:
        """Formata inteiros no padrão brasileiro (1.234.567)."""
        try:
            return f"{int(value):,}".replace(",", ".")
        except (TypeError, ValueError):
            return "0"

    @app.template_filter("pct")
    def format_pct(value) -> str:
        try:
            return f"{float(value):.1f}".replace(".", ",") + "%"
        except (TypeError, ValueError):
            return "0%"

    return app
