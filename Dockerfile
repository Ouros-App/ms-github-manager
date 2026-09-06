FROM python:3.12-slim

# Build arguments
ARG APP_NAME
ARG APP_PORT=8000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=${APP_PORT} \
    APP_NAME=${APP_NAME}

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | bash \
    && apt-get update \
    && apt-get install -y --no-install-recommends infisical \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements primeiro para melhor cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o restante da aplicação
COPY app ./app
COPY docker/infisical-entrypoint.sh /usr/local/bin/infisical-entrypoint
RUN chmod 755 /usr/local/bin/infisical-entrypoint

# Verificar templates
RUN test -f app/templates/workflows/fastapi.yml \
    && test -f app/templates/workflows/frontend.yml \
    && test -f app/templates/workflows/android.yml \
    && test -f app/templates/workflows/springboot.yml \
    && test -f app/templates/workflows/generic.yml

EXPOSE ${APP_PORT}

# CORREÇÃO: Usar sh -c para garantir expansão da variável
ENTRYPOINT ["/usr/local/bin/infisical-entrypoint"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]
