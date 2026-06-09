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
    echo "Uso: $0 [--reboot NUMERO]"
    echo ""
    echo "Opções:"
    echo "  (sem argumentos)   Builda a imagem e sobe um novo container com número incremental"
    echo "  --reboot NUMERO    Para, remove e rebuilda o container com o número especificado"
    echo "  -h, --help         Mostra esta ajuda"
    echo ""
    echo "Exemplos:"
    echo "  $0                 # Sobe novo container (ex: minha_app_1, minha_app_2, ...)"
    echo "  $0 --reboot 1      # Rebuilda do zero o container minha_app_1"
}

# ─────────────────────────────────────────
# Funções principais
# ─────────────────────────────────────────

carregar_env() {
    color_echo "blue" "📁 Verificando configurações..."
    if [ ! -f .env ]; then
        color_echo "red" "❌ Arquivo .env não encontrado!"
        exit 1
    fi

    # Parser seguro: só aceita linhas no formato CHAVE=VALOR, ignora comentários e texto solto
    while IFS='=' read -r key value; do
        # Pular linhas vazias, comentários e linhas sem '=' (texto solto)
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] && continue
        # Remover aspas do valor se existirem
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        export "$key=$value"
    done < .env

    if [ -z "$APP_NAME" ]; then
        color_echo "red" "❌ APP_NAME não encontrado no .env"
        exit 1
    fi

    BASE_NAME="$APP_NAME"
    color_echo "green" "✓ APP_NAME: $BASE_NAME"
    color_echo "green" "✓ Variáveis carregadas: APP_NAME=$APP_NAME, APP_PORT=${APP_PORT:-8000}"
}

proxima_porta_livre() {
    local porta=$((RANDOM % 9000 + 1000))
    while lsof -i :$porta &>/dev/null; do
        porta=$((RANDOM % 9000 + 1000))
    done
    echo $porta
}

buildar_imagem() {
    local nome=$1
    color_echo "blue" "🧹 Limpando cache de build..."
    (
        docker builder prune -f > /dev/null 2>&1
    ) &
    show_loading $! "🧹 Limpando cache"
    wait $!
    color_echo "green" "✓ Cache limpo"

    color_echo "blue" "🏗️ Construindo imagem $nome (sem cache, do zero)..."
    (
        docker build --no-cache --pull \
                     --build-arg APP_NAME=$APP_NAME \
                     --build-arg APP_PORT=${APP_PORT:-8000} \
                     -t $nome . > /tmp/docker_build_${nome}.log 2>&1
    ) &
    local build_pid=$!
    show_loading $build_pid "🏗️ Construindo imagem do zero (isso pode levar alguns minutos)"
    wait $build_pid

    if [ $? -eq 0 ]; then
        color_echo "green" "✓ Imagem construída com sucesso"
    else
        color_echo "red" "❌ Falha na construção da imagem"
        color_echo "yellow" "📋 Últimas linhas do log de build:"
        tail -10 /tmp/docker_build_${nome}.log
        rm -f /tmp/docker_build_${nome}.log
        exit 1
    fi
    rm -f /tmp/docker_build_${nome}.log
}

subir_container() {
    local nome=$1
    local porta=$2

    color_echo "blue" "🐳 Iniciando container $nome na porta $porta..."

    local args=("-d" "-p" "${porta}:8000" "--name" "$nome")
    
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] && continue
        if [[ "$key" != "APP_NAME" && "$key" != "APP_PORT" ]]; then
            value="${value%\"}"
            value="${value#\"}"
            value="${value%\'}"
            value="${value#\'}"
            args+=("-e" "${key}=${value}")
        fi
    done < .env
    
    args+=("$nome")
    
    color_echo "yellow" "📝 Executando docker run com ${#args[@]} argumentos"
    
    docker run "${args[@]}"
}

verificar_status() {
    local nome=$1
    local porta=$2

    echo ""
    color_echo "green" "✅ $nome iniciado na porta $porta"
    color_echo "cyan" "🌐 Acesse: http://localhost:$porta"
    echo ""

    # Aguardar 2s para o container estabilizar antes de verificar
    sleep 2

    if docker ps --format '{{.Names}}' | grep -q "^${nome}$"; then
        color_echo "green" "✓ Container está ativo e funcionando"
        color_echo "blue" "📋 Variáveis de ambiente carregadas do .env:"
        while IFS='=' read -r key value; do
            [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] && continue
            if [[ "$key" != "APP_NAME" && "$key" != "APP_PORT" ]]; then
                color_echo "yellow" "   - $key"
            fi
        done < .env
    else
        color_echo "red" "❌ Container subiu mas caiu em seguida. Logs:"
        docker logs $nome --tail=30 2>&1
        color_echo "yellow" "⚠️ Verifique os logs acima para identificar o erro."
        exit 1
    fi

    echo ""
    color_echo "green" "✨ Concluído com sucesso!"
}

# ─────────────────────────────────────────
# Modo: NOVO container incremental
# ─────────────────────────────────────────

modo_novo() {
    echo ""
    color_echo "cyan" "🚀 SUBINDO NOVO CONTAINER..."
    echo ""

    carregar_env

    # Descobrir próximo número disponível
    local numero=1
    while docker ps -a --format '{{.Names}}' | grep -q "^${BASE_NAME}_${numero}$"; do
        numero=$((numero + 1))
    done
    color_echo "green" "✓ Próximo número disponível: $numero"

    local nome="${BASE_NAME}_${numero}"
    local porta
    porta=$(proxima_porta_livre)
    color_echo "green" "✓ Porta disponível: $porta"

    buildar_imagem "$nome"
    subir_container "$nome" "$porta"
    verificar_status "$nome" "$porta"
}

# ─────────────────────────────────────────
# Modo: REBOOT de container existente
# ─────────────────────────────────────────

modo_reboot() {
    local NUMERO=$1

    echo ""
    color_echo "cyan" "🔄 REINICIANDO CONTAINER #$NUMERO..."
    echo ""

    carregar_env

    local NOME="${BASE_NAME}_${NUMERO}"

    # Verificar se o container existe
    color_echo "blue" "🔍 Verificando se o container $NOME existe..."
    if ! docker ps -a --format '{{.Names}}' | grep -q "^${NOME}$"; then
        color_echo "red" "❌ Container $NOME não encontrado!"
        exit 1
    fi
    color_echo "green" "✓ Container encontrado"

    # Obter porta atual
    local PORTA_ATUAL
    PORTA_ATUAL=$(docker port $NOME 8000 2>/dev/null | cut -d ':' -f2)
    if [ -z "$PORTA_ATUAL" ]; then
        color_echo "yellow" "⚠️ Não foi possível obter a porta atual, gerando nova porta..."
        PORTA_ATUAL=$(proxima_porta_livre)
    fi
    color_echo "green" "✓ Porta: $PORTA_ATUAL"

    # Parar container
    color_echo "blue" "🛑 Parando container $NOME..."
    (
        docker stop $NOME > /dev/null 2>&1
    ) &
    local stop_pid=$!
    show_loading $stop_pid "🛑 Parando container"
    wait $stop_pid
    color_echo "green" "✓ Container parado"

    # Remover container
    color_echo "blue" "🗑️ Removendo container $NOME..."
    (
        docker rm -f $NOME > /dev/null 2>&1
    ) &
    local rm_pid=$!
    show_loading $rm_pid "🗑️ Removendo container"
    wait $rm_pid
    color_echo "green" "✓ Container removido"

    # Remover imagem antiga
    color_echo "blue" "🗑️ Removendo imagem antiga do $NOME..."
    (
        docker rmi -f $NOME > /dev/null 2>&1
        docker image prune -f > /dev/null 2>&1
    ) &
    local rmi_pid=$!
    show_loading $rmi_pid "🗑️ Removendo imagem"
    wait $rmi_pid
    color_echo "green" "✓ Imagem removida"

    buildar_imagem "$NOME"
    subir_container "$NOME" "$PORTA_ATUAL"
    verificar_status "$NOME" "$PORTA_ATUAL"
}

# ─────────────────────────────────────────
# Roteamento de argumentos
# ─────────────────────────────────────────

if [ $# -eq 0 ]; then
    modo_novo

elif [ $# -eq 2 ] && [ "$1" = "--reboot" ]; then
    if ! [[ "$2" =~ ^[0-9]+$ ]]; then
        color_echo "red" "❌ Número inválido: $2"
        exit 1
    fi
    modo_reboot "$2"

elif [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help

else
    show_help
    exit 1
fi