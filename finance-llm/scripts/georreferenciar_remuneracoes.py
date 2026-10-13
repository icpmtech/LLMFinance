"""Georreferencia os concelhos e as freguesias de Portugal para o módulo de remunerações.

O recenseamento do MAI diz quantos **eleitores** tem cada concelho e cada
freguesia, mas não onde ficam: os polígonos que publica vivem no sistema de
coordenadas do seu próprio mapa. Este script vai buscar à Wikidata as
**coordenadas geográficas** (latitude/longitude) de cada município e de cada
freguesia — as mesmas que servem o OpenStreetMap — e grava-as em
`data/remuneracoes/geo_territorios.json`.

É o mesmo trabalho que `POST /remuneracoes/refresh` faz quando ainda não há
coordenadas; este script existe para o poder correr **fora da API** (por
exemplo, depois de uma recolha, ou para ver o relatório de cobertura) e para
dizer, no fim, que territórios ficaram de fora.

Uso::

    python scripts/georreferenciar_remuneracoes.py

As classes usadas são as da própria Wikidata para Portugal (definidas no
serviço): `Q13217644` «município de Portugal» e `Q1131296` «freguesia de
Portugal». O casamento dos nomes entre as duas fontes — que é onde está a
dificuldade, porque o MAI diz «União das freguesias de Aldeia do Mato e Souto»
onde a Wikidata diz «Aldeia do Mato e Souto» — vive no serviço
(`chave_territorio`/`variantes_territorio`/`coordenadas`), para o script e a API
não divergirem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import remuneracoes_service as remuneracoes  # noqa: E402


def main() -> int:
    print("A georreferenciar na Wikidata: municípios e freguesias de Portugal…")
    dados = remuneracoes.georreferenciar()
    for nivel in ("concelhos", "freguesias"):
        indice = dados[nivel]
        print(
            f"  {nivel}: {len(indice['por_nome'])} nomes inequívocos + "
            f"{len(indice['por_nome_concelho'])} pares «nome|concelho»"
        )
    destino = remuneracoes._data_dir() / remuneracoes.GEO_FILE
    print(f"escrito {destino} ({destino.stat().st_size / 1024:.0f} KB)")

    # Confronto com a árvore do MAI, quando já existir em disco: é o que diz se a
    # georreferenciação cobre mesmo os territórios que o módulo serve.
    remuneracoes.limpar_cache()
    territorios = remuneracoes.territorios()
    if not territorios.get("concelhos"):
        print("Sem árvore territorial do MAI em disco; nada a confrontar.")
        return 0

    sem_concelho = [
        c["nome"]
        for c in territorios.get("concelhos") or []
        if not remuneracoes.coordenadas("municipio", c["nome"], c.get("distrito"))
    ]
    sem_freguesia = [
        f"{f['nome']} ({f['concelho']})"
        for f in territorios.get("freguesias") or []
        if not remuneracoes.coordenadas("freguesia", f["nome"], f.get("concelho"))
    ]
    print(
        f"do MAI: {len(sem_concelho)} concelhos e {len(sem_freguesia)} freguesias sem coordenadas"
    )
    for nome in sem_concelho:
        print("   -", nome)
    for nome in sem_freguesia:
        print("   -", nome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
