BASE=/opt/iqos/servicos/backend

echo "=== site_assets na VM ==="
ls "$BASE/api/site_assets/" 2>/dev/null | wc -l

echo ""
echo "=== os 4 ficheiros existem? ==="
for f in icone-analise-medida.svg icone-dados.svg icone-imprensa.svg icone-correcao.svg; do
  p=$(find "$BASE" -name "$f" 2>/dev/null | head -1)
  if [ -n "$p" ]; then
    echo "  OK     $f  ->  $p"
  else
    echo "  FALTA  $f"
  fi
done

echo ""
echo "=== quantos icones 'icone-*' existem na VM ==="
find "$BASE" -name 'icone-*' 2>/dev/null | wc -l

echo ""
echo "=== data/cms/media na VM: conteudo ==="
ls "$BASE/data/cms/media/" 2>/dev/null | head -5
echo "  (total: $(ls "$BASE/data/cms/media/" 2>/dev/null | wc -l) entradas)"
