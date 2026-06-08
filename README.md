# Ouros GitHub Repository Manager

API FastAPI para listar templates e criar repositorios na organizacao "Ouros App" usando o GitHub CLI (`gh`).

O servico assume que o `gh` ja esta instalado, autenticado e autorizado no servidor onde a API roda.
Opcionalmente, o `gh` tambem pode autenticar usando `GH_TOKEN` definido no `.env`.

## Funcionalidades

- Lista repositorios de template da organizacao cujo nome termina em `-template`.
- Cria repositorio no modo cru com README, licenca MIT e `.gitignore` por linguagem quando disponivel.
- Cria repositorio a partir de um template existente na mesma organizacao.
- Aplica workflow de CI/CD para React + TypeScript + Vite, Java Spring Boot e Python FastAPI.
- Aplica protecao na branch `main`, exigindo pull request, uma aprovacao, status checks `ci` e `conventional-commits`, historico linear e conversas resolvidas.
- Expoe Swagger UI em `/docs`, ReDoc em `/redoc` e OpenAPI JSON em `/openapi.json`.
- Expoe status de criacao por `creation_id`.

## Configuracao

Crie o arquivo `.env` a partir do exemplo:

```bash
cp .env.example .env
```

Variaveis principais:

| Nome | Padrao | Descricao |
| --- | --- | --- |
| `APP_PORT` | `8000` | Porta publicada no host pelo Docker Compose. |
| `GITHUB_ORG_LOGIN` | `Ouros-App` | Login/slug da organizacao no GitHub usado pelo `gh`. |
| `GH_TOKEN` | - | Token do GitHub usado pelo GitHub CLI. Nao commitar este valor. |
| `TEMPLATE_SUFFIX` | `-template` | Sufixo usado para descobrir repositorios de template. |
| `DEFAULT_BRANCH` | `main` | Branch principal protegida pelo servico. |
| `GH_TIMEOUT_SECONDS` | `120` | Timeout para cada chamada ao `gh`. |

## Rodando localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Acesse:

- API: `http://localhost:8000`
- Health check: `http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Endpoints

### Listar templates

```http
GET /templates
```

Retorna os repositorios da organizacao cujo nome termina com `-template`.

### Criar repositorio cru

```http
POST /repositories/bare
```

```json
{
  "name": "orders-api",
  "description": "API de pedidos",
  "visibility": "private",
  "language": "fastapi"
}
```

Valores aceitos para `visibility`: `private`, `public`, `internal`.

Valores aceitos para `language`: `frontend`, `springboot`, `fastapi`.

O servico adiciona o workflow `.github/workflows/ci-cd.yml` conforme a linguagem escolhida. Backends sobem PostgreSQL, MongoDB e Redis no job de CI para testes de integracao.
Os templates usados ficam em `app/templates/workflows`.

### Criar repositorio a partir de template

```http
POST /repositories/from-template
```

```json
{
  "name": "billing-api",
  "template_name": "fastapi-template",
  "description": "API de faturamento",
  "visibility": "private"
}
```

O workflow de CI/CD e escolhido pelo nome do template quando ele contem `frontend`, `react`, `vite`, `typescript`, `spring`, `java` ou `fastapi`. Outros templates recebem um workflow generico.

### Consultar status de criacao

```http
GET /repositories/creations/{creation_id}
```

Exemplo de resposta:

```json
{
  "creation_id": "8ff5a88d-d2c4-4c27-9c2d-13e0a19599e1",
  "status": "running",
  "repository": "Ouros-App/orders-api",
  "mode": "bare",
  "started_at": "2026-06-07T23:00:00Z",
  "finished_at": null,
  "steps": ["Criando repositorio cru"],
  "error": null,
  "url": null
}
```

O status fica em memoria do processo. Para execucao com multiplas replicas ou historico persistente, substitua o armazenamento interno por banco ou fila.

## Rodando com Docker Compose

```bash
docker compose up --build
```

Para parar:

```bash
docker compose down
```
