INDICES="finance_arquivo_pt finance_esg_empresas finance_esg_indicadores finance_esg_recolhas finance_eu_taxonomy finance_municipios_contactos"

cd /opt/iqos/export 2>/dev/null || { echo "pasta /opt/iqos/export nao existe"; exit 0; }

echo "=== antes ==="
for i in $INDICES; do
  n=$(ls -1 "$i"-* 2>/dev/null | wc -l)
  echo "  $i -> $n ficheiros"
done

echo ""
echo "=== a remover ==="
for i in $INDICES; do
  rm -f "$i"-*
done
echo "  removido"

echo ""
echo "=== depois ==="
for i in $INDICES; do
  n=$(ls -1 "$i"-* 2>/dev/null | wc -l)
  echo "  $i -> $n ficheiros"
done

echo ""
echo "=== total de ficheiros em /opt/iqos/export ==="
ls -1 | wc -l
