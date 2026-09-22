"""Fluxo de escrita dos templates (preview → criar fonte → apagar).

Corre em processo: a validação de sessão exige um utilizador consistente no
Elasticsearch e a conta de QA deste ambiente tem o campo `id` em falta, pelo que
as rotas são chamadas diretamente com um pedido da sessão em falta (as rotas só
usam a sessão para autorização).

Uso:  python _test_scraper_templates_flow.py
Grava o relatório em `_test_scraper_templates_flow.txt` (UTF-8).
"""
from __future__ import annotations

from pathlib import Path

from api import scraper_routes as routes
from api.scraper_routes import TemplateSourcePayload

OUT = Path(__file__).resolve().parent / "_test_scraper_templates_flow.txt"
lines: list[str] = []


def emit(text: str = "") -> None:
    lines.append(text)
    print(text)


def main() -> None:
    galeria = routes.list_templates(None)
    emit(f"galeria: {galeria['total']} templates em {len(galeria['categories'])} categorias")

    emit(f"filtro por categoria: {routes.list_templates('Mercados (internacional)')['total']} template(s)")

    detalhe = routes.get_template("jornal-economico")["item"]
    source = detalhe["source"]
    emit(
        "detalhe jornal-economico: fetcher={0} lista={1!r} campos={2} detail={3!r} max_items={4}".format(
            source["fetcher"],
            source["list"]["selector"],
            len(source["fields"]),
            (source.get("detail") or {}).get("selector"),
            (source.get("detail") or {}).get("max_items"),
        )
    )

    preview = routes.preview_template("quotes-demo", None, limit=2, max_pages=1)
    emit(
        f"preview quotes-demo: ok={preview['ok']} itens={preview['total']} "
        f"exemplo={(preview['items'][0]['title'] if preview['items'] else '')[:70]!r}"
    )

    criada = routes.create_source_from_template(
        "quotes-demo",
        TemplateSourcePayload(name="Quotes (teste do fluxo)", cron="0 5 * * 1"),
        None,
    )["item"]
    emit(
        "fonte criada: id={0} cron={1!r} template_id={2} enabled={3}".format(
            criada["id"],
            criada["schedule"]["cron"],
            criada.get("template_id"),
            criada["enabled"],
        )
    )

    # Uma fonte de um jornal: confirma que o bloco de texto integral viaja até à definição guardada.
    jornal = routes.create_source_from_template("eco", TemplateSourcePayload(name="ECO (teste do fluxo)"), None)["item"]
    emit(
        "fonte do ECO: id={0} detail={1} max_items={2} campos={3}".format(
            jornal["id"],
            (jornal.get("detail") or {}).get("enabled"),
            (jornal.get("detail") or {}).get("max_items"),
            ",".join(f["name"] for f in jornal["fields"]),
        )
    )

    # Estraga um seletor à mão e reaplica o template: os seletores voltam, o nome
    # e a agenda mantêm-se (é o que acontece quando o site muda de marcação).
    from api import scraper_service as scraper

    estragada = {**jornal, "fields": [{**jornal["fields"][0], "selector": ".nao-existe::text"}]}
    scraper.upsert_source({**estragada, "_must_exist": True})
    sincronizada = routes.apply_template_to_source(jornal["id"], None)["item"]
    emit(
        "reaplicar template: nome={0!r} cron={1!r} detalhe={2} primeiro_seletor={3!r}".format(
            sincronizada["name"],
            sincronizada["schedule"]["cron"],
            sincronizada["detail"]["enabled"],
            sincronizada["fields"][0]["selector"],
        )
    )

    sem_template = routes.create_source_from_template(
        "quotes-demo", TemplateSourcePayload(name="Quotes (sem origem de teste)"), None
    )["item"]
    scraper.upsert_source(
        {**sem_template, "template_id": "", "_must_exist": True}
    )
    try:
        routes.apply_template_to_source(sem_template["id"], None)
        emit("fonte sem template: devia ter recusado (422)")
    except Exception as exc:
        emit(f"fonte sem template: recusado como esperado ({type(exc).__name__})")

    for source_id in (criada["id"], jornal["id"], sem_template["id"]):
        emit(f"remover {source_id}: {routes.delete_source(source_id, None)}")

    emit(f"templates após limpeza (fonte de exemplo continua): {routes.list_sources()['total']}")

    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
