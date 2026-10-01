"""Recolha assistida das Publicações de Atos Societários (publicacoes.mj.pt).

Porque existe este script
-------------------------
A pesquisa no portal do Ministério da Justiça exige um **reCAPTCHA v2 validado
no servidor**. Não há forma legítima de a automatizar em massa, pelo que este
script trabalha com uma pessoa no circuito: abre o browser no formulário, a
pessoa marca a caixa «Não sou um robô» e o script faz todo o resto.

Porque se recolhe por janelas temporais
---------------------------------------
A paginação e o detalhe **não** voltam a pedir captcha: uma pesquisa validada
autoriza o conjunto de resultados inteiro. Como o formulário aceita pesquisar só
por datas (intervalos até 10 dias), uma única resolução de captcha pode trazer
milhares de publicações de todo o país — em vez de uma por entidade.

Exemplos
--------
    # Uma janela de 10 dias (todas as publicações do país nesse período)
    python _recolha_mj_assistida.py --data-ini 2026-01-01 --data-fim 2026-01-10

    # Uma entidade
    python _recolha_mj_assistida.py --nif 500273170

    # O plano completo (janelas de 10 dias desde 2007), com retoma
    python _recolha_mj_assistida.py --plano

    # Só contar, sem abrir detalhe nem indexar (para medir o volume)
    python _recolha_mj_assistida.py --plano --limite-janelas 1 --sem-detalhe --sem-indexar

O progresso fica em `data/societario/estado.json` (use ``--recomecar`` para
ignorar). Interromper com Ctrl+C é seguro: o estado é gravado.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from collectors.publicacoes_mj import (  # noqa: E402
    DISTRITOS,
    PAGE,
    TIPOS_PUBLICACAO,
    PublicacoesMjClient,
)

logger = logging.getLogger("recolha_mj")

PFX = "ctl00$ContentPlaceHolderMain$"
SEL_GRID = "#ctl00_ContentPlaceHolderMain_gvSearchResult"
SEL_SEM_RESULTADO = "#ctl00_ContentPlaceHolderMain_lbNoResult"
SEL_CAPTCHA = '[name="g-recaptcha-response"]'
ESTADO_PADRAO = ROOT / "data" / "societario" / "estado.json"

# Primeira data com publicações no novo regime (o portal substituiu a 3.ª série do DR).
PRIMEIRA_DATA = "2007-01-01"


# --- janelas temporais ----------------------------------------------------


def janelas(desde: str, ate: str, dias: int = 10) -> List[Tuple[str, str]]:
    """Divide um intervalo em janelas de ``dias`` (o portal limita a 10 dias).

    A janela é inclusiva nas duas pontas, pelo que ``dias=10`` produz
    ``desde..desde+9``.
    """
    if dias < 1:
        raise ValueError("`--dias` tem de ser >= 1")
    inicio = datetime.strptime(desde, "%Y-%m-%d").date()
    fim = datetime.strptime(ate, "%Y-%m-%d").date()
    if fim < inicio:
        raise ValueError("`--ate` não pode ser anterior a `--desde`")
    out: List[Tuple[str, str]] = []
    passo = timedelta(days=dias - 1)
    atual = inicio
    while atual <= fim:
        ultimo = min(atual + passo, fim)
        out.append((atual.isoformat(), ultimo.isoformat()))
        atual = ultimo + timedelta(days=1)
    return out


def chave_janela(janela: Tuple[str, str]) -> str:
    return f"{janela[0]}:{janela[1]}"


# --- estado (retoma) -----------------------------------------------------


class Estado:
    """Progresso da recolha, para poder parar e retomar sem repetir trabalho."""

    def __init__(self, path: Path):
        self.path = path
        self.dados: Dict[str, Any] = {"feitas": [], "totais": {"janelas": 0, "publicacoes": 0}}
        if path.exists():
            try:
                self.dados.update(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:  # estado corrompido não deve travar a recolha
                logger.warning("Estado ilegível em %s (%s); a começar de novo.", path, exc)
        self.dados.setdefault("feitas", [])
        self.dados.setdefault("totais", {"janelas": 0, "publicacoes": 0})

    @property
    def feitas(self) -> set[str]:
        return set(self.dados.get("feitas") or [])

    def marcar(self, chave: str, publicacoes: int) -> None:
        if chave not in self.dados["feitas"]:
            self.dados["feitas"].append(chave)
        totais = self.dados["totais"]
        totais["janelas"] = totais.get("janelas", 0) + 1
        totais["publicacoes"] = totais.get("publicacoes", 0) + publicacoes
        self.guardar()

    def guardar(self) -> None:
        self.dados["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.dados, ensure_ascii=False, indent=2), encoding="utf-8")


# --- browser ------------------------------------------------------------


def _formato_formulario(valor: Optional[str]) -> str:
    """Converte uma data ISO para o formato do campo (máscara ``99/99/9999``).

    O formulário usa ``DD/MM/AAAA``; aceita-se ISO na linha de comandos por ser
    mais legível e menos sujeito a erros.
    """
    if not valor:
        return ""
    valor = valor.strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(valor, formato).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return valor


def preencher_formulario(page: Any, criterios: Dict[str, Any]) -> None:
    """Preenche o formulário de pesquisa (os campos usam o prefixo ``ctl00$ContentPlaceHolderMain$``)."""
    valores = {
        f"{PFX}txtDadosPubNif": criterios.get("nif") or "",
        f"{PFX}txtDadosPubEntidade": criterios.get("entidade") or "",
    }
    for nome, valor in valores.items():
        page.fill(f'input[name="{nome}"]', valor)

    for campo, chave in (("txtDataInit", "data_ini"), ("txtDataFim", "data_fim")):
        seletor = f'input[name="{PFX}{campo}"]'
        page.fill(seletor, _formato_formulario(criterios.get(chave)))
        page.dispatch_event(seletor, "blur")
        page.dispatch_event(seletor, "change")

    page.check(f'input[name="{PFX}rblTipoPub"][value="{criterios.get("tipo", "0")}"]')

    if criterios.get("distrito"):
        page.select_option(f'select[name="{PFX}comboDadosPubDistrito"]', criterios["distrito"])
        page.wait_for_timeout(1200)  # o concelho carrega por postback
        if criterios.get("concelho"):
            page.select_option(f'select[name="{PFX}comboDadosPubConcelho"]', criterios["concelho"])


def valores_submetidos(page: Any) -> Dict[str, str]:
    """Lê os valores do formulário tal como vão ser submetidos (diagnóstico)."""
    campos = (
        f"{PFX}txtDadosPubNif",
        f"{PFX}txtDadosPubEntidade",
        f"{PFX}txtDataInit",
        f"{PFX}txtDataFim",
        f"{PFX}comboDadosPubDistrito",
        f"{PFX}comboDadosPubConcelho",
    )
    return {campo.split("$")[-1]: page.input_value(f'input[name="{campo}"]') for campo in campos if page.locator(f'input[name="{campo}"]').count()}


def captcha_resolvido(page: Any) -> bool:
    """Indica se o reCAPTCHA já tem resposta (a pessoa marcou a caixa)."""
    return bool(
        page.evaluate(
            "() => { const t = document.getElementsByName('g-recaptcha-response')[0]; return !!(t && t.value); }"
        )
    )


def esperar_captcha(page: Any, descricao: str, timeout_s: int = 600) -> None:
    """Espera que a pessoa resolva o reCAPTCHA (mensagem clara no terminal)."""
    if captcha_resolvido(page):
        print("      captcha já resolvido.", flush=True)
        return
    print(
        f"\n  👉 Resolve o captcha na janela do browser (caixa «Não sou um robô»)\n"
        f"     {descricao}\n"
        f"     A aguardar até {timeout_s // 60} min... (Ctrl+C para parar)",
        flush=True,
    )
    page.wait_for_function(
        "() => { const t = document.getElementsByName('g-recaptcha-response')[0]; return !!(t && t.value); }",
        timeout=timeout_s * 1000,
    )
    print("      captcha aceite — a pesquisar...", flush=True)


def pesquisar_no_browser(
    page: Any,
    context: Any,
    criterios: Dict[str, Any],
    descricao: str,
    timeout_captcha: int = 600,
) -> Tuple[Optional[str], Dict[str, str], int]:
    """Faz a pesquisa no browser (com o captcha resolvido por uma pessoa).

    Devolve ``(html_dos_resultados, cookies, total_declarado)``; o HTML é ``None``
    quando a pesquisa não devolveu resultados.
    """
    page.goto(PAGE, wait_until="domcontentloaded", timeout=90_000)
    preencher_formulario(page, criterios)
    enviados = valores_submetidos(page)
    esperar_captcha(page, descricao, timeout_s=timeout_captcha)

    page.click(f'input[name="{PFX}btSearch"]')
    page.wait_for_selector(f"{SEL_GRID}, {SEL_SEM_RESULTADO}", timeout=180_000)

    cookies = {c["name"]: c["value"] for c in context.cookies()}
    if page.locator(SEL_GRID).count() == 0:
        mensagem = ""
        if page.locator(SEL_SEM_RESULTADO).count():
            mensagem = (page.locator(SEL_SEM_RESULTADO).inner_text() or "").strip()
        validador = ""
        seletor_validador = "#ctl00_ContentPlaceHolderMain_divValidator"
        if page.locator(seletor_validador).count():
            validador = (page.locator(seletor_validador).inner_text() or "").strip()
        logger.warning("Pesquisa sem resultados | campos=%s | mensagem=%r | validador=%r", enviados, mensagem, validador)
        print(f"      servidor: {mensagem or '(sem mensagem)'}", flush=True)
        print(f"      campos submetidos: {enviados}", flush=True)
        if "valida" in mensagem.lower():
            raise RuntimeError(
                "O portal recusou a pesquisa (captcha inválido ou expirado). "
                "Repita a tarefa: o token só é válido ~2 minutos."
            )
        return None, cookies, 0

    html = page.content()
    total = PublicacoesMjClient.result_range(html).get("total", 0)
    return html, cookies, total


# --- recolha ------------------------------------------------------------


def recolher(
    *,
    criterios: Dict[str, Any],
    result_html: str,
    cookies: Dict[str, str],
    with_details: bool,
    max_pages: int,
    min_interval: float,
) -> List[Dict[str, Any]]:
    """Recolhe a grelha inteira (e o detalhe, se pedido) a partir dos resultados do browser."""
    client = PublicacoesMjClient(cookies=cookies, min_interval=min_interval)
    publicacoes = client.collect(
        result_html=result_html,
        with_details=with_details,
        max_pages=max_pages,
        **criterios,
    )
    return [p.to_dict() for p in publicacoes]


def indexar(
    items: List[Dict[str, Any]],
    replace_for_nif: Optional[str] = None,
    drop_stale: bool = True,
) -> Dict[str, Any]:
    """Indexa no Elasticsearch (import tardio: `--sem-indexar` não precisa de ES).

    ``drop_stale`` tem de ser ``False`` quando a recolha é uma **janela** (uma
    parte das publicações da entidade) — senão a janela seguinte apagaria a
    anterior.
    """
    from api.societario_service import ingest

    return ingest(items, replace_for_nif=replace_for_nif, drop_stale=drop_stale)


def _browser_fechado(exc: BaseException) -> bool:
    """Diz se o erro é o fecho da janela do browser (a pessoa fechou-a).

    Reconhecido pelo nome/tipo para o script não depender do Playwright quando
    corre com ``--sem-indexar``/``--help``.
    """
    if type(exc).__name__ in ("TargetClosedError", "BrowserClosedError"):
        return True
    return "has been closed" in str(exc)


def resumo_janela(publicacoes: List[Dict[str, Any]], total_declarado: int) -> str:
    com_detalhe = sum(1 for p in publicacoes if p.get("detail_fetched"))
    entidades = {p.get("nif") for p in publicacoes if p.get("nif")}
    return (
        f"{len(publicacoes)} publicações"
        f" (anunciadas: {total_declarado or '?'}; {com_detalhe} com detalhe; {len(entidades)} entidades)"
    )


def recolher_uma(
    page: Any,
    context: Any,
    *,
    criterios: Dict[str, Any],
    descricao: str,
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, Any]], int]:
    """Pesquisa no browser e recolhe tudo (usado tanto no modo janela como no modo NIF)."""
    html, cookies, total = pesquisar_no_browser(page, context, criterios, descricao, args.timeout_captcha)
    if html is None:
        print("      sem resultados.", flush=True)
        return [], 0
    publicacoes = recolher(
        criterios=criterios,
        result_html=html,
        cookies=cookies,
        with_details=not args.sem_detalhe,
        max_pages=args.max_paginas,
        min_interval=args.intervalo,
    )
    return publicacoes, total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recolha assistida das publicações de atos societários (publicacoes.mj.pt).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--nif", help="NIF/NIPC de uma entidade")
    parser.add_argument("--entidade", help="Firma/denominação a pesquisar")
    parser.add_argument("--tipo", default="0", choices=sorted(TIPOS_PUBLICACAO), help="Tipo de publicação (0 = todos)")
    parser.add_argument("--distrito", choices=sorted(DISTRITOS), help="Código do distrito/ilha")
    parser.add_argument("--concelho", help="Código do concelho (requer --distrito)")
    parser.add_argument("--data-ini", help="Data inicial (AAAA-MM-DD) de uma janela única")
    parser.add_argument("--data-fim", help="Data final (AAAA-MM-DD) de uma janela única")
    parser.add_argument("--plano", action="store_true", help="Percorrer todas as janelas temporais")
    parser.add_argument("--desde", default=PRIMEIRA_DATA, help=f"Primeira data do plano (omissão {PRIMEIRA_DATA})")
    parser.add_argument("--ate", default=date.today().isoformat(), help="Última data do plano (omissão: hoje)")
    parser.add_argument("--dias", type=int, default=10, help="Dias por janela (máx. 10 no portal)")
    parser.add_argument("--max-paginas", type=int, default=300, help="Máximo de páginas da grelha por pesquisa")
    parser.add_argument("--intervalo", type=float, default=1.0, help="Intervalo mínimo entre pedidos (segundos)")
    parser.add_argument("--timeout-captcha", type=int, default=600, help="Segundos a esperar pelo captcha")
    parser.add_argument("--sem-detalhe", action="store_true", help="Guardar só a grelha (mais rápido)")
    parser.add_argument("--sem-indexar", action="store_true", help="Não escrever no Elasticsearch")
    parser.add_argument("--estado", default=str(ESTADO_PADRAO), help="Ficheiro de progresso")
    parser.add_argument("--recomecar", action="store_true", help="Ignorar o progresso guardado")
    parser.add_argument("--limite-janelas", type=int, help="Parar após N janelas (útil para testar)")
    parser.add_argument("--headless", action="store_true", help="Sem janela do browser (só para testes)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("recolha_mj").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    if args.dias > 10:
        parser.error("O portal não aceita intervalos superiores a 10 dias (--dias <= 10).")

    # --- lista de tarefas ---
    tarefas: List[Tuple[Dict[str, Any], str, Optional[str]]] = []  # (critérios, descrição, chave de estado)
    if args.plano:
        for janela in janelas(args.desde, args.ate, args.dias):
            criterios = {"data_ini": janela[0], "data_fim": janela[1], "tipo": args.tipo}
            tarefas.append((criterios, f"{janela[0]} a {janela[1]}", chave_janela(janela)))
    else:
        criterios = {
            "nif": args.nif,
            "entidade": args.entidade,
            "tipo": args.tipo,
            "distrito": args.distrito,
            "concelho": args.concelho,
            "data_ini": args.data_ini,
            "data_fim": args.data_fim,
        }
        if not any((args.nif, args.entidade, args.distrito, args.data_ini)):
            parser.error("Indique --plano, --nif, --entidade, --distrito ou uma data inicial.")
        descricao = args.nif or args.entidade or f"{args.data_ini} a {args.data_fim or args.data_ini}"
        tarefas.append((criterios, descricao, None))

    estado = Estado(Path(args.estado))
    if args.recomecar:
        estado.dados["feitas"] = []

    feitas = estado.feitas
    pendentes = [t for t in tarefas if not (t[2] and t[2] in feitas)]
    print(
        f"Janelas: {len(tarefas)} ({len(tarefas) - len(pendentes)} já feitas) | "
        f"tipo={args.tipo} | detalhe={'não' if args.sem_detalhe else 'sim'} | "
        f"indexar={'não' if args.sem_indexar else 'sim'}",
        flush=True,
    )
    if args.limite_janelas:
        pendentes = pendentes[: args.limite_janelas]

    if not pendentes:
        print("Nada a fazer.")
        return 0

    from playwright.sync_api import sync_playwright

    total_publicacoes = 0
    processadas = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            args=["--start-maximized"] if not args.headless else None,
        )
        context = browser.new_context(locale="pt-PT", viewport={"width": 1280, "height": 1000})
        page = context.new_page()
        if not args.headless:
            try:
                page.bring_to_front()
                print(f"      janela do browser aberta (PID {os.getpid()}) — procura pela janela do Chromium", flush=True)
            except Exception:
                pass
        try:
            for indice, (criterios, descricao, chave) in enumerate(pendentes, start=1):
                print(f"\n[{indice}/{len(pendentes)}] {descricao}", flush=True)
                inicio = time.monotonic()
                try:
                    publicacoes, total = recolher_uma(
                        page, context, criterios=criterios, descricao=descricao, args=args
                    )
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    if _browser_fechado(exc):
                        print("      o browser foi fechado — a interromper a recolha.", flush=True)
                        break
                    print(f"      ERRO: {exc}", flush=True)
                    logger.debug("detalhe do erro", exc_info=True)
                    continue

                print(f"      {resumo_janela(publicacoes, total)} em {time.monotonic() - inicio:.0f}s", flush=True)
                if publicacoes and not args.sem_indexar:
                    parcial = bool(criterios.get("data_ini") and criterios.get("data_fim"))
                    resultado = indexar(
                        publicacoes,
                        replace_for_nif=criterios.get("nif"),
                        drop_stale=not parcial,
                    )
                    print(
                        f"      indexadas: {resultado.get('indexed_count', 0)}"
                        f" | obsoletas removidas: {resultado.get('deleted_stale', 0)}"
                        f" | erros: {resultado.get('errors', 0)}",
                        flush=True,
                    )
                if chave:
                    estado.marcar(chave, len(publicacoes))
                total_publicacoes += len(publicacoes)
                processadas += 1
        except KeyboardInterrupt:
            print("\nInterrompido — progresso guardado.", flush=True)
        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    estado.guardar()
    print(
        f"\nConcluído: {processadas} tarefa(s), {total_publicacoes} publicações recolhidas.\n"
        f"Totais acumulados: {estado.dados['totais']}\n"
        f"Estado: {estado.path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
