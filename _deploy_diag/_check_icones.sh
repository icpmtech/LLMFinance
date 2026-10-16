BASE=/app/api/site_assets

echo "=== os 4 icones existem no contentor (api/site_assets)? ==="
for f in icone-analise-medida.svg icone-dados.svg icone-imprensa.svg icone-correcao.svg; do
  if [ -f "$BASE/$f" ]; then
    echo "  OK     $f  ($(stat -c%s "$BASE/$f") bytes)"
  else
    echo "  FALTA  $f"
  fi
done

echo ""
echo "=== os 4 icones como media na VM (data/cms/media/<id>.svg)? ==="
for i in med_a6940fe73d55 med_aa2933ff176b med_b39eb208f327 med_f581b89c0319; do
  p="/app/data/cms/media/$i.svg"
  if [ -f "$p" ]; then
    echo "  OK     $i.svg  ($(stat -c%s "$p") bytes)"
  else
    echo "  FALTA  $i.svg"
  fi
done

echo ""
echo "=== quantos icone-* no contentor ==="
ls "$BASE" | grep -c '^icone-'
