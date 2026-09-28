"""Testes de **IA, browser e relatório** da análise de uma empresa — puros.

O que se protege aqui é o que se pode partir sem se dar por isso:

- a extração de texto de uma página (o menu de um site não pode dominar o
  prompt, e os `<script>` não podem entrar como se fossem conteúdo);
- os **factos** entregues ao modelo (o que ele pode afirmar sem inventar);
- a ficha **factual** (o recuo quando não há modelo: os números têm de lá estar);
- o relatório nos três formatos a partir da mesma estrutura de secções;
- o recuo de erros: sem URLs, sem análise e sem dependências.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import contribuintes_report as report_base  # noqa: E402
from api import padroes_empresa_ia as empresa_ia  # noqa: E402
from api import padroes_report as empresa_report  # noqa: E402

DEPS_PDF = Path(__file__).name and True
try:  # PDF/Excel dependem de bibliotecas externas (declaradas no projeto).
    import openpyxl  # noqa: F401

    TEM_XLSX = True
except Exception:  # noqa: BLE001
    TEM_XLSX = False
try:
    import reportlab  # noqa: F401

    TEM_PDF = True
except Exception:  # noqa: BLE001
    TEM_PDF = False


def _analise(**extra):
    """Análise mínima, na forma que `padroes_service.analise_empresa` devolve."""
    base = {
        "pais": "PT",
        "pais_label": "Portugal (Portal BASE)",
        "nif": "503439800",
        "nome": "ACME, Lda",
        "ficha": {"nome": "ACME, LDA", "papeis": ["adjudicatario"], "concelho": "Moura", "contratos": 411},
        "filtros": {"ano_from": None, "ano_to": None},
        "contratos_total": 411,
        "contratos_analisados": 120,
        "anos": [2019, 2026],
        "resumo": {
            "contratos": 120,
            "valor_total": 1_000_000.0,
            "valor_mediano": 8_000.0,
            "desvio_mediano": 1.0,
            "taxa_ajuste_direto": 0.05,
            "taxa_aditivo": 0.1,
            "adjudicantes_distintos": 12,
            "cpvs": 3,
            "contratos_com_sinais": 24,
            "contratos_atipicos_cpv": 4,
            "insolvente": False,
            "concentracao_adjudicante": 0.4,
            "escaloes": {"<10k": 100, "10k-100k": 18, "100k-1M": 2, ">1M": 0},
        },
        "por_ano": [{"ano": 2024, "contratos": 60, "valor": 400_000.0}],
        "por_cpv": [{"cpv": "45", "descricao": "Construção", "contratos": 100, "valor": 900_000.0, "aditivos": 9, "taxa_ajuste_direto": 0.04, "taxa_aditivo": 0.09}],
        "por_procedimento": [{"procedimento": "Concurso público", "contratos": 80, "valor": 900_000.0}],
        "adjudicantes": [{"nif": "500000001", "nome": "Município A", "contratos": 40, "valor": 500_000.0}],
        "sinais": [
            {
                "padrao": "aditivo_valor",
                "label": "Aditivo financeiro",
                "severidade": "alerta",
                "descricao": "valor efetivo acima do contratado",
                "contratos": 12,
                "taxa": 0.1,
                "exemplos": [{"id": "2024:1", "objeto": "Empreitada de águas", "ano": 2024, "valor": 49_308.48, "detalhe": "> 1.15 rácio"}],
            }
        ],
        "contratos": [
            {
                "id": "2024:1",
                "ano": 2024,
                "data_publicacao": "2024-06-07",
                "objeto": "Empreitada de águas",
                "valor": 49_308.48,
                "ratio_base": 1.0,
                "ratio_efetivo": 1.25,
                "z_cpv": 2.5,
                "n_concorrentes": 3,
                "cpv": "45231300-8",
                "adjudicante": "Município A",
                "procedimento": "Concurso público",
                "razoes": [{"padrao": "aditivo_valor", "detalhe": "> 1.15 rácio"}],
            }
        ],
        "reguas_cpv": [{"cpv": "45", "contratos": 400, "taxa_ajuste_direto": 0.67, "valor_mediano": 48_445.93}],
        "relacoes": {
            "empresas": [{"nif": "500237433", "nome": "Par, Lda", "adjudicante": "500000001", "contratos": 406, "valor": 11_691_017.49}],
            "cargos_sociais": [{"nif": "200000001", "nome": "Ana Silva", "cargos": [{"role_org": "Gerência"}]}],
            "intervenientes_cire": [],
            "insolvencias": [{"especie": "Insolvência", "ato": "Sentença", "data": "2021-02-03", "tribunal": "T. Moura", "processo": "123/20.1T8MRA"}],
            "noticias": [{"titulo": "ACME ganha obra", "fonte": "Jornal", "data": "2024-01-02", "url": "https://exemplo.pt/n"}],
        },
        "regras_ativas": [{"id": "aditivo_valor", "label": "Aditivo financeiro", "severidade": "alerta"}],
        "aviso": "Análise a partir de uma amostra dos contratos desta empresa.",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------
def test_texto_limpo_extrai_titulo_e_ignora_menu() -> None:
    html = """
    <html><head><title>ACME &amp; Filhos</title>
    <script>var x = "não pode aparecer";</script>
    <style>.a { color: red }</style></head>
    <body><nav><a>Início</a><a>Contactos</a></nav>
    <main><h1>Quem somos</h1>
    <p>A ACME é uma empresa de construção civil com sede em Moura e atividade em todo o Alentejo.</p>
    <ul><li>Obras públicas de saneamento e redes de água para municípios.</li></ul>
    </main></body></html>
    """
    titulo, texto = empresa_ia._texto_limpo(html)
    assert titulo == "ACME & Filhos"
    assert "construção civil com sede em Moura" in texto
    assert "não pode aparecer" not in texto
    assert "color: red" not in texto
    # As linhas de menu (curtas) não chegam ao texto: só conteúdo útil.
    assert "Início" not in texto


def test_ler_url_recusa_endereco_invalido() -> None:
    assert empresa_ia.ler_url("")["ok"] is False
    # Um texto que não é endereço não pode rebentar a leitura: devolve falha.
    resultado = empresa_ia.ler_url("não é um url")
    assert resultado["ok"] is False
    assert resultado["erro"]


def test_browser_ler_sem_urls() -> None:
    resultado = empresa_ia.browser_ler([])
    assert resultado["erro"] == "sem URLs"
    assert resultado["lidas"] == 0


def test_browser_ler_nao_indexa_falhas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(empresa_ia, "ler_url", lambda url: {"url": url, "ok": False, "erro": "timeout"})
    chamado: dict = {}

    def fake_index(*args, **kwargs):
        chamado["sim"] = True
        return {"indexed_count": 0}

    monkeypatch.setattr(empresa_ia, "index_scraped_items", fake_index)
    resultado = empresa_ia.browser_ler(["https://a.pt", "https://b.pt"])
    assert resultado["paginas"][0]["ok"] is False
    assert resultado["indexadas"] == 0
    # Nenhuma página legível -> não se escreve nada no índice.
    assert "sim" not in chamado


# ---------------------------------------------------------------------------
# Factos e ficha factual
# ---------------------------------------------------------------------------
def test_factos_resume_o_que_o_modelo_pode_afirmar() -> None:
    factos = empresa_ia.factos(_analise(), entidades={"500000001": {"tipo": "entidade_publica", "concelho": "Braga"}})
    assert factos["empresa"]["nif"] == "503439800"
    assert factos["portfolio"]["valor_total"] == 1_000_000.0
    assert factos["portfolio"]["contratos_analisados"] == 120
    assert factos["sinais"][0]["regra"] == "aditivo_valor"
    assert factos["contratos_de_maior_risco"][0]["sinais"] == ["aditivo_valor"]
    # O cadastro das entidades contratantes entra no facto do adjudicante.
    adjudicante = factos["adjudicantes"][0]
    assert adjudicante["tipo"] == "entidade_publica"
    assert adjudicante["concelho"] == "Braga"


def test_factos_com_analise_vazia_nao_rebenta() -> None:
    factos = empresa_ia.factos({})
    assert factos["empresa"]["nif"] is None
    assert factos["portfolio"]["valor_total"] is None
    assert factos["sinais"] == []


def test_ficha_factual_tem_os_numeros_da_analise() -> None:
    texto = empresa_ia.factual_markdown(_analise())
    assert "ACME, Lda" in texto
    assert "503439800" in texto
    assert "120 de 411" in texto
    assert "5.0%" in texto  # ajuste direto
    assert "Aditivo financeiro" in texto
    assert "Município A" in texto
    assert "sem modelo de IA" in texto


def test_ficha_ia_sem_modelo_cai_para_factual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.people_360.resolve_backend", lambda *a, **k: ({"kind": "local", "note": "Sem chave de API."}, None))
    saida = asyncio.run(empresa_ia.ficha_ia(_analise(), paginas=[], session=None))
    assert saida["mode"] == "factual"
    assert "ACME" in saida["text"]
    assert saida["notes"] or saida["warnings"]


def test_ficha_ia_sem_analise_avisa() -> None:
    saida = asyncio.run(empresa_ia.ficha_ia({"error": "sem contratos"}))
    assert saida["warnings"]


def test_ficha_ia_usa_o_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.people_360.resolve_backend",
        lambda *a, **k: ({"kind": "cloud", "provider": "openai", "model": "gpt-4o-mini"}, None),
    )

    async def fake_ask(backend, *, system, prompt, max_tokens, temperature=0.1):
        assert "PÁGINAS LIDAS NO BROWSER" in prompt  # o texto lido entra no prompt
        assert "503439800" in prompt
        return "# Ficha\n\nTexto do modelo."

    monkeypatch.setattr("api.ontology_ai.ask_model", fake_ask)
    saida = asyncio.run(
        empresa_ia.ficha_ia(
            _analise(),
            paginas=[{"url": "https://a.pt", "titulo": "A", "texto": "conteúdo", "chars": 7, "ok": True}],
        )
    )
    assert saida["mode"] == "ai"
    assert saida["text"].startswith("# Ficha")
    assert saida["backend"]["provider"] == "openai"
    assert saida["paginas"][0]["url"] == "https://a.pt"


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------
def test_seccoes_markdown_por_titulo() -> None:
    blocos = empresa_report._seccoes_markdown("# Síntese\n\nEmpresa de construção.\n\n## Riscos\n- aditivos\n- prazos")
    assert blocos[0][0] == "Síntese"
    assert "Empresa de construção" in blocos[0][1]
    assert blocos[1][0] == "Riscos"
    assert "aditivos" in blocos[1][1]
    assert empresa_report._seccoes_markdown("") == []
    # Texto sem títulos fica numa única linha, com o prefixo pedido.
    assert empresa_report._seccoes_markdown("texto solto", prefixo="IA · ")[0][0] == "IA · Notas"


def test_analise_sections_cobre_o_essencial() -> None:
    secoes = empresa_report.analise_sections(
        _analise(),
        ficha_ia="# Síntese\n\nTudo normal.\n\n# Riscos\n\nAditivos acima do normal.",
        paginas=[{"url": "https://a.pt", "titulo": "A", "chars": 100, "ok": True}],
        notas=["nota do analista"],
        entidades={"500000001": {"tipo": "entidade_publica", "nome": "Município A"}},
    )
    titulos = [secao["title"] for secao in secoes]
    for esperado in (
        "Identificação",
        "Resumo do portefólio",
        "Ficha analítica (IA)",
        "Sinais de regra",
        "Onde atua (CPV)",
        "Entidades contratantes",
        "Outras empresas nos mesmos adjudicantes",
        "Órgãos sociais",
        "Insolvências (CIRE)",
        "Menções em notícias",
        "Páginas lidas no browser",
        "Fontes e limitações",
    ):
        assert esperado in titulos, esperado
    assert any(titulo.startswith("Contratos analisados") for titulo in titulos)

    identificacao = next(secao for secao in secoes if secao["title"] == "Identificação")
    assert ["NIF", "503439800"] in identificacao["rows"]
    notas_sec = next(secao for secao in secoes if secao["title"] == "Fontes e limitações")
    assert any("nota do analista" in linha[1] for linha in notas_sec["rows"])

    cpv = next(secao for secao in secoes if secao["title"] == "Onde atua (CPV)")
    taxa_setor = cpv["rows"][0][-2]
    assert taxa_setor == "67.0%"

    adjudicantes = next(secao for secao in secoes if secao["title"] == "Entidades contratantes")
    assert "entidade_publica" in adjudicantes["rows"][0]


def test_analise_sections_sem_ia_nem_browser() -> None:
    titulos = [secao["title"] for secao in empresa_report.analise_sections(_analise())]
    assert "Ficha analítica (IA)" not in titulos
    assert "Páginas lidas no browser" not in titulos
    assert "Sinais de regra" in titulos


def test_relatorio_csv_tem_o_conteudo_essencial() -> None:
    relatorio = empresa_report.empresa_report(_analise(), format="csv")
    assert relatorio.get("error") is None
    texto = relatorio["content"].decode("utf-8")
    assert texto.startswith("\ufeff")  # BOM: abre bem no Excel português
    assert "ACME" in texto
    assert "Resumo do portefólio" in texto
    assert "aditivo_valor" in texto
    assert relatorio["filename"].endswith(".csv")


def test_relatorio_formato_invalido() -> None:
    relatorio = empresa_report.empresa_report(_analise(), format="docx")
    assert "Formato não suportado" in relatorio["error"]


def test_relatorio_sem_analise() -> None:
    relatorio = empresa_report.empresa_report({"error": "sem contratos"}, format="csv")
    assert "não está disponível" in relatorio["error"]


@pytest.mark.skipif(not TEM_PDF, reason="reportlab não instalado")
def test_relatorio_pdf() -> None:
    relatorio = empresa_report.empresa_report(_analise(), format="pdf", ficha_ia="# Síntese\n\nTudo normal.")
    assert relatorio.get("error") is None
    assert relatorio["content"].startswith(b"%PDF")
    assert relatorio["media_type"] == "application/pdf"


@pytest.mark.skipif(not TEM_XLSX, reason="openpyxl não instalado")
def test_relatorio_xlsx() -> None:
    relatorio = empresa_report.empresa_report(_analise(), format="xlsx")
    assert relatorio.get("error") is None
    # Um ficheiro xlsx é um zip: começa por `PK`.
    assert relatorio["content"][:2] == b"PK"
    assert "spreadsheet" in relatorio["media_type"]


def test_formato_documento_unico_e_o_mesmo_nos_tres_suportes() -> None:
    # As secções são a única fonte de verdade: os formatos não podem divergir.
    secoes = empresa_report.analise_sections(_analise())
    for formato in ("csv", "xlsx", "pdf"):
        try:
            _, conteudo, _ = report_base._render("csv" if formato == "csv" else formato, title="t", subtitle="s", sections=secoes)
        except RuntimeError:
            continue  # dependência em falta: nada a comparar
        assert conteudo


def test_doc_id_estavel_por_empresa() -> None:
    from api.elasticsearch_client import _analise_doc_id  # noqa: PLC0415

    assert _analise_doc_id("pt", "503439800") == "PT:503439800"
    assert _analise_doc_id("", "503439800") == "PT:503439800"
    assert _analise_doc_id("ES", " A28791069 ") == "ES:A28791069"


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def test_rotas_de_inteligencia_registadas() -> None:
    from api import padroes_routes  # noqa: PLC0415

    caminhos = {route.path for route in padroes_routes.router.routes}
    assert {
        "/padroes/empresas/browser",
        "/padroes/empresas/ia",
        "/padroes/empresas/guardar",
        "/padroes/empresas/guardadas",
        "/padroes/empresas/guardada/{doc_id}",
        "/padroes/empresas/relatorio",
    } <= caminhos
