#!/bin/bash
# run.sh --reboot NUMERO

if [ "$1" != "--reboot" ] || [ -z "$2" ]; then
    echo "Uso: $0 --reboot NUMERO"
    exit 1
fi

source .env
NOME="${APP_NAME}_$2"
PORTA=$((RANDOM % 9000 + 1000))

echo "🔄 REBOOT $NOME na porta $PORTA"

# ==========================================
# 1. Remove container antigo (inclusive travado)
# ==========================================
echo "Removendo container antigo..."
if ! sudo docker rm -f "$NOME" 2>/dev/null; then
    # Falhou: tenta matar o processo manualmente
    PID=$(sudo docker inspect --format='{{.State.Pid}}' "$NOME" 2>/dev/null)
    if [ -n "$PID" ] && [ "$PID" != "0" ]; then
        echo "Container travado. Matando processo $PID..."
        sudo kill -9 "$PID"
        sleep 1
        sudo docker rm -f "$NOME"
    else
        echo "Não foi possível remover. Execute manualmente:"
        echo "  sudo kill -9 \$(sudo docker inspect --format='{{.State.Pid}}' $NOME)"
        echo "  sudo docker rm -f $NOME"
        exit 1
    fi
fi

# Remove imagem antiga
sudo docker rmi -f "$NOME" 2>/dev/null

# ==========================================
# 2. Build silencioso da nova imagem
# ==========================================
echo "🏗️ Build da imagem..."
sudo docker build --no-cache --pull -t "$NOME" . > /tmp/build.log 2>&1
if [ $? -ne 0 ]; then
    echo "❌ Build falhou. Últimas linhas do log:"
    tail -20 /tmp/build.log
    exit 1
fi

# ==========================================
# 3. Sobe o novo container
# ==========================================
echo "🐳 Subindo container..."
sudo docker run -d -p "$PORTA":8000 --name "$NOME" --env-file .env "$NOME"

if [ $? -eq 0 ]; then
    echo "✅ RODANDO: http://localhost:$PORTA"
else
    echo "❌ Falha ao subir. Logs:"
    sudo docker logs "$NOME" --tail=30
    exit 1
fi