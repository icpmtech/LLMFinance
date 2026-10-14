"""Separa POST que sao LEITURA (pesquisa/exportacao/analise) de POST que MUTAM estado.

Imprimir as duas listas permite rever a classificacao antes de a fixar em codigo.
"""
import json
import re
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:4180/api/openapi.json", timeout=60) as resp:
    spec = json.loads(resp.read().decode())

# Padroes de caminhos que, mesmo por POST, nao alteram estado.
LEITURA = re.compile(
    r"/(search|pesquisa|export|exportar|analy[sz]e|analise|preview|report|relatorio|summary|resumo"
    r"|chat|estimate|estimativa|simulate|simulacao|validate|validar|check|lookup|render|plot"
    r"|download|compare|comparar|aggregate|agregacao|stats|estatisticas|overview|list|meta"
    r"|autocomplete|suggest|translate|historico|history|detail|ficha|query|filter|resolve)\b",
    re.IGNORECASE,
)

leitura, escrita = [], []
for caminho, metodos in (spec.get("paths") or {}).items():
    for metodo in metodos:
        if metodo.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            (leitura if LEITURA.search(caminho) else escrita).append((metodo.upper(), caminho))

print(f"=== POST/PUT/PATCH/DELETE classificados como LEITURA ({len(leitura)}) ===")
for m, c in sorted(leitura, key=lambda x: x[1]):
    print(f"  {m:<7} {c}")

print(f"\n=== classificados como ESCRITA ({len(escrita)}) por prefixo ===")
por_prefixo = {}
for m, c in escrita:
    partes = [p for p in c.split("/") if p and not p.startswith("{")]
    por_prefixo.setdefault("/" + (partes[0] if partes else ""), []).append((m, c))
for prefixo, itens in sorted(por_prefixo.items(), key=lambda x: -len(x[1])):
    print(f"\n  {prefixo} ({len(itens)})")
    for m, c in sorted(itens, key=lambda x: x[1])[:40]:
        print(f"    {m:<7} {c}")
