#!/bin/bash
# run.sh [--reboot NUMERO]

# ==========================================
# Funções auxiliares
# ==========================================
source_env() {
    if [ ! -f .env ]; then
        echo "❌ Arquivo .env não encontrado"
        exit 1
    fi
    source .env
    if [ -z "$APP_NAME" ]; then
        echo "❌ APP_NAME não definido no .env"
        exit 1
    fi
}

proxima_porta_livre() {
    local porta=$((RANDOM % 9000 + 1000))
    while lsof -i :$porta &>/dev/null 2>&1; do
        porta=$((RANDOM % 9000 + 1000))
    done
    echo $porta
}

proximo_numero() {
    local num=1
    while docker ps -a --format '{{.Names}}' | grep -q "^${APP_NAME}_${num}$"; do
        num=$((num + 1))
    done
    echo $num
}

remove_container() {
    local nome=$1
    sudo docker rm -f "$nome" 2>/dev/null && return 0
    # Se falhou, tenta matar o processo manualmente
    local pid=$(sudo docker inspect --format='{{.State.Pid}}' "$nome" 2>/dev/null)
    if [ -n "$pid" ] && [ "$pid" != "0" ]; then
        echo "Container travado. Matando processo $pid..."
        sudo kill -9 "$pid" 2>/dev/null
        sleep 1
        sudo docker rm -f "$nome" 2>/dev/null
    fi
}

# ==========================================
# Modo NOVO (primeira execução)
# ==========================================
modo_novo() {
    source_env
    local numero=$(proximo_numero)
    local nome="${APP_NAME}_${numero}"
    local porta=$(proxima_porta_livre)

    echo "🚀 NOVO CONTAINER: $nome na porta $porta"

    echo "🏗️ Build da imagem..."
    sudo docker build --no-cache --pull -t "$nome" . > /tmp/build.log 2>&1
    if [ $? -ne 0 ]; then
        echo "❌ Build falhou. Últimas linhas:"
        tail -20 /tmp/build.log
        exit 1
    fi

    echo "🐳 Subindo container..."
    sudo docker run -d -p "$porta":8000 --name "$nome" --env-file .env "$nome" || {
        echo "❌ Falha ao subir container"
        exit 1
    }

    echo "✅ RODANDO: http://localhost:$porta"
}

# ==========================================
# Modo REBOOT (container já existe)
# ==========================================
modo_reboot() {
    local numero=$1
    source_env
    local nome="${APP_NAME}_${numero}"
    local porta=$(proxima_porta_livre)

    echo "🔄 REBOOT $nome na porta $porta"

    # Remove container antigo (travado ou não)
    echo "Removendo container antigo..."
    remove_container "$nome"
    sudo docker rmi -f "$nome" 2>/dev/null

    echo "🏗️ Build da imagem..."
    sudo docker build --no-cache --pull -t "$nome" . > /tmp/build.log 2>&1
    if [ $? -ne 0 ]; then
        echo "❌ Build falhou. Últimas linhas:"
        tail -20 /tmp/build.log
        exit 1
    fi

    echo "🐳 Subindo container..."
    sudo docker run -d -p "$porta":8000 --name "$nome" --env-file .env "$nome" || {
        echo "❌ Falha ao subir container"
        exit 1
    }

    echo "✅ RODANDO: http://localhost:$porta"
}

# ==========================================
# MAIN
# ==========================================
case "$1" in
    --reboot)
        if [[ -z "$2" || ! "$2" =~ ^[0-9]+$ ]]; then
            echo "❌ Uso: $0 --reboot NUMERO"
            exit 1
        fi
        modo_reboot "$2"
        ;;
    "")
        modo_novo
        ;;
    *)
        echo "Uso: $0            # primeiro container"
        echo "      $0 --reboot N # reinicia container N"
        exit 1
        ;;
esac