FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN test -f app/templates/workflows/fastapi.yml \
    && test -f app/templates/workflows/frontend.yml \
    && test -f app/templates/workflows/springboot.yml \
    && test -f app/templates/workflows/generic.yml

EXPOSE $PORT

CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
