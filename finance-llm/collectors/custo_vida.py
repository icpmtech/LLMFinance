"""Componentes do custo de vida por concelho.

Reúne os valores oficiais que entram numa comparação de custo de vida entre os
308 concelhos. Cada componente tem uma natureza diferente, e o módulo trata-as
de forma diferente de propósito:

* **IMI** — a taxa é deliberada por cada município e a Autoridade Tributária
  publica-a todos os anos. A lista por município não está em formato aberto no
  Portal das Finanças, mas está reproduzida, com atribuição e licença CC BY 4.0,
  pela API `flatin.pt` (que cita a AT como origem). É essa a fonte lida aqui,
  porque é a única que permite recolher os 308 concelhos sem trabalho manual.
  Oito municípios fixam a taxa **por freguesia** e aparecem em branco: branco
  não é zero, e é assim que fica.
* **Gasóleo** — a DGEG publica os preços comunicados por cada posto. A mediana
  por concelho é calculada aqui, posto a posto (média simples, não ponderada
  pelo volume vendido).
* **Eletricidade e gás** — a tarifa transitória de venda a clientes finais da
  ERSE é **nacional** (só se distingue por nível de tensão, potência e escalão
  de consumo). Não há, por isso, nada a diferenciar por concelho: o valor é
  lido do ficheiro oficial e replicado, e a página diz isso mesmo.
* **Água, resíduos e transportes** — não entram. Ver `LIMITES`: são casos em que
  o valor existe mas não há série aberta por concelho, e estimá-lo seria
  inventar.

A recolha é **explícita e datada**: escreve `data/custo-vida/componentes.json`,
com a leitura de cada fonte, para que o serviço (`api/custo_vida_service.py`)
não vá à rede a servir pedidos.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import statistics
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "custo-vida"
COMPONENTES_PATH = DATA_DIR / "componentes.json"

USER_AGENT = "IQOS/1.0 (+https://sabemos.studio; recolha de dados publicos)"

#: Taxas municipais de IMI (AT, reproduzidas em dados.gov.pt com CC BY 4.0).
IMI_API = "https://flatin.pt/api/v1/imi/rates.csv"
#: Preços de combustíveis comunicados à DGEG (API pública do portal).
DGEG_POSTOS = "https://precoscombustiveis.dgeg.gov.pt/api/PrecoComb/PesquisarPostos"
#: Gasóleo simples rodoviário.
DGEG_GASOLEO = 2101
#: Tarifas transitórias de venda a clientes finais (eletricidade e gás natural).
ERSE_ELETRICIDADE = "https://www.erse.pt/media/wbxljhas/s_tarifas_net_outubro-2026.xlsx"
ERSE_GAS = "https://www.erse.pt/media/efbcnpic/s_tarifas_net.xlsx"

#: O que fica de fora, e porquê. Fica no código (e não só no texto da página)
#: para a página conseguir explicar a cobertura a partir daqui.
LIMITES: Dict[str, Dict[str, str]] = {
    "agua": {
        "label": "Água, saneamento e resíduos",
        "motivo": (
            "A ERSAR publica o encargo mensal por concelho (10 m³/mês) apenas numa "
            "consulta interativa e em PDF por entidade gestora; o único ficheiro "
            "aberto da ERSAR no dados.gov.pt (RASARP) é de indicadores, não de "
            "tarifas. A tarifa é fixada por entidade gestora, não pelo município."
        ),
    },
    "transportes": {
        "label": "Transportes",
        "motivo": (
            "Os passes são fixados por autoridade de transporte (AML, AMP, CIM) e "
            "não existe tabela nacional por concelho; os tarifários publicados são "
            "imagens ou páginas dinâmicas, sem preço em formato reutilizável."
        ),
    },
    "alimentacao": {
        "label": "Alimentação, saúde e educação",
        "motivo": (
            "Não existe série de preços por município: o INE publica preços no "
            "máximo por NUTS II e o cabaz da DECO é nacional. Entra no orçamento "
            "familiar, mas não distingue territórios."
        ),
    },
}


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _fold(value: Any) -> str:
    """Chave comparável: sem acentos, minúsculas, espaços colapsados."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def _percent(value: Any) -> Optional[float]:
    """«0,324 %» → 0.324 (em pontos percentuais); branco → None."""
    text = str(value or "").strip().replace("%", "").replace("\u00a0", "").strip()
    if not text:
        return None
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _price(value: Any) -> Optional[float]:
    """«1,879 €» → 1.879; vazio → None."""
    text = str(value or "").replace("€", "").replace("\u00a0", "").strip()
    if not text:
        return None
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# IMI — taxa urbana deliberada por cada município
# --------------------------------------------------------------------------
def recolher_imi(ano: Optional[int] = None, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    """Taxa de IMI para prédios urbanos, por concelho, de um ano fiscal."""
    client = session or _session()
    params = {"year": ano} if ano else {}
    response = client.get(IMI_API, params=params, timeout=60)
    response.raise_for_status()
    text = response.text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    taxas: Dict[str, Dict[str, Any]] = {}
    anos = set()
    for row in reader:
        nome = (row.get("municipality") or "").strip()
        if not nome:
            continue
        ano_linha = (row.get("year") or "").strip()
        if ano_linha:
            anos.add(ano_linha)
        taxas[_fold(nome)] = {
            "concelho": nome,
            "concelho_publicado": (row.get("municipality_as_published") or "").strip(),
            "codigo": (row.get("codigo") or "").strip(),
            "distrito": (row.get("distrito") or "").strip(),
            "urbana_pct": _percent(row.get("urban_percent")),
            "rural_pct": _percent(row.get("rural_percent")),
            "ano": int(ano_linha) if ano_linha.isdigit() else None,
        }
    return {
        "fonte": "Autoridade Tributária e Aduaneira, reproduzido por flatin.pt (dados.gov.pt)",
        "url": IMI_API + (f"?year={ano}" if ano else ""),
        "licenca": "CC BY 4.0",
        "ano": int(max(anos)) if anos else ano,
        "concelhos": len(taxas),
        "sem_taxa_unica": sum(1 for item in taxas.values() if item["urbana_pct"] is None),
        "por_concelho": taxas,
    }


# --------------------------------------------------------------------------
# Gasóleo — mediana do preço por litro nas bombas de cada concelho
# --------------------------------------------------------------------------
def recolher_gasoleo(
    *,
    tipo: int = DGEG_GASOLEO,
    por_pagina: int = 5000,
    max_paginas: int = 12,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    """Preço mediano do gasóleo simples, por concelho, a partir dos postos da DGEG."""
    client = session or _session()
    precos: Dict[str, List[float]] = {}
    distritos: Dict[str, Dict[str, int]] = {}
    leitura = ""
    total = 0
    for pagina in range(1, max_paginas + 1):
        response = client.get(
            DGEG_POSTOS,
            params={"idsTiposComb": tipo, "qtdPorPagina": por_pagina, "pagina": pagina},
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json() or {}
        postos = payload.get("resultado") or []
        if not postos:
            break
        total += len(postos)
        for posto in postos:
            concelho = (posto.get("Municipio") or "").strip()
            preco = _price(posto.get("Preco"))
            if not concelho or preco is None or preco <= 0:
                continue
            precos.setdefault(concelho, []).append(preco)
            distrito = (posto.get("Distrito") or "").strip()
            if distrito:
                contagem = distritos.setdefault(concelho, {})
                contagem[distrito] = contagem.get(distrito, 0) + 1
            atualizado = str(posto.get("DataAtualizacao") or "")[:10]
            leitura = max(leitura, atualizado)
        if len(postos) < por_pagina:
            break
    por_concelho = {
        _fold(concelho): {
            "concelho": concelho,
            "preco_l": round(statistics.median(valores), 4),
            "postos": len(valores),
            # A DGEG escreve «Meda», «Calheta» ou «Lagoa» sem dizer de que região
            # são; o distrito do posto é o que permite não dar a Calheta da
            # Madeira o preço a Calheta dos Açores.
            "distrito": max(contagem, key=contagem.get) if (contagem := distritos.get(concelho)) else "",
        }
        for concelho, valores in precos.items()
    }
    return {
        "fonte": "DGEG — preços de combustíveis comunicados pelos postos",
        "url": DGEG_POSTOS,
        "leitura": leitura,
        "postos": total,
        "concelhos": len(por_concelho),
        "por_concelho": por_concelho,
    }


# --------------------------------------------------------------------------
# Eletricidade e gás — tarifa transitória de venda a clientes finais (ERSE)
# --------------------------------------------------------------------------
def _celulas(linha: Iterable[Any]) -> List[str]:
    return [str(c.value) if c.value is not None else "" for c in linha]


def _numero(valor: str) -> Optional[float]:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _ler_eletricidade(caminho: Path) -> Dict[str, Any]:
    import openpyxl

    livro = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    try:
        folha = livro["TVCFtrans_CUR_Continente_BT"]
        linhas = [_celulas(linha) for linha in folha.iter_rows(max_row=120)]
    finally:
        livro.close()

    bloco = None
    for indice, linha in enumerate(linhas):
        junto = " ".join(linha)
        if "BTN" in junto and "20,7" in junto and "2,3" in junto:
            bloco = indice
            break
    if bloco is None:
        raise ValueError("não encontrei o bloco BTN ≤20,7 kVA no ficheiro da ERSE")

    # O bloco tem duas secções: termos fixos (EUR/dia por potência) e energia
    # ativa (EUR/kWh por opção horária). Sem separar as duas, a linha
    # «Tarifa simples, bi-horária e tri-horária» da tabela de potências — que
    # tem um termo fixo ao lado — era lida como se fosse o preço da energia.
    inicio_energia = None
    for indice in range(bloco, min(bloco + 40, len(linhas))):
        if "energia ativa" in _fold(" ".join(linhas[indice])):
            inicio_energia = indice
            break
    if inicio_energia is None:
        raise ValueError("não encontrei a secção «Energia ativa» no ficheiro da ERSE")

    termo_fixo = None
    for linha in linhas[bloco:inicio_energia]:
        if "3.45" in [c.strip() for c in linha]:
            numeros = [v for v in (_numero(c) for c in linha) if v is not None]
            if len(numeros) >= 2:
                termo_fixo = numeros[-1]
                break

    energia = None
    for linha in linhas[inicio_energia:inicio_energia + 12]:
        primeira = _fold(next((c for c in linha if c.strip()), ""))
        if primeira.startswith("tarifa simples"):
            numeros = [v for v in (_numero(c) for c in linha) if v is not None]
            if numeros:
                energia = numeros[-1]
                break
    if termo_fixo is None or energia is None:
        raise ValueError("não encontrei o termo fixo e a energia da tarifa simples")
    return {"potencia_kva": 3.45, "termo_fixo_dia": termo_fixo, "energia_kwh": energia}


def _ler_gas(caminho: Path) -> Dict[str, Any]:
    import openpyxl

    livro = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    try:
        folha = livro["TarifaTransitoria"]
        linhas = [_celulas(linha) for linha in folha.iter_rows(max_row=60)]
    finally:
        livro.close()

    for linha in linhas:
        junto = _fold(" ".join(linha[:3]))
        if junto.startswith("escalao 1") or (linha[0] or "").strip() == "1":
            numeros = [v for v in (_numero(c) for c in linha) if v is not None]
            if len(numeros) >= 2:
                return {"escalao": 1, "termo_fixo_dia": numeros[-2], "energia_kwh": numeros[-1]}
    raise ValueError("não encontrei o escalão 1 da tarifa de gás")


def recolher_erse(session: Optional[requests.Session] = None, destino: Optional[Path] = None) -> Dict[str, Any]:
    """Tarifa transitória de venda a clientes finais: eletricidade e gás natural."""
    client = session or _session()
    pasta = destino or (DATA_DIR / "erse")
    pasta.mkdir(parents=True, exist_ok=True)

    ficheiros = {}
    for nome, url in (("eletricidade", ERSE_ELETRICIDADE), ("gas", ERSE_GAS)):
        caminho = pasta / f"{nome}.xlsx"
        resposta = client.get(url, timeout=120)
        resposta.raise_for_status()
        caminho.write_bytes(resposta.content)
        ficheiros[nome] = caminho

    return {
        "eletricidade": {
            **_ler_eletricidade(ficheiros["eletricidade"]),
            "fonte": "ERSE — tarifas transitórias de venda a clientes finais (BTN, Portugal continental)",
            "url": ERSE_ELETRICIDADE,
            "nota": "Preço da energia e das redes, sem impostos. Igual em todos os concelhos.",
        },
        "gas": {
            **_ler_gas(ficheiros["gas"]),
            "fonte": "ERSE — tarifa transitória de venda a clientes finais de gás natural",
            "url": ERSE_GAS,
            "nota": "Escalão 1 (até 220 m³/ano). Igual em todos os concelhos.",
        },
    }


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------
def recolher_tudo(ano_imi: Optional[int] = None) -> Dict[str, Any]:
    """Recolhe todos os componentes disponíveis e grava o instantâneo."""
    session = _session()
    componentes: Dict[str, Any] = {
        "recolhido_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "limites": LIMITES,
    }
    passos = (
        ("imi", lambda: recolher_imi(ano=ano_imi, session=session)),
        ("gasoleo", lambda: recolher_gasoleo(session=session)),
        ("erse", lambda: recolher_erse(session=session)),
    )
    for nome, passo in passos:
        try:
            componentes[nome] = passo()
            logger.info("custo de vida: %s recolhido", nome)
        except Exception as exc:  # rede, formato ou ficheiro em baixo
            logger.warning("custo de vida: %s falhou (%s)", nome, exc)
            componentes[nome] = {"erro": str(exc)}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COMPONENTES_PATH.write_text(
        json.dumps(componentes, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return componentes


def carregar_componentes() -> Dict[str, Any]:
    """Instantâneo gravado (vazio se ainda não houve recolha)."""
    if not COMPONENTES_PATH.exists():
        return {"limites": LIMITES}
    try:
        dados = json.loads(COMPONENTES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"limites": LIMITES}
    dados.setdefault("limites", LIMITES)
    return dados


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Recolhe os componentes do custo de vida")
    parser.add_argument("--ano-imi", type=int, default=None, help="ano fiscal do IMI (por omissão, o mais recente)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s")
    componentes = recolher_tudo(ano_imi=args.ano_imi)
    resumo = {
        chave: (
            {"concelhos": valor.get("concelhos"), "ano": valor.get("ano"), "leitura": valor.get("leitura")}
            if isinstance(valor, dict) and "erro" not in valor
            else valor
        )
        for chave, valor in componentes.items()
        if chave != "limites"
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    falhou = any(isinstance(v, dict) and "erro" in v for v in componentes.values())
    return 1 if falhou else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
