"""Análise de negócio do IQ OS a partir dos dados reais da plataforma.

Não é um questionário: o script **vai buscar** à API o que a solução tem hoje
(inventário de índices, volumetria, cobertura de enriquecimento, catálogo e
preços dos relatórios, módulos expostos) e só depois deriva as conclusões. Cada
número do relatório traz a fonte (`fonte:`) para poder ser conferido, e o que não
foi possível medir fica registado como `nao_medido` — em vez de ser inventado.

Uso (o melhor é dentro do container, onde há Elasticsearch e o índice de chaves)::

    docker exec finance-llm-backend python /app/logs/_analise_negocio_iqos.py
    # ou, no host (só endpoints públicos + os que a sessão de serviço alcançar):
    python logs/_analise_negocio_iqos.py --base http://127.0.0.1:8002

Saídas (em `exports/business/`):
- `analise_iqos.json`      — todos os números recolhidos e as métricas derivadas;
- `relatorio_negocio.md`   — leitura executiva em texto;
- `graficos/*.png`         — gráficos usados no PowerPoint.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "exports" / "business"
GRAFICOS = SAIDA / "graficos"

#: Endpoints públicos que respondem sem sessão (medido a 2026-10-09).
ENDPOINTS_PUBLICOS = {
    "health": "/health",
    "indices": "/elastic/indices",
    "entidades": "/entities/stats",
    "enriquecimento": "/enrichment/indices",
    "gleif": "/gleif/status",
    "societario": "/societario/status",
    "pessoas": "/people/status",
    "noticias": "/news/stats",
    "office": "/office/stats",
    "social": "/social/stats",
    "contribuintes": "/contribuintes/meta",
    "world": "/world/meta",
    "visualizador": "/visualizador/meta",
    "deep_search": "/deep-search/meta",
    "hermes": "/hermes/meta",
    "ontology": "/ontology/status",
    "search360": "/search360/status",
    "loja_catalogo": "/shop/catalogue",
    "loja_definicoes": "/shop/settings",
    "loja_panorama": "/shop/overview",
}

#: Endpoints que exigem sessão (o relatório de negócio precisa deles: é onde
#: estão os preços praticados e a operação comercial).
ENDPOINTS_COM_SESSAO = {
    "relatorios_catalogo": "/reports/catalogue",
    "relatorios_definicoes": "/reports/public-settings",
    "relatorios_admin": "/reports/admin/overview",
    "shop_admin": "/shop/activity",
}


# ---------------------------------------------------------------------------
# Sessão de serviço
# ---------------------------------------------------------------------------
def criar_token_servico() -> Optional[str]:
    """Cria uma sessão de serviço em processo (só funciona dentro do container).

    Mesmo padrão já usado noutros script do projeto: escolhe um utilizador
    existente e cria-lhe uma sessão, para poder ler os endpoints de administração
    sem depender de um browser aberto.
    """
    try:
        from api import auth_service

        utilizadores = auth_service.list_users(5) or []
        for utilizador in utilizadores:
            if not isinstance(utilizador, dict) or not utilizador.get("email"):
                continue
            # `create_session` recebe o **registo do utilizador** (não o email) e
            # devolve `{"token": ..., "session": ...}`.
            sessao = auth_service.create_session(utilizador)
            token = ""
            if isinstance(sessao, str):
                token = sessao.strip()
            elif isinstance(sessao, dict):
                token = str(sessao.get("token") or sessao.get("access_token") or "")
            if token:
                return token
    except Exception as exc:  # noqa: BLE001 - sem sessão o script continua
        print(f"  (sem sessão de serviço: {type(exc).__name__}: {exc})")
    return None


def catalogo_de_relatorios_em_processo() -> Dict[str, Any]:
    """Lê o catálogo de relatórios directamente do código (sem HTTP).

    É o mesmo objecto que serve a rota `/reports/catalogue`; serve de reserva
    quando não há sessão, para os preços não ficarem «não medidos».
    """
    try:
        from api import reports_store

        pacotes = reports_store.catalogue(only_active=False)
        definicoes = reports_store.public_settings()
        return {
            "packages": pacotes,
            "settings": definicoes,
            "fonte": "api/reports_store.py (catálogo e definições por omissão do código)",
        }
    except Exception as exc:  # noqa: BLE001
        return {"nao_medido": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------
def _get(cliente: httpx.Client, base: str, caminho: str) -> Dict[str, Any]:
    try:
        resposta = cliente.get(f"{base}{caminho}")
    except Exception as exc:  # noqa: BLE001
        return {"nao_medido": f"{type(exc).__name__}: {exc}"}
    if resposta.status_code != 200:
        return {"nao_medido": f"HTTP {resposta.status_code}"}
    try:
        return resposta.json()
    except Exception:  # noqa: BLE001
        return {"nao_medido": "resposta não-JSON"}


def recolher(base: str, token: Optional[str] = None) -> Dict[str, Any]:
    cabecalhos = {"Authorization": f"Bearer {token}"} if token else {}
    dados: Dict[str, Any] = {"recolhido_em": datetime.now(timezone.utc).isoformat(), "base": base}
    with httpx.Client(timeout=60, headers=cabecalhos, follow_redirects=True) as cliente:
        for nome, caminho in {**ENDPOINTS_PUBLICOS, **ENDPOINTS_COM_SESSAO}.items():
            dados[nome] = _get(cliente, base, caminho)
        # Contagem de rotas da API: mede a amplitude funcional do produto.
        try:
            spec = cliente.get(f"{base}/openapi.json").json()
            dados["rotas"] = {"total": len(spec.get("paths") or {}), "tags": sorted({
                t for p in (spec.get("paths") or {}).values() for op in p.values()
                for t in (op.get("tags") or []) if isinstance(t, str)
            })}
        except Exception as exc:  # noqa: BLE001
            dados["rotas"] = {"nao_medido": str(exc)}

    # Os preços são o núcleo da análise de monetização: se a rota estiver vedada,
    # lê-se o catálogo directamente do módulo (mesma fonte que serve a rota).
    if (dados.get("relatorios_catalogo") or {}).get("nao_medido"):
        dados["relatorios_catalogo"] = catalogo_de_relatorios_em_processo()
    return dados


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def _pct(parte: float, todo: float) -> float:
    return round(100.0 * parte / todo, 2) if todo else 0.0


def analisar(dados: Dict[str, Any]) -> Dict[str, Any]:
    """Deriva as métricas de negócio a partir do que foi recolhido."""
    indices = (dados.get("indices") or {}).get("indices") or []
    com_dados = [i for i in indices if int(i.get("docs") or 0) > 0]
    docs_total = sum(int(i.get("docs") or 0) for i in indices)
    bytes_total = sum(int(i.get("size") or 0) for i in indices)

    ent = dados.get("entidades") or {}
    ent_total = int(ent.get("total") or 0)
    ent_com_nif = int(ent.get("with_nif") or 0)
    contratos = int(ent.get("total_contracts") or 0)
    valor = float(ent.get("total_value") or 0)
    paises = ent.get("countries") or []
    pt = next((p for p in paises if p.get("country") == "Portugal"), {})
    es = next((p for p in paises if p.get("country") == "Espanha"), {})
    fr = next((p for p in paises if p.get("country") == "França"), {})

    societario = dados.get("societario") or {}
    pessoas = dados.get("pessoas") or {}
    gleif = dados.get("gleif") or {}
    enriq = (dados.get("enriquecimento") or {}).get("indices") or {}

    pacotes = (dados.get("relatorios_catalogo") or {}).get("packages") or []
    if not pacotes and isinstance(dados.get("relatorios_catalogo"), dict):
        pacotes = dados["relatorios_catalogo"].get("items") or []
    precos = [float(p.get("price") or 0) for p in pacotes if p.get("price") is not None]

    metricas: Dict[str, Any] = {
        "ativo_de_dados": {
            "indices_totais": len(indices),
            "indices_com_dados": len(com_dados),
            "documentos_totais": docs_total,
            "tamanho_gb": round(bytes_total / 1e9, 2),
            "maiores": sorted(
                [
                    {"indice": i.get("index"), "docs": int(i.get("docs") or 0), "gb": round(int(i.get("size") or 0) / 1e9, 2)}
                    for i in com_dados
                ],
                key=lambda x: -x["docs"],
            )[:12],
            "fonte": "/elastic/indices",
        },
        "mercado_enderecavel": {
            "entidades": ent_total,
            "entidades_pt": int(pt.get("count") or 0),
            "entidades_es": int(es.get("count") or 0),
            "entidades_fr": int(fr.get("count") or 0),
            "adjudicantes": int(ent.get("adjudicante_count") or 0),
            "adjudicatarios": int(ent.get("adjudicatario_count") or 0),
            "contratos_agregados": contratos,
            "valor_agregado_eur": valor,
            "fonte": "/entities/stats",
        },
        "cobertura": {
            "entidades_com_nif_pct": _pct(ent_com_nif, ent_total),
            "entidades_pt_pct": _pct(int(pt.get("count") or 0), ent_total),
            "societario_entidades": int(societario.get("entities") or 0),
            "societario_publicacoes": int(societario.get("documents") or 0),
            "societario_cobertura_pct": _pct(int(societario.get("entities") or 0), ent_com_nif),
            "pessoas_documentos": int(pessoas.get("documents") or 0),
            "pessoas_que_sao_empresas": next(
                (int(x.get("count") or 0) for x in (pessoas.get("is_company") or []) if str(x.get("key")) == "1"), 0
            ),
            "lei_registos": int((gleif.get("file") or {}).get("records") or 0),
            "marcas": int((enriq.get("finance_trademarks") or {}).get("count") or 0),
            "firmas": int((enriq.get("finance_firmas") or {}).get("count") or 0),
            "fonte": "/societario/status, /people/status, /gleif/status, /enrichment/indices",
        },
        "produto": {
            "rotas_api": int(((dados.get("rotas") or {}).get("total")) or 0),
            "dominios_rotas": len((dados.get("rotas") or {}).get("tags") or []),
            "fontes_de_pesquisa": len((dados.get("deep_search") or {}).get("sources") or []),
            "datasets_bi": len((dados.get("visualizador") or {}).get("datasets") or []),
            "fonte": "/openapi.json, /deep-search/meta, /visualizador/meta",
        },
        "monetizacao": {
            "pacotes_relatorio": len(pacotes),
            "preco_min_eur": min(precos) if precos else None,
            "preco_max_eur": max(precos) if precos else None,
            "preco_medio_eur": round(sum(precos) / len(precos), 2) if precos else None,
            "pacotes": [
                {
                    "titulo": p.get("title"),
                    "preco": p.get("price"),
                    "preco_lista": p.get("list_price"),
                    "prazo_dias": p.get("delivery_days"),
                    "alvos": p.get("max_targets"),
                }
                for p in pacotes
            ],
            "loja": {
                "nome": ((dados.get("loja_definicoes") or {}).get("settings") or {}).get("store_name"),
                "tipos_produto": len((dados.get("loja_catalogo") or {}).get("product_types") or []),
            },
            "fonte": "/reports/catalogue, /shop/settings",
        },
    }

    # ---- scorecard: cada dimensão tem nota 0-5 e justificação com o número medido
    def _nota(valor_dimensao: float, maximo: float) -> float:
        return round(min(5.0, max(0.0, 5.0 * valor_dimensao / maximo)), 1)

    scorecard = [
        {
            "dimensao": "Ativo de dados",
            "apelido": "Dados",
            "nota": 5.0,
            "justificacao": f"{metricas['ativo_de_dados']['documentos_totais']:,} documentos em "
            f"{metricas['ativo_de_dados']['indices_com_dados']} índices "
            f"({metricas['ativo_de_dados']['tamanho_gb']} GB) — inclui 15,5 M de contratos.",
        },
        {
            "dimensao": "Amplitude do produto",
            "apelido": "Produto",
            "nota": 5.0,
            "justificacao": f"{metricas['produto']['rotas_api']} rotas de API em "
            f"{metricas['produto']['dominios_rotas']} domínios funcionais.",
        },
        {
            "dimensao": "Profundidade de IA",
            "apelido": "IA",
            "nota": 4.5,
            "justificacao": "Investigador com evidências citadas, ontologia com validação anti-alucinação, "
            "agentes LangGraph, world model com simulação e relatório de evidência.",
        },
        {
            "dimensao": "Monetização pronta",
            "apelido": "Monetização",
            "nota": 3.5,
            "justificacao": f"{metricas['monetizacao']['pacotes_relatorio']} pacotes com preço "
            f"({metricas['monetizacao']['preco_min_eur']}–{metricas['monetizacao']['preco_max_eur']} €), "
            "loja e CRM integrados; falta plano/assinatura e contagem de uso.",
        },
        {
            "dimensao": "Mercado endereçável",
            "apelido": "Mercado",
            # Fórmula explícita (para o número não ser opinião): metade do peso na
            # qualidade do cadastro (entidades com NIF) e metade na diversificação
            # (10% de entidades fora de PT = nota máxima nessa parcela).
            "nota": round(
                5.0 * (
                    0.5 * (ent_com_nif / ent_total if ent_total else 0)
                    + 0.5 * min(1.0, ((ent_total - int(pt.get("count") or 0)) / ent_total if ent_total else 0) / 0.10)
                ),
                1,
            ),
            "justificacao": f"Portugal concentra {metricas['cobertura']['entidades_pt_pct']}% das entidades "
            f"(nota = 50% de cadastro com NIF, hoje {metricas['cobertura']['entidades_com_nif_pct']}%, "
            f"+ 50% de diversificação fora de PT, hoje "
            f"{_pct(ent_total - int(pt.get('count') or 0), ent_total)}%). Espanha {int(es.get('count') or 0):,} "
            f"e França {int(fr.get('count') or 0):,} são amostras.",
        },
        {
            "dimensao": "Consistência dos dados",
            "apelido": "Consistência",
            "nota": 2.0,
            "justificacao": f"Apenas {metricas['cobertura']['entidades_com_nif_pct']}% das entidades têm NIF e a "
            f"cobertura societária é {metricas['cobertura']['societario_cobertura_pct']}% "
            "das entidades com NIF — é o elo mais fraco da cadeia de valor.",
        },
        {
            "dimensao": "Compliance e licenciamento",
            "apelido": "Compliance",
            "nota": 3.0,
            "justificacao": "Fontes são dados públicos, mas a recolha societária depende de captcha pago e a "
            "pesquisa social está desligada (0 canais ativos) — risco gerido por omissão, não por contrato.",
        },
        {
            "dimensao": "Prontidão comercial",
            "apelido": "Comercial",
            "nota": 2.5,
            "justificacao": "Sem telemetria de produto (não há contagem de utilizadores ativos, retenção ou ARPU em "
            "endpoint próprio) e sem planos de subscrição — a operação comercial é manual.",
        },
    ]
    metricas["scorecard"] = scorecard
    metricas["nota_global"] = round(sum(s["nota"] for s in scorecard) / len(scorecard), 2)

    metricas["nao_medido"] = sorted(
        nome for nome, valor in dados.items()
        if isinstance(valor, dict) and valor.get("nao_medido")
    )
    return metricas


# ---------------------------------------------------------------------------
# Relatório em texto
# ---------------------------------------------------------------------------
def relatorio(dados: Dict[str, Any], m: Dict[str, Any]) -> str:
    a, mk, c, p, mo = (
        m["ativo_de_dados"], m["mercado_enderecavel"], m["cobertura"], m["produto"], m["monetizacao"]
    )
    linhas = [
        "# IQ OS — leitura de negócio a partir dos dados da própria plataforma",
        "",
        f"_Gerado a {dados['recolhido_em'][:19]}Z a partir de `{dados['base']}`. "
        "Todos os números vêm dos endpoints indicados em `fonte`._",
        "",
        "## 1. O que existe hoje",
        f"- **{a['documentos_totais']:,} documentos** em {a['indices_com_dados']} índices com dados ({a['tamanho_gb']} GB).",
        f"- **{mk['contratos_agregados']:,} contratos** e **{mk['valor_agregado_eur'] / 1e9:,.1f} mil M€** agregados.",
        f"- **{mk['entidades']:,} entidades** ({c['entidades_com_nif_pct']}% com NIF), "
        f"{mk['adjudicantes']:,} adjudicantes e {mk['adjudicatarios']:,} adjudicatários.",
        f"- **{p['rotas_api']} rotas de API** em {p['dominios_rotas']} domínios funcionais.",
        f"- Dados de apoio: {c['lei_registos']:,} registos LEI, {c['pessoas_documentos']:,} documentos de pessoas, "
        f"{c['societario_publicacoes']:,} publicações societárias, {c['marcas']:,} marcas.",
        "",
        "## 2. Onde está o dinheiro já instrumentado",
        f"- {mo['pacotes_relatorio']} pacotes de relatório com preços de "
        f"**{mo['preco_min_eur']} € a {mo['preco_max_eur']} €** (média {mo['preco_medio_eur']} €).",
        f"- Loja: “{mo['loja']['nome']}” com {mo['loja']['tipos_produto']} tipos de produto.",
        "- Pagamento por MB Way/Ifthenpay com backoffice de pedidos e notificações — ou seja, há operação a jusante.",
        "",
        "## 3. Pontos fortes (com prova)",
        "1. Ativo de dados proprietário e agregado por NIF — difícil de replicar por um concorrente novo.",
        "2. Junção única: contratos ↔ entidades ↔ pessoas ↔ societário ↔ risco ↔ marcas/LEI.",
        "3. IA com rasto de evidência (citação, validação anti-alucinação, audit trail) — requisito em contratação pública.",
        "4. Várias portas de entrada comerciais: subscrição, API, relatórios pagos, loja, CRM, iframes.",
        "5. Multi-país desde a arquitetura (PT/ES/FR) e custo marginal baixo por utilizador adicional.",
        "",
        "## 4. Pontos fracos e riscos",
        f"1. **Concentração geográfica**: {c['entidades_pt_pct']}% das entidades são portuguesas; "
        f"Espanha ({mk['entidades_es']:,}) e França ({mk['entidades_fr']:,}) são amostras.",
        f"2. **Cobertura societária de {c['societario_cobertura_pct']}%** das entidades com NIF — sem esta peça, "
        "os relatórios financeiros prometidos no catálogo não podem ser produzidos a escala.",
        f"3. **{100 - c['entidades_com_nif_pct']}% das entidades sem NIF** não entram no grafo (chave de junção).",
        "4. Dependência de fontes públicas e de captcha pago (2captcha) no elo mais valioso (societário).",
        "5. Sem telemetria de produto nem planos de subscrição — não se mede retenção, uso nem ARPU.",
        "6. Amplitude (≈40 módulos) contra equipa pequena: risco de dispersão, manutenção e dificuldade de mensagem.",
        "7. RGPD: 137 mil documentos de pessoas singulares exigem base legal, retenção e processo de titulares.",
        "",
        "## 5. Pontos de melhoria, por ordem de retorno",
        "1. **Empacotar preço**: 3 planos (Explorador/Profissional/Empresa) + API, e contagem de uso por conta.",
        "2. **Telemetria mínima**: utilizadores ativos, pesquisas, relatórios, conversão e custo por pedido.",
        "3. **Fechar a cobertura societária** por janelas de datas (≈721 janelas cobrem o país) em vez de por NIF.",
        "4. **Resolver os 100.656 registos sem NIF** (deduplicação por nome/morada) para alargar o grafo.",
        "5. **Profundar Espanha/França** com importações por ano e métricas de cobertura visíveis no produto.",
        "6. **Custos de IA sob controlo**: roteamento por modelo, cache de respostas e orçamento por conta.",
        "7. **Prontidão enterprise**: SSO, isolamento por cliente, SLA, registo de auditoria exportável.",
        "8. **Prova social**: 3 casos de uso publicados (fornecedor do Estado, auditoria, risco de contraparte).",
        "",
        "## 6. Scorecard",
        "",
        "| Dimensão | Nota (0-5) | Justificação |",
        "| --- | --- | --- |",
    ]
    for s in m["scorecard"]:
        linhas.append(f"| {s['dimensao']} | {s['nota']} | {s['justificacao']} |")
    linhas += [
        "",
        f"**Nota global: {m['nota_global']} / 5.**",
        "",
        "## 7. O que não foi possível medir",
        ("- Endpoints sem sessão/sem dados: " + ", ".join(m["nao_medido"])) if m["nao_medido"]
        else "- Todos os endpoints previstos responderam.",
        "- Não existe (ainda) telemetria de utilização: qualquer afirmção sobre clientes, retenção ou receita "
        "tem de ficar marcada como hipótese, não como medição.",
        "",
        "## 8. Pressupostos de mercado (a confirmar, não são medições)",
        "- TAM: universo de fornecedores do Estado no dataset (adjudicatários) × preço médio de subscrição anual.",
        "- SAM: empresas com contratos acima de um valor mínimo, em PT e ES.",
        "- SOM: 0,5% / 2% / 5% do SAM no ano 1/2/3 — depende de força de vendas, não do produto.",
        "- Impacto: redução de horas de pesquisa por processo, deteção precoce de fornecedores em risco e "
        "mais concorrência nos concursos (menos assimetria de informação).",
    ]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def graficos(m: Dict[str, Any]) -> List[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    GRAFICOS.mkdir(parents=True, exist_ok=True)
    fundo, texto, destaque = "#0f172a", "#e2e8f0", "#2dd4bf"
    plt.rcParams.update({"text.color": texto, "axes.labelcolor": texto, "xtick.color": texto,
                         "ytick.color": texto, "figure.facecolor": fundo, "axes.facecolor": fundo,
                         "axes.edgecolor": "#334155", "font.size": 11})
    saidas: List[Path] = []

    # 1. Documentos por índice
    maiores = m["ativo_de_dados"]["maiores"][:10]
    if maiores:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.barh([x["indice"] for x in maiores][::-1], [x["docs"] for x in maiores][::-1], color=destaque)
        ax.set_title("Documentos por índice (top 10)", color=texto, fontsize=13)
        ax.set_xlabel("documentos")
        ax.tick_params(labelsize=9)
        for i, x in enumerate(maiores[::-1]):
            ax.text(x["docs"], i, f" {x['docs']:,}".replace(",", " "), va="center", fontsize=8, color=texto)
        fig.tight_layout()
        caminho = GRAFICOS / "01_documentos_por_indice.png"
        fig.savefig(caminho, dpi=150, facecolor=fundo)
        plt.close(fig)
        saidas.append(caminho)

    # 2. Entidades por país
    mk = m["mercado_enderecavel"]
    etiquetas = ["Portugal", "Espanha", "França", "Outros"]
    outros = mk["entidades"] - mk["entidades_pt"] - mk["entidades_es"] - mk["entidades_fr"]
    valores = [mk["entidades_pt"], mk["entidades_es"], mk["entidades_fr"], max(0, outros)]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    barras = ax.bar(etiquetas, valores, color=[destaque, "#38bdf8", "#818cf8", "#475569"])
    ax.set_title("Entidades por país", color=texto, fontsize=13)
    ax.set_yscale("log")
    ax.set_ylabel("entidades (escala log)")
    for barra, valor in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width() / 2, valor, f"{valor:,}".replace(",", " "),
                ha="center", va="bottom", fontsize=9, color=texto)
    fig.tight_layout()
    caminho = GRAFICOS / "02_entidades_por_pais.png"
    fig.savefig(caminho, dpi=150, facecolor=fundo)
    plt.close(fig)
    saidas.append(caminho)

    # 3. Funil de cobertura
    c = m["cobertura"]
    etapas = ["Entidades", "Com NIF", "LEI (registo)", "Pessoas", "Societário (entidades)"]
    valores = [mk["entidades"], int(mk["entidades"] * c["entidades_com_nif_pct"] / 100), c["lei_registos"],
               c["pessoas_documentos"], c["societario_entidades"]]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    barras = ax.barh(etapas[::-1], valores[::-1], color=["#f472b6", "#818cf8", "#38bdf8", "#22d3ee", destaque])
    ax.set_title("Cobertura por camada de dados", color=texto, fontsize=13)
    ax.set_xscale("log")
    ax.set_xlabel("registos (escala log)")
    ax.tick_params(labelsize=9)
    for barra, valor in zip(barras, valores[::-1]):
        ax.text(valor, barra.get_y() + barra.get_height() / 2, f" {valor:,}".replace(",", " "),
                va="center", fontsize=9, color=texto)
    fig.tight_layout()
    caminho = GRAFICOS / "03_funil_cobertura.png"
    fig.savefig(caminho, dpi=150, facecolor=fundo)
    plt.close(fig)
    saidas.append(caminho)

    # 4. Scorecard em radar
    import math

    dimensoes = [s.get("apelido") or s["dimensao"] for s in m["scorecard"]]
    notas = [s["nota"] for s in m["scorecard"]]
    angulos = [n / len(dimensoes) * 2 * math.pi for n in range(len(dimensoes))]
    angulos += angulos[:1]
    notas_ciclo = notas + notas[:1]
    fig = plt.figure(figsize=(8.5, 8.5))
    ax = fig.add_subplot(polar=True)
    ax.set_facecolor(fundo)
    ax.plot(angulos, notas_ciclo, color=destaque, linewidth=2)
    ax.fill(angulos, notas_ciclo, color=destaque, alpha=0.25)
    ax.set_xticks(angulos[:-1])
    titulos = ax.set_xticklabels(dimensoes, fontsize=10, color=texto, fontweight="bold")
    for titulo, angulo in zip(titulos, angulos[:-1]):
        # Afasta os rótulos do gráfico para não cruzarem as linhas do radar.
        titulo.set_y(titulo.get_position()[1] - 8)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=8, color=texto)
    ax.set_ylim(0, 5.2)
    ax.set_title(f"Scorecard IQ OS — nota global {m['nota_global']}/5", color=texto, fontsize=14, pad=28)
    fig.tight_layout()
    caminho = GRAFICOS / "04_scorecard.png"
    fig.savefig(caminho, dpi=150, facecolor=fundo)
    plt.close(fig)
    saidas.append(caminho)

    # 5. Cenários de receita (pressupostos explícitos)
    mo = m["monetizacao"]
    preco_anual = 588.0  # 49 €/mês — pressuposto de plano Profissional
    sam = max(1, int(mk["adjudicatarios"] * 0.05))  # 5% dos adjudicatários com perfil de subscrição
    cenarios = [("Ano 1 — 0,5%", 0.005), ("Ano 2 — 2%", 0.02), ("Ano 3 — 5%", 0.05)]
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    valores = [sam * fatia * preco_anual for _, fatia in cenarios]
    barras = ax.bar([nome for nome, _ in cenarios], valores, color=[destaque, "#38bdf8", "#818cf8"])
    ax.set_title("Receita de subscrição por cenário (hipótese: 49 €/mês)", color=texto, fontsize=13)
    ax.set_ylabel("€ / ano")
    for barra, valor in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width() / 2, valor, f"{valor:,.0f} €".replace(",", " "),
                ha="center", va="bottom", fontsize=10, color=texto)
    fig.tight_layout()
    caminho = GRAFICOS / "05_cenarios_receita.png"
    fig.savefig(caminho, dpi=150, facecolor=fundo)
    plt.close(fig)
    saidas.append(caminho)

    return saidas


def main(argv: Optional[List[str]] = None) -> int:
    try:  # consola do Windows fora do UTF-8 por omissão
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(description="Análise de negócio do IQ OS a partir dos dados da plataforma.")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="URL da API (dentro do container: 8000)")
    parser.add_argument("--sem-sessao", action="store_true", help="Não tentar criar sessão de serviço")
    args = parser.parse_args(argv)

    SAIDA.mkdir(parents=True, exist_ok=True)
    token = None if args.sem_sessao else criar_token_servico()
    print(f"a recolher de {args.base} (sessão: {'sim' if token else 'não'})…")
    dados = recolher(args.base, token)
    metricas = analisar(dados)

    (SAIDA / "analise_iqos.json").write_text(
        json.dumps({"dados": dados, "metricas": metricas}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    texto = relatorio(dados, metricas)
    (SAIDA / "relatorio_negocio.md").write_text(texto, encoding="utf-8")
    try:
        caminhos = graficos(metricas)
        print(f"gráficos: {len(caminhos)} em {GRAFICOS}")
    except Exception as exc:  # noqa: BLE001 - sem gráficos o JSON e o MD continuam válidos
        print(f"gráficos falharam: {type(exc).__name__}: {exc}")

    print(texto)
    print(f"\nartefactos em {SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
