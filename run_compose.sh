#!/bin/bash

BASE_NAME=$(grep APP_NAME .env | cut -d '=' -f2)
PORTA=$((RANDOM % 9000 + 1000))

while lsof -i :$PORTA &>/dev/null; do
    PORTA=$((RANDOM % 9000 + 1000))
done

NUM=1
while docker ps -a --format '{{.Names}}' | grep -q "^${BASE_NAME}_${NUM}$"; do
    NUM=$((NUM + 1))
done

export APP_PORT=$PORTA
export INSTANCE=$NUM
export APP_NAME=$BASE_NAME

docker-compose up -d > /dev/null 2>&1

echo "✅ ${BASE_NAME}_${NUM} rodando na porta $PORTA"