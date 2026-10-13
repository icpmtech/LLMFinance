import re

import httpx

CABECALHOS = {"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"}


def obter_wikitext(pagina: str) -> str:
    r = httpx.get(
        "https://pt.wikipedia.org/w/api.php",
        params={"action": "parse", "page": pagina, "prop": "wikitext", "format": "json", "formatversion": "2"},
        headers=CABECALHOS,
        timeout=120.0,
    )
    return r.json()["parse"]["wikitext"]


def primeira_tabela(texto: str) -> str:
    inicio = texto.index("{|")
    profundidade = 0
    linhas = texto[inicio:].split("\n")
    saida = []
    for linha in linhas:
        if linha.lstrip().startswith("{|"):
            profundidade += 1
        if linha.lstrip().startswith("|}"):
            profundidade -= 1
            if profundidade == 0:
                saida.append(linha)
                break
        saida.append(linha)
    return "\n".join(saida)


def limpar(valor: str) -> str:
    valor = re.sub(r"<ref[^>]*>.*?</ref>", "", valor, flags=re.DOTALL)
    valor = re.sub(r"<ref[^>]*/>", "", valor)
    valor = re.sub(r"\{\{fmtn\|([^}]*)\}\}", r"\1", valor)
    valor = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", valor)
    valor = re.sub(r"\[\[([^\]]*)\]\]", r"\1", valor)
    valor = re.sub(r"'{2,}", "", valor)
    valor = re.sub(r"<[^>]+>", " ", valor)
    return re.sub(r"\s+", " ", valor).strip()


texto = obter_wikitext("Lista de municípios de Portugal")
tabela = primeira_tabela(texto)
linhas = tabela.split("\n")
print("tabela linhas:", len(linhas))

celulas: list[list[str]] = []
for linha in linhas:
    crua = linha.strip()
    if crua.startswith("|-"):
        celulas.append([])
        continue
    if not celulas:
        continue
    if crua.startswith("|") and not crua.startswith("|}"):
        corpo = crua[1:]
        partes = corpo.split("||")
        celulas[-1].extend(partes)
    elif crua.startswith("!"):
        continue

linhas_dados = [c for c in celulas if c]
print("linhas com células:", len(linhas_dados))
print("tamanhos:", sorted({len(c) for c in linhas_dados}))

registos = []
for c in linhas_dados:
    if len(c) < 4:
        print("  linha curta:", [x[:40] for x in c])
        continue
    imagem = re.search(r"(?:Imagem|Ficheiro|File)\s*:\s*([^|\]]+)", c[0])
    nome = limpar(c[1])
    criacao = limpar(c[2])
    codigo = limpar(c[3])
    populacao = limpar(c[4]) if len(c) > 4 else ""
    registos.append({
        "municipio": nome,
        "imagem": imagem.group(1).strip() if imagem else None,
        "criacao": criacao,
        "ano": (re.search(r"\b(\d{3,4})\b", criacao) or [None, None])[1] if re.search(r"\b(\d{3,4})\b", criacao) else None,
        "codigo": codigo,
        "populacao_2021": populacao,
    })

print("registos:", len(registos))
for r in registos[:10]:
    print("  ", r)
sem_imagem = [r["municipio"] for r in registos if not r["imagem"]]
print("sem imagem:", len(sem_imagem), sem_imagem[:20])
sem_ano = [r["municipio"] for r in registos if not r["ano"]]
print("sem ano:", len(sem_ano), sem_ano[:20])

# Cobertura no Commons
nomes = [r["imagem"] for r in registos if r["imagem"]]
encontrados = {}
for inicio in range(0, len(nomes), 50):
    pedaco = nomes[inicio : inicio + 50]
    dados = httpx.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": "160",
            "titles": "|".join(f"File:{n}" for n in pedaco),
        },
        headers=CABECALHOS,
        timeout=120.0,
    ).json()
    for pagina in dados.get("query", {}).get("pages", []):
        info = (pagina.get("imageinfo") or [None])[0]
        if info:
            encontrados[pagina["title"][5:].replace("_", " ")] = info.get("thumburl")
print("no Commons:", len(encontrados), "de", len(nomes))
faltam = [n for n in nomes if n.replace("_", " ") not in encontrados and n not in encontrados]
print("fora do Commons:", len(faltam), faltam[:20])
