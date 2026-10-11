# syntax=docker/dockerfile:1
FROM python:3.14-slim

# Ambiente Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/app/data/processed/eleicao.db

WORKDIR /app

# Dependências do sistema (mínimas) + dependências Python
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Código da aplicação, ETL e módulo compartilhado de esquema
COPY app ./app
COPY etl ./etl
COPY esquema.py ./
COPY wsgi.py run.py ./

# Dados de origem (arquivo .zip fornecido em data/raw)
COPY data/raw/ ./data/raw/

# Script de entrada
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /app/data/processed

# Usuário sem privilégios
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "wsgi:app"]
