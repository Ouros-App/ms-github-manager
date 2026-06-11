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
    echo "Uso: $0 [--reboot NUMERO] [--force]"
    echo ""
    echo "Opções:"
    echo "  (sem argumentos)   Builda a imagem e sobe um novo container com número incremental"
    echo "  --reboot NUMERO    Para, remove e rebuilda o container com o número especificado"
    echo "  --force            Força limpeza TOTAL do Docker (cuidado!)"
    echo "  -h, --help         Mostra esta ajuda"
    echo ""
    echo "Exemplos:"
    echo "  $0                 # Sobe novo container (ex: minha_app_1, minha_app_2, ...)"
    echo "  $0 --reboot 1      # Rebuilda do zero o container minha_app_1"
    echo "  $0 --reboot 1 --force # Limpa TUDO e rebuilda"
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

# Limpeza agressiva
limpeza_profunda() {
    local force=$1
    
    color_echo "blue" "🧹 Realizando limpeza profunda..."
    
    if [ "$force" = "--force" ]; then
        color_echo "yellow" "⚠️  Modo FORCE: limpando recursos não utilizados..."
        (
            docker system prune -a -f --volumes > /dev/null 2>&1
            docker builder prune -a -f > /dev/null 2>&1
            docker image prune -a -f > /dev/null 2>&1
            docker volume prune -f > /dev/null 2>&1
            docker network prune -f > /dev/null 2>&1
        ) &
        show_loading $! "💣 Limpeza nuclear em andamento"
        wait $!
    else
        (
            docker builder prune -f > /dev/null 2>&1
            docker image prune -f > /dev/null 2>&1
        ) &
        show_loading $! "🧹 Limpando cache"
        wait $!
    fi
    color_echo "green" "✓ Limpeza concluída"
}

# Para e remove container com garantia
parar_e_remover_container() {
    local nome=$1
    
    color_echo "blue" "🔍 Verificando se container $nome existe..."
    
    # Verifica se o container existe (rodando ou parado)
    if docker ps -a --format '{{.Names}}' | grep -q "^${nome}$"; then
        color_echo "yellow" "⚠️ Container encontrado. Removendo..."
        
        # Força parada e remoção em um comando
        if docker rm -f "$nome" > /dev/null 2>&1; then
            color_echo "green" "✓ Container $nome removido com sucesso"
        else
            color_echo "red" "❌ Falha ao remover container $nome"
            return 1
        fi
    else
        color_echo "green" "✓ Container $nome não existe"
    fi
    
    return 0
}

# Remove imagem com garantia
remover_imagem() {
    local nome=$1
    
    color_echo "blue" "🗑️ Verificando se imagem $nome existe..."
    
    # Verifica se a imagem existe
    if docker images --format '{{.Repository}}' | grep -q "^${nome}$"; then
        color_echo "yellow" "⚠️ Imagem encontrada. Removendo..."
        
        if docker rmi -f "$nome" > /dev/null 2>&1; then
            color_echo "green" "✓ Imagem $nome removida com sucesso"
        else
            color_echo "yellow" "⚠️ Não foi possível remover imagem $nome"
        fi
    else
        color_echo "green" "✓ Imagem $nome não existe"
    fi
}

buildar_imagem() {
    local nome=$1
    local force=$2
    
    # Limpeza antes do build
    limpeza_profunda "$force"
    
    # Cache buster para garantir rebuild
    local cache_buster=$(date +%s)
    
    color_echo "blue" "🏗️ Construindo imagem $nome (rebuild forçado)..."
    color_echo "yellow" "   Cache buster: $cache_buster"
    
    # Build sem cache
    (
        docker build --no-cache --pull --force-rm \
                     --build-arg CACHE_BUST=$cache_buster \
                     --build-arg APP_NAME=$APP_NAME \
                     --build-arg APP_PORT=${APP_PORT:-8000} \
                     -t $nome . > /tmp/docker_build_${nome}.log 2>&1
    ) &
    local build_pid=$!
    show_loading $build_pid "🏗️ Construindo imagem (pode levar alguns minutos)"
    wait $build_pid
    
    if [ $? -eq 0 ]; then
        color_echo "green" "✓ Imagem construída com sucesso"
        
        # Mostra informações da imagem
        color_echo "blue" "📊 Imagem criada:"
        docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}" | grep "$nome" || true
    else
        color_echo "red" "❌ Falha na construção da imagem"
        color_echo "yellow" "📋 Últimas linhas do log:"
        tail -20 /tmp/docker_build_${nome}.log
        rm -f /tmp/docker_build_${nome}.log
        exit 1
    fi
    rm -f /tmp/docker_build_${nome}.log
}

subir_container() {
    local nome=$1
    local porta=$2
    
    color_echo "blue" "🐳 Iniciando container $nome na porta $porta..."
    
    # Prepara argumentos do docker run
    local args=("-d" "-p" "${porta}:8000" "--name" "$nome")
    
    # Adiciona variáveis de ambiente do .env (exceto APP_NAME e APP_PORT)
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
    
    # Executa e verifica resultado
    local output
    output=$(docker run "${args[@]}" 2>&1)
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        color_echo "red" "❌ Erro ao iniciar container:"
        echo "$output"
        
        # Se for erro de conflito, tenta remover e tentar novamente
        if echo "$output" | grep -q "already in use"; then
            color_echo "yellow" "⚠️ Container conflitante detectado. Removendo e tentando novamente..."
            docker rm -f "$nome" > /dev/null 2>&1
            sleep 2
            
            # Segunda tentativa
            output=$(docker run "${args[@]}" 2>&1)
            exit_code=$?
            
            if [ $exit_code -ne 0 ]; then
                color_echo "red" "❌ Falha novamente:"
                echo "$output"
                return 1
            fi
        else
            return 1
        fi
    fi
    
    color_echo "green" "✓ Container iniciado com sucesso"
    sleep 3
    return 0
}

verificar_status() {
    local nome=$1
    local porta=$2
    
    echo ""
    
    # Verifica se o container está rodando
    if docker ps --format '{{.Names}}' | grep -q "^${nome}$"; then
        color_echo "green" "✅ $nome rodando na porta $porta"
        color_echo "cyan" "🌐 Acesse: http://localhost:$porta"
        echo ""
        color_echo "green" "✓ Container está ativo"
        
        # Verifica código (opcional)
        color_echo "blue" "📋 Variáveis de ambiente carregadas:"
        while IFS='=' read -r key value; do
            [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] && continue
            if [[ "$key" != "APP_NAME" && "$key" != "APP_PORT" ]]; then
                color_echo "yellow" "   - $key"
            fi
        done < .env
        
        echo ""
        color_echo "green" "✨ Concluído com sucesso!"
        return 0
    else
        color_echo "red" "❌ Container não está rodando!"
        color_echo "yellow" "📋 Últimos logs:"
        docker logs "$nome" --tail=30 2>&1 || echo "Container não encontrado"
        return 1
    fi
}

# ─────────────────────────────────────────
# Modo: NOVO container
# ─────────────────────────────────────────

modo_novo() {
    local force=$1
    
    echo ""
    color_echo "cyan" "🚀 SUBINDO NOVO CONTAINER..."
    echo ""
    
    carregar_env
    
    # Próximo número disponível
    local numero=1
    while docker ps -a --format '{{.Names}}' | grep -q "^${BASE_NAME}_${numero}$"; do
        numero=$((numero + 1))
    done
    color_echo "green" "✓ Próximo número: $numero"
    
    local nome="${BASE_NAME}_${numero}"
    local porta
    porta=$(proxima_porta_livre)
    color_echo "green" "✓ Porta: $porta"
    
    buildar_imagem "$nome" "$force"
    subir_container "$nome" "$porta"
    verificar_status "$nome" "$porta"
}

# ─────────────────────────────────────────
# Modo: REBOOT
# ─────────────────────────────────────────

modo_reboot() {
    local numero=$1
    local force=$2
    
    echo ""
    color_echo "cyan" "🔄 REBOOT COMPLETO DO CONTAINER #$numero..."
    echo ""
    
    carregar_env
    
    local nome="${BASE_NAME}_${numero}"
    
    # Passo 1: Para e remove container
    echo ""
    color_echo "cyan" "📦 [1/5] Removendo container antigo..."
    if ! parar_e_remover_container "$nome"; then
        color_echo "red" "❌ Falha ao remover container. Abortando."
        exit 1
    fi
    
    # Passo 2: Remove imagem antiga
    echo ""
    color_echo "cyan" "🗑️ [2/5] Removendo imagem antiga..."
    remover_imagem "$nome"
    
    # Passo 3: Limpeza profunda
    echo ""
    color_echo "cyan" "🧹 [3/5] Limpando cache e recursos..."
    limpeza_profunda "$force"
    
    # Passo 4: Build nova imagem
    echo ""
    color_echo "cyan" "🏗️ [4/5] Construindo nova imagem..."
    buildar_imagem "$nome" "$force"
    
    # Passo 5: Sobe novo container
    echo ""
    color_echo "cyan" "🐳 [5/5] Subindo novo container..."
    
    # Escolhe porta (tenta manter a mesma ou nova)
    local porta
    porta=$(proxima_porta_livre)
    color_echo "green" "✓ Porta escolhida: $porta"
    
    if subir_container "$nome" "$porta"; then
        verificar_status "$nome" "$porta"
    else
        color_echo "red" "❌ Falha ao subir container. Verifique os erros acima."
        exit 1
    fi
}

# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

FORCE_FLAG=""
REBOOT_NUM=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --reboot)
            REBOOT_NUM="$2"
            shift 2
            ;;
        --force)
            FORCE_FLAG="--force"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            show_help
            exit 1
            ;;
    esac
done

if [ -n "$REBOOT_NUM" ]; then
    if ! [[ "$REBOOT_NUM" =~ ^[0-9]+$ ]]; then
        color_echo "red" "❌ Número inválido: $REBOOT_NUM"
        exit 1
    fi
    modo_reboot "$REBOOT_NUM" "$FORCE_FLAG"
else
    modo_novo "$FORCE_FLAG"
fi