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
color_echo "cyan" "🚀 INICIANDO DEPLOY COM DOCKER-COMPOSE (COM REBUILD)..."
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

# Verificar docker-compose.yml
if [ ! -f docker-compose.yml ]; then
    color_echo "red" "❌ Arquivo docker-compose.yml não encontrado!"
    exit 1
fi
color_echo "green" "✓ docker-compose.yml encontrado"

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

# Exportar variáveis
export APP_PORT=$PORTA
export INSTANCE=$NUM
export APP_NAME=$BASE_NAME

color_echo "blue" "📦 Configurações exportadas:"
color_echo "yellow" "   - APP_PORT: $APP_PORT"
color_echo "yellow" "   - INSTANCE: $INSTANCE"
color_echo "yellow" "   - APP_NAME: $APP_NAME"

# Parar containers antigos (se houver)
if docker-compose ps 2>/dev/null | grep -q "Up"; then
    color_echo "yellow" "⚠️ Containers ativos detectados. Parando..."
    (
        docker-compose down > /dev/null 2>&1
    ) &
    down_pid=$!
    show_loading $down_pid "🛑 Parando containers antigos"
    wait $down_pid
    color_echo "green" "✓ Containers antigos parados"
fi

# REMOVER IMAGENS ANTIGAS (opcional - garante rebuild completo)
color_echo "blue" "🗑️  Removendo imagens antigas do projeto..."
(
    docker-compose down --rmi local > /dev/null 2>&1
) &
clean_pid=$!
show_loading $clean_pid "🗑️  Limpando imagens antigas"
wait $clean_pid
color_echo "green" "✓ Imagens antigas removidas"

# RECONSTRUIR IMAGEM FORÇADAMENTE
color_echo "blue" "🔨 Reconstruindo imagem (com --no-cache)..."
(
    docker-compose build --no-cache > /tmp/docker_build_output.log 2>&1
) &
build_pid=$!
show_loading $build_pid "🔨 Build da imagem (isso pode levar alguns minutos)"
wait $build_pid

if [ $? -ne 0 ]; then
    color_echo "red" "❌ Falha ao construir a imagem"
    color_echo "yellow" "📋 Últimas linhas do log de build:"
    tail -10 /tmp/docker_build_output.log
    exit 1
fi
color_echo "green" "✓ Imagem reconstruída com sucesso"

# Iniciar com docker-compose
color_echo "blue" "🐳 Iniciando containers com docker-compose..."

(
    docker-compose up -d > /tmp/docker_compose_output.log 2>&1
) &
compose_pid=$!
show_loading $compose_pid "🐳 Subindo containers (isso pode levar alguns segundos)"
wait $compose_pid

if [ $? -eq 0 ]; then
    color_echo "green" "✓ Containers iniciados com sucesso"
else
    color_echo "red" "❌ Falha ao iniciar containers"
    color_echo "yellow" "📋 Últimas linhas do log:"
    tail -10 /tmp/docker_compose_output.log
    exit 1
fi

echo ""
color_echo "green" "✅ ${BASE_NAME}_${NUM} rodando na porta $PORTA"
color_echo "cyan" "🌐 Acesse: http://localhost:$PORTA"
echo ""

# Mostrar status dos containers
color_echo "blue" "📊 Status dos containers:"
docker-compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

# Verificar logs recentes
color_echo "blue" "📝 Últimos logs:"
docker-compose logs --tail=10

echo ""
color_echo "green" "✨ Deploy concluído com sucesso!"
color_echo "yellow" "💡 Nota: A imagem foi reconstruída com --no-cache para garantir código mais recente"