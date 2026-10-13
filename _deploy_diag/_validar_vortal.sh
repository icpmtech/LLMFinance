PASTA=/opt/iqos/servicos/backend/data/vortal

if [ ! -d "$PASTA" ]; then
  echo "  PASTA AUSENTE"
  exit 0
fi

cd "$PASTA" || exit 1

echo "  $(find . -type f | wc -l) ficheiros, $(du -sm . | cut -f1) MB"

echo "  --- extensoes ---"
find . -type f -name '*.*' -printf '%f\n' 2>/dev/null | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -8

echo "  --- 5 mais recentes ---"
ls -lt --time-style=+%Y-%m-%d | head -6 | tail -5
