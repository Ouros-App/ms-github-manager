#!/bin/bash

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

# Help
show_help() {
    echo "Uso: $0 [--reboot NUMERO]"
    echo ""
    echo "Opções:"
    echo "  (sem argumentos)   Sobe novo container com número incremental"
    echo "  --reboot NUMERO    Rebuilda o container do número especificado"
    echo "  -h, --help         Mostra esta ajuda"
}

# Carregar .env
carregar_env() {
    if [ ! -f .env ]; then
        color_echo "red" "❌ Arquivo .env não encontrado!"
        exit 1
    fi

    source .env

    if [ -z "$APP_NAME" ]; then
        color_echo "red" "❌ APP_NAME não encontrado no .env"
        exit 1
    fi

    color_echo "green" "✓ APP_NAME: $APP_NAME"
}

# Porta livre
proxima_porta_livre() {
    local porta=$((RANDOM % 9000 + 1000))
    while lsof -i :$porta &>/dev/null 2>&1; do
        porta=$((RANDOM % 9000 + 1000))
    done
    echo $porta
}

# ─────────────────────────────────────────
# MODO REBOOT (SIMPLES E FUNCIONAL)
# ─────────────────────────────────────────
modo_reboot() {
    local numero=$1
    
    echo ""
    color_echo "cyan" "🔄 REBOOT DO CONTAINER #$numero"
    echo ""
    
    carregar_env
    
    local nome="${APP_NAME}_${numero}"
    local porta=$(proxima_porta_livre)
    
    color_echo "green" "✓ Nome: $nome"
    color_echo "green" "✓ Porta: $porta"
    
    # 1. Matar container e imagem
    color_echo "yellow" "💣 Destruindo $nome..."
    docker stop "$nome" 2>/dev/null
    docker rm "$nome" 2>/dev/null
    docker rm -f "$nome" 2>/dev/null
    docker rmi "$nome" 2>/dev/null
    docker rmi -f "$nome" 2>/dev/null
    color_echo "green" "✓ Destruído"
    
    # 2. Build da imagem
    color_echo "blue" "🏗️ Buildando $nome..."
    if ! docker build --no-cache --pull \
        --build-arg APP_NAME=$APP_NAME \
        --build-arg APP_PORT=${APP_PORT:-8000} \
        -t "$nome" .; then
        color_echo "red" "❌ Build falhou"
        exit 1
    fi
    color_echo "green" "✓ Build concluído"
    
    # 3. Subir container (usando --env-file em vez de -e manual)
    color_echo "blue" "🐳 Subindo $nome na porta $porta..."
    
    if ! docker run -d \
        -p ${porta}:8000 \
        --name "$nome" \
        --env-file .env \
        "$nome"; then
        color_echo "red" "❌ Falha ao iniciar container"
        exit 1
    fi
    
    # 4. Verificar status
    sleep 2
    if docker ps | grep -q "$nome"; then
        echo ""
        color_echo "green" "✅ $nome rodando na porta $porta"
        color_echo "cyan" "🌐 http://localhost:$porta"
        echo ""
        color_echo "green" "✨ REBOOT CONCLUÍDO!"
    else
        color_echo "red" "❌ Container não está rodando"
        color_echo "yellow" "Logs:"
        docker logs "$nome" --tail=30
        exit 1
    fi
}

# ─────────────────────────────────────────
# MODO NOVO
# ─────────────────────────────────────────
modo_novo() {
    echo ""
    color_echo "cyan" "🚀 SUBINDO NOVO CONTAINER..."
    echo ""
    
    carregar_env
    
    # Próximo número
    local numero=1
    while docker ps -a --format '{{.Names}}' | grep -q "^${APP_NAME}_${numero}$"; do
        numero=$((numero + 1))
    done
    
    local nome="${APP_NAME}_${numero}"
    local porta=$(proxima_porta_livre)
    
    color_echo "green" "✓ Nome: $nome"
    color_echo "green" "✓ Porta: $porta"
    
    # Build
    color_echo "blue" "🏗️ Buildando $nome..."
    if ! docker build --no-cache --pull \
        --build-arg APP_NAME=$APP_NAME \
        --build-arg APP_PORT=${APP_PORT:-8000} \
        -t "$nome" .; then
        color_echo "red" "❌ Build falhou"
        exit 1
    fi
    color_echo "green" "✓ Build concluído"
    
    # Subir
    color_echo "blue" "🐳 Subindo $nome na porta $porta..."
    if ! docker run -d \
        -p ${porta}:8000 \
        --name "$nome" \
        --env-file .env \
        "$nome"; then
        color_echo "red" "❌ Falha ao iniciar container"
        exit 1
    fi
    
    sleep 2
    if docker ps | grep -q "$nome"; then
        echo ""
        color_echo "green" "✅ $nome rodando na porta $porta"
        color_echo "cyan" "🌐 http://localhost:$porta"
        echo ""
    else
        color_echo "red" "❌ Container não está rodando"
        docker logs "$nome" --tail=30
        exit 1
    fi
}

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

case "$1" in
    --reboot)
        if [[ -z "$2" || ! "$2" =~ ^[0-9]+$ ]]; then
            color_echo "red" "❌ Número inválido"
            show_help
            exit 1
        fi
        modo_reboot "$2"
        ;;
    -h|--help)
        show_help
        ;;
    "")
        modo_novo
        ;;
    *)
        color_echo "red" "❌ Opção inválida"
        show_help
        exit 1
        ;;
esac