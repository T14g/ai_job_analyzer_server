# AI Job Analyzer — server

API do AI Job Analyzer, em FastAPI. Ela coleta vagas de páginas da Gupy com Selenium, grava um JSON por busca e devolve a lista para o front.

## Como rodar

Na pasta `server`, com Python 3.12:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Edite o `.env` com o nome e a URL de cada empresa. O arquivo `.env` fica fora do Git. O modelo versionado é o `.env.example`.

O Chrome precisa estar instalado. O Selenium sobe em modo headless durante a coleta.

## Endpoints

- `GET /hello` — teste da API.
- `GET /jobs` — vagas do JSON mais recente em `data/vagas`.
- `POST /jobs/search` — percorre as empresas do `.env`, grava `data/vagas/vagas-AAAA-MM-DD-HH-MM.json` e envia o andamento em tempo real (Server-Sent Events). No fim, devolve a lista com empresa, título e link.

O Swagger fica em `http://127.0.0.1:8000/docs`.

O front em `http://localhost:3000` está liberado no CORS.

## Estrutura

- `app/main.py` — sobe a API.
- `app/api/jobs.py` — rotas de vagas.
- `app/services/gupy.py` — coleta com Selenium.
- `data/vagas` — JSON de cada busca. A pasta fica no projeto; os arquivos gerados ficam no `.gitignore`.
