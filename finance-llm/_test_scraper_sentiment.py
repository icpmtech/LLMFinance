"""Testa o sentimento por notícia: léxico local, modelo de IA e análise à posteriori.

Uso:
    python _test_scraper_sentiment.py                 # léxico + IA (se houver)
    python _test_scraper_sentiment.py --ia 2          # só IA, 2 itens
    python _test_scraper_sentiment.py --backfill eco-sapo-27cd8a 6
Grava o relatório em `_test_scraper_sentiment.txt` (UTF-8).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_sentiment as sentimento  # noqa: E402
from api import scraper_service as scraper  # noqa: E402

OUT = Path(__file__).resolve().parent / "_test_scraper_sentiment.txt"
lines: list[str] = []


def emit(text: str = "") -> None:
    lines.append(text)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def main() -> None:
    argumentos = sys.argv[1:]
    alvo_ia = None
    if "--ia" in argumentos:
        alvo_ia = int(argumentos[argumentos.index("--ia") + 1])
    fonte_backfill = None
    limite_backfill = 6
    if "--backfill" in argumentos:
        fonte_backfill = argumentos[argumentos.index("--backfill") + 1]
        if len(argumentos) > argumentos.index("--backfill") + 2 and argumentos[argumentos.index("--backfill") + 2].isdigit():
            limite_backfill = int(argumentos[argumentos.index("--backfill") + 2])

    # Procura itens com texto utilizável em todas as fontes (as mais recentes
    # podem ser de fontes que só recolhem títulos).
    itens = []
    for fonte in scraper.list_sources():
        encontrados = scraper.search_items(source_id=fonte["id"], size=20, sort="recent")
        for item in encontrados.get("items") or []:
            texto = str(item.get("text") or "")
            if len(texto) >= 200 or len(str(item.get("summary") or "")) >= 120:
                itens.append(item)
        if len(itens) >= 6:
            break
    emit(f"itens com texto utilizável: {len(itens)}")
    if not itens:
        emit("Sem itens com texto para analisar (recolha algo primeiro).")
        return

    config = sentimento.normalize_config({"enabled": True, "engine": "lexicon", "max_items": 6})
    for item in itens[:4]:
        texto = sentimento.item_text(item, config)
        resultado = sentimento.analyze_lexicon(texto)
        emit(
            "léxico: {label:9s} polaridade={polarity:+.3f} termos={hits:3d} chars={chars:5d} :: {title}".format(
                label=resultado["label"],
                polarity=resultado["polarity"],
                hits=resultado["hits"],
                chars=len(texto),
                title=str(item.get("title") or "")[:70],
            )
        )

    quantos = alvo_ia if alvo_ia is not None else 2
    if quantos:
        config_ia = sentimento.normalize_config(
            {"enabled": True, "engine": "ai", "max_items": quantos, "min_chars": 80}
        )
        emit("")
        emit(f"modelo de IA ({quantos} item(ns), fornecedor do ambiente/Ollama quando não há chave):")
        for item in itens[:quantos]:
            inicio = time.perf_counter()
            resultado = sentimento.analyze_item(item, config_ia)
            gasto = int((time.perf_counter() - inicio) * 1000)
            if not resultado:
                emit("  sem texto suficiente")
                continue
            emit(
                "  {label:9s} polaridade={polarity:+.3f} motor={engine:8s} modelo={model:22s} {ms:6d} ms :: {title}".format(
                    label=resultado.get("label") or "(erro)",
                    polarity=float(resultado.get("polarity") or 0.0),
                    engine=resultado.get("engine") or "?",
                    model=str(resultado.get("model") or "-")[:22],
                    ms=gasto,
                    title=str(item.get("title") or "")[:60],
                )
            )
            if resultado.get("justification"):
                emit(f"      justificação: {resultado['justification'][:120]}")
            if resultado.get("error"):
                emit(f"      erro: {resultado['error'][:160]}")

    if fonte_backfill:
        emit("")
        emit(f"análise à posteriori da fonte {fonte_backfill} (até {limite_backfill} itens):")
        resultado = scraper.sentiment_backfill(source_id=fonte_backfill, limit=limite_backfill, engine="auto")
        emit(f"  {resultado}")
        depois = scraper.search_items(source_id=fonte_backfill, size=1)
        emit(f"  sentimento da pesquisa: {depois.get('sentiment')}")


if __name__ == "__main__":
    main()
