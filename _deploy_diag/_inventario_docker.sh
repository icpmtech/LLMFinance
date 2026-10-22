echo "=== disco ==="
df -h / | tail -1

echo ""
echo "=== docker system df (resumo) ==="
docker system df

echo ""
echo "=== build cache: total ==="
docker system df -v 2>/dev/null | sed -n '/Build cache usage/,$p' | head -5

echo ""
echo "=== imagens TAGGED (estas NAO se tocam) ==="
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep -v '<none>' | sort

echo ""
echo "=== imagens DANGLING (untagged, candidatas a remocao) ==="
docker images -f dangling=true --format '{{.ID}}  {{.Size}}' | head -40
echo "  total dangling: $(docker images -f dangling=true -q | wc -l)"

echo ""
echo "=== contentores a correr (nenhum deve ser afectado) ==="
docker ps --format '{{.Names}}  {{.Status}}' | sort
