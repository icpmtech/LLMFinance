BASE=http://elasticsearch:9200

echo "=== contagens reais no ES da VM ==="
for i in finance_eu_taxonomy finance_esg_indicadores finance_esg_empresas finance_esg_recolhas finance_municipios_contactos finance_grandes_litigantes finance_massa_insolvente finance_vendas_penhorados finance_arquivo_pt; do
  n=$(curl -s "$BASE/$i/_count" | sed -n 's/.*"count":\([0-9]*\).*/\1/p')
  printf "  %-36s %7s\n" "$i" "${n:-erro}"
done

echo ""
echo "=== distribuicao de finance_eu_taxonomy por campo (se existir) ==="
curl -s "$BASE/finance_eu_taxonomy/_search" -H 'Content-Type: application/json' -d '{"size":0,"aggs":{"por_tipo":{"terms":{"field":"type","size":20}}}}' \
  | head -c 600
echo ""

echo ""
echo "=== 1 documento de finance_esg_indicadores ==="
curl -s "$BASE/finance_esg_indicadores/_search?size=1" | head -c 700
