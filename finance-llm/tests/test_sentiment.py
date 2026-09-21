"""Testes da análise de sentimento (`api/sentiment_service.py`).

Correr com:

    c:\\LLMFinance\\.venv\\Scripts\\python.exe -m pytest tests/test_sentiment.py -q

Os casos de referência são o contrato do motor: se um deles mudar de leitura, a
alteração tem de ser justificada (não é «o teste que está mal»). Servem para
impedir regressões como a conjunção «mas» a contar como «más».
"""
from __future__ import annotations

import pytest

from api import sentiment_service as sentiment


# --------------------------------------------------------- casos de referência
@pytest.mark.parametrize(
    "text, expected_label, min_polarity, max_polarity",
    [
        ("Os resultados foram excelentes e o crescimento superou as expectativas.", "positivo", 0.5, 1.0),
        ("A empresa falhou os objetivos e registou prejuízos elevados.", "negativo", -1.0, -0.5),
        ("A reunião decorreu na terça-feira na sede da empresa, em Lisboa.", "neutro", -0.15, 0.15),
        ("Os lucros e as vitórias superaram as perdas e os problemas.", "positivo", 0.15, 1.0),
        ("O mercado está em crise e há incerteza.", "negativo", -1.0, -0.15),
    ],
)
def test_reference_cases(text: str, expected_label: str, min_polarity: float, max_polarity: float) -> None:
    result = sentiment.analyze_text(text)
    assert min_polarity <= result["polarity"] <= max_polarity, result
    assert result["label"] == expected_label, result


def test_negation_flips_sign() -> None:
    bom = sentiment.analyze_text("O produto é bom.")
    mau = sentiment.analyze_text("O produto não é bom.")
    assert bom["polarity"] > 0
    assert mau["polarity"] < 0


def test_intensifier_increases_magnitude() -> None:
    simples = sentiment.analyze_text("O crescimento foi forte.")
    intenso = sentiment.analyze_text("O crescimento foi muito forte.")
    assert intenso["polarity"] > simples["polarity"]


def test_conjunction_mas_is_not_negative() -> None:
    """Regressão: «mas» (conjunção) não pode ser pontuada como «más»."""
    result = sentiment.analyze_text("A empresa cresceu, mas os custos subiram.")
    assert not any(item["term"] == "mas" for item in result["matched"]), result["matched"]


def test_domain_phrase_is_neutralised() -> None:
    """«Acordo quadro» é um instrumento de contratação pública, não um elogio."""
    result = sentiment.analyze_text(
        "Aquisição de serviços de manutenção ao abrigo do Acordo Quadro celebrado com a entidade."
    )
    assert result["polarity"] == 0.0, result
    assert "acordo quadro" in result["neutralised"], result


def test_plural_forms_are_recognised() -> None:
    plural = sentiment.analyze_text("Grandes lucros e vitórias para a empresa.")
    assert plural["hits"] >= 2, plural
    assert plural["polarity"] > 0


# ----------------------------------------------------------------- agregação
def test_aggregation_reports_coverage_and_aspects() -> None:
    documents = [
        {"id": "1", "title": "A", "source": "Fonte A", "text": "Excelentes resultados e crescimento forte.", "tags": ["economia"]},
        {"id": "2", "title": "B", "source": "Fonte A", "text": "Prejuízos elevados e crise no mercado.", "tags": ["economia"]},
        {"id": "3", "title": "C", "source": "Fonte B", "text": "Reunião na terça-feira às 10h em Lisboa.", "tags": ["nacional"]},
    ]
    analysis = sentiment.analyze_documents(documents, engine="lexicon")
    summary = analysis["summary"]
    assert summary["documents"] == 3
    assert summary["documents_with_signal"] == 2
    assert summary["coverage"] == pytest.approx(2 / 3, abs=0.01)
    # A leitura usa apenas os documentos com sinal (o factual não dilui a média).
    assert summary["label"] in {"positivo", "negativo"}
    assert any(row["tag"] == "economia" for row in analysis["by_tag"])
    assert analysis["by_source"][0]["documents"] >= 1


def test_short_corpus_does_not_crash_without_terms() -> None:
    """Regressão: corpus sem termos do léxico (firmas/marcas) tem de devolver neutro."""
    documents = [{"id": "1", "title": "EMPRESA XPTO LDA", "source": "Firmas", "text": "EMPRESA XPTO LDA Almada Deferido"}]
    analysis = sentiment.analyze_documents(documents, engine="lexicon")
    assert analysis["summary"]["documents"] == 1
    assert analysis["summary"]["coverage"] == 0
    assert analysis["summary"]["label"] == "neutro"
    # Sem termos de sentimento não há tabela de termos (as palavras-chave TF-IDF
    # são vocabulário do corpus, não sentimento, e podem existir).
    assert analysis["rows"][0]["hits"] == 0
    assert analysis["terms"] == []


def test_markdown_and_csv_are_generated() -> None:
    analysis = sentiment.analyze_documents(
        [{"id": "1", "title": "A", "source": "Fonte", "text": "Excelentes resultados.", "tags": ["economia"]}],
        engine="lexicon",
    )
    markdown = sentiment.build_markdown(analysis, title="Teste", term="teste")
    assert "## Indicadores" in markdown
    assert "Cobertura" in markdown
    csv = sentiment.to_csv(analysis)
    assert csv.startswith("id,title,source,date,polarity,label")


def test_sources_catalog_covers_the_system() -> None:
    """Todas as fontes do sistema têm de estar no catálogo analisável."""
    ids = {entry["id"] for entry in sentiment.ORIGINS}
    assert {
        "scraped",
        "news",
        "contracts",
        "firmas",
        "trademarks",
        "rag",
        "dossier",
        "office",
        "crm",
        "email",
        "text",
    } <= ids
    # As fontes privadas têm de exigir sessão.
    private = {entry["id"] for entry in sentiment.ORIGINS if entry.get("session")}
    assert private == {"crm", "email"}
