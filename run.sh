#!/bin/bash

# Função para mostrar loading
show_loading() {
    local pid=$1
    local message=$2
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    
    while kill -0 $pid 2>/dev/null; do
        i=$(( (i+1) % ${#spin} ))
        printf "\r%s ${spin:$i:1}" "$message"
        sleep 0.1
    done
    printf "\r"
}

# Função para feedback colorido
color_echo() {
    local color=$1
    local message=$2
    case $color in
        "green") echo -e "\033[0;32m$message\033[0m" ;;
        "red") echo -e "\033[0;31m$message\033[0m" ;;
        "yellow") echo -e "\033[1;33m$message\033[0m" ;;
        "blue") echo -e "\033[0;34m$message\033[0m" ;;
        "cyan") echo -e "\033[0;36m$message\033[0m" ;;
        *) echo "$message" ;;
    esac
}

echo ""
color_echo "cyan" "🚀 INICIANDO DEPLOY..."
echo ""

# Verificar arquivo .env
color_echo "blue" "📁 Verificando configurações..."
if [ ! -f .env ]; then
    color_echo "red" "❌ Arquivo .env não encontrado!"
    exit 1
fi

BASE_NAME=$(grep APP_NAME .env | cut -d '=' -f2)
if [ -z "$BASE_NAME" ]; then
    color_echo "red" "❌ APP_NAME não encontrado no .env"
    exit 1
fi
color_echo "green" "✓ APP_NAME: $BASE_NAME"

# Gerar porta aleatória
color_echo "blue" "🔍 Selecionando porta disponível..."
PORTA=$((RANDOM % 9000 + 1000))

(
    while lsof -i :$PORTA &>/dev/null; do
        PORTA=$((RANDOM % 9000 + 1000))
    done
) &
loading_pid=$!
show_loading $loading_pid "🔍 Verificando porta $PORTA"
wait $loading_pid

color_echo "green" "✓ Porta selecionada: $PORTA"

# Gerar número da instância
color_echo "blue" "🔢 Gerando número da instância..."
NUM=1
while docker ps -a --format '{{.Names}}' | grep -q "^${BASE_NAME}_${NUM}$"; do
    NUM=$((NUM + 1))
done
color_echo "green" "✓ Instância #$NUM"

NOME="${BASE_NAME}_${NUM}"

# Build da imagem
color_echo "blue" "🏗️ Construindo imagem Docker..."
(
    docker build -t $NOME . > /dev/null 2>&1
) &
build_pid=$!
show_loading $build_pid "🏗️ Construindo imagem Docker (isso pode levar alguns segundos)"
wait $build_pid

if [ $? -eq 0 ]; then
    color_echo "green" "✓ Imagem construída com sucesso"
else
    color_echo "red" "❌ Falha na construção da imagem"
    exit 1
fi

# Executar container
color_echo "blue" "🐳 Iniciando container..."
(
    docker run -d -p $PORTA:8000 --name $NOME $NOME > /dev/null 2>&1
) &
run_pid=$!
show_loading $run_pid "🐳 Iniciando container"
wait $run_pid

if [ $? -eq 0 ]; then
    color_echo "green" "✓ Container iniciado com sucesso"
else
    color_echo "red" "❌ Falha ao iniciar container"
    exit 1
fi

echo ""
color_echo "green" "✅ $NOME rodando na porta $PORTA"
color_echo "cyan" "🌐 Acesse: http://localhost:$PORTA"
echo ""

# Verificar se o container está realmente rodando
if docker ps | grep -q $NOME; then
    color_echo "green" "✓ Container está ativo e funcionando"
else
    color_echo "yellow" "⚠️ Container criado mas não está rodando. Verifique os logs."
fi