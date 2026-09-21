"""Bateria de 15 perguntas no Hermes para avaliar qualidade pós-correcções."""
import asyncio
import json
import time
from pathlib import Path
from api import hermes_service as hermes

QUESTIONS = [
    # 1-2 Totais globais
    ("global_total_count", "Quantos contratos temos na plataforma?"),
    ("global_total_value", "Qual o valor total dos contratos na plataforma?"),
    # 3-5 Empresas / entidades
    ("entity_edp_contracts", "Quantos contratos temos da EDP?"),
    ("entity_edp_value", "Qual o valor total dos contratos da EDP?"),
    ("entity_lowercase", "contratos da edp"),
    # 6-8 Setores / CPV
    ("sector_health", "Quais as empresas com mais contratos no setor da saúde?"),
    ("cpv_energy", "Quantos contratos de energia existem em Portugal?"),
    ("sector_it", "Quais as empresas com mais contratos de informática?"),
    # 9-10 Mercados / ações
    ("market_edp", "Como fecharam as ações da EDP hoje?"),
    ("market_galp", "Qual a cotação atual da GALP?"),
    # 11-12 Notícias / recolha
    ("news_edp", "Que notícias recentes existem sobre a EDP?"),
    ("news_galp", "Notícias recentes sobre a GALP?"),
    # 13-14 Ontologia / plataforma
    ("ontology", "O que é a ontologia do IQ OS e que objetos tem?"),
    ("platform_facts", "Quais são os dados disponíveis na plataforma IQ OS?"),
    # 15 Comparativo / complexo
    ("compare", "Qual a diferença de contratos entre EDP e GALP?"),
]


def grade(question_id: str, text: str, facts: list) -> dict:
    """Classificação heurística simples baseada em conteúdo."""
    ok = False
    notes = []
    t = text or ""
    if question_id == "global_total_count":
        ok = "2 250 969" in t or "2250969" in t or "2.250.969" in t
        notes.append("esperado ~2.250.969 contratos")
    elif question_id == "global_total_value":
        ok = "156.50 mM" in t or "156,50" in t or "mil milhões" in t
        notes.append("esperado ~156.50 mM€")
    elif question_id in ("entity_edp_contracts", "entity_edp_value", "entity_lowercase"):
        ok = ("EDP" in t or "edp" in t.lower()) and ("4" in t)  # esperado ~4k contratos
        notes.append("esperado EDP com ~4.143/4.177 contratos")
    elif question_id == "sector_health":
        ok = "saúde" in t.lower() or "saude" in t.lower()
        notes.append("esperado filtro setor saúde")
    elif question_id == "cpv_energy":
        ok = "energia" in t.lower() or "contratos" in t.lower()
        notes.append("esperado agregação energia")
    elif question_id == "sector_it":
        ok = "informática" in t.lower() or "informatica" in t.lower() or "tecnologias" in t.lower()
        notes.append("esperado filtro setor IT")
    elif question_id in ("market_edp", "market_galp"):
        ok = ("EDP" in t or "GALP" in t) and ("€" in t or "euro" in t.lower() or "cotação" in t.lower() or "fecho" in t.lower() or "%" in t)
        notes.append("esperado cotação com €")
    elif question_id in ("news_edp", "news_galp"):
        ok = "notícia" in t.lower() or "noticia" in t.lower() or "fonte" in t.lower()
        notes.append("esperado menção a notícias/fontes")
    elif question_id == "ontology":
        ok = "ontologia" in t.lower() and ("objeto" in t.lower() or "classe" in t.lower() or "entidade" in t.lower())
        notes.append("esperado descrição da ontologia")
    elif question_id == "platform_facts":
        ok = "IQ OS" in t or "plataforma" in t.lower()
        notes.append("esperado lista de dados da plataforma")
    elif question_id == "compare":
        ok = "EDP" in t and "GALP" in t and ("contrato" in t.lower() or "diferença" in t.lower())
        notes.append("esperado comparação EDP vs GALP")
    return {"ok": ok, "notes": "; ".join(notes)}


async def main():
    results = []
    for qid, question in QUESTIONS:
        started = time.perf_counter()
        try:
            resp = await hermes.ask(question, depth="rapida")
            elapsed = time.perf_counter() - started
            text = resp.get("text", "")
            facts = resp.get("facts", [])
            g = grade(qid, text, facts)
            results.append({
                "id": qid,
                "question": question,
                "elapsed": round(elapsed, 2),
                "ok": g["ok"],
                "grade_notes": g["notes"],
                "model": resp.get("model"),
                "facts": facts,
                "text_preview": text[:500],
                "error": resp.get("error"),
            })
            print(f"[{len(results):02d}/15] {qid}: {'OK' if g['ok'] else 'FAIL'} ({elapsed:.1f}s)")
        except Exception as e:
            results.append({
                "id": qid,
                "question": question,
                "elapsed": None,
                "ok": False,
                "grade_notes": f"EXCEÇÃO: {e}",
                "model": None,
                "facts": [],
                "text_preview": "",
                "error": str(e),
            })
            print(f"[{len(results):02d}/15] {qid}: ERRO ({e})")

    out = Path("c:/LLMFinance/finance-llm/_hermes_battery_report.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_count = sum(1 for r in results if r["ok"])
    print(f"\nRelatório guardado em {out}")
    print(f"Passaram: {ok_count}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
