import json, markdown
from api import custo_vida_service as s
from api import custo_vida_pagina as p
r = s.construir()
md = p.bloco_mapa(r["docs"], r["meta"])
html = markdown.markdown(md, extensions=["extra","sane_lists","nl2br","toc"], output_format="html5")
page = """<!doctype html><html lang="pt-PT"><head><meta charset="utf-8"><title>preview</title>
<style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:0 auto;padding:24px;background:#f7f8fa}</style>
</head><body><h1>Custo de vida (pré-visualização)</h1>""" + html + "</body></html>"
open(r"c:\LLMFinance\_tmp_cv_preview.html","w",encoding="utf-8").write(page)
print("bytes", len(page))
