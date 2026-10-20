"""Grafo da Transparência: pessoas, cargos, entidades públicas e empresas.

Constrói, a partir das **declarações únicas** da Entidade para a Transparência
(recolhidas pelo módulo `/entidade-transparencia`), a rede que liga:

- **pessoas** — os titulares de cargos políticos e altos cargos públicos;
- **cargos** — o cargo/função exercido (ex.: «Presidente», «Vereador»);
- **entidades públicas** — o órgão ou organismo onde o cargo é exercido;
- **empresas** — as entidades privadas do **registo de interesses** (atividades
  profissionais, filiação associativa, sociedades, apoios e serviços prestados);
- **sedes** — o «Local da sede» de cada empresa é geocodificado
  (`api/transparencia_geo.py`) para desenhar o **mapa de onde estão as empresas**.

Relações:

| Relação | Origem → destino | Fonte |
| --- | --- | --- |
| `EXERCE` | pessoa → cargo | metadados da declaração + titularidades da EPT |
| `CARGO_EM` | cargo → entidade pública | idem |
| `ATIVIDADE` | pessoa → empresa/entidade | «Atividades profissionais, cargos e funções» |
| `PARTICIPACAO` | pessoa → empresa | «Filiação ou participação em entidades associativas», «Sociedades» |
| `BENEFICIO` | pessoa → empresa/entidade | «Apoios ou benefícios» |
| `SERVICO` | pessoa → empresa/entidade | «Serviços prestados» |

O resultado é gravado em `data/transparencia-grafo/grafo/` (JSONL + manifesto) e
indexado em `finance_ept_grafo_nos`, `finance_ept_grafo_arestas` e
`finance_ept_grafo_recolhas`. A leitura serve o grafo, a ficha de cada nó, a
lista de empresas e o mapa — sempre com a proveniência e a precisão do geo.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from api import elasticsearch_client as esc
from api import entidade_transparencia_service as ept
from api.transparencia_geo import PRECISAO_LABELS, resolver_local

logger = logging.getLogger(__name__)

DATA_DIR_ENV = "TRANSPARENCIA_GRAFO_DATA_DIR"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "transparencia-grafo"
_SUBDIR = "grafo"
_MANIFEST = "_manifest.json"

FONTE = "entidade-transparencia"
FONTE_URL = "https://entidadetransparencia.pt"

#: Tipos de nó, com o rótulo e a cor usados no grafo e na legenda.
TIPOS_NO: Dict[str, Dict[str, str]] = {
    "pessoa": {"label": "Pessoas (titulares)", "curto": "Pessoa", "cor": "#f472b6"},
    "cargo": {"label": "Cargos e funções", "curto": "Cargo", "cor": "#fbbf24"},
    "entidade": {"label": "Entidades públicas", "curto": "Entidade", "cor": "#2dd4bf"},
    "empresa": {"label": "Empresas e outras entidades", "curto": "Empresa", "cor": "#60a5fa"},
}

#: Relações entre nós, com a frase que se lê na aresta.
RELACOES: Dict[str, Dict[str, str]] = {
    "EXERCE": {"label": "exerce o cargo", "curto": "Exerce"},
    "CARGO_EM": {"label": "é cargo de", "curto": "Cargo em"},
    "ATIVIDADE": {"label": "exerce atividade em", "curto": "Atividade"},
    "PARTICIPACAO": {"label": "tem participação em", "curto": "Participação"},
    "BENEFICIO": {"label": "recebeu apoio de", "curto": "Apoio"},
    "SERVICO": {"label": "prestou serviço a", "curto": "Serviço"},
}

#: Ramos do registo de interesses que dão empresas ao grafo.
_INTERESSES_ATIVIDADE = "Atividades profissionais"
_INTERESSES_FILIACAO = "Filiação"
_INTERESSES_SOCIEDADES = "Sociedades"
_INTERESSES_APOIOS = "Apoios ou benefícios"
_INTERESSES_SERVICOS = "Serviços prestados"

#: Palavras que denunciam uma entidade pública sem id no catálogo da EPT.
_PUBLICO = (
    "public",
    "estado",
    "ministerio",
    "ministério",
    "camara municipal",
    "câmara municipal",
    "junta de freguesia",
    "instituto",
    "agencia",
    "agência",
    "autoridade",
    "universidade",
    "politecnico",
    "politécnico",
    "escola",
    "hospital",
    "fundacao",
    "fundação",
    "administracao",
    "administração",
    "seguranca social",
    "segurança social",
    "assembleia",
    "parlamento",
    "tribunal",
    "conservatoria",
    "conservatória",
    "servico",
    "serviço",
    "direcao-geral",
    "direção-geral",
    "comissao",
    "comissão",
    "conselho",
    "empresa municipal",
    "sociedade de desenvolvimento",
)

_LOTE_ES = 500
_CACHE_TTL = 30.0


# ---------------------------------------------------------------------------
# Pastas, manifesto e utilitários
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def data_dir() -> Path:
    """Pasta do módulo (`TRANSPARENCIA_GRAFO_DATA_DIR` sobrepõe-se)."""
    return Path(os.environ.get(DATA_DIR_ENV) or _DEFAULT_DATA_DIR)


def grafo_dir() -> Path:
    return data_dir() / _SUBDIR


def nos_path() -> Path:
    return grafo_dir() / "nos.jsonl"


def arestas_path() -> Path:
    return grafo_dir() / "arestas.jsonl"


def manifest_path() -> Path:
    return grafo_dir() / _MANIFEST


def read_manifest() -> Dict[str, Any]:
    caminho = manifest_path()
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Manifesto do grafo ilegível: %s", exc)
        return {}


def _write_manifest(manifest: Dict[str, Any]) -> None:
    grafo_dir().mkdir(parents=True, exist_ok=True)
    temporario = manifest_path().with_suffix(".tmp")
    temporario.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(manifest_path())


def _fold(value: Any) -> str:
    """Minúsculas sem acentos nem pontuação — chave de comparação de nomes."""
    if value is None:
        return ""
    normalizado = unicodedata.normalize("NFKD", str(value))
    sem_acentos = "".join(ch for ch in normalizado if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9\s]", " ", sem_acentos)).strip().lower()


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-") or "sem-nome"


def _nif(value: Any) -> Optional[str]:
    """NIF/NIPC válido (9 dígitos, não repetido) ou `None`."""
    digitos = re.sub(r"\D", "", str(value or ""))
    if len(digitos) != 9 or len(set(digitos)) == 1:
        return None
    return digitos


def _parece_publico(nome: Any, natureza: Any = None) -> bool:
    texto = _fold(f"{nome or ''} {natureza or ''}")
    return any(chave in texto for chave in _PUBLICO)


def _iter_jsonl(caminho: Path) -> Iterator[Dict[str, Any]]:
    if not caminho.exists():
        return
    with caminho.open("r", encoding="utf-8") as ficheiro:
        for linha in ficheiro:
            linha = linha.strip()
            if not linha:
                continue
            try:
                yield json.loads(linha)
            except json.JSONDecodeError:
                continue


def _escrever_jsonl(caminho: Path, linhas: Iterable[Dict[str, Any]]) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    total = 0
    with temporario.open("w", encoding="utf-8", newline="\n") as ficheiro:
        for linha in linhas:
            ficheiro.write(json.dumps(linha, ensure_ascii=False))
            ficheiro.write("\n")
            total += 1
    temporario.replace(caminho)
    return total


# ---------------------------------------------------------------------------
# Construção do grafo
# ---------------------------------------------------------------------------


class _Grafo:
    """Acumulador de nós e arestas durante a construção."""

    def __init__(self) -> None:
        self.nos: Dict[str, Dict[str, Any]] = {}
        self.arestas: Dict[str, Dict[str, Any]] = {}
        self.locais: Dict[str, Counter] = defaultdict(Counter)
        self.nomes: Dict[str, Counter] = defaultdict(Counter)
        self.nif_entidade: Dict[str, str] = {}
        # Linhas do registo de interesses à espera de classificação (empresa/entidade).
        self.pendentes: List[Dict[str, Any]] = []

    # ------------------------------------------------------------- nós
    def no(self, no_id: str, tipo: str, nome: str, **extra: Any) -> Dict[str, Any]:
        atual = self.nos.get(no_id)
        if atual is None:
            atual = {
                "no_id": no_id,
                "tipo": tipo,
                "subtipo": None,
                "nome": nome or no_id,
                "nome_normalizado": _fold(nome),
                "ref_id": str(extra.get("ref_id") or no_id.split(":", 1)[-1]),
                "nif": None,
                "nif_entidade": None,
                "url": None,
                "entidade_ids": set(),
                "cargos": set(),
                "anos": set(),
                "declaracoes": 0,
                "grau": 0,
                "peso": 0,
                "local_sede": None,
                "concelho": None,
                "precisao_geo": None,
                "lat": None,
                "lon": None,
                "detalhes": {},
            }
            self.nos[no_id] = atual
        for chave, valor in extra.items():
            if valor in (None, "", [], {}):
                continue
            if chave == "anos":
                atual["anos"].update(valor if isinstance(valor, (list, set, tuple)) else [valor])
            elif chave == "entidade_ids":
                atual["entidade_ids"].update(valor if isinstance(valor, (list, set, tuple)) else [valor])
            elif chave == "cargos":
                atual["cargos"].update(valor if isinstance(valor, (list, set, tuple)) else [valor])
            elif chave == "declaracoes":
                atual["declaracoes"] += int(valor or 0)
            elif chave in ("local_sede", "concelho", "precisao_geo", "lat", "lon"):
                if atual.get(chave) in (None, ""):
                    atual[chave] = valor
            elif chave == "detalhes":
                atual["detalhes"].update(valor or {})
            elif chave == "nome":
                continue
            elif chave == "ano":
                atual["anos"].add(int(valor))
            else:
                atual[chave] = valor
        if nome:
            self.nomes[no_id][nome] += 1
        return atual

    def nome_final(self, no_id: str) -> str:
        """Nome mais frequente do nó (as declarações variam na grafia)."""
        contagem = self.nomes.get(no_id)
        if not contagem:
            return self.nos[no_id]["nome"]
        return contagem.most_common(1)[0][0]

    def local(self, no_id: str, texto: Optional[str]) -> None:
        if texto:
            self.locais[no_id][str(texto).strip()] += 1

    # ---------------------------------------------------------- arestas
    def aresta(
        self,
        origem: str,
        destino: str,
        relacao: str,
        *,
        peso: int = 1,
        ano: Optional[int] = None,
        detalhe: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not origem or not destino or origem == destino:
            return
        chave = f"{origem}|{relacao}|{destino}"
        atual = self.arestas.get(chave)
        if atual is None:
            atual = {
                "aresta_id": chave,
                "origem": origem,
                "destino": destino,
                "origem_tipo": self.nos.get(origem, {}).get("tipo"),
                "destino_tipo": self.nos.get(destino, {}).get("tipo"),
                "relacao": relacao,
                "peso": 0,
                "anos": set(),
                "detalhe": {},
            }
            self.arestas[chave] = atual
        atual["peso"] += int(peso or 1)
        if ano:
            atual["anos"].add(int(ano))
        if detalhe:
            for chave_detalhe, valor in detalhe.items():
                if valor in (None, "", [], {}):
                    continue
                atual["detalhe"].setdefault(chave_detalhe, [])
                if valor not in atual["detalhe"][chave_detalhe]:
                    atual["detalhe"][chave_detalhe].append(valor)


def _id_pessoa(titular_id: Any) -> str:
    return f"pessoa:{titular_id}"


def _id_entidade(entidade_id: Any) -> str:
    return f"entidade:{entidade_id}"


def _id_cargo(cargo_id: Any, nome: Any) -> str:
    if cargo_id:
        return f"cargo:{cargo_id}"
    return f"cargo:nome:{_slug(nome)}"


def _id_alvo(grafo: _Grafo, nome: str, nif: Optional[str], natureza: Optional[str]) -> Tuple[str, str]:
    """Id e tipo do destino de uma linha de interesses.

    Um NIF que já é uma entidade do catálogo da EPT continua a ser **entidade
    pública**; os restantes organismos públicos sem id no catálogo entram como
    `entidade:nif:<nif>` (a partir da natureza/nome). Tudo o resto é empresa.
    """
    if nif and nif in grafo.nif_entidade:
        return _id_entidade(grafo.nif_entidade[nif]), "entidade"
    if _parece_publico(nome, natureza):
        return (f"entidade:nif:{nif}" if nif else f"entidade:nome:{_slug(nome)}"), "entidade"
    return (f"empresa:{nif}" if nif else f"empresa:nome:{_slug(nome)}"), "empresa"


def _ler_titularidades() -> Iterator[Dict[str, Any]]:
    return _iter_jsonl(ept.data_dir() / "catalogo" / "titularidades.jsonl")


def _declaracoes_path() -> Path:
    return ept.data_dir() / "_normalized" / "declaracoes.jsonl"


def construir(
    *,
    forcar: bool = False,
    indexar_es: bool = True,
    progresso: Optional[Dict[str, Any]] = None,
    es: Any = None,
    limite_declaracoes: Optional[int] = None,
) -> Dict[str, Any]:
    """Lê as declarações em disco, constrói o grafo e (opcionalmente) indexa-o."""
    progresso = progresso if progresso is not None else {}
    origem = _declaracoes_path()
    if not origem.exists():
        return {
            "error": "Sem declarações normalizadas em disco. Recolha primeiro o módulo /entidade-transparencia.",
            "ficheiro": str(origem),
        }
    if not forcar and nos_path().exists() and arestas_path().exists():
        manifesto = read_manifest()
        if manifesto.get("atualizado_em") and manifesto["atualizado_em"] >= _mtime_iso(origem):
            return {"reutilizado": True, "manifesto": manifesto, "nos": manifesto.get("totais", {}).get("nos", 0)}

    grafo = _Grafo()
    progresso.update({"phase": "a ler declarações", "current": origem.name, "declaracoes": 0})
    total = 0

    for declaracao in _iter_jsonl(origem):
        total += 1
        if limite_declaracoes and total > limite_declaracoes:
            break
        _absorver_declaracao(grafo, declaracao)
        if total % 500 == 0:
            progresso["declaracoes"] = total
            progresso["current"] = declaracao.get("titular") or origem.name
    progresso["declaracoes"] = total

    progresso["phase"] = "a ler titularidades"
    _absorver_titularidades(grafo, progresso)

    progresso["phase"] = "a geocodificar sedes"
    _resolver_geografia(grafo)

    progresso["phase"] = "a calcular graus"
    _calcular_graus(grafo)

    nos = [_serializar_no(no, grafo) for no in grafo.nos.values()]
    nos.sort(key=lambda item: (item["tipo"], -item["grau"], item["nome_normalizado"]))
    arestas = [_serializar_aresta(aresta) for aresta in grafo.arestas.values()]
    arestas.sort(key=lambda item: (-item["peso"], item["aresta_id"]))

    progresso["phase"] = "a gravar"
    total_nos = _escrever_jsonl(nos_path(), nos)
    total_arestas = _escrever_jsonl(arestas_path(), arestas)

    por_tipo = Counter(item["tipo"] for item in nos)
    por_relacao = Counter(item["relacao"] for item in arestas)
    empresas_geo = [item for item in nos if item["tipo"] == "empresa" and item.get("lat") is not None]
    manifesto = {
        "fonte": FONTE,
        "fonte_url": FONTE_URL,
        "atualizado_em": _now(),
        "declaracoes_lidas": total,
        "totais": {
            "nos": total_nos,
            "arestas": total_arestas,
            "pessoas": por_tipo.get("pessoa", 0),
            "cargos": por_tipo.get("cargo", 0),
            "entidades": por_tipo.get("entidade", 0),
            "empresas": por_tipo.get("empresa", 0),
            "com_geo": len(empresas_geo),
        },
        "relacoes": dict(sorted(por_relacao.items(), key=lambda par: -par[1])),
        "concelhos": _top_concelhos(empresas_geo, 15),
    }
    _write_manifest(manifesto)
    resultado: Dict[str, Any] = {
        "nos": total_nos,
        "arestas": total_arestas,
        "por_tipo": dict(por_tipo),
        "por_relacao": dict(por_relacao),
        "manifesto": manifesto,
        "pasta": str(grafo_dir()),
    }
    progresso["phase"] = "gravado"
    progresso["registos"] = total_nos + total_arestas

    if indexar_es:
        progresso["phase"] = "a indexar"
        resultado["indexacao"] = indexar(progresso=progresso, es=es)
    _invalidar_cache()
    return resultado


def _mtime_iso(caminho: Path) -> str:
    try:
        return datetime.fromtimestamp(caminho.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return ""


def _absorver_declaracao(grafo: _Grafo, declaracao: Dict[str, Any]) -> None:
    titular_id = declaracao.get("titular_id")
    nome_titular = (declaracao.get("titular") or "").strip()
    if not titular_id or not nome_titular:
        return
    ano = declaracao.get("ano")
    entidade_id = declaracao.get("entidade_id")
    entidade_nome = (declaracao.get("entidade") or "").strip()
    cargo_id = declaracao.get("cargo_id")
    cargo_nome = (declaracao.get("cargo") or "").strip()
    nif_entidade = _nif(declaracao.get("nif_entidade"))

    pessoa = _id_pessoa(titular_id)
    grafo.no(
        pessoa,
        "pessoa",
        nome_titular,
        ref_id=str(titular_id),
        anos=[ano] if ano else [],
        declaracoes=1,
        url=declaracao.get("url_publica"),
        cargos=[cargo_nome] if cargo_nome else [],
        entidade_ids=[entidade_id] if entidade_id else [],
    )

    if entidade_id and entidade_nome:
        grafo.no(
            _id_entidade(entidade_id),
            "entidade",
            entidade_nome,
            ref_id=str(entidade_id),
            nif_entidade=nif_entidade,
            anos=[ano] if ano else [],
            declaracoes=1,
        )
        if nif_entidade:
            grafo.nif_entidade.setdefault(nif_entidade, str(entidade_id))

    if cargo_nome:
        cargo = _id_cargo(cargo_id, cargo_nome)
        grafo.no(
            cargo,
            "cargo",
            cargo_nome,
            ref_id=str(cargo_id or _slug(cargo_nome)),
            anos=[ano] if ano else [],
        )
        grafo.aresta(
            pessoa,
            cargo,
            "EXERCE",
            ano=ano,
            detalhe={"entidades": [entidade_nome] if entidade_nome else [], "naturezas": [declaracao.get("natureza")]},
        )
        if entidade_id and entidade_nome:
            grafo.aresta(cargo, _id_entidade(entidade_id), "CARGO_EM", ano=ano)

    for item in declaracao.get("interesses") or []:
        _pendente(grafo, pessoa, item, ano, declaracao.get("declaracao_id"))


def _pendente(grafo: _Grafo, pessoa: str, item: Dict[str, Any], ano: Any, declaracao_id: Any) -> None:
    tipo = (item.get("tipo") or "").strip()
    valores = item.get("valores") or {}
    if not isinstance(valores, dict):
        return
    if tipo.startswith(_INTERESSES_ATIVIDADE) or tipo.startswith(_INTERESSES_FILIACAO):
        grafo_nome = valores.get("Entidade")
        nif = _nif(valores.get("NIF/NIPC"))
        local = valores.get("Local da sede")
        natureza = valores.get("Natureza e área de atuação da entidade")
        relacao = "ATIVIDADE" if tipo.startswith(_INTERESSES_ATIVIDADE) else "PARTICIPACAO"
        grafo.pendentes.append(
            {
                "pessoa": pessoa,
                "relacao": relacao,
                "nome": (grafo_nome or "").strip(),
                "nif": nif,
                "local": local,
                "natureza": natureza,
                "ano": ano,
                "detalhe": {
                    "funcao": valores.get("Cargo/Função/Atividade"),
                    "inicio": valores.get("Data de início"),
                    "fim": valores.get("Data de termo"),
                    "remunerado": valores.get("Remuneração (se aplicável)"),
                    "declaracao": f"ept:{declaracao_id}" if declaracao_id else None,
                },
            }
        )
    elif tipo.startswith(_INTERESSES_SOCIEDADES):
        grafo.pendentes.append(
            {
                "pessoa": pessoa,
                "relacao": "PARTICIPACAO",
                "nome": (valores.get("Coluna col1") or "").strip(),
                "nif": _nif(valores.get("Coluna col7")),
                "local": valores.get("Coluna col3"),
                "natureza": valores.get("Coluna col2"),
                "ano": ano,
                "detalhe": {
                    "objeto": valores.get("Coluna col2"),
                    "quota": valores.get("Coluna col4"),
                    "percentagem": valores.get("Coluna col5"),
                    "declaracao": f"ept:{declaracao_id}" if declaracao_id else None,
                },
            }
        )
    elif tipo.startswith(_INTERESSES_APOIOS):
        grafo.pendentes.append(
            {
                "pessoa": pessoa,
                "relacao": "BENEFICIO",
                "nome": (valores.get("Coluna col2") or "").strip(),
                "nif": _nif(valores.get("Coluna col6")),
                "local": None,
                "natureza": valores.get("Coluna col3"),
                "ano": ano,
                "detalhe": {
                    "apoio": valores.get("Coluna col1"),
                    "descricao": valores.get("Coluna col4"),
                    "data": valores.get("Coluna col5"),
                    "declaracao": f"ept:{declaracao_id}" if declaracao_id else None,
                },
            }
        )
    elif tipo.startswith(_INTERESSES_SERVICOS):
        grafo.pendentes.append(
            {
                "pessoa": pessoa,
                "relacao": "SERVICO",
                "nome": (valores.get("Coluna col2") or "").strip(),
                "nif": _nif(valores.get("Coluna col6")),
                "local": valores.get("Coluna col4"),
                "natureza": None,
                "ano": ano,
                "detalhe": {
                    "servico": valores.get("Coluna col1"),
                    "funcao": valores.get("Coluna col3"),
                    "data": valores.get("Coluna col5"),
                    "declaracao": f"ept:{declaracao_id}" if declaracao_id else None,
                },
            }
        )


def _absorver_titularidades(grafo: _Grafo, progresso: Dict[str, Any]) -> None:
    total = 0
    for linha in _ler_titularidades():
        total += 1
        titular_id = linha.get("titular_id")
        titular = (linha.get("titular") or "").strip()
        entidade_id = linha.get("entidade_id")
        entidade = (linha.get("entidade") or "").strip()
        cargo_nome = (linha.get("cargo") or "").strip()
        if not titular_id or not titular or not cargo_nome:
            continue
        pessoa = _id_pessoa(titular_id)
        grafo.no(pessoa, "pessoa", titular, ref_id=str(titular_id), cargos=[cargo_nome])
        cargo = _id_cargo(linha.get("cargo_id"), cargo_nome)
        grafo.no(cargo, "cargo", cargo_nome, ref_id=str(linha.get("cargo_id") or _slug(cargo_nome)))
        grafo.aresta(
            pessoa,
            cargo,
            "EXERCE",
            detalhe={
                "entidades": [entidade] if entidade else [],
                "inicio": linha.get("inicio"),
                "fim": linha.get("fim"),
            },
        )
        if entidade_id and entidade:
            grafo.no(_id_entidade(entidade_id), "entidade", entidade, ref_id=str(entidade_id))
            grafo.aresta(cargo, _id_entidade(entidade_id), "CARGO_EM")
        if total % 2000 == 0:
            progresso["current"] = f"{total} titularidades"
    progresso["titularidades"] = total


def _resolver_geografia(grafo: _Grafo) -> None:
    """Aplica as linhas de interesses pendentes e resolve a sede de cada empresa."""
    pendentes = list(grafo.pendentes)
    grafo.pendentes.clear()

    for linha in pendentes:
        nome = linha.get("nome") or ""
        nif = linha.get("nif")
        if not nome and not nif:
            continue
        alvo, tipo = _id_alvo(grafo, nome, nif, linha.get("natureza"))
        grafo.no(
            alvo,
            tipo,
            nome or (f"NIPC {nif}" if nif else "Entidade sem nome"),
            ref_id=nif or _slug(nome),
            nif=nif,
            anos=[linha["ano"]] if linha.get("ano") else [],
        )
        grafo.local(alvo, linha.get("local"))
        grafo.aresta(
            linha["pessoa"],
            alvo,
            linha["relacao"],
            ano=linha.get("ano"),
            detalhe=linha.get("detalhe"),
        )
        if tipo == "empresa" and linha.get("natureza"):
            grafo.nos[alvo].setdefault("naturezas", Counter())[linha["natureza"]] += 1

    for no_id, contagem in grafo.locais.items():
        no = grafo.nos.get(no_id)
        if not no or no.get("lat") is not None:
            continue
        # Resolve as variantes do «Local da sede» e escolhe a mais frequente com ponto.
        candidatos = Counter()
        resolvidos: Dict[str, Dict[str, Any]] = {}
        for texto, peso in contagem.items():
            resolvido = resolver_local(texto)
            if not resolvido:
                continue
            resolvidos[resolvido["concelho"]] = resolvido
            candidatos[resolvido["concelho"]] += peso
        if not candidatos:
            continue
        escolhido = candidatos.most_common(1)[0][0]
        resolvido = resolvidos[escolhido]
        no["local_sede"] = resolvido["local"]
        no["concelho"] = resolvido["concelho"]
        no["precisao_geo"] = resolvido["precisao"]
        no["lat"] = resolvido["lat"]
        no["lon"] = resolvido["lon"]

    for no in grafo.nos.values():
        naturezas = no.pop("naturezas", None)
        if naturezas:
            no["detalhes"]["natureza"] = naturezas.most_common(1)[0][0]


def _calcular_graus(grafo: _Grafo) -> None:
    vistos: Dict[str, set] = defaultdict(set)
    pesos: Dict[str, int] = Counter()
    for aresta in grafo.arestas.values():
        origem, destino = aresta["origem"], aresta["destino"]
        if origem in grafo.nos and destino in grafo.nos:
            vistos[origem].add(destino)
            vistos[destino].add(origem)
            pesos[origem] += aresta["peso"]
            pesos[destino] += aresta["peso"]
    for no_id, vizinhos in vistos.items():
        grafo.nos[no_id]["grau"] = len(vizinhos)
        grafo.nos[no_id]["peso"] = pesos[no_id]


def _serializar_no(no: Dict[str, Any], grafo: _Grafo) -> Dict[str, Any]:
    dados = dict(no)
    dados["nome"] = grafo.nome_final(no["no_id"])
    dados["nome_normalizado"] = _fold(dados["nome"])
    dados["anos"] = sorted(no["anos"])
    dados["entidade_ids"] = sorted(no["entidade_ids"])
    dados["cargos"] = sorted(no["cargos"])
    if dados.get("lat") is not None and dados.get("lon") is not None:
        # `geo_point` aceita [lon, lat] (convenção GeoJSON).
        dados["location"] = [dados["lon"], dados["lat"]]
    if not dados.get("url") and no["tipo"] == "pessoa":
        dados["url"] = f"{FONTE_URL}/#/consultardeclaracaopublica"
    return dados


def _serializar_aresta(aresta: Dict[str, Any]) -> Dict[str, Any]:
    dados = dict(aresta)
    dados["anos"] = sorted(aresta["anos"])
    return dados


def _top_concelhos(nos: Iterable[Dict[str, Any]], limite: int = 15) -> List[Dict[str, Any]]:
    contagem: Counter = Counter()
    pontos: Dict[str, Dict[str, Any]] = {}
    for no in nos:
        concelho = no.get("concelho")
        if not concelho:
            continue
        contagem[concelho] += 1
        pontos.setdefault(concelho, {"concelho": concelho, "lat": no.get("lat"), "lon": no.get("lon")})
    return [
        {**pontos[concelho], "empresas": total}
        for concelho, total in contagem.most_common(limite)
        if pontos.get(concelho, {}).get("lat") is not None
    ]


# ---------------------------------------------------------------------------
# Índice (Elasticsearch)
# ---------------------------------------------------------------------------


def _cliente(es: Any = None) -> Any:
    return es or esc.get_es_client()


def _enviar(cliente: Any, bulk: Any, acoes: List[Dict[str, Any]]) -> int:
    sucesso, _ = bulk(cliente, acoes, refresh=False, raise_on_error=False)
    return int(sucesso or 0)


def indexar(*, progresso: Optional[Dict[str, Any]] = None, es: Any = None) -> Dict[str, Any]:
    """Indexa o grafo em disco nos índices `finance_ept_grafo_*`."""
    from elasticsearch.helpers import bulk

    progresso = progresso if progresso is not None else {}
    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível", "indexados": 0}
    if not nos_path().exists():
        return {"error": "Grafo ainda não construído", "indexados": 0}

    esc.ensure_indices(cliente)
    resultado: Dict[str, Any] = {"indexados": 0, "nos": 0, "arestas": 0, "errors": []}
    lotes = [
        (esc.TRANSPARENCIA_GRAFO_NOS_INDEX, nos_path(), "no_id", "nos"),
        (esc.TRANSPARENCIA_GRAFO_ARESTAS_INDEX, arestas_path(), "aresta_id", "arestas"),
    ]
    for indice, caminho, campo_id, chave in lotes:
        if not caminho.exists():
            continue
        progresso["current"] = caminho.name
        acoes: List[Dict[str, Any]] = []
        enviados = 0
        try:
            for documento in _iter_jsonl(caminho):
                identificador = documento.get(campo_id)
                if not identificador:
                    continue
                fonte = dict(documento)
                acoes.append({"_index": indice, "_id": str(identificador), "_source": fonte})
                if len(acoes) >= _LOTE_ES:
                    enviados += _enviar(cliente, bulk, acoes)
                    acoes = []
            if acoes:
                enviados += _enviar(cliente, bulk, acoes)
        except Exception as exc:  # noqa: BLE001 - um ficheiro mau não trava o resto
            logger.exception("Grafo da Transparência: falha a indexar %s", caminho)
            resultado["errors"].append({"ficheiro": caminho.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        resultado[chave] = enviados
        resultado["indexados"] += enviados
        progresso["registos"] = resultado["indexados"]

    manifesto = read_manifest()
    try:
        cliente.index(
            index=esc.TRANSPARENCIA_GRAFO_RECOLHAS_INDEX,
            id="transparencia-grafo",
            document={
                "recolha_id": "transparencia-grafo",
                "fonte": FONTE,
                "totais": manifesto.get("totais") or {},
                "relacoes": manifesto.get("relacoes") or {},
                "atualizado_em": manifesto.get("atualizado_em") or _now(),
                "ingested_at": _now(),
            },
        )
        resultado["recolhas"] = 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("Grafo da Transparência: recolha não registada (%s)", exc)

    for indice in (esc.TRANSPARENCIA_GRAFO_NOS_INDEX, esc.TRANSPARENCIA_GRAFO_ARESTAS_INDEX):
        try:
            cliente.indices.refresh(index=indice)
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh de %s ignorado: %s", indice, exc)
    progresso["phase"] = "indexado"
    progresso["current"] = None
    return resultado


# ---------------------------------------------------------------------------
# Leitura e pesquisa
# ---------------------------------------------------------------------------

_CACHE: Dict[str, Any] = {"assinatura": None, "nos": [], "arestas": [], "por_id": {}, "vistos_em": 0.0}
_CACHE_LOCK = threading.Lock()

#: Contratação pública por NIF (portal BASE): evita repetir a agregação ao abrir
#: fichas e concelhos seguidos.
_CONTRATO_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_CONTRATO_TTL = 900.0

#: Contratação pública por NIF, na ficha do nó. Evita consultar o Portal BASE
#: (via Elasticsearch) sempre que se abre a mesma empresa; `_CONTRATO_TTL`
#: limita a idade do valor guardado.
_CONTRATO_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CONTRATO_TTL = 300.0


def _invalidar_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["assinatura"] = None


def _assinatura() -> Tuple[float, float]:
    try:
        return (nos_path().stat().st_mtime, arestas_path().stat().st_mtime)
    except OSError:
        return (0.0, 0.0)


def carregar(*, forcar: bool = False) -> Dict[str, Any]:
    """Carrega o grafo de disco, com cache curta (mtime + TTL)."""
    import time

    assinatura = _assinatura()
    with _CACHE_LOCK:
        valido = (
            _CACHE["assinatura"] == assinatura
            and _CACHE["nos"] is not None
            and (time.time() - _CACHE["vistos_em"]) < _CACHE_TTL
        )
        if valido and not forcar:
            return _CACHE
        nos = list(_iter_jsonl(nos_path()))
        arestas = list(_iter_jsonl(arestas_path()))
        _CACHE.update(
            {
                "assinatura": assinatura,
                "nos": nos,
                "arestas": arestas,
                "por_id": {no["no_id"]: no for no in nos},
                "vistos_em": time.time(),
            }
        )
        return _CACHE


def _match_no(no: Dict[str, Any], *, tipo: Optional[set], q: Optional[str], ano: Optional[int], nif: Optional[str]) -> bool:
    if tipo and no.get("tipo") not in tipo:
        return False
    if nif and no.get("nif") != nif:
        return False
    if ano and ano not in (no.get("anos") or []):
        return False
    if q:
        alvo = _fold(q)
        texto = f"{no.get('nome_normalizado') or ''} {_fold(no.get('nif'))} {_fold(no.get('concelho'))}"
        if alvo not in texto:
            return False
    return True


def _selecionar_equilibrado(nos: List[Dict[str, Any]], limite: int) -> List[Dict[str, Any]]:
    """Mantém os nós mais ligados sem esgotar a quota com um só tipo."""
    if limite <= 0 or len(nos) <= limite:
        return nos
    presentes = {no["tipo"] for no in nos}
    quota = max(1, limite // max(1, len(presentes)))
    escolhidos: List[Dict[str, Any]] = []
    vistos: set = set()
    por_tipo: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for no in sorted(nos, key=lambda item: -int(item.get("grau") or 0)):
        por_tipo[no["tipo"]].append(no)
    for tipo in sorted(presentes):
        for no in por_tipo[tipo][:quota]:
            escolhidos.append(no)
            vistos.add(no["no_id"])
    if len(escolhidos) < limite:
        for no in sorted(nos, key=lambda item: -int(item.get("grau") or 0)):
            if no["no_id"] in vistos:
                continue
            escolhidos.append(no)
            vistos.add(no["no_id"])
            if len(escolhidos) >= limite:
                break
    return escolhidos[:limite]


def grafo(
    *,
    tipo: Optional[str] = None,
    relacao: Optional[str] = None,
    q: Optional[str] = None,
    ano: Optional[int] = None,
    nif: Optional[str] = None,
    foco: Optional[str] = None,
    profundidade: int = 1,
    min_peso: int = 1,
    limit: int = 80,
    edge_limit: int = 400,
) -> Dict[str, Any]:
    """Monta o subgrafo pedido a partir dos filtros (disco como fonte de verdade)."""
    dados = carregar()
    nos: List[Dict[str, Any]] = dados["nos"]
    arestas: List[Dict[str, Any]] = dados["arestas"]
    por_id: Dict[str, Dict[str, Any]] = dados["por_id"]
    if not nos:
        return {"error": "Grafo ainda não construído", "nodes": [], "edges": []}

    tipos = {parte.strip() for parte in (tipo or "").split(",") if parte.strip()} or None
    relacoes = {parte.strip().upper() for parte in (relacao or "").split(",") if parte.strip()} or None
    if relacoes:
        relacoes = {item for item in relacoes if item in RELACOES} or None

    if foco:
        # Vizinhança a N saltos do nó escolhido.
        if foco not in por_id:
            return {"error": f"Nó desconhecido: {foco}", "nodes": [], "edges": []}
        incluidos = {foco}
        fronteira = {foco}
        for _ in range(max(1, min(3, profundidade))):
            seguinte: set = set()
            for aresta in arestas:
                if aresta["origem"] in fronteira or aresta["destino"] in fronteira:
                    for no_id in (aresta["origem"], aresta["destino"]):
                        if no_id not in incluidos:
                            seguinte.add(no_id)
            incluidos |= seguinte
            fronteira = seguinte
        candidatos = [por_id[no_id] for no_id in incluidos if no_id in por_id]
        candidatos = [no for no in candidatos if _match_no(no, tipo=tipos, q=q, ano=ano, nif=nif)]
    else:
        candidatos = [no for no in nos if _match_no(no, tipo=tipos, q=q, ano=ano, nif=nif)]

    if not candidatos:
        return {"nodes": [], "edges": [], "meta": {"total_nos": 0, "total_arestas": 0}}

    selecionados = _selecionar_equilibrado(candidatos, limit)
    ids = {no["no_id"] for no in selecionados}

    ligacoes = []
    for aresta in arestas:
        if relacoes and aresta["relacao"] not in relacoes:
            continue
        if int(aresta.get("peso") or 0) < min_peso:
            continue
        if aresta["origem"] not in ids or aresta["destino"] not in ids:
            continue
        ligacoes.append(aresta)

    if edge_limit:
        ligacoes.sort(key=lambda item: -int(item.get("peso") or 0))
        ligacoes = ligacoes[:edge_limit]

    # Sem arestas não há rede para desenhar: devolve só os nós escolhidos.
    usados = {aresta["origem"] for aresta in ligacoes} | {aresta["destino"] for aresta in ligacoes}
    if usados:
        selecionados = [no for no in selecionados if no["no_id"] in usados]

    nodes = [_no_para_grafo(no) for no in selecionados]
    edges = [_aresta_para_grafo(aresta) for aresta in ligacoes]
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "dimension_a": "no",
            "dimension_b": None,
            "metric": "ligacoes",
            "mode": "disco",
            "complete": True,
            "sample_order": "grau",
            "sample_limit": limit,
            "documents_scanned": len(nos),
            "documents_matching": len(candidatos),
            "total_nos": len(nos),
            "total_arestas": len(arestas),
            "total_empresas": sum(1 for no in nos if no.get("tipo") == "empresa"),
            "filtros": {
                "tipo": sorted(tipos) if tipos else None,
                "relacao": sorted(relacoes) if relacoes else None,
                "q": q,
                "ano": ano,
                "nif": nif,
                "foco": foco,
                "profundidade": profundidade if foco else None,
                "min_peso": min_peso,
            },
            "tipos": TIPOS_NO,
            "relacoes": RELACOES,
        },
    }


def _no_para_grafo(no: Dict[str, Any]) -> Dict[str, Any]:
    """Nó no formato dos grafos partilhados (`ContractGraphBuildNode`)."""
    tipo = no.get("tipo") or "empresa"
    return {
        "id": no["no_id"],
        "key": no.get("ref_id"),
        "label": no.get("nome"),
        "dimension": tipo,
        "type": tipo,
        "count": int(no.get("grau") or 0),
        "total_value": 0,
        "grau": int(no.get("grau") or 0),
        "peso": int(no.get("peso") or 0),
        "nif": no.get("nif"),
        "concelho": no.get("concelho"),
        "lat": no.get("lat"),
        "lon": no.get("lon"),
        "precisao_geo": no.get("precisao_geo"),
        "anos": no.get("anos") or [],
        "declaracoes": no.get("declaracoes") or 0,
    }


def _aresta_para_grafo(aresta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": aresta["origem"],
        "target": aresta["destino"],
        "count": int(aresta.get("peso") or 0),
        "value": 0,
        "relation": RELACOES.get(aresta["relacao"], {}).get("label", aresta["relacao"]),
        "relacao": aresta["relacao"],
        "anos": aresta.get("anos") or [],
    }


def no_detail(no_id: str) -> Dict[str, Any]:
    """Ficha de um nó com os vizinhos e as relações que os unem."""
    dados = carregar()
    no = dados["por_id"].get(no_id)
    if not no:
        return {"error": f"Nó desconhecido: {no_id}"}
    vizinhos: List[Dict[str, Any]] = []
    for aresta in dados["arestas"]:
        if aresta["origem"] == no_id:
            outro = aresta["destino"]
            sentido = "saida"
        elif aresta["destino"] == no_id:
            outro = aresta["origem"]
            sentido = "entrada"
        else:
            continue
        vizinho = dados["por_id"].get(outro)
        if not vizinho:
            continue
        vizinhos.append(
            {
                "no": _no_para_grafo(vizinho),
                "sentido": sentido,
                "relacao": aresta["relacao"],
                "relacao_label": RELACOES.get(aresta["relacao"], {}).get("label", aresta["relacao"]),
                "peso": aresta.get("peso") or 0,
                "anos": aresta.get("anos") or [],
                "detalhe": aresta.get("detalhe") or {},
            }
        )
    vizinhos.sort(key=lambda item: (-item["peso"], item["no"]["label"] or ""))
    resultado: Dict[str, Any] = {
        "no": no,
        "vizinhos": vizinhos,
        "total_vizinhos": len(vizinhos),
        "tipos": TIPOS_NO,
        "relacoes": RELACOES,
    }
    if no.get("nif"):
        resultado["contratacao"] = _contratacao([no["nif"]]).get(no["nif"])
    return resultado


def _adjudicantes_da_amostra(amostra: Any) -> List[str]:
    """Nomes dos adjudicantes a partir dos documentos de amostra do top_hits."""
    nomes: List[str] = []
    for hit in ((amostra or {}).get("hits") or {}).get("hits") or []:
        partes = (hit.get("_source") or {}).get("adjudicantes") or []
        if isinstance(partes, dict):
            for parte in partes.get("parsed") or []:
                nome = (parte or {}).get("nome")
                if nome and nome not in nomes:
                    nomes.append(nome)
            for bruto in partes.get("raw") or []:
                nome = str(bruto).split(" - ", 1)[-1].strip()
                if nome and nome not in nomes:
                    nomes.append(nome)
        elif isinstance(partes, list):
            for bruto in partes:
                nome = str(bruto).split(" - ", 1)[-1].strip()
                if nome and nome not in nomes:
                    nomes.append(nome)
        if len(nomes) >= 3:
            break
    return nomes[:3]


def _contratacao(nifs: Iterable[Optional[str]]) -> Dict[str, Dict[str, Any]]:
    """Contratação pública (portal BASE) de cada NIF, numa só consulta.

    Agrega, por adjudicatário, o número de contratos, o valor contratual, os anos
    e os principais adjudicantes. Uma empresa sem contratos fica com
    `contratos: 0` e `disponivel: true`; se o Elasticsearch estiver indisponível,
    `disponivel: false` — a ficha diz «indisponível» em vez de «sem contratos».
    """
    unicos = sorted({str(nif) for nif in nifs if nif})
    if not unicos:
        return {}
    agora = time.time()
    saida: Dict[str, Dict[str, Any]] = {
        nif: dados
        for nif, (quando, dados) in _CONTRATO_CACHE.items()
        if nif in unicos and agora - quando < _CONTRATO_TTL
    }
    faltam = [nif for nif in unicos if nif not in saida]
    if not faltam:
        return saida
    cliente = _cliente()
    if not cliente:
        for nif in faltam:
            saida[nif] = {"contratos": 0, "valor": 0.0, "anos": [], "adjudicantes": [], "disponivel": False}
        return saida
    corpo = {
        "size": 0,
        "query": {
            "nested": {
                "path": "adjudicatarios.parsed",
                "query": {"terms": {"adjudicatarios.parsed.nif": faltam}},
            }
        },
        "aggs": {
            "empresas": {
                "nested": {"path": "adjudicatarios.parsed"},
                "aggs": {
                    "nifs": {
                        "terms": {"field": "adjudicatarios.parsed.nif", "size": len(faltam)},
                        "aggs": {
                            "raiz": {
                                "reverse_nested": {},
                                "aggs": {
                                    "valor": {"sum": {"field": "precoContratual"}},
                                    "anos": {"terms": {"field": "Ano", "size": 20, "order": {"_key": "desc"}}},
                                    # Os adjudicantes vivem noutra lista `nested`; uma
                                    # agregação `nested` dentro de `reverse_nested` não
                                    # devolve os termos, por isso leem-se 4 documentos.
                                    "amostra": {
                                        "top_hits": {
                                            "size": 4,
                                            "sort": [{"precoContratual": {"order": "desc", "missing": "_last"}}],
                                            "_source": {"includes": ["adjudicantes"]},
                                        }
                                    },
                                },
                            }
                        },
                    }
                },
            }
        },
    }
    try:
        resposta = cliente.search(index=esc.CONTRACTS_INDEX, body=corpo)
        baldes = (((resposta.get("aggregations") or {}).get("empresas") or {}).get("nifs") or {}).get("buckets") or []
        for balde in baldes:
            nif = str(balde.get("key"))
            raiz = balde.get("raiz") or {}
            dados = {
                "contratos": int(raiz.get("doc_count") or 0),
                "valor": float((raiz.get("valor") or {}).get("value") or 0),
                "anos": [
                    int(item.get("key"))
                    for item in (raiz.get("anos") or {}).get("buckets") or []
                    if item.get("key")
                ],
                "adjudicantes": _adjudicantes_da_amostra(raiz.get("amostra")),
                "disponivel": True,
            }
            saida[nif] = dados
            _CONTRATO_CACHE[nif] = (agora, dados)
    except Exception as exc:  # noqa: BLE001 - a ficha continua sem contratação
        logger.debug("Contratação pública indisponível (%s)", exc)
        for nif in faltam:
            saida[nif] = {"contratos": 0, "valor": 0.0, "anos": [], "adjudicantes": [], "disponivel": False}
        return saida
    for nif in faltam:
        if nif in saida:
            continue
        dados = {"contratos": 0, "valor": 0.0, "anos": [], "adjudicantes": [], "disponivel": True}
        saida[nif] = dados
        _CONTRATO_CACHE[nif] = (agora, dados)
    return saida


def _relacoes_por_no(ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Relações de cada nó (por tipo e com quem), numa única passagem pelas arestas."""
    dados = carregar()
    alvo = {no_id for no_id in ids if no_id}
    saida: Dict[str, Dict[str, Any]] = {
        no_id: {"por_relacao": Counter(), "ligados": {}} for no_id in alvo
    }
    for aresta in dados["arestas"]:
        origem, destino = aresta["origem"], aresta["destino"]
        for proprio, outro, sentido in ((origem, destino, "saida"), (destino, origem, "entrada")):
            if proprio not in alvo:
                continue
            registo = saida[proprio]
            registo["por_relacao"][aresta["relacao"]] += int(aresta.get("peso") or 1)
            vizinho = dados["por_id"].get(outro)
            if not vizinho or vizinho.get("tipo") not in ("pessoa", "entidade"):
                continue
            ligado = registo["ligados"].setdefault(
                outro,
                {
                    "no_id": outro,
                    "nome": vizinho.get("nome"),
                    "tipo": vizinho.get("tipo"),
                    "relacoes": Counter(),
                    "sentido": sentido,
                    "peso": 0,
                    "anos": set(),
                },
            )
            ligado["relacoes"][aresta["relacao"]] += int(aresta.get("peso") or 1)
            ligado["peso"] += int(aresta.get("peso") or 1)
            ligado["anos"].update(aresta.get("anos") or [])
    for registo in saida.values():
        registo["ligados"] = [
            {
                **ligado,
                "relacoes": dict(ligado["relacoes"]),
                "anos": sorted(ligado["anos"]),
            }
            for ligado in sorted(registo["ligados"].values(), key=lambda item: (-item["peso"], _fold(item["nome"])))
        ]
        registo["por_relacao"] = dict(registo["por_relacao"])
    return saida


def concelho_detalhe(
    concelho: str,
    *,
    limite: int = 100,
    offset: int = 0,
    incluir_contratacao: bool = True,
) -> Dict[str, Any]:
    """Empresas de um concelho, com as relações no grafo e a contratação pública.

    É a vista que o mapa abre ao clicar num concelho: quem são as empresas com
    sede ali, que titulares lhes estão ligados (e por que relação) e quanto
    contrataram com o Estado (portal BASE).
    """
    alvo = _fold(concelho)
    dados = carregar()
    if not alvo:
        return {"error": "Concelho inválido"}
    empresas_no = [
        no
        for no in dados["nos"]
        if no.get("tipo") in ("empresa", "entidade") and _fold(no.get("concelho")) == alvo
    ]
    if not empresas_no:
        return {"error": f"Sem empresas no concelho «{concelho}»"}
    relacoes = _relacoes_por_no(no["no_id"] for no in empresas_no)
    contratos = _contratacao(no.get("nif") for no in empresas_no) if incluir_contratacao else {}

    itens: List[Dict[str, Any]] = []
    for no in empresas_no:
        relacao = relacoes.get(no["no_id"]) or {"por_relacao": {}, "ligados": []}
        item = _empresa_para_lista(no)
        item["relacoes"] = relacao["por_relacao"]
        item["ligados"] = relacao["ligados"][:6]
        item["contratacao"] = contratos.get(no.get("nif"))
        itens.append(item)

    def chave(item: Dict[str, Any]) -> tuple:
        contrato = item.get("contratacao") or {}
        return (
            -float(contrato.get("valor") or 0),
            -int(item.get("ligacoes") or 0),
            _fold(item.get("nome")),
        )

    itens.sort(key=chave)
    total = len(itens)
    pagina = itens[offset : offset + limite] if limite and limite > 0 else itens[offset:]
    primeiro = empresas_no[0]
    valores = [float((item.get("contratacao") or {}).get("valor") or 0) for item in itens]
    return {
        "concelho": primeiro.get("concelho") or concelho,
        "lat": primeiro.get("lat"),
        "lon": primeiro.get("lon"),
        "total": total,
        "offset": offset,
        "limite": limite,
        "com_contratos": sum(1 for item in itens if (item.get("contratacao") or {}).get("contratos")),
        "contratos_total": sum(int((item.get("contratacao") or {}).get("contratos") or 0) for item in itens),
        "valor_contratos": sum(valores),
        "contratacao_disponivel": any((item.get("contratacao") or {}).get("disponivel") for item in itens)
        if incluir_contratacao
        else False,
        "empresas": pagina,
        "tipos": TIPOS_NO,
        "relacoes": RELACOES,
    }


def empresas(
    *,
    q: Optional[str] = None,
    concelho: Optional[str] = None,
    com_geo: Optional[bool] = None,
    tipo: str = "empresa",
    limit: int = 100,
    offset: int = 0,
    ordenar: str = "grau",
) -> Dict[str, Any]:
    """Lista as empresas (ou entidades) do grafo, com a sede e a geolocalização."""
    dados = carregar()
    tipos = {parte.strip() for parte in (tipo or "empresa").split(",") if parte.strip()}
    itens = []
    for no in dados["nos"]:
        if no.get("tipo") not in tipos:
            continue
        if com_geo is True and no.get("lat") is None:
            continue
        if com_geo is False and no.get("lat") is not None:
            continue
        if concelho and _fold(no.get("concelho")) != _fold(concelho):
            continue
        if q:
            alvo = _fold(q)
            texto = f"{no.get('nome_normalizado')} {_fold(no.get('nif'))} {_fold(no.get('concelho'))} {_fold(no.get('local_sede'))}"
            if alvo not in texto:
                continue
        itens.append(no)
    chave = {
        "nome": lambda item: _fold(item.get("nome")),
        "ligacoes": lambda item: -int(item.get("grau") or 0),
        "grau": lambda item: -int(item.get("grau") or 0),
        "peso": lambda item: -int(item.get("peso") or 0),
    }.get(ordenar, lambda item: -int(item.get("grau") or 0))
    itens.sort(key=chave)
    total = len(itens)
    pagina = itens[offset : offset + limit] if limit and limit > 0 else itens[offset:]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_empresa_para_lista(no) for no in pagina],
        "tipos": TIPOS_NO,
    }


def _empresa_para_lista(no: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "no_id": no["no_id"],
        "nome": no.get("nome"),
        "tipo": no.get("tipo"),
        "nif": no.get("nif"),
        "local_sede": no.get("local_sede"),
        "concelho": no.get("concelho"),
        "precisao_geo": no.get("precisao_geo"),
        "precisao_label": PRECISAO_LABELS.get(no.get("precisao_geo") or "", None),
        "lat": no.get("lat"),
        "lon": no.get("lon"),
        "ligacoes": int(no.get("grau") or 0),
        "anos": no.get("anos") or [],
        "detalhes": no.get("detalhes") or {},
    }


def mapa(
    *,
    q: Optional[str] = None,
    concelho: Optional[str] = None,
    tipo: str = "empresa",
    limite_pontos: int = 1500,
    limite_concelhos: int = 60,
    limite_sem_geo: int = 200,
) -> Dict[str, Any]:
    """Pontos, agregados por concelho e lista das empresas sem coordenadas.

    As empresas sem coordenadas não entram no mapa, mas continuam a ser
    entidades do grafo: a lista (`sem_geo_itens`) permite abri-las na ficha e
    trabalhá-las como as restantes, sem as esconder atrás de um contador.
    """
    listagem = empresas(q=q, concelho=concelho, com_geo=True, tipo=tipo, limit=0, offset=0)
    itens = listagem["items"]
    agregados: Dict[str, Dict[str, Any]] = {}
    for item in itens:
        nome = item.get("concelho") or "Sem concelho"
        agregado = agregados.setdefault(
            nome,
            {"concelho": nome, "lat": item.get("lat"), "lon": item.get("lon"), "empresas": 0, "ligacoes": 0},
        )
        agregado["empresas"] += 1
        agregado["ligacoes"] += item.get("ligacoes") or 0
    concelhos = sorted(agregados.values(), key=lambda item: (-item["empresas"], -(item["ligacoes"] or 0)))
    pontos = sorted(itens, key=lambda item: (-(item.get("ligacoes") or 0), _fold(item.get("nome"))))[:limite_pontos]
    # A lista de sem coordenadas respeita os mesmos filtros (q, concelho e tipo);
    # o contador global antigo ignorava-os e não permitia abrir as entidades.
    sem_geo_listagem = empresas(
        q=q,
        concelho=concelho,
        com_geo=False,
        tipo=tipo,
        limit=max(0, min(int(limite_sem_geo), 1_000)),
        offset=0,
    )
    return {
        "total": listagem["total"],
        "com_geo": listagem["total"],
        "sem_geo": sem_geo_listagem["total"],
        "sem_geo_itens": sem_geo_listagem["items"],
        "pontos": pontos,
        "concelhos": concelhos[:limite_concelhos],
        "total_concelhos": len(concelhos),
        "precisoes": PRECISAO_LABELS,
        "tipos": TIPOS_NO,
    }


def stats() -> Dict[str, Any]:
    """Volumetria do grafo em disco e no índice."""
    manifesto = read_manifest()
    totais = dict(manifesto.get("totais") or {})
    dados = carregar()
    totais.setdefault("nos", len(dados["nos"]))
    totais.setdefault("arestas", len(dados["arestas"]))
    if "empresas" not in totais:
        totais["empresas"] = sum(1 for no in dados["nos"] if no.get("tipo") == "empresa")
    if "com_geo" not in totais:
        totais["com_geo"] = sum(
            1 for no in dados["nos"] if no.get("tipo") == "empresa" and no.get("lat") is not None
        )
    indice = {"nos": None, "arestas": None}
    cliente = _cliente()
    if cliente:
        indice["nos"] = _contagem(esc.TRANSPARENCIA_GRAFO_NOS_INDEX, cliente)
        indice["arestas"] = _contagem(esc.TRANSPARENCIA_GRAFO_ARESTAS_INDEX, cliente)
    return {
        **totais,
        "atualizado_em": manifesto.get("atualizado_em"),
        "declaracoes_lidas": manifesto.get("declaracoes_lidas"),
        "relacoes": manifesto.get("relacoes") or {},
        "concelhos": manifesto.get("concelhos") or [],
        "indice": indice,
        "fonte_indexada": indice["nos"] is not None,
        "indice_desatualizado": bool(indice["nos"] is not None and indice["nos"] != totais.get("nos")),
    }


def _contagem(indice: str, cliente: Any) -> Optional[int]:
    try:
        if not cliente.indices.exists(index=indice):
            return None
        resposta = cliente.count(index=indice)
        return int(resposta.get("count") or 0)
    except Exception:  # noqa: BLE001
        return None


def meta() -> Dict[str, Any]:
    """Proveniência, ficheiros, índices, relações e parâmetros do módulo."""
    manifesto = read_manifest()
    return {
        "fonte": FONTE,
        "fonte_url": FONTE_URL,
        "descricao": (
            "Grafo de pessoas, cargos, entidades públicas e empresas extraído das "
            "declarações únicas da Entidade para a Transparência, com a sede das "
            "empresas geocodificada para o mapa."
        ),
        "pasta": str(grafo_dir()),
        "declaracoes": str(_declaracoes_path()),
        "ficheiros": {"nos": str(nos_path()), "arestas": str(arestas_path()), "manifesto": str(manifest_path())},
        "indices": [
            esc.TRANSPARENCIA_GRAFO_NOS_INDEX,
            esc.TRANSPARENCIA_GRAFO_ARESTAS_INDEX,
            esc.TRANSPARENCIA_GRAFO_RECOLHAS_INDEX,
        ],
        "tipos": TIPOS_NO,
        "relacoes": RELACOES,
        "precisoes": PRECISAO_LABELS,
        "manifesto": {
            "atualizado_em": manifesto.get("atualizado_em"),
            "declaracoes_lidas": manifesto.get("declaracoes_lidas"),
            "totais": manifesto.get("totais") or {},
            "relacoes": manifesto.get("relacoes") or {},
        },
        "endpoints": {
            "grafo": "/transparencia-grafo/grafo",
            "no": "/transparencia-grafo/nos/{id}",
            "empresas": "/transparencia-grafo/empresas",
            "concelho": "/transparencia-grafo/concelhos/{concelho}",
            "mapa": "/transparencia-grafo/mapa",
            "construir": "/transparencia-grafo/construir",
            "indexar": "/transparencia-grafo/indexar",
            "export": "/transparencia-grafo/export.csv",
        },
        "elasticsearch": bool(_cliente()),
    }


def csv_bytes(**filtros: Any) -> bytes:
    """CSV (Excel) das empresas ou dos nós filtrados."""
    tipo = filtros.get("tipo") or "empresa"
    if filtros.get("vista") == "nos":
        dados = grafo(
            tipo=filtros.get("no_tipo"),
            q=filtros.get("q"),
            limit=int(filtros.get("limit") or 5000),
            edge_limit=0,
        )
        buffer = io.StringIO()
        escritor = csv.writer(buffer, delimiter=";", lineterminator="\n")
        escritor.writerow(["id", "tipo", "nome", "nif", "grau", "peso", "anos"])
        for no in dados.get("nodes") or []:
            escritor.writerow(
                [no["id"], no.get("type"), no.get("label"), no.get("nif") or "", no.get("grau"), no.get("peso"), ",".join(map(str, no.get("anos") or []))]
            )
        return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    listagem = empresas(
        q=filtros.get("q"),
        concelho=filtros.get("concelho"),
        com_geo=filtros.get("com_geo"),
        tipo=tipo,
        limit=int(filtros.get("limit") or 50_000),
    )
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\n")
    escritor.writerow(["id", "nome", "tipo", "nif", "local_sede", "concelho", "precisao", "lat", "lon", "ligacoes", "anos"])
    for item in listagem["items"]:
        escritor.writerow(
            [
                item["no_id"],
                item["nome"],
                item["tipo"],
                item.get("nif") or "",
                item.get("local_sede") or "",
                item.get("concelho") or "",
                item.get("precisao_label") or "",
                item.get("lat") if item.get("lat") is not None else "",
                item.get("lon") if item.get("lon") is not None else "",
                item["ligacoes"],
                ",".join(map(str, item.get("anos") or [])),
            ]
        )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------
# Trabalhos em segundo plano
# ---------------------------------------------------------------------------

_JOBS_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_KEEP = 10
_JOB_SEQ = 0
TIPOS_JOB = ("construir", "indexar")


def start_job(tipo: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Arranca a construção ou a indexação em segundo plano."""
    global _JOB_SEQ
    if tipo not in TIPOS_JOB:
        raise ValueError(f"Tipo de trabalho desconhecido: {tipo}")
    with _JOBS_LOCK:
        _JOB_SEQ += 1
        job_id = f"{tipo}-{int(datetime.now(timezone.utc).timestamp())}-{_JOB_SEQ}"
        job = {
            "job_id": job_id,
            "tipo": tipo,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "payload": payload or {},
            "progress": {"phase": "na fila"},
            "result": None,
            "error": None,
        }
        _JOBS[job_id] = job
        while len(_JOBS) > _JOBS_KEEP:
            _JOBS.pop(next(iter(_JOBS)))
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    try:
        progresso = job["progress"]
        if job["tipo"] == "construir":
            payload = job["payload"] or {}
            resultado = construir(
                forcar=bool(payload.get("forcar")),
                indexar_es=bool(payload.get("indexar", True)),
                limite_declaracoes=payload.get("limite_declaracoes"),
                progresso=progresso,
            )
        else:
            resultado = indexar(progresso=progresso)
        job["result"] = resultado
        job["status"] = "error" if isinstance(resultado, dict) and resultado.get("error") else "done"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Grafo da Transparência: trabalho %s falhou", job.get("job_id"))
        job["status"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        job["finished_at"] = _now()


def list_jobs() -> Dict[str, Any]:
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda item: item["started_at"] or "", reverse=True)
    return {"jobs": jobs}


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    return dict(job) if job else None


__all__ = [
    "RELACOES",
    "TIPOS_NO",
    "csv_bytes",
    "concelho_detalhe",
    "construir",
    "data_dir",
    "empresas",
    "grafo",
    "indexar",
    "job_status",
    "list_jobs",
    "mapa",
    "meta",
    "no_detail",
    "read_manifest",
    "start_job",
    "stats",
]
