#!/bin/bash

# ============================================
# CONFIGURAÇÕES
# ============================================
set -e  # Para o script se algum comando falhar (mas com tratamento)

# Cores
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

# Spinner de loading enquanto um processo roda em background
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
    wait $pid
    return $?
}

# Help
show_help() {
    echo "Uso: $0 [--reboot NUMERO]"
    echo "  --reboot NUMERO    Reconstrói e reinicia o container com o número especificado"
    echo "  -h, --help         Mostra esta ajuda"
}

# Carrega .env (simples source)
carregar_env() {
    if [ ! -f .env ]; then
        color_echo "red" "❌ Arquivo .env não encontrado"
        exit 1
    fi
    source .env
    if [ -z "$APP_NAME" ]; then
        color_echo "red" "❌ APP_NAME não definido no .env"
        exit 1
    fi
    color_echo "green" "✓ APP_NAME: $APP_NAME"
}

# Porta aleatória livre
proxima_porta_livre() {
    local porta=$((RANDOM % 9000 + 1000))
    while lsof -i :$porta &>/dev/null 2>&1; do
        porta=$((RANDOM % 9000 + 1000))
    done
    echo $porta
}

# ============================================
# MODO REBOOT (o que você quer)
# ============================================
modo_reboot() {
    local numero=$1
    local nome="${APP_NAME}_${numero}"
    local porta=$(proxima_porta_livre)

    echo ""
    color_echo "cyan" "🔄 REBOOT DO CONTAINER $nome"
    echo ""

    # 1. Destruir container e imagem (FORÇADO, sem perguntas)
    color_echo "yellow" "💣 Removendo container e imagem antigos..."
    docker rm -f "$nome" 2>/dev/null || true
    docker rmi -f "$nome" 2>/dev/null || true
    color_echo "green" "✓ Limpeza concluída"

    # 2. Build silencioso com spinner
    color_echo "blue" "🏗️ Construindo imagem (isso pode levar alguns minutos)..."
    local build_log="/tmp/docker_build_${nome}.log"
    (
        docker build --no-cache --pull \
            --build-arg APP_NAME="$APP_NAME" \
            --build-arg APP_PORT="${APP_PORT:-8000}" \
            -t "$nome" . > "$build_log" 2>&1
    ) &
    local build_pid=$!
    show_loading $build_pid "🏗️ Construindo imagem"
    if [ $? -ne 0 ]; then
        color_echo "red" "❌ Build falhou. Veja o log: $build_log"
        tail -20 "$build_log"
        exit 1
    fi
    color_echo "green" "✓ Build concluído"

    # 3. Subir container (usando --env-file)
    color_echo "blue" "🐳 Subindo container na porta $porta..."
    if ! docker run -d \
        -p "${porta}:8000" \
        --name "$nome" \
        --env-file .env \
        "$nome" > /dev/null 2>&1; then
        color_echo "red" "❌ Falha ao iniciar container"
        exit 1
    fi

    # 4. Verificar se está rodando
    sleep 2
    if docker ps --format '{{.Names}}' | grep -q "^${nome}$"; then
        echo ""
        color_echo "green" "✅ $nome está rodando!"
        color_echo "cyan" "🌐 http://localhost:$porta"
        echo ""
    else
        color_echo "red" "❌ Container não está rodando. Logs:"
        docker logs "$nome" --tail=30
        exit 1
    fi
}

# ============================================
# MAIN
# ============================================
case "$1" in
    --reboot)
        if [[ -z "$2" || ! "$2" =~ ^[0-9]+$ ]]; then
            color_echo "red" "❌ Número inválido para --reboot"
            show_help
            exit 1
        fi
        carregar_env
        modo_reboot "$2"
        ;;
    -h|--help)
        show_help
        ;;
    *)
        color_echo "red" "❌ Uso: $0 --reboot NUMERO"
        show_help
        exit 1
        ;;
esac