"""Rotas da interface (SPA): o que é página indexável, o que é aplicação e o que não existe.

O `index.html` é servido pelo backend para qualquer endereço da interface (ver
`serve_spa_deep_link`, em `api/main.py`), e é aqui que se decide o que fazer com
cada endereço:

* **indexável** — páginas públicas, com título, descrição e canónica próprios
  (`_seo_meta_for_path`) e listadas no `sitemap-app.xml`. São as que interessam ao
  Google.
* **aplicação** — a rota existe, mas o HTML é uma casca que o JavaScript
  preenche (e, na maioria dos casos, atrás de sessão). Sai com `noindex`: a
  documentação do Google é explícita — para tirar páginas do índice usa-se
  `noindex`, não o `robots.txt` (que só impede o rastreio, não a indexação de um
  endereço já conhecido).
* **desconhecida** — não corresponde a rota nenhuma: devolve **404**. Um
  endereço inexistente servido com 200 é um *soft 404* — o Google indexa-o ou
  marca-o como erro, e nos dois casos gasta orçamento de rastreio.

`SEGMENTOS_DA_APP` espelha `chat-ui/src/App.tsx` (`pathForView`). A comparação é
por **primeiro segmento**, e não pela rota inteira, para não duplicar aqui as
~140 rotas da aplicação — e para que um caminho novo dentro de uma área já
conhecida (`/tickers/EDP/grafico`) continue a funcionar. O preço é que também
deixa passar `/tickers/qualquer-coisa` (200 em vez de 404); a alternativa
(fechar ao detalhe) dava 404 a páginas reais que o frontend ganhasse entretanto.

`tests/test_spa_rotas.py` compara esta lista com os caminhos declarados no
frontend e falha se faltar algum: uma rota em falta dava 404 ao recarregar a
página — pior do que deixar passar uma que não existe.
"""
from __future__ import annotations

#: Classificação de um endereço da interface.
INDEXAVEL = "indexavel"
APP = "app"
DESCONHECIDA = "desconhecida"

#: Páginas públicas com meta própria no `<head>` — exactamente as que o
#: `chat-ui/public/sitemap-app.xml` lista. A home (`/`) tem meta próprio no
#: `index.html` do build e por isso também é indexável. O teste confirma que
#: cada uma destas rotas continua a ter título/descrição diferentes do genérico:
#: juntar uma rota aqui **e** ao sitemap é o que a torna pública.
ROTAS_INDEXAVEIS = frozenset(
    {
        "/",
        "/administracao-central",
        "/benchmark",
        "/benchmark/comprador",
        "/benchmark/cruzar",
        "/benchmark/espanha",
        "/benchmark/franca",
        "/benchmark/portugal",
        "/benchmark/vendedor",
        "/companies/search",
        "/contracts/search",
    }
)

#: Primeiro segmento de todas as rotas da aplicação (`chat-ui/src/App.tsx`).
#: Agrupado por área para se ver o que existe sem abrir o frontend.
SEGMENTOS_DA_APP = frozenset(
    {
        # Entrada, conta e administração
        "admin",
        "cli",
        "cms",
        "crm",
        "docs",
        "email",
        "login",
        "permissoes",
        "register",
        "settings",
        "shop",
        # Contratos e entidades
        "adjudicantes",
        "adjudicatarios",
        "companies",
        "contratos-es",
        "contratos-fr",
        "contracts",
        "contracts-list",
        "contribuintes",
        "empresas",
        "empresas-global",
        "empresas-iq",
        "empresas-recolha",
        "empresas-risco",
        "entidade-transparencia",
        "entidades",
        "entities",
        "municipios",
        "partidos",
        "remuneracoes",
        "subvencoes",
        # Mercados e previsões
        "chart",
        "grafico",
        "lorenz",
        "market",
        "mercado",
        "noticias",
        "sentimento",
        "simulador",
        "tickers",
        "trading",
        "world",
        # Análise, investigação e assistentes
        "administracao-central",
        "arquivo",
        "benchmark",
        "benchmarks",
        "browser",
        "chat",
        "cire",
        "citacoes",
        "compare",
        "dashboard",
        "deep-search",
        "descoberta",
        "descoberta-pessoas",
        "documentos",
        "elastic",
        "erc",
        "finder",
        "forecast",
        "gleif",
        "governo",
        "hermes",
        "iframe-pages",
        "import",
        "jarvis",
        "mirofish",
        "office",
        "ontology",
        "osint",
        "padroes",
        "pesquisa",
        "pessoas-iq",
        "racius",
        "rag",
        "report-studio",
        "reports",
        "researcher",
        "rigorbiz",
        "rss",
        "scraper",
        "search",
        "search360",
        "social",
        "societario",
        "visualizador",
        "vortal",
    }
)


def primeiro_segmento(path: str) -> str:
    """Primeiro segmento do caminho (`/tickers/EDP/grafico` → `tickers`)."""
    partes = [parte for parte in (path or "").split("/") if parte]
    return partes[0] if partes else ""


def classificar(path: str) -> str:
    """`INDEXAVEL`, `APP` ou `DESCONHECIDA` para um caminho da interface."""
    normalizado = "/" + "/".join(parte for parte in (path or "").split("/") if parte)
    if normalizado in ROTAS_INDEXAVEIS:
        return INDEXAVEL
    if primeiro_segmento(normalizado) in SEGMENTOS_DA_APP:
        return APP
    return DESCONHECIDA
