
BASE_NAME=$(grep APP_NAME .env | cut -d '=' -f2)
PORTA=$((RANDOM % 9000 + 1000))

while lsof -i :$PORTA &>/dev/null; do
    PORTA=$((RANDOM % 9000 + 1000))
done

NUM=1
while docker ps -a --format '{{.Names}}' | grep -q "^${BASE_NAME}_${NUM}$"; do
    NUM=$((NUM + 1))
done

NOME="${BASE_NAME}_${NUM}"

docker build -t $NOME . > /dev/null 2>&1
docker run -d -p $PORTA:8000 --name $NOME $NOME > /dev/null 2>&1

echo "✅ $NOME rodando na porta $PORTA"