# Ouros GitHub Repository Manager

API FastAPI para listar templates e criar repositórios na organização `Ouros-App` usando `PyGithub`.

## Status e escopo

O serviço atual:

- lista repositórios de template da organização;
- cria repositórios no modo cru ou a partir de um template;
- aplica workflows de CI/CD, templates de pull request, label de reexecução da CI e proteção da branch principal;
- gera estruturas específicas para frontend, Spring Boot, FastAPI, Android, PostgreSQL e templates genéricos;
- mantém o status de cada criação em memória e o consulta por `creation_id`;
- serve uma UI estática, documentação OpenAPI e métricas Prometheus.

As criações são iniciadas de forma assíncrona. O status pode ser `queued`, `running`, `done` ou `failed`.

## Principais recursos

- Templates de workflow em `app/templates/workflows`.
- Integração com a API do GitHub por `PyGithub`.
- Scaffolds PostgreSQL e MongoDB, incluindo configuração de secrets quando aplicável.
- SonarCloud em job separado e CodeQL no workflow gerado.
- Proteção da branch definida por `DEFAULT_BRANCH` (`main` por padrão), com pull request, aprovação, checks configurados, histórico linear e conversas resolvidas.
- Interface web em `app/static`.
- Métricas `http_requests_total`, `http_request_duration_seconds` e métricas padrão de processo Python.

## Pré-requisitos

- Python e `pip`.
- Um token do GitHub com permissões suficientes para a organização e os repositórios gerenciados.
- Bash para os scripts `run.sh` e `run_compose.sh`.
- Docker apenas para os fluxos de container.

As dependências Python estão fixadas em `requirements.txt`, incluindo FastAPI, Uvicorn, `python-dotenv`, `PyGithub`, `httpx` e `prometheus-client`.

## Configuração

Crie o arquivo `.env` a partir do exemplo:

```bash
cp .env.example .env
```

Variáveis usadas pelo serviço:

| Variável | Padrão no código | Uso |
| --- | --- | --- |
| `APP_PORT` | `8000` no exemplo | Porta usada pela configuração de execução. |
| `PROJECT_NAME` | `Ouros GitHub Repository Manager` | Nome da API. |
| `PROJECT_DESCRIPTION` | descrição da API | Descrição da API. |
| `GITHUB_ORG_LOGIN` | `Ouros-App` | Organização gerenciada. |
| `GH_TOKEN` ou `GITHUB_TOKEN` | sem padrão | Token usado pelo GitHub. |
| `SONAR_CLOUD_TOKEN` | sem padrão | Token usado na integração com SonarCloud. |
| `TEMPLATE_SUFFIX` | `-template` | Sufixo para descobrir templates. |
| `DEFAULT_BRANCH` | `main` | Branch protegida; este é apenas o valor padrão. |
| `GH_TIMEOUT_SECONDS` | `120` no código | Timeout do cliente GitHub. |
| `APP_NAME` | `ms-github-manager` no exemplo | Nome usado pelos scripts/container. |
| `VERSION` | `0.1.0` no código | Versão exposta pela API. |
| `AUTH_USERNAME` | `admin` | Usuário do login da UI/API. |
| `AUTH_PASSWORD` | sem padrão | Senha do login. |
| `SESSION_SECRET` | sem padrão | Segredo para assinar a sessão. |
| `SESSION_TTL_SECONDS` | `28800` | Duração da sessão. |
| `AUTH_COOKIE_SECURE` | `true` | Define o atributo Secure do cookie. |
| `METRICS_TOKEN` | sem padrão | Token Bearer para `/metrics`. |

Não versione valores reais de `GH_TOKEN`, `GITHUB_TOKEN`, `SONAR_CLOUD_TOKEN`, `AUTH_PASSWORD` ou `SESSION_SECRET`.

Para execução local em HTTP, `AUTH_COOKIE_SECURE=false` pode ser necessário para que o navegador envie o cookie de sessão. Em produção, mantenha cookies seguros conforme o ambiente HTTPS.

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pytest
uvicorn app.main:app --reload
```

A API escuta em `http://localhost:8000` por padrão. As rotas de criação exigem uma sessão autenticada. Faça login em `POST /auth/login` com:

```json
{
  "username": "admin",
  "password": "sua-senha"
}
```

A sessão é mantida em um cookie HTTP-only chamado `session`.

## Endpoints

### Autenticação e acesso

- `POST /auth/login`: cria a sessão.
- `GET /auth/session`: valida a sessão atual.
- `POST /auth/logout`: remove a sessão.
- `GET /health`: health check com serviço, versão, organização e branch padrão.
- `GET /ui`: interface web estática.
- `GET /app`: redireciona para `/ui`.
- `GET /static/*`: arquivos estáticos.

As demais rotas, incluindo `/docs`, `/redoc`, `/openapi.json`, `/`, `/templates` e as rotas de criação, passam pela autenticação de sessão. `/metrics` exige `Authorization: Bearer <METRICS_TOKEN>`; com o middleware atual, deixe `METRICS_TOKEN` preenchido para acessar a rota.

### Templates

```http
GET /templates
```

Lista os repositórios cujo nome termina com o valor de `TEMPLATE_SUFFIX`.

### Criação de repositório cru

```http
POST /repositories/bare
```

Exemplo de payload:

```json
{
  "name": "orders-api",
  "description": "API de pedidos",
  "visibility": "private",
  "language": "fastapi"
}
```

Valores aceitos para `language`: `generic`, `frontend`, `springboot`, `fastapi`, `android` e `postgres`. Repositórios PostgreSQL devem terminar com `-database`.

### Criação a partir de template

```http
POST /repositories/from-template
```

Exemplo:

```json
{
  "name": "billing-api",
  "template_name": "ms-fastapi-template",
  "description": "API de faturamento",
  "visibility": "private"
}
```

Templates PostgreSQL e MongoDB exigem nomes terminados em `-database` e os respectivos objetos de conexão no payload. O repositório informado em `template_name` precisa estar marcado como template no GitHub.

Para templates PostgreSQL, o campo `postgres` exige `host`, `database`, `user`, `password`, `root_user` e `root_password`; `port` (padrão `5432`) e `root_database` (padrão `postgres`) são configuráveis:

```json
{
  "postgres": {
    "host": "db.example.com",
    "port": 5432,
    "database": "app_db",
    "user": "app_user",
    "password": "senha-do-banco",
    "root_database": "postgres",
    "root_user": "admin",
    "root_password": "senha-do-root"
  }
}
```

Para templates MongoDB, o campo `mongodb` exige uma `connection_url` válida:

```json
{
  "mongodb": {
    "connection_url": "mongodb+srv://usuario:senha@cluster.example.com/app_db"
  }
}
```

Os modelos completos também estão disponíveis em [/openapi.json](/openapi.json).

### Status da criação

```http
GET /repositories/creations/{creation_id}
```

O retorno informa `status`, repositório, modo (`bare` ou `template`), etapas, erro e URL quando disponíveis. O estado fica somente na memória do processo e não é compartilhado entre réplicas.

### Documentação e métricas

- `/docs`: Swagger UI.
- `/redoc`: ReDoc.
- `/openapi.json`: schema OpenAPI.
- `/metrics`: formato Prometheus, protegido por Bearer.

## Execução com Docker

O repositório contém `docker-compose.2.yml`, que publica a porta `6539` do host para a porta `8000` do container:

```bash
cp .env.example .env
docker compose -f docker-compose.2.yml up --build
```

O `docker-compose.2.yml` injeta as variáveis de `.env` em tempo de execução por meio de `env_file`. O `Dockerfile` não copia `.env` para a imagem, e o build não precisa de um arquivo `.env` com segredos. Nunca coloque tokens ou senhas nas camadas da imagem; use `.env.example` como referência e mantenha os valores reais apenas no ambiente de execução.

Para o script de containers Docker:

```bash
./run.sh
./run.sh --reboot NUMERO
./run.sh --remove NUMERO
./run.sh --list
```

Para o script que gera Compose por instância:

```bash
./run_compose.sh
./run_compose.sh --rebuild
./run_compose.sh --rebuild NUMERO
./run_compose.sh --reboot NUMERO
./run_compose.sh --bind NUMERO
./run_compose.sh --help
```

## Testes e qualidade

Os testes estão em `tests/` e usam `pytest` para validar a API, schemas, fluxos de criação, integração com o gerenciador GitHub e helpers de scaffold. O `requirements.txt` não declara `pytest`; ele precisa estar disponível no ambiente para executar a suíte:

```bash
python -m pytest
```

## Estrutura do projeto

```text
.
├── app/
│   ├── api/routes.py
│   ├── core/
│   ├── schemas/
│   ├── services/github_manager.py
│   ├── static/
│   └── templates/workflows/
├── tests/
├── .env.example
├── Dockerfile
├── docker-compose.2.yml
├── main.py
├── requirements.txt
├── run.sh
└── run_compose.sh
```

## Contribuição

Faça alterações em uma branch própria e use os templates de pull request disponíveis em `.github/PULL_REQUEST_TEMPLATE`. Não versione segredos nem tokens.

## Licença

Este projeto está sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE).
