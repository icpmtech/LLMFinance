"""Teste rápido (temporário) do serviço de remunerações da AP."""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from api import remuneracoes_ap_service as servico  # noqa: E402

origem = Path(os.environ["TEMP"]) / "srap"
servico.PASTA.mkdir(parents=True, exist_ok=True)
(servico.PASTA / "pdf").mkdir(parents=True, exist_ok=True)
for ficheiro in origem.glob("*.pdf"):
    destino = servico.PASTA / "pdf" / ficheiro.name
    if not destino.exists():
        shutil.copy2(ficheiro, destino)

ano = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
nome = servico.FICHEIROS[ano]
modelo = servico.recolher_ano(ano, forcar=True)
saida = io.open(Path(os.environ["TEMP"]) / f"srap_modelo_{ano}.txt", "w", encoding="utf-8")
escrever = lambda *partes: saida.write(" ".join(str(parte) for parte in partes) + "\n")  # noqa: E731

escrever("versao:", modelo.get("versao"))
escrever("contagens:", json.dumps(modelo.get("contagens"), ensure_ascii=False))
escrever("\n--- niveis (TRU), primeiros e ultimos ---")
for item in (modelo["niveis"][:6] + modelo["niveis"][-4:]):
    escrever("  ", json.dumps(item, ensure_ascii=False))
escrever("\n--- tru_notas ---")
for nota in modelo["tru_notas"][:6]:
    escrever("  ", nota)

escrever("\n--- carreiras por seccao ---")
seccoes: dict = {}
for item in modelo["carreiras"]:
    seccoes.setdefault(item["seccao"], []).append(item)
for seccao, itens in seccoes.items():
    escrever(f"  {seccao}: {len(itens)} registos")
escrever("\n--- Carreiras Gerais ---")
for item in seccoes.get("Carreiras Gerais", []):
    escrever("  carreira=", item["carreira"], "| categoria=", item["categoria"])
    escrever("     posicoes=", [(p["posicao"], p["niveis_texto"], p["remuneracao"]) for p in item["posicoes"]])

escrever("\n--- amostra de cada outra seccao (3) ---")
for seccao, itens in seccoes.items():
    if seccao == "Carreiras Gerais":
        continue
    for item in itens[:3]:
        escrever(f"  [{seccao}] {item['carreira']} | {item['categoria']} -> {[(p['posicao'], p['remuneracao']) for p in item['posicoes']][:4]}")

escrever("\n--- dirigentes (amostra) ---")
for item in modelo["dirigentes"][:12]:
    escrever("  ", json.dumps({k: item[k] for k in ("ambito", "grupo", "cargo", "indice", "niveis_texto", "remuneracao")}, ensure_ascii=False))
escrever("  total dirigentes:", len(modelo["dirigentes"]))
escrever("  ambits:", sorted({str(i["ambito"]) for i in modelo["dirigentes"]}))

escrever("\n--- notas ---")
for nota in modelo["notas"]:
    escrever("  seccao:", nota["seccao"], "| linhas:", len(nota["texto"]), "| 1.ª:", (nota["texto"][:3]))
escrever("\n--- base legal ---")
for tabela in modelo["base_legal"]:
    escrever("  seccao:", tabela["seccao"], "| linhas:", len(tabela["linhas"]), "| cabecalho:", tabela["cabecalho"])
    for linha in tabela["linhas"][:2]:
        escrever("     ", json.dumps(linha, ensure_ascii=False)[:220])

escrever("\n--- parametros ---")
escrever("  ", json.dumps(servico.parametros_do_ano(ano), ensure_ascii=False))
escrever("\n--- simulacao ---")
escrever("  nivel 40:", json.dumps(servico.simular(ano=ano, nivel=40), ensure_ascii=False)[:300])
escrever("  carreira:", json.dumps(servico.simular(ano=ano, carreira="Tecnico superior", posicao="1"), ensure_ascii=False)[:300])
saida.close()
print("escrito", Path(os.environ["TEMP"]) / f"srap_modelo_{ano}.txt")
