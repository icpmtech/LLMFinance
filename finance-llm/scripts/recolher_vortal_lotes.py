"""Recolha em lote (mês e ano) das peças do procedimento da Vortal.

Corre os lotes de um período **até acabar**, escrevendo o progresso no stdout —
é o que permite deixar a recolha a correr destacada, com a saída num log, sem
depender de uma sessão aberta (a rota `POST /vortal/lote` exige sessão, esta
executa o mesmo motor por dentro do contentor).

Uso::

    python scripts/recolher_vortal_lotes.py --ano 2026 --mes 10

Na VM, destacado, com o log no volume de `logs/`::

    docker exec -d iqos-backend sh -c \
      'nohup python -u /app/scripts/recolher_vortal_lotes.py --ano 2026 --mes 10 --lote 4 --lotes 1 --pausa 60 \
       >> /app/logs/vortal_lote_2026-10.log 2>&1 & echo $! > /app/logs/vortal_lote_2026-10.pid'

Para ver quando falta: ``python scripts/recolher_vortal_lotes.py --ano 2026 --mes 10 --planear``.

**Ritmo**: a Vortal limita por IP. Uma recolha sem pausas (50 avisos seguidos)
fez o IP da VM passar a responder **403** a quase tudo — e os mesmos tokens
voltaram a **200** minutos depois, com um pedido isolado. Por isso o ritmo por
omissão é conservador (lotes pequenos e 60 s de pausa) e o script **abranda
sozinho** quando um lote falha em mais de metade, parando ao fim de alguns lotes
sem trazer nada.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import vortal_service as vortal  # noqa: E402


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _log(mensagem: str) -> None:
    print(f"[{_agora()}] {mensagem}", flush=True)


def _bytes(valor: int) -> str:
    for unidade in ("B", "kB", "MB", "GB"):
        if valor < 1024 or unidade == "GB":
            return f"{valor:.1f} {unidade}" if unidade != "B" else f"{valor} B"
        valor /= 1024.0
    return f"{valor:.1f} GB"


def _ler_periodo(args: argparse.Namespace) -> dict:
    return vortal.avisos_do_periodo(
        ano=args.ano,
        mes=args.mes,
        limite=10,
        escanear=args.escanear,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recolher em lote as peças de um mês/ano da Vortal")
    parser.add_argument("--ano", type=int, required=True, help="Ano de publicação dos contratos")
    parser.add_argument("--mes", type=int, default=None, help="Mês (por omissão, o ano inteiro)")
    parser.add_argument("--lote", type=int, default=vortal.LOTE_PADRAO, help="Avisos por lote")
    parser.add_argument("--lotes", type=int, default=5, help="Lotes por chamada (1-%d)" % vortal.LOTES_POR_VEZ)
    parser.add_argument("--escanear", type=int, default=vortal.ESCANEAR_PADRAO, help="Contratos a ler do índice por chamada")
    parser.add_argument(
        "--pausa",
        type=float,
        default=60.0,
        help="Segundos entre lotes (a Vortal limita o ritmo por IP; 60 s é conservador de propósito)",
    )
    parser.add_argument("--max-lotes", type=int, default=500, help="Teto de segurança de lotes nesta execução")
    parser.add_argument("--max-sem-novos", type=int, default=3, help="Lotes seguidos sem nada recolhido antes de parar")
    parser.add_argument("--sem-indexar", action="store_true", help="Descarregar sem indexar no Elasticsearch")
    parser.add_argument("--sem-extrair", action="store_true", help="Não extrair o texto das peças")
    parser.add_argument("--forcar", action="store_true", help="Refazer o período desde o início (re-descarga)")
    parser.add_argument("--planear", action="store_true", help="Só ler o estado do período (não recolhe nada)")
    args = parser.parse_args(argv)

    periodo = _ler_periodo(args)
    if not periodo.get("disponivel"):
        _log(f"Elasticsearch indisponível: {periodo.get('erro')}")
        return 1

    _log(
        f"período {args.ano}-{args.mes or 'ano'}: {periodo['total']} contrato(s), "
        f"{periodo['unicos']} aviso(s) único(s), {periodo['em_disco']} em disco, "
        f"{periodo['pendentes']} por recolher"
        + (" (lista truncada pelo teto de contratos)" if periodo.get("truncado") else "")
    )
    if args.planear:
        return 0

    comecou = time.time()
    avisos = pecas = indexados = 0
    total_bytes = 0
    erros = 0
    sem_novos = 0
    pausa = max(1.0, args.pausa)

    for numero in range(1, max(1, args.max_lotes) + 1):
        resultado = vortal.recolher_lote(
            ano=args.ano,
            mes=args.mes,
            lote=args.lote,
            lotes=args.lotes,
            indexar=not args.sem_indexar,
            extrair=not args.sem_extrair,
            forcar=args.forcar,
            escanear=args.escanear,
        )
        if not resultado.get("ok"):
            _log(f"lote {numero}: falhou — {resultado.get('erro')}")
            return 1

        tentados = int(resultado.get("processados") or 0)
        colhidos = int(resultado.get("recolhidos") or 0)
        falhados = max(0, tentados - colhidos)
        restantes = int(resultado.get("restantes") or 0)
        avisos += colhidos
        pecas += int(resultado.get("pecas") or 0)
        total_bytes += int(resultado.get("bytes") or 0)
        indexados += int(resultado.get("indexados") or 0)
        erros += len(resultado.get("erros") or [])
        _log(
            f"lote {numero}: tentados {tentados} · recolhidos {colhidos} · peças {resultado.get('pecas')} · "
            f"{_bytes(int(resultado.get('bytes') or 0))} · indexadas {resultado.get('indexados')} · "
            f"falhas {falhados} · faltam {restantes} de {resultado.get('candidatos')} (pausa {pausa:.0f}s)"
        )
        for erro in (resultado.get("erros") or [])[:3]:
            _log(f"    erro: {erro[:200]}")

        if restantes <= 0:
            _log("período concluído")
            break

        sem_novos = sem_novos + 1 if colhidos == 0 else 0
        if sem_novos >= max(1, args.max_sem_novos):
            _log(f"{sem_novos} lote(s) sem nada recolhido — paro (a Vortal pode estar a limitar o ritmo)")
            break

        # Recuo: a Vortal limita por IP e responde 403/500 a rajadas (medido: uma
        # corrida sem pausas passou a ~97 % de recusas). Abranda-se quando falha
        # muito e volta-se ao ritmo pedido quando os lotes saem limpos.
        if tentados and falhados / tentados >= 0.5:
            pausa = min(pausa * 2, 600.0)
            _log(f"    falhas em {falhados}/{tentados} — a abrandar para {pausa:.0f}s entre lotes")
        elif colhidos == tentados and pausa > args.pausa:
            pausa = max(args.pausa, pausa / 2)
            _log(f"    lote limpo — a acelerar para {pausa:.0f}s entre lotes")
        time.sleep(pausa)
    else:
        _log(f"atingido o teto de {args.max_lotes} lote(s) — voltar a correr para continuar")

    duracao = time.time() - comecou
    _log(
        f"fim: {avisos} aviso(s), {pecas} peça(s), {_bytes(total_bytes)}, {indexados} indexada(s), "
        f"{erros} erro(s) em {duracao / 60:.1f} min ({duracao / max(1, avisos):.1f} s por aviso)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        _log("interrompido")
        raise SystemExit(130)
