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
    echo "  --reboot NUMERO    Reinicia o container com o número especificado"
    echo "  -h, --help         Mostra esta ajuda"
    echo ""
    echo "Exemplo:"
    echo "  $0 --reboot 1      # Reinicia o container minha_app_1"
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
color_echo "cyan" "🔄 REINICIANDO CONTAINER #$NUMERO..."
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
color_echo "blue" "🔍 Verificando se o container $NOME existe..."
if ! docker ps -a --format '{{.Names}}' | grep -q "^${NOME}$"; then
    color_echo "red" "❌ Container $NOME não encontrado!"
    exit 1
fi
color_echo "green" "✓ Container encontrado"

# Obter porta atual
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

# Parar e remover container antigo
color_echo "blue" "🛑 Parando container $NOME..."
(
    docker stop $NOME > /dev/null 2>&1
) &
stop_pid=$!
show_loading $stop_pid "🛑 Parando container"
wait $stop_pid
color_echo "green" "✓ Container parado"

color_echo "blue" "🗑️ Removendo container $NOME..."
(
    docker rm $NOME > /dev/null 2>&1
) &
rm_pid=$!
show_loading $rm_pid "🗑️ Removendo container"
wait $rm_pid
color_echo "green" "✓ Container removido"

# Remover imagem antiga
color_echo "blue" "🗑️ Removendo imagem antiga do $NOME..."
(
    docker rmi $NOME > /dev/null 2>&1
) &
rmi_pid=$!
show_loading $rmi_pid "🗑️ Removendo imagem"
wait $rmi_pid
color_echo "green" "✓ Imagem antiga removida"

# Build da nova imagem
color_echo "blue" "🏗️ Construindo nova imagem para $NOME..."
(
    docker build -t $NOME . > /dev/null 2>&1
) &
build_pid=$!
show_loading $build_pid "🏗️ Construindo imagem (isso pode levar alguns segundos)"
wait $build_pid

if [ $? -eq 0 ]; then
    color_echo "green" "✓ Imagem construída com sucesso"
else
    color_echo "red" "❌ Falha na construção da imagem"
    exit 1
fi

# Executar novo container
color_echo "blue" "🐳 Iniciando novo container $NOME..."
(
    docker run -d -p $PORTA_ATUAL:8000 --name $NOME $NOME > /dev/null 2>&1
) &
run_pid=$!
show_loading $run_pid "🐳 Iniciando container"
wait $run_pid

if [ $? -eq 0 ]; then
    color_echo "green" "✓ Container reiniciado com sucesso"
else
    color_echo "red" "❌ Falha ao iniciar container"
    exit 1
fi

echo ""
color_echo "green" "✅ $NOME reiniciado na porta $PORTA_ATUAL"
color_echo "cyan" "🌐 Acesse: http://localhost:$PORTA_ATUAL"
echo ""

# Verificar se o container está realmente rodando
if docker ps | grep -q $NOME; then
    color_echo "green" "✓ Container está ativo e funcionando"
else
    color_echo "yellow" "⚠️ Container criado mas não está rodando. Verifique os logs."
    color_echo "blue" "📝 Logs do container:"
    docker logs $NOME --tail=20
fi