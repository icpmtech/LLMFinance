"""Vista de mercado por país (`api/market_view.py`): país resolvido e agrupamento.

As duas regras que a vista promete, e que estes testes fixam:

* **o país tem origem declarada** — Yahoo, sufixo do mercado ou «desconhecido»,
  por esta ordem; nunca um palpite apresentado como facto;
* **uma falha não vira número** — um ticker sem cotação aparece com o motivo, e
  um país sem cotações continua a existir no resultado.

Nada aqui vai à rede (o Yahoo é substituído por uma função fixa) nem toca em
`data/`: a cache de países vive em `tmp_path`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import empresas_perfil  # noqa: E402
from api import market_view as mv  # noqa: E402


@pytest.fixture()
def cache_em_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cache de perfis, cache de resposta e pasta de logótipos isoladas.

    A pasta dos logótipos também é redireccionada: sem isso os testes liam os
    ficheiros reais de `data/empresas/logos/` e o resultado dependia da máquina
    (bastava ter lá a marca de uma empresa para um teste de «sem marca» falhar).
    """
    monkeypatch.setattr(mv, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(mv, "PROFILE_CACHE_PATH", tmp_path / "tickers.json")
    monkeypatch.setattr(mv, "_cache", None)
    monkeypatch.setattr(empresas_perfil, "LOGOS_DIR", tmp_path / "logos")
    return tmp_path / "tickers.json"


def _linha(ticker: str, country: str, *, price: Any = 10.0, change: Any = 1.0, cap: Any = 1e9) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "name": ticker,
        "price": price,
        "change_pct": change,
        "market_cap": cap,
        "currency": "USD",
        "country": country,
        "country_label": mv.country_label(country),
        "country_source": "yahoo",
        "url": f"/tickers/{ticker}",
    }


# ------------------------------------------------------------------ universo
def test_universo_poe_a_carteira_seguida_a_frente_e_sem_repetir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mv.market, "watchlist", lambda: ["NVDA", "AAPL"])
    monkeypatch.setattr(mv, "_extended_tickers", lambda: ["AAPL", "MSFT"])

    assert mv.universe() == ["NVDA", "AAPL", "MSFT"]


def test_universo_ignora_simbolos_invalidos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mv.market, "watchlist", lambda: [])
    monkeypatch.setattr(mv, "_extended_tickers", lambda: ["AAPL", "não é ticker !", ""])

    assert mv.universe() == ["AAPL"]


# ---------------------------------------------------------------------- país
def test_sufixo_do_mercado_da_o_pais() -> None:
    assert mv._suffix_country("EDP.LS") == ("PT", "Portugal")
    assert mv._suffix_country("SAP.DE") == ("DE", "Alemanha")
    assert mv._suffix_country("AAPL") is None
    assert mv._suffix_country("XXX.ZZ") is None


def test_nome_de_pais_do_yahoo_vira_codigo() -> None:
    assert mv._code_from_name("United States") == "US"
    assert mv._code_from_name("portugal") == "PT"
    assert mv._code_from_name("Hong Kong") == "HK"
    assert mv._code_from_name("") == ""
    assert mv._code_from_name("Wakanda") == ""


def test_pais_vem_do_yahoo_quando_existe(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv, "_profile_from_yahoo", lambda ticker: {"country": "PT", "country_label": "Portugal", "name": "EDP, S.A."})

    perfil = mv.resolve_profile("EDP.LS", {})

    assert perfil["country"] == "PT"
    assert perfil["country_source"] == "yahoo"
    assert perfil["name"] == "EDP, S.A."


def test_sem_yahoo_o_sufixo_do_mercado_responde(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv, "_profile_from_yahoo", lambda ticker: None)

    perfil = mv.resolve_profile("EDP.LS", {})

    assert perfil["country"] == "PT"
    assert perfil["country_source"] == "mercado"


def test_sem_yahoo_nem_sufixo_o_pais_fica_desconhecido(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv, "_profile_from_yahoo", lambda ticker: None)

    perfil = mv.resolve_profile("AAPL", {})

    assert perfil["country"] == mv.UNKNOWN_CODE
    assert perfil["country_source"] == "desconhecido"


def test_pais_gravado_em_cache_nao_volta_a_pedir_ao_yahoo(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    """Uma entrada **completa** responde sem tocar na rede."""
    chamadas: List[str] = []

    def yahoo(ticker: str) -> Dict[str, Any]:
        chamadas.append(ticker)
        return {"country": "US", "country_label": "Estados Unidos", "name": "Apple Inc."}

    monkeypatch.setattr(mv, "_profile_from_yahoo", yahoo)

    perfil = mv.resolve_profile(
        "AAPL",
        {
            "AAPL": {
                "country": "US",
                "country_label": "Estados Unidos",
                "country_source": "yahoo",
                "name": "Apple Inc.",
                "site": "https://www.apple.com",
                "site_verificado": True,
            }
        },
    )

    assert perfil["country"] == "US"
    assert perfil["site"] == "https://www.apple.com"
    assert chamadas == []


# ------------------------------------------------------------------ agrupar
def test_agrupa_por_pais_e_ordena_pelos_maiores() -> None:
    resultado = mv.group_by_country(
        [
            _linha("EDP.LS", "PT"),
            _linha("AAPL", "US"),
            _linha("MSFT", "US"),
            _linha("BTC-USD", mv.UNKNOWN_CODE),
        ]
    )

    assert [grupo["country"] for grupo in resultado["countries"]] == ["US", "PT", mv.UNKNOWN_CODE]


def test_o_grupo_dos_desconhecidos_fica_sempre_no_fim() -> None:
    resultado = mv.group_by_country([_linha("BTC-USD", mv.UNKNOWN_CODE), _linha("AAPL", "US")])

    assert resultado["countries"][-1]["unknown"] is True


def test_agregados_do_pais_contam_o_que_foi_lido() -> None:
    resultado = mv.group_by_country(
        [
            _linha("A", "US", price=10.0, change=2.0, cap=100.0),
            _linha("B", "US", price=10.0, change=-1.0, cap=300.0),
            _linha("C", "US", price=10.0, change=0.0, cap=None),
            _linha("D", "US", price=None, change=None, cap=None),
        ]
    )

    stats = resultado["countries"][0]["stats"]

    assert stats["tickers"] == 4
    assert stats["quoted"] == 3
    assert stats["without_quote"] == 1
    assert stats["advancers"] == 1
    assert stats["decliners"] == 1
    assert stats["flat"] == 1
    assert stats["average_change_pct"] == pytest.approx(1 / 3, abs=1e-4)
    assert stats["market_cap"] == 400.0
    assert stats["market_cap_count"] == 2


def test_melhor_e_pior_do_pais_ignoram_quem_nao_tem_cotacao() -> None:
    resultado = mv.group_by_country(
        [
            _linha("A", "US", change=2.0),
            _linha("B", "US", change=-3.0),
            _linha("C", "US", price=None, change=None),
        ]
    )

    grupo = resultado["countries"][0]

    assert grupo["best"]["ticker"] == "A"
    assert grupo["worst"]["ticker"] == "B"


def test_pais_com_um_so_ticker_nao_repete_melhor_e_pior() -> None:
    """Com um único cotado, «melhor» e «pior» seriam o mesmo número duas vezes."""
    resultado = mv.group_by_country([_linha("ACN", "IE", change=4.8)])

    grupo = resultado["countries"][0]

    assert grupo["best"] is None
    assert grupo["worst"] is None


def test_ressalva_da_vista_e_sobre_a_fonte_dos_precos() -> None:
    """Não se reutiliza a ressalva do sentimento (essa é sobre correlação)."""
    assert mv.CAVEAT != mv.market.PRICE_CAVEAT
    assert "Yahoo Finance" in mv.CAVEAT


def test_leitura_curta_da_variacao_media() -> None:
    assert mv._rank_summary(None)["id"] == "sem-cotacao"
    assert mv._rank_summary(1.5)["id"] == "em-alta"
    assert mv._rank_summary(-1.5)["id"] == "em-baixa"
    assert mv._rank_summary(0.1)["id"] == "estavel"


def test_sem_cotacao_a_linha_explica_porque() -> None:
    linha = {"ticker": "BPI.LS", "price": None}

    assert "Sem cotação" in str(mv._erro(linha))
    assert mv._erro({"ticker": "A", "price": 1.0}) is None
    assert mv._erro({"ticker": "A", "price": None, "error": "símbolo descontinuado"}) == "símbolo descontinuado"


# ----------------------------------------------------------------- formatação
def test_capitalizacao_em_forma_curta() -> None:
    assert mv._market_cap(4.9e12) == "4.90 t"
    assert mv._market_cap(1.7e10) == "17.00 b"
    assert mv._market_cap(729.94e6) == "729.94 m"
    assert mv._market_cap(1234) == "1.23 k"
    assert mv._market_cap(0) is None
    assert mv._market_cap(None) is None


def test_preco_leva_o_simbolo_da_moeda() -> None:
    assert mv._price(4.83, "EUR") == "€ 4.83"
    assert mv._price(342.4, "USD") == "$ 342.40"
    assert mv._price(None, "USD") is None


def test_variacao_leva_sinal() -> None:
    assert mv._change(1.5) == "+1.50 %"
    assert mv._change(-1.5) == "-1.50 %"
    assert mv._change(0) == "0.00 %"
    assert mv._change(None) is None


# ------------------------------------------------------------- leitura completa
def test_leitura_completa_sem_rede(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    """`by_country` de ponta a ponta, com o Yahoo substituído."""
    monkeypatch.setattr(mv.market, "watchlist", lambda: ["AAPL", "EDP.LS"])
    monkeypatch.setattr(mv, "_extended_tickers", lambda: ["BPI.LS"])

    def cotacao(ticker: str) -> Dict[str, Any]:
        if ticker == "BPI.LS":
            return {"ticker": ticker, "price": None, "market_cap": None}
        return {"ticker": ticker, "price": 10.0, "change_pct": 1.5, "market_cap": 1e9, "currency": "USD"}

    monkeypatch.setattr(mv.market, "live_quote", cotacao)
    monkeypatch.setattr(
        mv,
        "_profile_from_yahoo",
        lambda ticker: {"country": "US", "country_label": "Estados Unidos", "name": f"{ticker} Inc."} if ticker == "AAPL" else None,
    )
    resultado = mv.by_country(limit=10, workers=2)

    assert resultado["source"] == mv.market.LIVE_SOURCE
    assert resultado["universe"]["requested"] == 3
    assert resultado["universe"]["errors"][0]["ticker"] == "BPI.LS"
    por_codigo = {grupo["country"]: grupo for grupo in resultado["countries"]}
    assert set(por_codigo) == {"US", "PT"}
    assert por_codigo["US"]["tickers"][0]["name"] == "AAPL Inc."
    # Os dois tickers `.LS` caem em Portugal pelo sufixo (o Yahoo não respondeu
    # por eles) e o que ficou por cotar continua a contar para o país.
    assert por_codigo["PT"]["stats"]["tickers"] == 2
    assert por_codigo["PT"]["stats"]["without_quote"] == 1
    assert {row["country_source"] for row in por_codigo["PT"]["tickers"]} == {"mercado"}
    # A leitura gravou o país aprendido para não voltar a pedi-lo.
    gravado = json.loads(cache_em_tmp.read_text(encoding="utf-8"))
    assert gravado["AAPL"]["country"] == "US"


def test_resposta_fica_em_cache_e_o_refresh_ignora_a(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    chamadas: List[str] = []

    def cotacao(ticker: str) -> Dict[str, Any]:
        chamadas.append(ticker)
        return {"ticker": ticker, "price": 10.0, "change_pct": 0.0, "currency": "EUR"}

    monkeypatch.setattr(mv.market, "watchlist", lambda: ["EDP.LS"])
    monkeypatch.setattr(mv, "_extended_tickers", lambda: [])
    monkeypatch.setattr(mv.market, "live_quote", cotacao)
    monkeypatch.setattr(mv, "_profile_from_yahoo", lambda ticker: None)

    mv.by_country(limit=10)
    mv.by_country(limit=10, refresh=False)
    assert chamadas == ["EDP.LS"]

    mv.by_country(limit=10, refresh=True)
    assert chamadas == ["EDP.LS", "EDP.LS"]


def test_limite_corta_o_universo_e_diz_quanto(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv.market, "watchlist", lambda: [])
    monkeypatch.setattr(mv, "_extended_tickers", lambda: ["AAA", "BBB", "CCC", "DDD"])
    monkeypatch.setattr(mv.market, "live_quote", lambda ticker: {"ticker": ticker, "price": 1.0, "change_pct": 0.0})
    monkeypatch.setattr(mv, "_profile_from_yahoo", lambda ticker: None)

    resultado = mv.by_country(limit=2)

    assert resultado["universe"]["requested"] == 2
    assert resultado["universe"]["available"] == 4
    assert resultado["universe"]["truncated"] == 2


def test_sem_universo_usa_os_tickers_predefinidos(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv.market, "watchlist", lambda: [])
    monkeypatch.setattr(mv, "_extended_tickers", lambda: [])
    monkeypatch.setattr(mv.market, "live_quote", lambda ticker: {"ticker": ticker, "price": 1.0, "change_pct": 0.0})
    monkeypatch.setattr(mv, "_profile_from_yahoo", lambda ticker: None)

    resultado = mv.by_country(limit=3)

    assert resultado["universe"]["requested"] == 3
    assert {row["ticker"] for grupo in resultado["countries"] for row in grupo["tickers"]} <= set(mv.market.LIVE_DEFAULT_TICKERS)


# ---------------------------------------------------------------------- marcas
def test_ficheiro_da_chave_troca_o_que_o_disco_nao_aceita() -> None:
    """A chave lógica tem `:`, o nome do ficheiro não pode ter.

    No Windows `n:edp.png` não é um ficheiro na pasta: o `:` é lido como letra de
    unidade e a escrita falha (`FileNotFoundError`). Sem esta conversão, nenhum
    logótipo encontrado **por nome** chegava ao disco.
    """
    from api import empresas_perfil

    assert empresas_perfil.ficheiro_da_chave("n:apple inc") == "n-apple inc"
    assert empresas_perfil.ficheiro_da_chave("n:edp s a") == "n-edp s a"
    # As chaves de NIF são só dígitos: os logótipos já guardados continuam iguais.
    assert empresas_perfil.ficheiro_da_chave("500023875") == "500023875"


def test_perfil_sem_pais_mas_com_site_fica_marcado(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    """Uma cripto não tem país; isso não pode impedir o site de ser guardado."""
    monkeypatch.setattr(
        mv,
        "_profile_from_yahoo",
        lambda ticker: {"country": None, "country_label": None, "name": "Bitcoin USD", "site": "https://bitcoin.org/"},
    )

    perfil = mv.resolve_profile("BTC-USD", {})

    assert perfil["site"] == "https://bitcoin.org/"
    assert perfil["name"] == "Bitcoin USD"
    assert perfil["site_verificado"] is True
    assert perfil["country"] == mv.UNKNOWN_CODE


def test_perfil_completo_em_cache_nao_volta_a_pedir_o_site(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    chamadas: List[str] = []

    def yahoo(ticker: str) -> Dict[str, Any]:
        chamadas.append(ticker)
        return {}

    monkeypatch.setattr(mv, "_profile_from_yahoo", yahoo)

    perfil = mv.resolve_profile("AAPL", {"AAPL": {"country": "US", "country_label": "Estados Unidos", "site_verificado": True, "site": "https://www.apple.com"}})

    assert perfil["site"] == "https://www.apple.com"
    assert chamadas == []


def test_perfil_antigo_sem_site_volta_a_ser_perguntado(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    """Entradas gravadas antes de o site ser lido não podem ficar sem marca."""
    chamadas: List[str] = []

    def yahoo(ticker: str) -> Dict[str, Any]:
        chamadas.append(ticker)
        return {"country": "US", "country_label": "Estados Unidos", "name": "Apple Inc.", "site": "https://www.apple.com"}

    monkeypatch.setattr(mv, "_profile_from_yahoo", yahoo)

    perfil = mv.resolve_profile("AAPL", {"AAPL": {"country": "US", "country_label": "Estados Unidos", "name": "Apple Inc."}})

    assert chamadas == ["AAPL"]
    assert perfil["site"] == "https://www.apple.com"
    assert perfil["site_verificado"] is True


def test_sem_site_nao_se_anuncia_logotipo(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    """Um índice não tem marca a procurar: não se pede uma imagem que só falha."""
    linha = _linha("^GSPC", "US")
    linha["name"] = "S&P 500"
    linha["site"] = None

    assert mv._logo_url("^GSPC", linha, {}) is None


def test_com_site_anuncia_o_logotipo(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    linha = _linha("AAPL", "US")
    linha["name"] = "Apple Inc."
    linha["site"] = "https://www.apple.com"

    assert mv._logo_url("AAPL", linha, {}) == "/market/logo/AAPL"


def test_tentativa_recente_nao_volta_a_ser_anunciada(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    """Um site que não rendeu marca não é visitado a cada visita à página."""
    linha = _linha("AAPL", "US")
    linha["name"] = "Apple Inc."
    linha["site"] = "https://www.apple.com"
    chave = mv._logo_key("AAPL", linha)

    recente = {"logo_chave": chave, "logo_verificado_em": mv._now()}
    assert mv._logo_url("AAPL", linha, recente) is None

    # Nome diferente: a tentativa anterior era outra procura e não conta.
    outra = {"logo_chave": "n:outra empresa", "logo_verificado_em": mv._now()}
    assert mv._logo_url("AAPL", linha, outra) == "/market/logo/AAPL"


def test_marca_vencida_permite_nova_tentativa() -> None:
    from datetime import datetime, timedelta, timezone

    antigo = (datetime.now(timezone.utc) - timedelta(days=mv.LOGO_RETRY_DAYS + 1)).isoformat()

    assert mv._logo_vencido(antigo) is True
    assert mv._logo_vencido(None) is True
    assert mv._logo_vencido("não é uma data") is True
    assert mv._logo_vencido(mv._now()) is False


def test_logo_sem_site_conhecido_nao_vai_a_rede(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv, "PROFILE_CACHE_PATH", cache_em_tmp)
    mv._write_profile_cache({"^GSPC": {"country": "US", "country_label": "Estados Unidos", "name": "S&P 500", "site_verificado": True}})

    assert mv.logo("^GSPC") is None


def test_logo_reutiliza_o_ficheiro_guardado(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    """Com marca já guardada, a rota não volta a sair para a internet."""
    monkeypatch.setattr(mv, "PROFILE_CACHE_PATH", cache_em_tmp)
    mv._write_profile_cache({"AAPL": {"country": "US", "country_label": "Estados Unidos", "name": "Apple Inc.", "site": "https://www.apple.com", "site_verificado": True}})

    empresas_perfil.LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    (empresas_perfil.LOGOS_DIR / f"{empresas_perfil.ficheiro_da_chave('n:apple inc')}.png").write_bytes(b"x" * 200)

    def nao_chamar(*args: Any, **kwargs: Any) -> Dict[str, Any]:  # pragma: no cover - não deve ser chamado
        raise AssertionError("não devia ir buscar a marca outra vez")

    monkeypatch.setattr(empresas_perfil, "obter_logo_do_site", nao_chamar)

    encontrado = mv.logo("AAPL")

    assert encontrado is not None
    assert encontrado[0].name == "n-apple inc.png"
    assert encontrado[1] == "image/png"


def test_meta_descreve_a_marca_sem_a_ir_buscar(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv, "universe", lambda: ["AAPL"])

    dados = mv.meta()

    assert dados["logo"]["rota"] == "/market/logo/{ticker}"
    assert dados["logo"]["retry_days"] == mv.LOGO_RETRY_DAYS


def test_meta_descreve_a_fonte_sem_a_ir_buscar(monkeypatch: pytest.MonkeyPatch, cache_em_tmp: Path) -> None:
    monkeypatch.setattr(mv, "universe", lambda: ["AAPL", "MSFT"])

    dados = mv.meta()

    assert dados["source"] == mv.market.LIVE_SOURCE
    assert dados["universe"] == 2
    assert dados["max_limit"] == mv.MAX_TICKERS
    assert set(dados["country_sources"]) == {"yahoo", "mercado", "desconhecido"}
