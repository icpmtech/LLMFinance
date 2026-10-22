echo "=== contentores (todos devem estar Up) ==="
docker ps --format '{{.Names}}  {{.Status}}' | sort

echo ""
echo "=== o dangling d57f86d85303 ainda existe? ==="
docker images -f dangling=true --format '{{.ID}}  {{.Size}}'
echo "  total dangling: $(docker images -f dangling=true -q | wc -l)"

echo ""
echo "=== imagens: quais sao as 18.67GB 'reclaimable' ==="
docker images --format '{{.Repository}}:{{.Tag}}|{{.Size}}|{{.ID}}' | grep -v '<none>' | while IFS='|' read -r nome tam id; do
  usada=$(docker ps -a --format '{{.Image}}' | grep -c "${id#sha256:}" 2>/dev/null || true)
  usada2=$(docker ps -a --format '{{.Image}}' | grep -c "$nome" 2>/dev/null || true)
  total=$(( ${usada:-0} + ${usada2:-0} ))
  if [ "$total" -eq 0 ]; then
    printf "  NAO EM USO  %-52s %s\n" "$nome" "$tam"
  fi
done

echo ""
echo "=== saude do backend e do site ==="
curl -s -o /dev/null -w '  backend  %{http_code}\n' http://127.0.0.1:8002/health
curl -s -o /dev/null -w '  frontend %{http_code}\n' http://127.0.0.1:4180/
curl -s -o /dev/null -w '  monitor  %{http_code}\n' http://127.0.0.1:8091/monitor/healthz

echo ""
echo "=== disco ==="
df -h / | tail -1
