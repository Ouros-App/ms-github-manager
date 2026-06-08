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

# Help
show_help() {
    echo "Uso: $0 --reboot {numero}"
    echo ""
    echo "Opções:"
    echo "  --reboot NUMERO    Reinicia o compose com o número da instância especificada"
    echo "  -h, --help         Mostra esta ajuda"
    echo ""
    echo "Exemplo:"
    echo "  $0 --reboot 1      # Reinicia a instância 1 do compose"
}

# Verificar argumentos
if [ $# -ne 2 ] || [ "$1" != "--reboot" ]; then
    show_help
    exit 1
fi

NUMERO=$2

# Validar número
if ! [[ "$NUMERO" =~ ^[0-9]+$ ]]; then
    color_echo "red" "❌ Número inválido: $NUMERO"
    exit 1
fi

echo ""
color_echo "cyan" "🔄 REINICIANDO COMPOSE INSTÂNCIA #$NUMERO..."
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

NOME="${BASE_NAME}_${NUMERO}"

# Verificar se o container existe
color_echo "blue" "🔍 Verificando se a instância $NUMERO existe..."
if ! docker ps -a --format '{{.Names}}' | grep -q "^${NOME}$"; then
    color_echo "red" "❌ Instância $NOME não encontrada!"
    exit 1
fi
color_echo "green" "✓ Instância encontrada"

# Obter porta atual do container
PORTA_ATUAL=$(docker port $NOME 8000 | cut -d ':' -f2)
if [ -z "$PORTA_ATUAL" ]; then
    color_echo "yellow" "⚠️ Não foi possível obter a porta atual, gerando nova porta..."
    PORTA_ATUAL=$((RANDOM % 9000 + 1000))
    
    # Verificar se porta está disponível
    while lsof -i :$PORTA_ATUAL &>/dev/null; do
        PORTA_ATUAL=$((RANDOM % 9000 + 1000))
    done
fi
color_echo "green" "✓ Porta atual: $PORTA_ATUAL"

# Parar o compose específico (precisamos usar docker-compose com projeto separado)
color_echo "blue" "🛑 Parando containers da instância $NUMERO..."

# Criar arquivo docker-compose específico para esta instância
cat > docker-compose.${NUMERO}.yml << EOF
services:
  api:
    build: .
    container_name: ${BASE_NAME}_${NUMERO}
    env_file:
      - .env
    ports:
      - "${PORTA_ATUAL}:8000"
    restart: unless-stopped
EOF

# Parar containers específicos da instância
(
    docker-compose -f docker-compose.${NUMERO}.yml down > /dev/null 2>&1
) &
down_pid=$!
show_loading $down_pid "🛑 Parando containers"
wait $down_pid
color_echo "green" "✓ Containers parados"

# Remover imagem antiga
color_echo "blue" "🗑️ Removendo imagem antiga..."
(
    docker-compose -f docker-compose.${NUMERO}.yml down --rmi local > /dev/null 2>&1
) &
clean_pid=$!
show_loading $clean_pid "🗑️ Removendo imagens antigas"
wait $clean_pid
color_echo "green" "✓ Imagens antigas removidas"

# Reconstruir imagem
color_echo "blue" "🔨 Reconstruindo imagem (com --no-cache)..."
(
    docker-compose -f docker-compose.${NUMERO}.yml build --no-cache > /tmp/docker_build_${NUMERO}.log 2>&1
) &
build_pid=$!
show_loading $build_pid "🔨 Build da imagem (isso pode levar alguns minutos)"
wait $build_pid

if [ $? -ne 0 ]; then
    color_echo "red" "❌ Falha ao construir a imagem"
    color_echo "yellow" "📋 Últimas linhas do log de build:"
    tail -10 /tmp/docker_build_${NUMERO}.log
    exit 1
fi
color_echo "green" "✓ Imagem reconstruída com sucesso"

# Exportar variáveis para a instância
export APP_PORT=$PORTA_ATUAL
export INSTANCE=$NUMERO
export APP_NAME=$BASE_NAME

# Iniciar containers
color_echo "blue" "🐳 Iniciando containers com docker-compose..."

(
    docker-compose -f docker-compose.${NUMERO}.yml up -d > /tmp/docker_compose_${NUMERO}.log 2>&1
) &
compose_pid=$!
show_loading $compose_pid "🐳 Subindo containers"
wait $compose_pid

if [ $? -eq 0 ]; then
    color_echo "green" "✓ Containers iniciados com sucesso"
else
    color_echo "red" "❌ Falha ao iniciar containers"
    color_echo "yellow" "📋 Últimas linhas do log:"
    tail -10 /tmp/docker_compose_${NUMERO}.log
    exit 1
fi

echo ""
color_echo "green" "✅ ${BASE_NAME}_${NUMERO} reiniciado na porta $PORTA_ATUAL"
color_echo "cyan" "🌐 Acesse: http://localhost:$PORTA_ATUAL"
echo ""

# Mostrar status
color_echo "blue" "📊 Status do container:"
docker-compose -f docker-compose.${NUMERO}.yml ps

# Verificar logs recentes
color_echo "blue" "📝 Últimos logs:"
docker-compose -f docker-compose.${NUMERO}.yml logs --tail=10

echo ""
color_echo "green" "✨ Reboot concluído com sucesso!"

# Limpar arquivos temporários (opcional)
# rm docker-compose.${NUMERO}.yml