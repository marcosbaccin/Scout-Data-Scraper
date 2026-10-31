# syntax=docker/dockerfile:1
# Imagem de produção da API + dashboard (somente leitura sobre o scout.db).
# O scraping NÃO roda aqui: o banco é gerado fora e montado como volume em /data.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production \
    DB_PATH=/app/scout.db \
    PORT=8000 \
    WEB_CONCURRENCY=1

WORKDIR /app

# Dependências primeiro (melhor cache de camadas).
COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

# Apenas o código necessário para servir a API e o dashboard.
COPY api ./api
COPY core ./core
COPY frontend ./frontend
COPY analytics_engine.py explorer_engine.py ./

# Banco de dados Gold consolidado (~7 MB) para execução self-contained na nuvem
COPY scout.db ./scout.db

# Usuário sem privilégios; /data suporta montagem de volume externo opcional
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin scout \
    && mkdir -p /data && chown scout /data && chown scout /app/scout.db
USER scout

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4).status == 200 else 1)"

# Forma shell para expandir $PORT/$WEB_CONCURRENCY; `exec` repassa sinais (SIGTERM) ao uvicorn.
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY}"]

