"""Porque e que a recolha de Angra do Heroismo deu "0/0 concelhos".

`run_district_sync` faz:

    nomes = [concelhos pedidos] or concelhos_do_site(distrito)

Se `concelhos_do_site` devolver lista vazia, `nomes` fica vazio, o ciclo nao corre
uma unica vez e o trabalho fecha com estado **done**, 0 empresas e 0/0 concelhos.
A UI mostra isso como um trabalho concluido -- parece sucesso e nao e.

Este script mostra o que o site devolve para esse distrito, ao lado de um que
funciona (Evora), e lista todas as ligacoes `/diretorio/` da pagina sem filtro --
para se ver se o problema e a pagina nao ter concelhos ou o filtro nao os apanhar.

    python _probe_angra_concelhos.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import empresas_recolha_service as s  # noqa: E402


def analisar(distrito: str) -> None:
    print(f"=== {distrito!r} ===")
    slug = s._slugify(distrito)
    print(f"  slug          : {slug}")
    print(f"  url           : {s._distrito_url(distrito)}")
    try:
        itens = s.concelhos_com_nome_do_site(distrito)
        print(f"  concelhos     : {len(itens)}")
        for i in itens[:10]:
            print(f"      {i['slug']:<26} {i['nome']:<30} {i['empresas']}")
    except Exception as e:  # noqa: BLE001
        print(f"  ERRO          : {type(e).__name__}: {e}")
    print()


for nome in ("angra-do-heroismo", "Angra do Heroísmo", "Évora", "ponta-delgada"):
    analisar(nome)

# Todas as ligacoes da pagina do distrito, sem filtro nenhum.
print("=== ligacoes cruas da pagina de angra-do-heroismo ===")
try:
    page = s._fetch_html(s._distrito_url("angra-do-heroismo"))
    if page is None:
        print("  pagina sem resposta (None)")
    else:
        hrefs = [str(n.attrib.get("href") or "").strip() for n in page.css("a")]
        print(f"  total de <a>      : {len(hrefs)}")
        diretorio = sorted({h for h in hrefs if "/diretorio/" in h})
        print(f"  ligacoes /diretorio/: {len(diretorio)}")
        for h in diretorio[:30]:
            print(f"      {h}")
        preferido = sorted({h for h in hrefs if "angra" in h.lower()})
        print(f"  ligacoes com 'angra': {len(preferido)}")
        for h in preferido[:30]:
            print(f"      {h}")
except Exception as e:  # noqa: BLE001
    print(f"  ERRO: {type(e).__name__}: {e}")

# O que o catalogo (o que a UI mostra) diz deste distrito.
print()
print("=== o que o catalogo diz ===")
try:
    cat = s.catalogo()
    for d in cat.get("distritos", []):
        if "angra" in d["slug"] or "acor" in d["slug"] or "ponta" in d["slug"]:
            concelhos = d.get("concelhos") or []
            print(f"  {d['slug']:<24} nome={d.get('nome')!r} empresas={d.get('empresas')} "
                  f"concelhos={len(concelhos)}")
            for c in concelhos[:10]:
                print(f"      {c}")
except Exception as e:  # noqa: BLE001
    print(f"  ERRO: {type(e).__name__}: {e}")
