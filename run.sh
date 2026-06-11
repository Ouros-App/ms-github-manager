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

# NOVA função: limpeza agressiva
limpeza_nuclear() {
    local force=$1
    
    color_echo "yellow" "⚠️  ATENÇÃO: Limpeza profunda do Docker!"
    
    if [ "$force" = "--force" ]; then
        color_echo "red" "💣 Modo FORCE ativado - limpando TUDO (containers parados, imagens não usadas, volumes órfãos)..."
        (
            docker system prune -a -f --volumes > /dev/null 2>&1
            docker builder prune -a -f > /dev/null 2>&1
            docker image prune -a -f > /dev/null 2>&1
            docker volume prune -f > /dev/null 2>&1
            docker network prune -f > /dev/null 2>&1
        ) &
        show_loading $! "💣 Limpeza nuclear em andamento"
        wait $!
        color_echo "green" "✓ Limpeza nuclear concluída"
    else
        # Limpeza padrão mais agressiva que a original
        (
            docker builder prune -a -f > /dev/null 2>&1
            docker image prune -f > /dev/null 2>&1
            docker volume prune -f > /dev/null 2>&1
        ) &
        show_loading $! "🧹 Limpeza profunda em andamento"
        wait $!
        color_echo "green" "✓ Cache e recursos órfãos limpos"
    fi
}

# Função para verificar integridade do código no container
verificar_codigo_container() {
    local nome=$1
    local arquivo_teste=$2  # Caminho para um arquivo específico dentro do container
    
    color_echo "blue" "🔍 Verificando se o código foi atualizado no container..."
    
    if [ -n "$arquivo_teste" ] && docker exec $nome test -f "$arquivo_teste" 2>/dev/null; then
        local data_container=$(docker exec $nome stat -c %Y "$arquivo_teste" 2>/dev/null)
        local data_host=$(stat -c %Y "$(basename $arquivo_teste)" 2>/dev/null)
        
        if [ -n "$data_container" ] && [ -n "$data_host" ]; then
            if [ $data_container -ge $data_host ]; then
                color_echo "green" "✓ Código parece atualizado (timestamp ok)"
            else
                color_echo "red" "⚠️ Código no container parece mais antigo que no host!"
                color_echo "yellow" "   Container: $(date -d @$data_container)"
                color_echo "yellow" "   Host: $(date -d @$data_host)"
            fi
        fi
    else
        color_echo "yellow" "⚠️ Não foi possível verificar o código automaticamente"
    fi
}

buildar_imagem() {
    local nome=$1
    local force=$2
    
    # Limpeza mais robusta
    limpeza_nuclear "$force"
    
    # Forçar rebuild com cache-busting
    local cache_buster=$(date +%s)
    
    color_echo "blue" "🏗️ Construindo imagem $nome (REBUILD FORÇADO)..."
    color_echo "yellow" "   Cache buster: $cache_buster"
    
    (
        docker build --no-cache --pull --force-rm \
                     --build-arg BUILDKIT_PROGRESS=plain \
                     --build-arg CACHE_BUST=$cache_buster \
                     --build-arg APP_NAME=$APP_NAME \
                     --build-arg APP_PORT=${APP_PORT:-8000} \
                     -t $nome . > /tmp/docker_build_${nome}.log 2>&1
    ) &
    local build_pid=$!
    show_loading $build_pid "🏗️ Construindo imagem do zero (sem cache)"
    wait $build_pid

    if [ $? -eq 0 ]; then
        color_echo "green" "✓ Imagem construída com sucesso"
        
        # Debug: listar camadas da imagem
        color_echo "blue" "📊 Camadas da imagem (últimas 5):"
        docker history $nome --no-trunc --human | head -6 | tail -5
    else
        color_echo "red" "❌ Falha na construção da imagem"
        color_echo "yellow" "📋 Últimas linhas do log de build:"
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

    # IMPORTANTE: NÃO montar volumes de código para não sobrescrever
    local args=("-d" "-p" "${porta}:8000" "--name" "$nome")
    
    # Se houver necessidade de volumes, apenas para dados, NÃO para código
    # args+=("-v" "dados_persistentes:/data")  # Exemplo seguro
    
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
    
    # Pequena pausa para o container inicializar
    sleep 3
}

verificar_status() {
    local nome=$1
    local porta=$2

    echo ""
    color_echo "green" "✅ $nome iniciado na porta $porta"
    color_echo "cyan" "🌐 Acesse: http://localhost:$porta"
    echo ""

    if docker ps --format '{{.Names}}' | grep -q "^${nome}$"; then
        color_echo "green" "✓ Container está ativo e funcionando"
        
        # Verificar código se tiver um arquivo de referência
        # Altere para um arquivo específico do seu projeto
        if docker exec $nome test -f /app/app.py 2>/dev/null; then
            verificar_codigo_container "$nome" "/app/app.py"
        elif docker exec $nome test -f /usr/src/app/main.py 2>/dev/null; then
            verificar_codigo_container "$nome" "/usr/src/app/main.py"
        fi
        
        color_echo "blue" "📋 Variáveis de ambiente carregadas do .env:"
        while IFS='=' read -r key value; do
            [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] && continue
            if [[ "$key" != "APP_NAME" && "$key" != "APP_PORT" ]]; then
                color_echo "yellow" "   - $key"
            fi
        done < .env
        
        echo ""
        color_echo "green" "✨ Concluído com sucesso!"
    else
        color_echo "red" "❌ Container subiu mas caiu em seguida. Logs:"
        docker logs $nome --tail=30 2>&1
        color_echo "yellow" "⚠️ Verifique os logs acima para identificar o erro."
        exit 1
    fi
}

# ─────────────────────────────────────────
# Modo: NOVO container incremental
# ─────────────────────────────────────────

modo_novo() {
    local force=$1
    
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

    buildar_imagem "$nome" "$force"
    subir_container "$nome" "$porta"
    verificar_status "$nome" "$porta"
}

# ─────────────────────────────────────────
# Modo: REBOOT de container existente
# ─────────────────────────────────────────

modo_reboot() {
    local NUMERO=$1
    local force=$2

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

    # Remover imagem antiga FORÇADAMENTE
    color_echo "blue" "🗑️ Removendo imagem antiga do $NOME e dependências..."
    (
        docker rmi -f $NOME > /dev/null 2>&1
        docker image prune -a -f > /dev/null 2>&1
        # Remover também imagens dangling
        docker images -f "dangling=true" -q | xargs -r docker rmi -f > /dev/null 2>&1
    ) &
    local rmi_pid=$!
    show_loading $rmi_pid "🗑️ Removendo imagens antigas"
    wait $rmi_pid
    color_echo "green" "✓ Imagens removidas"

    # Build com limpeza agressiva
    buildar_imagem "$NOME" "$force"
    subir_container "$NOME" "$PORTA_ATUAL"
    verificar_status "$NOME" "$PORTA_ATUAL"
}

# ─────────────────────────────────────────
# Roteamento de argumentos
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