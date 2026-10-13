"""Fichas públicas de municípios: os dados, o resumo factual e o texto com IA.

O CMS publica **uma ficha por município** em `/site/municipio/{slug}`. Nessa
página há duas coisas de naturezas diferentes:

* o **texto**, que é editorial — escrito por uma pessoa, ou começado a partir de
  um rascunho que a IA redige com os números à frente;
* os **dados**, que são a fotografia da ficha das despesas e da contratação
  pública (`/municipios/despesas/{município}`) no momento em que foram lidos.

Este módulo é a ponte entre os dois: lê a ficha dos municípios para dentro do
documento do CMS (para a página publicada não depender do Elasticsearch nem
mudar sozinha debaixo dos pés de quem a leu) e escreve o rascunho do texto.

Os números que saem daqui são **sempre os oficiais**: a despesa vem do indicador
0013909 do INE (origem DGAL) e a contratação do Portal BASE. A IA recebe-os já
calculados e não os inventa — o que ela faz é escrever.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional

from api import municipios_service as municipios

logger = logging.getLogger(__name__)

#: Classificadores económicos na ordem oficial (do total para o detalhe).
CLASSIFICADORES = municipios.CLASSIFICADORES

#: Classificadores que viram números de destaque na ficha pública.
DESTAQUES = ("D", "D1", "D2", "D11", "D12")

#: Quantos fornecedores a ficha pública mostra.
MAX_FORNECEDORES = 5

PROMPT_TEXTO = """És o redator do site público do IQ OS, uma plataforma de análise \
financeira portuguesa. Escreves em português de Portugal, com frases curtas, \
sem adjetivos de propaganda e sem inventar nada: todos os números que usares \
têm de sair dos dados abaixo.

Município: {municipio}

Dados oficiais (já calculados — não os alteres nem os estimes):
{resumo}

Instruções do editor (podem vir vazias; se vierem, têm prioridade sobre o estilo):
{instrucoes}

Escreve a ficha pública deste município. Responde **só** com um objeto JSON, sem \
texto antes nem depois, com esta forma:

{{"titulo": "título com até 70 caracteres", "resumo": "uma frase com até 160 \
caracteres, para a meta descrição", "corpo": "3 a 5 parágrafos curtos em Markdown"}}

No `corpo`, usa `##` para as secções (por exemplo «A despesa», «A contratação \
pública»), diz sempre o **ano** a que os valores respeitam e o que o município \
mais gasta. Não uses tabelas, imagens nem links."""


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
def _euros(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _serie_de_despesas(ficha: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Série anual da despesa total, do classificador `D` de cada ano.

    O indicador do INE publica um ano de cada vez; o resto da série aparece
    sozinho assim que a recolha trouxer mais anos.
    """
    por_ano = ficha.get("despesas_por_ano") or {}
    serie: List[Dict[str, Any]] = []
    for ano, valores in por_ano.items():
        if not isinstance(valores, dict):
            continue
        total = valores.get("D")
        if total is None:
            continue
        serie.append({"ano": str(ano), "total": _euros(total)})
    serie.sort(key=lambda ponto: ponto["ano"])
    return serie


def _por_classificador(ficha: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Despesa do ano publicado, por classificador económico, na ordem oficial."""
    ano = ficha.get("ano_despesas")
    por_ano = ficha.get("despesas_por_ano") or {}
    valores = por_ano.get(str(ano)) or por_ano.get(ano) or {}
    if not isinstance(valores, dict):
        return []
    return [
        {"codigo": codigo, "etiqueta": etiqueta, "valor": _euros(valores.get(codigo))}
        for codigo, _campo, etiqueta in CLASSIFICADORES
        if codigo in valores
    ]


def dados_do_municipio(nome_ou_codigo: str) -> Dict[str, Any]:
    """Fotografia da ficha de um município, pronta a guardar no documento do CMS.

    Devolve `{"error": …}` quando o município não existe — a rota que a chama
    recusa gravar uma ficha sem dados em vez de publicar uma página vazia.
    """
    ficha = municipios.ficha(nome_ou_codigo)
    if ficha.get("error") or not ficha.get("nome"):
        return {"error": ficha.get("error") or f"Município «{nome_ou_codigo}» não encontrado."}

    detalhe = ficha.get("contratos_detalhe") or {}
    fornecedores = [
        {
            "nome": str(item.get("nome") or ""),
            "contratos": int(item.get("contratos") or 0),
            "valor": _euros(item.get("valor")),
        }
        for item in (detalhe.get("fornecedores") or [])[:MAX_FORNECEDORES]
        if item.get("nome")
    ]
    return {
        "municipio": ficha.get("nome"),
        "geocod": ficha.get("geocod"),
        "geocod_curto": ficha.get("geocod_curto"),
        "distrito": ficha.get("distrito"),
        "nuts": ficha.get("nuts"),
        "nuts_nome": ficha.get("nuts_nome"),
        "ano_despesas": ficha.get("ano_despesas"),
        "anos_despesas": ficha.get("anos") or [],
        "serie_despesas": _serie_de_despesas(ficha),
        "por_classificador": _por_classificador(ficha),
        "despesas_total": _euros(ficha.get("despesas_total")),
        "despesas_correntes": _euros(ficha.get("despesas_correntes")),
        "despesas_capital": _euros(ficha.get("despesas_capital")),
        "despesas_pessoal": _euros(ficha.get("despesas_pessoal")),
        "despesas_bens_servicos": _euros(ficha.get("despesas_bens_servicos")),
        "contratos": {
            "total": int(ficha.get("contratos_total") or 0),
            "valor": _euros(ficha.get("contratos_valor")),
            "primeiro_ano": ficha.get("contratos_primeiro_ano"),
            "ultimo_ano": ficha.get("contratos_ultimo_ano"),
            "por_ano": ficha.get("contratos_por_ano") or {},
            "fornecedores": fornecedores,
            "adjudicantes": ficha.get("adjudicantes") or [],
        },
        "recolhido_em": ficha.get("recolhido_em"),
        "fontes": [
            {"documento": ficha.get("fonte_despesas"), "url": municipios.INE_URL_HUMANO},
            {"documento": ficha.get("fonte_contratos"), "url": municipios.DADOS_GOV_URL},
        ],
    }


def opcoes() -> Dict[str, Any]:
    """Os municípios que se podem publicar, com o que já tem ficha no CMS.

    A lista sai do ficheiro local das fichas (308 concelhos, sem depender do
    Elasticsearch): é o que o seletor do CMS precisa para não deixar criar duas
    fichas do mesmo município.
    """
    from api import cms_store as store

    existentes: Dict[str, Dict[str, Any]] = {}
    for ficha in store.list_items("municipios", limit=500)["items"]:
        chave = _chave(str(ficha.get("municipio") or ""))
        if chave:
            existentes[chave] = {
                "id": ficha.get("id"),
                "slug": ficha.get("slug"),
                "status": ficha.get("status"),
            }

    itens: List[Dict[str, Any]] = []
    for ficha in municipios.fichas_locais():
        nome = str(ficha.get("nome") or "").strip()
        if not nome:
            continue
        existente = existentes.get(_chave(nome))
        itens.append({
            "municipio": nome,
            "geocod": ficha.get("geocod"),
            "distrito": ficha.get("distrito"),
            "nuts_nome": ficha.get("nuts_nome"),
            "ano_despesas": ficha.get("ano_despesas"),
            "despesas_total": _euros(ficha.get("despesas_total")),
            "ficha_id": (existente or {}).get("id"),
            "ficha_status": (existente or {}).get("status"),
        })
    itens.sort(key=lambda item: item["municipio"])
    anos = [str(item["ano_despesas"]) for item in itens if item.get("ano_despesas")]
    return {
        "total": len(itens),
        "items": itens,
        "ano_despesas": max(anos) if anos else None,
    }


def _chave(texto: str) -> str:
    """Forma comparável de um nome de município (sem acentos nem pontuação)."""
    sem_acentos = unicodedata.normalize("NFKD", texto or "")
    sem_acentos = "".join(ch for ch in sem_acentos if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", sem_acentos.lower()).strip()


# ---------------------------------------------------------------------------
# Resumo factual (o que a IA e a página recebem)
# ---------------------------------------------------------------------------
def _milhoes(valor: float) -> str:
    """Valor em euros escrito como se lê («22,3 milhões de euros»)."""
    if valor >= 1_000_000:
        milhoes = valor / 1_000_000
        if abs(milhoes - 1) < 0.05:
            return "1 milhão de euros"
        return f"{milhoes:.1f}".replace(".", ",") + " milhões de euros"
    return f"{valor:,.0f} euros".replace(",", " ")


def resumo_dos_dados(dados: Dict[str, Any]) -> str:
    """Os números em texto corrido, para o prompt da IA e para a página.

    É a forma **verificável** dos dados: tudo o que a IA pode dizer sem inventar
    sai daqui, e é este texto que se mostra como «os dados usados».
    """
    if not dados or dados.get("error"):
        return ""
    linhas: List[str] = [
        f"Município: {dados.get('municipio')}"
        + (f" (distrito de {dados.get('distrito')})" if dados.get("distrito") else ""),
        f"Ano da despesa: {dados.get('ano_despesas')}",
        f"Despesa total: {_milhoes(_euros(dados.get('despesas_total')))}",
        f"Despesas correntes: {_milhoes(_euros(dados.get('despesas_correntes')))}, "
        f"despesas de capital: {_milhoes(_euros(dados.get('despesas_capital')))}",
        f"Despesa com pessoal: {_milhoes(_euros(dados.get('despesas_pessoal')))}; "
        f"aquisição de bens e serviços: {_milhoes(_euros(dados.get('despesas_bens_servicos')))}",
    ]
    classificadores = dados.get("por_classificador") or []
    if classificadores:
        principais = ", ".join(
            f"{item['etiqueta']} {_milhoes(_euros(item['valor']))}"
            for item in classificadores
            if item.get("codigo") in ("D11", "D12", "D21", "D13", "D22")
        )
        if principais:
            linhas.append(f"Principais rubricas: {principais}")

    contratos = dados.get("contratos") or {}
    if contratos.get("total"):
        anos = (
            f" entre {contratos.get('primeiro_ano')} e {contratos.get('ultimo_ano')}"
            if contratos.get("primeiro_ano") and contratos.get("ultimo_ano")
            else ""
        )
        linhas.append(
            f"Contratação pública no Portal BASE{anos}: {contratos['total']} contratos, "
            f"{_milhoes(_euros(contratos.get('valor')))}"
        )
        fornecedores = contratos.get("fornecedores") or []
        if fornecedores:
            linhas.append(
                "Principais fornecedores: "
                + "; ".join(
                    f"{item['nome']} ({item['contratos']} contratos, {_milhoes(_euros(item['valor']))})"
                    for item in fornecedores
                )
            )
    elif contratos:
        linhas.append("Contratação pública no Portal BASE: sem contratos com este município como adjudicante.")

    fontes = [fonte.get("documento") for fonte in (dados.get("fontes") or []) if fonte.get("documento")]
    if fontes:
        linhas.append("Fontes: " + "; ".join(fontes))
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Texto com IA
# ---------------------------------------------------------------------------
def _extrato_json(texto: str) -> Optional[Dict[str, Any]]:
    """Objeto JSON dentro de uma resposta de IA (que às vezes traz cercas ```)."""
    limpo = re.sub(r"```(?:json)?", " ", texto or "")
    inicio = limpo.find("{")
    fim = limpo.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        valor = json.loads(limpo[inicio : fim + 1])
    except json.JSONDecodeError:
        return None
    return valor if isinstance(valor, dict) else None


def _normalizar_texto(objeto: Dict[str, Any], resposta: str, dados: Dict[str, Any]) -> Dict[str, Any]:
    """Título, resumo e corpo a partir do que o modelo devolveu.

    Um modelo que devolva prosa em vez do JSON pedido não se deita fora: aproveita-se
    o texto como corpo e tiram-se o título e o resumo do município e do corpo.
    """
    municipio = str(dados.get("municipio") or "")
    titulo = str(objeto.get("titulo") or "").strip()
    resumo = str(objeto.get("resumo") or "").strip()
    corpo = str(objeto.get("corpo") or "").strip()
    if not corpo:
        corpo = (resposta or "").strip()
    if not titulo:
        titulo = f"Despesas da Câmara Municipal de {municipio}" if municipio else "Despesas municipais"
    if not resumo:
        first = re.sub(r"\s+", " ", re.sub(r"[#*>_`]", " ", corpo)).strip()
        resumo = (first[:157] + "…") if len(first) > 160 else first
    return {"titulo": titulo[:200], "resumo": resumo[:300], "corpo": corpo}


def texto_com_ia(
    municipio: str,
    *,
    dados: Optional[Dict[str, Any]] = None,
    instrucoes: str = "",
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Rascunho do texto da ficha, escrito pela IA a partir dos números reais.

    Devolve `{"ok": False, "error": …}` quando não há fornecedor de IA configurado
    ou o modelo falha — a rota não inventa texto nesse caso.
    """
    base = dados or dados_do_municipio(municipio)
    if base.get("error"):
        return {"ok": False, "error": base["error"]}

    from api.scraper_ai import pick_provider

    provider_id, spec, model_id, key = pick_provider(user_id, provider, model)
    if not provider_id or not spec:
        return {
            "ok": False,
            "error": "Nenhum fornecedor de IA configurado. Defina uma chave em Definições → Fornecedores de IA.",
        }

    prompt = PROMPT_TEXTO.format(
        municipio=base.get("municipio") or municipio,
        resumo=resumo_dos_dados(base),
        instrucoes=(instrucoes or "").strip() or "(sem instruções)",
    )

    from api import cloud_chat

    async def run() -> str:
        return await cloud_chat.complete_answer(
            provider=provider_id,
            spec=spec,
            model=model_id or spec.get("default_model") or "",
            messages=[{"role": "user", "content": prompt}],
            api_key=key,
            temperature=0.4,
            max_tokens=1600,
        )

    try:
        resposta = asyncio.run(run())
    except RuntimeError:
        # Já existe um ciclo de eventos (rota async): corre num ciclo próprio.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            resposta = pool.submit(lambda: asyncio.run(run())).result(timeout=240)
    except Exception as exc:
        logger.warning("Texto por IA falhou (%s): %s", provider_id, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    resposta = str(resposta or "").strip()
    if not resposta:
        return {"ok": False, "error": "O modelo não devolveu resposta."}

    texto = _normalizar_texto(_extrato_json(resposta) or {}, resposta, base)
    return {
        "ok": True,
        **texto,
        "municipio": base.get("municipio"),
        "resumo_dos_dados": resumo_dos_dados(base),
        "ai": {
            "provider": provider_id,
            "provider_label": spec.get("label") or provider_id,
            "model": model_id,
        },
    }
