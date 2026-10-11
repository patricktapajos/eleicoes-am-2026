# Painel de Votação — Eleições 2026 (AM)

Aplicação web em **Python 3.14 + Flask** para visualizar os dados de votação da
eleição de **Deputado Estadual** em **Manaus/AM**. O painel traz **números
grandes** (KPIs), **gráficos de pizza**, **gráficos de barras** e **tabelas**,
além de uma API JSON e exportação CSV.

## O que a aplicação faz

1. **Extrai** o arquivo `data/raw/votacao_secao-deputado_estadual_t1_2026_am.csv.zip`.
2. **Agrupa** os registros pelas colunas
   `nr_zona`, `nm_local_votacao`, `nr_votavel`, `nm_votavel`, `nr_secao`
   e **totaliza** `qt_votos` (ETL em `etl/etl.py`).
3. Carrega o resultado agregado em um banco **SQLite** (`data/processed/eleicao.db`), junto com duas
   tabelas-resumo pré-calculadas: `votos_local` (mesma agregação **sem a seção**, 74.337 linhas)
   e `zona_stats` (13 linhas, com votos/locais/seções por zona). Elas deixam os painéis rápidos:
   nenhuma requisição precisa agregar os 345 mil registros.
4. Serve um painel Flask com KPIs, gráficos e tabelas.

## Estrutura do projeto

```
.
├── app/
│   ├── __init__.py          # fábrica da aplicação (create_app)
│   ├── db.py                # acesso ao SQLite (somente leitura)
│   ├── queries.py           # consultas SQL (KPIs, rankings, tabela paginada)
│   ├── routes.py            # páginas, API JSON e exportação CSV
│   ├── templates/           # Jinja2: base, dashboard, candidatos, zonas, dados
│   └── static/              # CSS, JS e Chart.js (vendorizado, funciona offline)
├── etl/etl.py               # extração do .zip, agrupamento e carga no SQLite
├── data/
│   ├── raw/                 # arquivo .zip de origem
│   └── processed/           # eleicao.db (gerado pelo ETL)
├── Dockerfile
├── docker-compose.yml
├── docker/entrypoint.sh
├── requirements.txt
├── run.py                   # servidor de desenvolvimento
└── wsgi.py                  # ponto de entrada WSGI (gunicorn)
```

## Execução local (sem Docker)

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1) Gera a base agregada (extrai o .zip, agrupa e grava o SQLite)
python -m etl.etl

# 2) Sobe a aplicação
python run.py          # ou: gunicorn --bind 0.0.0.0:5000 wsgi:app
```

Acesse <http://localhost:5000>.

## Execução com Docker

O `entrypoint` gera a base agregada automaticamente na primeira inicialização
(quando o banco ainda não existe) e depois inicia o **gunicorn**.

```bash
# Build + subida
docker compose up --build -d

# Acompanhar logs
docker compose logs -f web
```

Acesse <http://localhost:5000>. O banco fica persistido no volume nomeado
`dados_processados`.

Para forçar o reprocessamento do CSV:

```bash
FORCE_ETL=1 docker compose up -d
```

> **Banco de uma versão anterior?** A aplicação detecta e corrige isso sozinha:
> na inicialização ela compara o esquema do SQLite com o esperado e cria as
> tabelas-resumo que faltarem (ex.: `votos_local`, `zona_stats`), sem precisar
> regerar a base. Rodar `python -m etl.etl` ou `FORCE_ETL=1` também resolve.

### Recarga automática (sem rebuild)

O `docker-compose.yml` monta o **código-fonte** (`./app` e `./etl`) como bind
mount e sobe o gunicorn com `--reload`. Assim, alterações no código refletem no
container **sem precisar rebuildar** a imagem:

| Alteração | Como reflete |
| --- | --- |
| Arquivos `.py` em `app/` ou `etl/` | `gunicorn --reload` reinicia os workers automaticamente |
| Templates HTML (`app/templates/`) | Jinja com `auto_reload` (ativado por `FLASK_DEBUG=1`) |
| CSS/JS (`app/static/`) | Servidos a partir do bind mount (recarregue o navegador) |

Basta subir uma vez e editar os arquivos:

```bash
docker compose up -d            # a build só é necessária na primeira vez
docker compose logs -f web      # acompanha os reloads
```

O que **ainda exige** `docker compose up --build`:

- dependências em `requirements.txt`;
- `Dockerfile` e `docker/entrypoint.sh`;
- arquivos de origem em `data/raw` (o `.zip` é embutido na imagem);
- `wsgi.py` / `run.py` na raiz (pontos de entrada, não são montados).

Para desativar o modo de desenvolvimento (sem reload/tracebacks), defina
`FLASK_DEBUG: "0"` e remova `--reload` do `command` no `docker-compose.yml`.

Build manual da imagem:

```bash
docker build -t eleicoes2026:latest .
docker run --rm -p 5000:5000 eleicoes2026:latest
```

## Páginas e endpoints

| Rota | Descrição |
| --- | --- |
| `GET /` | Painel: números grandes, pizzas e barras |
| `GET /candidatos` | Ranking de candidatos (busca + paginação) e gráficos |
| `GET /zonas` | Votos por zona eleitoral (tabela, barra e pizza) |
| `GET /dados` | Tabela agregada com filtros e paginação (zona, **local de votação múltiplo**, **candidato múltiplo**, partido, categoria, busca). **Agrupa por zona/local/votável por padrão; marque “Incluir seção” para detalhar por `nr_secao`** |
| `GET /dados/export.csv` | Exportação CSV da base agregada (respeita os filtros) |
| `GET /api/resumo` | Metadados + KPIs em JSON |
| `GET /api/votos-por-categoria` | Votos por tipo (Candidato/Legenda/Branco/Nulo) |
| `GET /api/votos-por-partido` | Votos por partido |
| `GET /api/top-candidatos?limite=N` | Candidatos mais votados |
| `GET /api/votos-por-zona` | Votos por zona |
| `GET /api/top-locais?limite=N` | Locais de votação mais votados |

## Classificação dos votáveis

O ETL deriva, a partir do número votável (`nr_votavel`):

- **Candidato** — número de 5 dígitos (o partido vem do prefixo de 2 dígitos);
- **Legenda** — número de 2 dígitos de partido;
- **Branco** (`95`) e **Nulo** (`96`).

## Variáveis de ambiente

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `DB_PATH` | `data/processed/eleicao.db` | Caminho do banco SQLite |
| `RAW_DIR` | `data/raw` | Diretório do arquivo de origem |
| `PROCESSED_DIR` | `data/processed` | Diretório de saída do ETL |
| `ZIP_PATH` | `data/raw/votacao_secao-...csv.zip` | Caminho do `.zip` |
| `FORCE_ETL` | `0` | Se `1`, reprocessa o CSV na inicialização do contêiner |

## Resultado do ETL (base de exemplo)

- 345.398 registros de origem → 345.398 linhas agregadas (por seção) + 74.337 no resumo sem seção
- 1.220.980 votos no total · 278 candidatos · 13 zonas · 4.013 seções · 477 locais
