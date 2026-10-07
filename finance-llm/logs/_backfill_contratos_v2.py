"""Backfill paralelo dos embeddings do índice `contratos` (retomável).

Porque é que isto não usa o `vector_service.index_missing_embeddings` direto:
um único processo fazia **~15 docs/s** (medido: 89% do tempo na codificação e
o Elasticsearch a responder a 229 docs/s), o que daria ~40 h para 2,25 M de
contratos. Aqui:

* **vários processos**, cada um com poucas threads do PyTorch (um processo com
  12 threads não satura a máquina — a codificação é limitada por largura de
  banda de memória);
* **um scroll por fatia** (`slice`), por isso os processos não se cruzam nem
  precisam de coordenação;
* **lotes ordenados por comprimento** antes de codificar: o `model.encode`
  preenche todos os textos do lote até ao mais longo, e os contratos variam de
  477 a 3501 caracteres — ordenar evita pagar 3501 caracteres por contrato
  curto;
* **retomável**: cada processo só pede documentos **sem** `embedding`, por isso
  parar a meio e voltar a arrancar não repete trabalho.

Uso:
    python logs/_backfill_contratos.py --workers 4 --threads 3
    python logs/_backfill_contratos.py --workers 1 --threads 12 --max-docs 20000
    python logs/_backfill_contratos.py --workers 4 --threads 3 --anos 2023,2024,2025,2026
"""
from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

LOG = RAIZ / "logs" / "_backfill_contratos.log"

# Tamanho do lote de codificação depois de ordenar por comprimento.
BATCH_CODIFICACAO = 96
# Documentos pedidos ao Elasticsearch de cada vez.
BATCH_LEITURA = 768
# Criar este ficheiro pede PAUSA: os processos acabam o lote em curso e saem
# sem perder trabalho (o backfill só pede documentos sem `embedding`).
PAUSA = RAIZ / "logs" / "_backfill.pausa"
# Anos por omissão, do mais recente para o mais antigo.
ANOS_PADRAO = list(range(2026, 2011, -1))


def _pausa_pedida() -> bool:
    """Existe pedido de pausa? (o controlador cria/remove o ficheiro)"""
    return PAUSA.exists()


def _configurar_log(nome: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s " + nome + " %(message)s",
        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    for ruidoso in ("elastic_transport", "elasticsearch", "urllib3", "httpx", "httpcore", "sentence_transformers"):
        logging.getLogger(ruidoso).setLevel(logging.ERROR)


def _corpo_pesquisa(anos: list[int] | None, fatia: dict | None, tamanho: int) -> dict:
    """Consulta: documentos sem `embedding` (e, se pedido, de certos anos)."""
    filtros: list[dict] = [{"bool": {"must_not": {"exists": {"field": "embedding"}}}}]
    if anos:
        filtros.append({"terms": {"Ano": anos}})
    corpo: dict = {
        "query": {"bool": {"filter": filtros}},
        "_source": ["objectoContrato", "descContrato", "fundamentacao", "search_text", "adjudicantes", "adjudicatarios", "cpv"],
        "size": tamanho,
    }
    if fatia:
        corpo["slice"] = fatia
    return corpo


def _codificar(modelo, textos: list[str]):
    """Codifica por lotes **ordenados por comprimento** (menos preenchimento)."""
    ordem = sorted(range(len(textos)), key=lambda i: len(textos[i]))
    saida = [None] * len(textos)
    for inicio in range(0, len(ordem), BATCH_CODIFICACAO):
        indice = ordem[inicio : inicio + BATCH_CODIFICACAO]
        vetores = modelo.encode([textos[i] for i in indice], batch_size=len(indice), normalize_embeddings=True, show_progress_bar=False)
        for posicao, i in enumerate(indice):
            saida[i] = vetores[posicao]
    return saida


def trabalhador(numero: int, total: int, threads: int, anos: list[int] | None, max_docs: int, modelo_nome: str) -> None:
    """Um processo: fatia `numero`/`total` do índice."""
    import torch

    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(1)
    except Exception:  # pragma: no cover
        pass

    _configurar_log(f"[w{numero}]")
    from api import vector_service as vs

    es = vs.get_es_client()
    if es is None:
        logging.error("Elasticsearch indisponível")
        return
    modelo = vs._get_embedding_model(modelo_nome)
    logging.info("modelo pronto (%s threads, fatia %d/%d)", threads, numero, total)

    feitos = 0
    erros = 0
    lotes = 0
    inicio = time.time()
    ultimo_log = inicio
    fatia = {"id": numero, "max": total} if total > 1 else None
    corpo = _corpo_pesquisa(anos, fatia, BATCH_LEITURA)

    while True:
        if _pausa_pedida():
            logging.info("PAUSA pedida: a sair antes de novo lote")
            break
        if max_docs and feitos >= max_docs:
            break
        try:
            resposta = es.search(index=vs.CONTRACTS_INDEX, body=corpo, scroll="10m")
        except Exception as erro:  # noqa: BLE001
            logging.error("pesquisa falhou (%s); nova tentativa em 10 s", erro)
            time.sleep(10)
            continue
        scroll_id = resposta.get("_scroll_id")
        if not resposta["hits"]["hits"]:
            break

        while scroll_id and resposta["hits"]["hits"]:
            if _pausa_pedida():
                logging.info("PAUSA pedida: a sair depois do lote anterior")
                break
            hits = resposta["hits"]["hits"]
            ids = [h["_id"] for h in hits]
            textos = [vs._contract_text(h.get("_source", {})) for h in hits]
            if lotes == 0:
                logging.info(
                    "primeiro lote: %d docs, %d caracteres no total (máx %d)",
                    len(textos),
                    sum(len(t) for t in textos),
                    max((len(t) for t in textos), default=0),
                )
            lotes += 1
            uteis = [(i, t) for i, t in zip(ids, textos) if t]
            if uteis:
                ids, textos = map(list, zip(*uteis))
                try:
                    t_enc = time.time()
                    vetores = _codificar(modelo, textos)
                    t_enc = time.time() - t_enc
                    logging.info(
                        "encode de %d docs em %.1fs (%.1f docs/s)", len(textos), t_enc, len(textos) / max(t_enc, 0.001)
                    )
                except Exception as erro:  # noqa: BLE001
                    erros += len(ids)
                    logging.error("codificação falhou (%s)", erro)
                    vetores = []
                if vetores:
                    corpo_bulk = []
                    for doc_id, vetor in zip(ids, vetores):
                        corpo_bulk.append({"update": {"_index": vs.CONTRACTS_INDEX, "_id": doc_id}})
                        corpo_bulk.append({"doc": {"embedding": vetor.tolist() if hasattr(vetor, "tolist") else vetor}})
                    try:
                        bruto = es.bulk(body=corpo_bulk, refresh=False)
                        if bruto.get("errors"):
                            for item in bruto.get("items", []):
                                if item.get("update", {}).get("error"):
                                    erros += 1
                            feitos += len(ids) - sum(1 for i in bruto.get("items", []) if i.get("update", {}).get("error"))
                        else:
                            feitos += len(ids)
                    except Exception as erro:  # noqa: BLE001
                        erros += len(ids)
                        logging.error("bulk falhou (%s)", erro)

            gasto = max(time.time() - inicio, 0.001)
            if feitos and (time.time() - ultimo_log) >= 30:
                ultimo_log = time.time()
                logging.info("%d feitos, %d erros | %.1f docs/s | %.1f min", feitos, erros, feitos / gasto, gasto / 60)
            if max_docs and feitos >= max_docs:
                break
            try:
                resposta = es.scroll(scroll_id=scroll_id, scroll="10m")
            except Exception as erro:  # noqa: BLE001
                logging.error("scroll falhou (%s)", erro)
                break
            scroll_id = resposta.get("_scroll_id")

        if scroll_id:
            try:
                es.clear_scroll(scroll_id=scroll_id)
            except Exception:  # pragma: no cover
                pass
        break  # um scroll por fatia chega para varrer o índice todo

    try:
        es.indices.refresh(index=vs.CONTRACTS_INDEX)
    except Exception:  # pragma: no cover
        pass
    logging.info("fim: %d feitos, %d erros, %.1f min", feitos, erros, (time.time() - inicio) / 60)


def cobertura() -> dict:
    from api import vector_service as vs

    es = vs.get_es_client()
    total = es.count(index=vs.CONTRACTS_INDEX).get("count", 0)
    com = es.count(index=vs.CONTRACTS_INDEX, body={"query": {"exists": {"field": "embedding"}}}).get("count", 0)
    return {"total": total, "com": com, "sem": total - com}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill paralelo de embeddings (retomável).")
    parser.add_argument("--workers", type=int, default=4, help="Processos de codificação.")
    parser.add_argument("--threads", type=int, default=3, help="Threads do PyTorch por processo.")
    parser.add_argument("--anos", default="", help="Anos a preencher (ex.: 2023,2024). Vazio = todos.")
    parser.add_argument("--max-docs", type=int, default=0, help="Limite por processo (0 = sem limite).")
    parser.add_argument("--por-ano", action="store_true", help="Percorrer os anos um a um, do mais recente para o mais antigo.")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    args = parser.parse_args()

    mp.freeze_support()
    pedidos = [int(a) for a in args.anos.split(",") if a.strip()]
    # Cada alvo e um par (rotulo, anos): com `--por-ano` corre um ano de cada vez,
    # do mais recente para o mais antigo; senao e uma unica passagem com todos os
    # anos pedidos (ou sem filtro nenhum).
    if args.por_ano:
        alvos: list = [(str(ano), [ano]) for ano in (pedidos or ANOS_PADRAO)]
    else:
        alvos = [(",".join(str(a) for a in pedidos) if pedidos else "todos os anos", pedidos or None)]
    _configurar_log("[main]")

    estado = cobertura()
    logging.info(
        "cobertura: %s de %s (%.2f%%), %s em falta | %d processos x %d threads",
        f"{estado['com']:,}",
        f"{estado['total']:,}",
        100.0 * estado["com"] / estado["total"] if estado["total"] else 0.0,
        f"{estado['sem']:,}",
        args.workers,
        args.threads,
    )
    if estado["sem"] == 0:
        logging.info("nada a fazer")
        return 0

    inicio = time.time()
    com_inicial = estado["com"]
    for rotulo, anos_alvo in alvos:
        if _pausa_pedida():
            logging.info("pausa pedida: a parar antes de %s", rotulo)
            return 3
        logging.info("=== a processar %s ===", rotulo)
        procs = [
            mp.Process(
                target=trabalhador,
                args=(i, args.workers, args.threads, anos_alvo, args.max_docs, args.model),
                name=f"bf{i}",
            )
            for i in range(args.workers)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        if _pausa_pedida():
            logging.info("pausa pedida: a parar depois de %s", rotulo)
            return 3

    estado = cobertura()
    gasto = max(time.time() - inicio, 0.001)
    novos = max(estado["com"] - com_inicial, 0)
    logging.info(
        "FIM: %s de %s com embedding (%.2f%%), %s em falta | +%s nesta execucao | %.1f min | %.1f docs/s",
        f"{estado['com']:,}",
        f"{estado['total']:,}",
        100.0 * estado["com"] / estado["total"] if estado["total"] else 0.0,
        f"{estado['sem']:,}",
        f"{novos:,}",
        gasto / 60,
        novos / gasto,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
