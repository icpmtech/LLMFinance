INDICES="finance_grandes_litigantes finance_grandes_litigantes_recolhas finance_massa_insolvente finance_vendas_penhorados"

echo "=== contagens na VM ==="
for i in $INDICES; do
  n=$(curl -s "http://elasticsearch:9200/$i/_count" | sed -n 's/.*"count":\([0-9]*\).*/\1/p')
  printf "  %-38s %7s\n" "$i" "${n:-erro}"
done

echo ""
echo "=== total de indices na VM ==="
curl -s "http://elasticsearch:9200/_cat/indices?h=index" \
  | grep -c '^finance_'

echo ""
echo "=== indices finance_ a zero ==="
curl -s "http://elasticsearch:9200/_cat/indices?h=index,docs.count" \
  | awk '$1 ~ /^finance_/ && $2 == 0 { print "  " $1 }'
