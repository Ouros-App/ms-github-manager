# Ouros GitHub Repository Manager

API FastAPI para listar templates e criar repositorios na organizacao "Ouros App" usando `PyGithub`.

O servico usa `GH_TOKEN` ou `GITHUB_TOKEN` definido no `.env` para autenticar na API do GitHub.

## Funcionalidades

- Lista repositorios de template da organizacao cujo nome termina em `-template`.
- Cria repositorio no modo cru com README, licenca MIT e `.gitignore` por linguagem quando disponivel.
- Cria repositorio a partir de um template existente na mesma organizacao.
- Aplica workflow de CI/CD com build, testes e SonarCloud para React + TypeScript + Vite, Java Spring REST com Gradle, Python FastAPI e Android Kotlin com Gradle.
- Aplica protecao na branch `main`, exigindo pull request, uma aprovacao, status checks `ci`, `conventional-commits`, `sonarcloud` e `codeql`, historico linear e conversas resolvidas.
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
| `GITHUB_ORG_LOGIN` | `Ouros-App` | Login/slug da organizacao no GitHub. |
| `GH_TOKEN` | - | Token do GitHub usado pelo `PyGithub`. Nao commitar este valor. |
| `SONAR_CLOUD_TOKEN` | - | Token usado para criar o secret `SONAR_TOKEN` nos repositorios gerados. |
| `TEMPLATE_SUFFIX` | `-template` | Sufixo usado para descobrir repositorios de template. |
| `DEFAULT_BRANCH` | `main` | Branch principal protegida pelo servico. |
| `GH_TIMEOUT_SECONDS` | `120` | Timeout para as chamadas do cliente GitHub. |

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

Valores aceitos para `language`: `frontend`, `springboot`, `fastapi`, `android`.

O servico adiciona o workflow `.github/workflows/ci-cd.yml` conforme a linguagem escolhida. O template Spring gera um esqueleto REST com `build.gradle`, `settings.gradle`, controllers, teste basico, plugins de `jacoco` e `sonarqube`, e sobrescreve `application.properties` e `application-local.properties` com base no nome do repositorio, descartando o prefixo `ms-` e o sufixo `-template` quando existirem. O template Android gera estrutura Kotlin/Gradle no padrao do Android Studio com `settings.gradle.kts`, `build.gradle.kts`, modulo `app`, `AndroidManifest.xml`, `MainActivity.kt`, recursos e teste unitario. Quando o repo nasce de um template Android, o servico substitui `{{PROJECT_NAME}}`, `{{APP_LABEL}}`, `{{PACKAGE_NAME}}`, `{{PACKAGE_PATH}}` e `{{APPLICATION_CLASS_NAME}}`, incluindo caminhos de arquivo. Quando o repo nasce de um template Spring, a estrutura herdada em `src/main/java`, `src/main/kotlin`, `src/test/java` e `src/test/kotlin` tambem e limpa antes de gerar as classes novas. Exemplo: `ms-orders-api-template` vira `spring.application.name=orders-api`, `com.ourosapp.ordersapi` e `OrdersApiApplication`. O SonarCloud roda em um job separado chamado `sonarcloud` e usa `SONAR_TOKEN` como secret do repositorio. O GitHub CodeQL roda em paralelo no job `codeql`. O deploy nao faz parte desse workflow: releases podem disparar outra pipeline separada.
Os templates usados ficam em `app/templates/workflows`.

### Criar repositorio a partir de template

```http
POST /repositories/from-template
```

```json
{
  "name": "billing-api",
  "template_name": "ms-fastapi-template",
  "description": "API de faturamento",
  "visibility": "private"
}
```

O workflow de CI/CD e escolhido pelo nome do template quando ele contem `frontend`, `react`, `vite`, `typescript`, `spring`, `java`, `android`, `kotlin`, `mobile` ou `fastapi`. Outros templates recebem um workflow generico.

O repositorio escolhido em `template_name` precisa estar marcado como template no GitHub. Se o nome existir mas o repo nao estiver habilitado como template, a API do GitHub pode responder com `404 Not Found`.

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
