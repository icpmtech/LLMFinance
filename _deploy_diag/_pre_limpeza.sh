DANGLING=d57f86d85303

echo "=== todos os contentores (incluindo parados) ==="
docker ps -a --format '{{.Names}}  {{.Status}}  {{.Image}}' | sort

echo ""
echo "=== algum contentor usa o dangling $DANGLING? ==="
uso=$(docker ps -a --format '{{.Image}} {{.Names}}' | grep -c "$DANGLING")
echo "  referencias encontradas: $uso"

echo ""
echo "=== qual e a imagem dangling (historico) ==="
docker image inspect "$DANGLING" --format '  id: {{.Id}}
  criada: {{.Created}}
  tamanho: {{.Size}}
  tags: {{.RepoTags}}
  parent: {{.Parent}}' 2>&1 | head -8

echo ""
echo "=== a imagem que o backend usa agora ==="
docker inspect iqos-backend --format '  imagem: {{.Config.Image}}
  image id: {{.Image}}'

echo ""
echo "=== volumes (NAO TOCAR: 37.9 GB de dados) ==="
docker volume ls --format '{{.Name}}' | head -20
echo "  total: $(docker volume ls -q | wc -l)"
