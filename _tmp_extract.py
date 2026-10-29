import json, re, io, os
src = open(r"c:\LLMFinance\_tmp_bloco0.md", encoding="utf-8").read()
m = re.search(r"const CV = (\[.*?\]);", src, re.S)
rows = json.loads(m.group(1))
assert len(rows) == 308, len(rows)
os.makedirs(r"c:\LLMFinance\finance-llm\data\custo-vida", exist_ok=True)
out = {
    "gerado_em": "2026-10-28",
    "fonte": "Página publicada em /site/solucoes/custo-de-vida (snapshot do IQ OS)",
    "concelhos": rows,
}
with open(r"c:\LLMFinance\finance-llm\data\custo-vida\base_concelhos.json", "w", encoding="utf-8", newline="\n") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print("ok", len(rows), os.path.getsize(r"c:\LLMFinance\finance-llm\data\custo-vida\base_concelhos.json"))
