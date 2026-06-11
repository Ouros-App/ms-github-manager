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

    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] && continue
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

# Destruir container e imagem (SEM FRESCURA)
destruir_tudo() {
    local nome=$1
    
    color_echo "yellow" "💣 Destruindo $nome..."
    
    # Para e remove container (ignora erros)
    docker stop "$nome" 2>/dev/null
    docker rm "$nome" 2>/dev/null
    docker rm -f "$nome" 2>/dev/null
    
    # Remove imagem
    docker rmi "$nome" 2>/dev/null
    docker rmi -f "$nome" 2>/dev/null
    
    color_echo "green" "✓ Destruído"
}

# Build da imagem
build_imagem() {
    local nome=$1
    
    color_echo "blue" "🏗️ Buildando $nome..."
    
    # Build sem cache
    if docker build --no-cache --pull \
        --build-arg APP_NAME=$APP_NAME \
        --build-arg APP_PORT=${APP_PORT:-8000} \
        -t "$nome" .; then
        color_echo "green" "✓ Build concluído"
        return 0
    else
        color_echo "red" "❌ Build falhou"
        return 1
    fi
}

# Subir container
subir_container() {
    local nome=$1
    local porta=$2
    
    color_echo "blue" "🐳 Subindo $nome na porta $porta..."
    
    # Monta comando
    local cmd="docker run -d -p ${porta}:8000 --name $nome"
    
    # Adiciona variáveis do .env
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] && continue
        if [[ "$key" != "APP_NAME" && "$key" != "APP_PORT" ]]; then
            value="${value%\"}"
            value="${value#\"}"
            value="${value%\'}"
            value="${value#\'}"
            cmd="$cmd -e $key=$value"
        fi
    done < .env
    
    cmd="$cmd $nome"
    
    # Executa
    if eval "$cmd"; then
        color_echo "green" "✓ Container iniciado"
        return 0
    else
        color_echo "red" "❌ Falha ao iniciar"
        return 1
    fi
}

# Verificar status
verificar_status() {
    local nome=$1
    local porta=$2
    
    sleep 2
    
    if docker ps --format '{{.Names}}' | grep -q "^${nome}$"; then
        echo ""
        color_echo "green" "✅ $nome está rodando!"
        color_echo "cyan" "🌐 http://localhost:$porta"
        echo ""
        return 0
    else
        color_echo "red" "❌ Container não está rodando"
        color_echo "yellow" "Logs:"
        docker logs "$nome" --tail=20 2>/dev/null
        return 1
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
    
    build_imagem "$nome" || exit 1
    subir_container "$nome" "$porta" || exit 1
    verificar_status "$nome" "$porta"
}

# ─────────────────────────────────────────
# MODO REBOOT
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
    
    # 1. Destruir tudo
    destruir_tudo "$nome"
    
    # 2. Build
    build_imagem "$nome" || exit 1
    
    # 3. Subir
    subir_container "$nome" "$porta" || exit 1
    
    # 4. Verificar
    verificar_status "$nome" "$porta"
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