"""Comparação de **várias empresas** no painel de Descoberta.

O painel de uma empresa responde «o que é isto?». Este módulo responde às
perguntas que só existem com duas ou mais: *quem é maior, quem depende mais de um
só comprador, o que partilham, e o que verificar primeiro no conjunto?*

Três camadas, todas reutilizando o que já existe:

1. **Por empresa** — a mesma recolha e o mesmo motor de decisão do painel
   individual (`descoberta_service.recolher` + `descoberta_decisao.decisao`), para
   os números do conjunto **não** divergirem dos do painel de cada uma.
2. **Comparação** — métricas alinhadas (escala, concentração, procedimento,
   preços, prazos, risco) com o melhor e o pior de cada linha marcados.
3. **Cruzamento** — adjudicantes, pessoas e processos partilhados e a rede do
   conjunto, calculados por `padroes_service.analise_empresas`: a mesma definição
   que a página de Padrões usa, para os cruzamentos serem os mesmos nas duas.

Nada aqui consulta índices diretamente: só orquestra os serviços existentes.
"""
from __future__ import annotations

import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from api import descoberta_decisao as decisao_mod
from api import descoberta_service as service
from api import padroes_service as padroes

logger = logging.getLogger(__name__)

#: Teto de empresas por pedido — acima disto a recolha paralela e a leitura do
#: conjunto deixam de caber num painel que se lê de uma vez.
MAX_EMPRESAS = 8
MIN_EMPRESAS = 2
#: Recolha por empresa (16 fontes) em paralelo, mas sem esgotar as ligações.
MAX_WORKERS = 4
#: Ordem de leitura dos pontos de atenção, do mais grave para o mais informativo.
SEVERIDADE_ORDEM = {"alerta": 0, "aviso": 1, "info": 2}


def _resumo(dados: Dict[str, Any]) -> Dict[str, Any]:
    return dados.get("resumo") or {}


def _concentracao(dados: Dict[str, Any]) -> Dict[str, Any]:
    return dados.get("concentracao") or {}


def _procedimento(dados: Dict[str, Any]) -> Dict[str, Any]:
    return dados.get("procedimento") or {}


def _precos(dados: Dict[str, Any]) -> Dict[str, Any]:
    return dados.get("precos") or {}


def _concorrencia(dados: Dict[str, Any]) -> Dict[str, Any]:
    return dados.get("concorrencia") or {}


def _prazos(dados: Dict[str, Any]) -> Dict[str, Any]:
    return dados.get("prazos") or {}


def _risco(dados: Dict[str, Any]) -> Dict[str, Any]:
    return dados.get("risco") or {}


#: Métricas comparadas. `maior_melhor=None` com `alvo` compara por distância ao alvo.
METRICAS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "contratos",
        "label": "Contratos lidos",
        "unidade": "contratos",
        "maior_melhor": True,
        "extrair": lambda dados: _resumo(dados).get("contratos_lidos") or _resumo(dados).get("contratos"),
        "porque": "Volume de amostra: por baixo dos outros números, mostra quanto vale a pena confiar neles.",
    },
    {
        "id": "valor_total",
        "label": "Valor contratado",
        "unidade": "€",
        "maior_melhor": True,
        "extrair": lambda dados: _resumo(dados).get("valor_total"),
        "porque": "Escala económica da relação com o Estado.",
    },
    {
        "id": "adjudicantes",
        "label": "Compradores distintos",
        "unidade": "entidades",
        "maior_melhor": True,
        "extrair": lambda dados: _concentracao(dados).get("adjudicantes"),
        "porque": "Carteira diversificada resiste à perda de um cliente.",
    },
    {
        "id": "top1",
        "label": "Maior comprador",
        "unidade": "% do valor",
        "maior_melhor": False,
        "extrair": lambda dados: _concentracao(dados).get("top1"),
        "porque": "Quanto mais alto, mais a empresa depende de uma só entidade.",
    },
    {
        "id": "hhi",
        "label": "HHI (concentração)",
        "unidade": "índice",
        "maior_melhor": False,
        "extrair": lambda dados: _concentracao(dados).get("hhi"),
        "porque": "Concentração da carteira numa escala comparável entre empresas.",
    },
    {
        "id": "ajuste_direto",
        "label": "Ajuste direto",
        "unidade": "taxa",
        "maior_melhor": False,
        "extrair": lambda dados: _procedimento(dados).get("taxa_ajuste_direto"),
        "porque": "Contratação sem concurso por desenho, não por exceção.",
    },
    {
        "id": "concorrentes",
        "label": "Concorrentes por contrato",
        "unidade": "concorrentes",
        "maior_melhor": True,
        "extrair": lambda dados: _concorrencia(dados).get("mediana"),
        "porque": "Mediana de concorrentes registados em cada contrato.",
    },
    {
        "id": "preco",
        "label": "Adjudicado/base",
        "unidade": "rácio",
        "maior_melhor": None,
        "alvo": 1.0,
        "extrair": lambda dados: _precos(dados).get("mediana"),
        "porque": "Desvio face ao preço base: 1,00 é adjudicar exatamente o esperado.",
    },
    {
        "id": "dias_publicacao",
        "label": "Decisão → publicação",
        "unidade": "dias",
        "maior_melhor": False,
        "extrair": lambda dados: _prazos(dados).get("mediana_decisao_publicacao"),
        "porque": "Transparência tardia: o escrutínio chega depois de estar decidido.",
    },
    {
        "id": "risco",
        "label": "Risco (0–100)",
        "unidade": "pontos",
        "maior_melhor": False,
        "extrair": lambda dados: _risco(dados).get("score"),
        "porque": "Prioridade de análise do motor de risco, para ordenar o que olhar primeiro.",
    },
)


def _euros(valor: Optional[float]) -> str:
    if valor is None:
        return "—"
    if abs(valor) >= 1_000_000:
        return f"{valor / 1_000_000:.1f} M€"
    if abs(valor) >= 1_000:
        return f"{valor / 1_000:.0f} mil €"
    return f"{valor:.0f} €"


def _taxa(valor: Optional[float]) -> str:
    return "—" if valor is None else f"{round(valor * 100)} %"


def _texto_metrica(metrica: Dict[str, Any], valor: Optional[float]) -> str:
    """Formata uma métrica para a frase de síntese (unidade certa por métrica)."""
    if valor is None:
        return "sem dados"
    unidade = str(metrica.get("unidade") or "")
    if metrica["id"] == "valor_total":
        return _euros(valor)
    if unidade == "taxa":
        return _taxa(valor)
    if unidade.startswith("%"):
        return f"{valor:.1f}".replace(".", ",") + " %"
    if unidade == "rácio":
        return f"{valor:.2f}".replace(".", ",")
    if unidade == "índice":
        return f"{valor:.3f}".replace(".", ",")
    if float(valor).is_integer():
        return f"{int(valor):,}".replace(",", " ")
    return f"{valor:.1f}".replace(".", ",")


def _linha_decisao(nif: str, nome: Optional[str], pais: str) -> Dict[str, Any]:
    """Recolha + decisão de uma empresa, isolada: uma falha não derruba o conjunto."""
    try:
        recolha = service.recolher(nif, pais=pais, nome=nome)
    except Exception as exc:  # noqa: BLE001 - uma empresa má não invalida o conjunto
        logger.warning("Descoberta do conjunto falhou para %s: %s", nif, exc)
        return {"nif": nif, "nome": nome or nif, "erro": str(exc), "decisao": None}
    if recolha.get("error"):
        return {"nif": nif, "nome": nome or nif, "erro": recolha["error"], "decisao": None}
    try:
        return {
            "nif": str(recolha.get("nif") or nif),
            "nome": str(recolha.get("nome") or nome or nif),
            "erro": None,
            "decisao": decisao_mod.decisao(recolha),
            "fontes_ok": len([fonte for fonte in recolha.get("fontes") or [] if fonte.get("estado") == "ok"]),
            "fontes": len(recolha.get("fontes") or []),
            "em_falta": recolha.get("em_falta") or [],
            "ms": recolha.get("ms"),
        }
    except Exception as exc:  # noqa: BLE001 - o motor de decisão nunca derruba o pedido
        logger.warning("Decisão do conjunto falhou para %s: %s", nif, exc)
        return {"nif": nif, "nome": nome or nif, "erro": str(exc), "decisao": None}


def _comparacao(linhas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cada métrica alinhada por empresa, com o melhor e o pior marcados."""
    saida: List[Dict[str, Any]] = []
    for metrica in METRICAS:
        extrair: Callable[[Dict[str, Any]], Optional[float]] = metrica["extrair"]
        valores: List[Dict[str, Any]] = []
        for linha in linhas:
            decisao = linha.get("decisao")
            valor = extrair(decisao) if decisao else None
            if valor is not None:
                try:
                    valor = float(valor)
                except (TypeError, ValueError):
                    valor = None
            valores.append({"nif": linha["nif"], "nome": linha["nome"], "valor": valor, "melhor": False})
        presentes = [item for item in valores if item["valor"] is not None]
        melhor: Optional[Dict[str, Any]] = None
        pior: Optional[Dict[str, Any]] = None
        if presentes:
            if metrica.get("alvo") is not None:
                alvo = float(metrica["alvo"])
                melhor = min(presentes, key=lambda item: abs(item["valor"] - alvo))
                pior = max(presentes, key=lambda item: abs(item["valor"] - alvo))
            elif metrica["maior_melhor"]:
                melhor = max(presentes, key=lambda item: item["valor"])
                pior = min(presentes, key=lambda item: item["valor"])
            else:
                melhor = min(presentes, key=lambda item: item["valor"])
                pior = max(presentes, key=lambda item: item["valor"])
            for item in presentes:
                item["melhor"] = item["valor"] == melhor["valor"]
        numeros = [item["valor"] for item in presentes]
        saida.append(
            {
                "id": metrica["id"],
                "label": metrica["label"],
                "unidade": metrica["unidade"],
                "maior_melhor": metrica["maior_melhor"],
                "alvo": metrica.get("alvo"),
                "porque": metrica["porque"],
                "valores": valores,
                "melhor": (
                    {
                        "nif": melhor["nif"],
                        "nome": melhor["nome"],
                        "valor": melhor["valor"],
                        "texto": _texto_metrica(metrica, melhor["valor"]),
                    }
                    if melhor
                    else None
                ),
                "pior": (
                    {"nif": pior["nif"], "nome": pior["nome"], "valor": pior["valor"], "texto": _texto_metrica(metrica, pior["valor"])}
                    if pior
                    else None
                ),
                "mediana": round(statistics.median(numeros), 4) if numeros else None,
                "amplitude": round(melhor["valor"] - pior["valor"], 4) if numeros and metrica.get("alvo") is None else None,
                "sem_dados": [item["nome"] for item in valores if item["valor"] is None],
            }
        )
    return saida


def _perfil_comparado(linhas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Séries do mesmo radar: uma por empresa, nas mesmas dimensões."""
    dimensoes: List[Dict[str, str]] = []
    indice: Dict[str, int] = {}
    for linha in linhas:
        for dimensao in (linha.get("decisao") or {}).get("perfil") or []:
            identificador = str(dimensao.get("id") or "")
            if identificador and identificador not in indice:
                indice[identificador] = len(dimensoes)
                dimensoes.append({"id": identificador, "label": str(dimensao.get("label") or identificador)})
    series = []
    for linha in linhas:
        valores = {str(dimensao.get("id")): dimensao.get("valor") for dimensao in (linha.get("decisao") or {}).get("perfil") or []}
        series.append(
            {
                "nif": linha["nif"],
                "nome": linha["nome"],
                "valores": {dimensao["id"]: valores.get(dimensao["id"]) for dimensao in dimensoes},
                "detalhes": {
                    str(dimensao.get("id")): dimensao.get("detalhe")
                    for dimensao in (linha.get("decisao") or {}).get("perfil") or []
                },
            }
        )
    return {"dimensoes": dimensoes, "series": series}


def _atencao(linhas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pontos de atenção de todas as empresas, agregados por gravidade."""
    itens: List[Dict[str, Any]] = []
    for linha in linhas:
        for ponto in (linha.get("decisao") or {}).get("atencao") or []:
            itens.append(
                {
                    "nif": linha["nif"],
                    "nome": linha["nome"],
                    "severidade": ponto.get("severidade") or "info",
                    "titulo": ponto.get("titulo") or "",
                    "detalhe": ponto.get("detalhe") or "",
                    "verificar": ponto.get("verificar") or "",
                }
            )
    itens.sort(key=lambda item: (SEVERIDADE_ORDEM.get(item["severidade"], 3), item["nome"], item["titulo"]))
    return itens


def _linha_empresa(linha: Dict[str, Any]) -> Dict[str, Any]:
    """Versão enxuta da empresa para o painel (sem repetir os gráficos individuais)."""
    decisao = linha.get("decisao") or {}
    risco = _risco(decisao)
    resumo = _resumo(decisao)
    return {
        "nif": linha["nif"],
        "nome": linha["nome"],
        "erro": linha.get("erro"),
        "encontrada": decisao.get("encontrada", linha.get("erro") is None),
        "contratos": resumo.get("contratos"),
        "contratos_lidos": resumo.get("contratos_lidos"),
        "valor_total": resumo.get("valor_total"),
        "adjudicantes": resumo.get("adjudicantes"),
        "top1": _concentracao(decisao).get("top1"),
        "insolvencias": resumo.get("insolvencias"),
        "mencoes_cire": resumo.get("mencoes_cire"),
        "risco": {
            "score": risco.get("score"),
            "nivel": risco.get("nivel"),
            "nivel_label": risco.get("nivel_label"),
            "cor": risco.get("cor"),
            "confianca": risco.get("confianca"),
            "cobertura": risco.get("cobertura"),
        },
        "perfil": decisao.get("perfil") or [],
        "atencao": decisao.get("atencao") or [],
        "leitura": decisao.get("leitura") or "",
        "avisos": decisao.get("avisos") or [],
        "fontes_ok": linha.get("fontes_ok"),
        "fontes": linha.get("fontes"),
        "em_falta": linha.get("em_falta") or [],
        "ms": linha.get("ms"),
    }


def _cruzamentos(base: Dict[str, Any], linhas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cruzamentos do conjunto (reutiliza a página de Padrões) com contagens legíveis."""
    crus = base.get("cruzamentos") or {}
    nomes = {linha["nif"]: linha["nome"] for linha in linhas}
    for grupo in ("adjudicantes", "cpvs", "pessoas", "processos"):
        for item in crus.get(grupo) or []:
            item["empresas_nome"] = [nomes.get(nif, nif) for nif in item.get("empresas") or []]
    return {
        "adjudicantes": crus.get("adjudicantes") or [],
        "pessoas": crus.get("pessoas") or [],
        "processos": crus.get("processos") or [],
        "cpvs": crus.get("cpvs") or [],
        "resumo": {
            "adjudicantes": len(crus.get("adjudicantes") or []),
            "pessoas": len(crus.get("pessoas") or []),
            "processos": len(crus.get("processos") or []),
            "cpvs": len(crus.get("cpvs") or []),
        },
    }


def _leitura(empresas: List[Dict[str, Any]], comparacao: List[Dict[str, Any]], cruzamentos: Dict[str, Any]) -> str:
    """Síntese determinística do conjunto: quem é quem e o que decidir."""
    com_dados = [empresa for empresa in empresas if empresa.get("contratos_lidos")]
    if not com_dados:
        return (
            "Nenhuma das empresas tem contratos lidos na amostra: a comparação de contratação "
            "não se aplica. Use os alarmes e o cruzamento de processos para decidir o que verificar."
        )
    partes: List[str] = [f"{len(empresas)} empresas comparadas, {len(com_dados)} com contratos lidos"]

    def metrica(identificador: str) -> Optional[Dict[str, Any]]:
        return next((item for item in comparacao if item["id"] == identificador), None)

    escala = metrica("valor_total")
    if escala and escala.get("melhor"):
        partes.append(f"maior escala: {escala['melhor']['nome']} ({escala['melhor']['texto']})")
    dependencia = metrica("top1")
    if dependencia and dependencia.get("pior"):
        partes.append(
            f"mais dependente de um só comprador: {dependencia['pior']['nome']} "
            f"({_texto_metrica(dependencia, dependencia['pior']['valor'])} do valor)"
        )
    risco = metrica("risco")
    if risco and risco.get("pior") and risco["pior"]["valor"] is not None:
        partes.append(f"prioridade de análise mais alta: {risco['pior']['nome']} ({risco['pior']['texto']}/100)")

    resumo_cruzamentos = cruzamentos.get("resumo") or {}
    partilhados = [
        f"{resumo_cruzamentos.get('adjudicantes')} comprador(es)",
        f"{resumo_cruzamentos.get('cpvs')} CPV",
        f"{resumo_cruzamentos.get('pessoas')} pessoa(s)",
        f"{resumo_cruzamentos.get('processos')} processo(s) do CIRE",
    ]
    partes.append("partilham " + ", ".join(partilhados))

    graves = sum(len([ponto for ponto in empresa.get("atencao") or [] if ponto.get("severidade") == "alerta"]) for empresa in empresas)
    partes.append(
        f"{graves} ponto(s) de atenção graves no conjunto — resolver antes de decidir"
        if graves
        else "sem pontos de atenção graves no conjunto"
    )
    return " · ".join(partes) + "."


def _pedidos(nifs: Optional[Sequence[str]], nomes: Optional[Sequence[str]]) -> List[str]:
    """NIFs e nomes pedidos, sem repetições e pela ordem indicada."""
    vistos: List[str] = []
    for valor in list(nifs or []) + list(nomes or []):
        texto = str(valor or "").strip()
        if texto and texto not in vistos:
            vistos.append(texto)
    return vistos


def conjunto(
    *,
    nifs: Optional[Sequence[str]] = None,
    nomes: Optional[Sequence[str]] = None,
    pais: str = service.PAIS_DEFAULT,
    max_empresas: int = 6,
) -> Dict[str, Any]:
    """Compara várias empresas: números alinhados, cruzamentos, rede e o que verificar.

    Levanta `ValueError` com uma mensagem legível quando o pedido não serve
    (menos de duas empresas, país não suportado, nenhuma empresa analisada) — a
    rota transforma isso no erro HTTP certo.
    """
    codigo = str(pais or service.PAIS_DEFAULT).strip().upper()
    if codigo not in service.PAISES_SUPORTADOS:
        raise ValueError(f"País não suportado: {codigo or '(vazio)'}. Use um de: {', '.join(service.PAISES_SUPORTADOS)}.")
    pedidos = _pedidos(nifs, nomes)
    if len(pedidos) < MIN_EMPRESAS:
        raise ValueError(f"Indique pelo menos {MIN_EMPRESAS} empresas (NIFs ou nomes) para comparar.")
    limite = max(MIN_EMPRESAS, min(int(max_empresas or 6), MAX_EMPRESAS))
    if len(pedidos) > limite:
        pedidos = pedidos[:limite]

    base = padroes.analise_empresas(nifs=nifs, nomes=nomes, pais=codigo, max_empresas=limite)
    if base.get("error"):
        raise ValueError(str(base["error"]))
    alvos = [(str(item.get("nif") or ""), item.get("nome")) for item in base.get("empresas") or []]
    alvos = [(nif, nome) for nif, nome in alvos if nif]
    if len(alvos) < MIN_EMPRESAS:
        raise ValueError(
            "Não foi possível analisar duas empresas do pedido"
            + (f": {'; '.join(base.get('avisos') or [])}" if base.get("avisos") else ".")
        )

    linhas: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(alvos))) as pool:
        futuros = {pool.submit(_linha_decisao, nif, nome, codigo): nif for nif, nome in alvos}
        por_nif = {nif: None for nif, _ in alvos}
        for futuro, nif in futuros.items():
            try:
                por_nif[nif] = futuro.result()
            except Exception as exc:  # noqa: BLE001 - o conjunto sobrevive a uma falha
                logger.warning("Recolha do conjunto falhou para %s: %s", nif, exc)
                por_nif[nif] = {"nif": nif, "nome": nif, "erro": str(exc), "decisao": None}
        linhas = [por_nif[nif] for nif, _ in alvos if por_nif.get(nif)]

    comparacao = _comparacao(linhas)
    perfis = _perfil_comparado(linhas)
    cruzamentos = _cruzamentos(base, linhas)
    empresas = [_linha_empresa(linha) for linha in linhas]
    avisos = list(base.get("avisos") or [])
    for empresa in empresas:
        if empresa.get("erro"):
            avisos.append(f"{empresa['nome']}: {empresa['erro']}")
        elif empresa.get("encontrada") is False:
            avisos.append(f"{empresa['nome']}: NIF não encontrado no cadastro nem nos contratos.")

    return {
        "pais": base.get("pais") or codigo,
        "pais_label": base.get("pais_label"),
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "pedido": {"empresas": len(pedidos), "analisadas": len(empresas), "max_empresas": limite},
        "empresas": empresas,
        "comparacao": comparacao,
        "perfil": perfis,
        "cruzamentos": cruzamentos,
        "grafo": base.get("grafo"),
        "atencao": _atencao(linhas),
        "totais": base.get("totais") or {},
        "leitura": _leitura(empresas, comparacao, cruzamentos),
        "avisos": avisos,
    }


__all__: Iterable[str] = ("conjunto", "MAX_EMPRESAS", "MIN_EMPRESAS")
