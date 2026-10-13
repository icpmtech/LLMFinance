"""Abonos dos eleitos locais e o que cada município recebe.

O módulo junta duas fontes independentes:

1. **Direito aplicável** — a *Tabela de Abonos dos Eleitos Locais* (artigos 5.º,
   5.º-A, 7.º e 8.º da Lei n.º 11/96, de 18 de abril), transcrita para
   `data/remuneracoes/abonos_eleitos_locais.json`. A tabela está organizada por
   **escalão de eleitores** (a remuneração do presidente da junta e de câmara é
   uma percentagem da remuneração do Presidente da República) e por **rubrica**
   (remuneração mensal, despesas de representação, compensação para encargos,
   senhas de presença), dentro de cada regime (tempo inteiro, meio tempo, não
   permanência).

2. **Território** — quantos **eleitores inscritos** tem cada concelho e cada
   freguesia (recenseamento do MAI, `eleicoes.mai.gov.pt/autarquicas2025`), mais
   o **polígono** de cada um para o mapa. Sem esta segunda metade não se sabe em
   que escalão cai o território — logo não se sabe quanto é que ele recebe.

A partir das duas, o módulo calcula **os abonos de cada concelho e de cada
freguesia**: o escalão em que caem pelo número de eleitores e os valores que lhes
correspondem. Tudo é persistido em `data/remuneracoes/` (JSON) e indexado em
`finance_remuneracoes` (linhas da tabela) e `finance_remuneracoes_territorios`
(o direito aplicado a cada território).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

MAI_BASE_URL = "https://www.eleicoes.mai.gov.pt/autarquicas2025"
MAI_ASSETS = "{base}/assets/static"
MAI_COORDS_URL = MAI_ASSETS + "/territory/coords-electionId={election}-territoryId={territory}.json"
MAI_RESULT_URL = (
    MAI_ASSETS + "/result/territory-electionId={election}-territoryId={territory}-organId={organ}.json"
)
# Candidatos **eleitos**: o MAI publica aqui os presidentes de câmara eleitos, com
# o nome e a lista por que concorreram. `territoryId=null` dá o país todo, em duas
# páginas; `candidatesElected=false` devolve só as cabeças de lista.
MAI_ELEITOS_URL = (
    MAI_ASSETS
    + "/candidate/candidates-electionId={election}"
    + "-territoryId=null-votingOptionName=null-candidatesElected=true-page={page}.json"
)
MAI_ELEITOS_ESTADO_PRESIDENTE = "President"
# As páginas nacionais dos eleitos são duas; o limite é só uma trava de segurança
# para o ciclo não disparar se o MAI devolver um `numberOfPages` absurdo.
MAI_MAXIMO_PAGINAS = 20

# Árvore territorial do MAI: 1 = Portugal, daí para baixo distrito → concelho →
# freguesia, com `typeId` 5, 6 e 7 respetivamente.
MAI_ROOT_TERRITORY = 1
MAI_ELECTION_ID = 1
# Órgão 4 é a Câmara Municipal (concelhos) / Assembleia de Freguesia (freguesias).
# O número de **inscritos** é do território, não do órgão.
MAI_ORGAN_ID = 4
MAI_TIPO_DISTRITO = 5
MAI_TIPO_CONCELHO = 6
MAI_TIPO_FREGUESIA = 7

# Portugal tem 308 municípios (278 no continente + 19 nos Açores + 11 na Madeira),
# e cerca de 3259 freguesias. Servem de bitola: uma recolha que traga muito menos
# do que isto está truncada e não pode substituir o que já está bom.
MAI_TOTAL_CONCELHOS = 308

# O site do MAI está atrás do Akamai, que responde **403** a quem lhe pede
# depressa de mais — e foram precisos ~3900 pedidos. A concorrência é baixa e há
# uma pausa entre pedidos: mais vale demorar alguns minutos do que ser travado a
# meio (a recolha é retomável, mas ser travado custa mais tempo do que abrandar).
MAI_CONCORRENCIA = 2
MAI_PAUSA = 0.25

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "remuneracoes"
# Pasta configurável (usada pelos testes para trabalhar numa pasta temporária).
DATA_DIR_ENV = "REMUNERACOES_DATA_DIR"
TABELA_FILE = "abonos_eleitos_locais.json"
TERRITORIOS_FILE = "mai_territorios.json"
GEO_FILE = "geo_territorios.json"
# Eleitos nas autárquicas de 2025: presidente da câmara e vereadores por partido.
ELEITOS_FILE = "mai_eleitos.json"
# Cache da recolha do MAI, escrito **à medida que avança**: a árvore completa são
# ~3900 pedidos e, sem isto, um corte a meio (ou o servidor a pedir para abrandar)
# obrigaria a pedir tudo de novo.
RECOLHA_FILE = "mai_recolha.json"

_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Acessos a disco
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    configurado = os.environ.get(DATA_DIR_ENV)
    path = Path(configurado) if configurado else DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(name: str) -> Optional[Dict[str, Any]]:
    path = _data_dir() / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Ficheiro %s inválido: %s", name, exc)
        return None


def _write_json(name: str, payload: Dict[str, Any]) -> Path:
    path = _data_dir() / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def abonos() -> Dict[str, Any]:
    """Devolve a tabela de abonos (memória → disco → vazio)."""
    with _LOCK:
        cached = _CACHE.get("abonos")
        if cached:
            return cached
    data = _read_json(TABELA_FILE) or {"fonte": {}, "referencias": {}, "tabelas": []}
    with _LOCK:
        _CACHE["abonos"] = data
    return data


def territorios() -> Dict[str, Any]:
    """Devolve a árvore territorial recolhida do MAI (memória → disco → vazio)."""
    with _LOCK:
        cached = _CACHE.get("territorios")
        if cached:
            return cached
    data = _read_json(TERRITORIOS_FILE) or {
        "cached_at": None,
        "distritos": [],
        "concelhos": [],
        "freguesias": [],
    }
    with _LOCK:
        _CACHE["territorios"] = data
    return data


def geo() -> Dict[str, Any]:
    """Georreferenciação (Wikidata/OSM) dos concelhos e freguesias.

    O MAI não publica latitude/longitude — só os polígonos no sistema de
    coordenadas do seu próprio mapa. Sem isto, o mapa do OpenStreetMap não sabe
    onde fica cada concelho. O ficheiro é gerado por
    `scripts/georreferenciar_remuneracoes.py`.
    """
    with _LOCK:
        cached = _CACHE.get("geo")
        if cached:
            return cached
    data = _read_json(GEO_FILE) or {}
    with _LOCK:
        _CACHE["geo"] = data
    return data


# ---------------------------------------------------------------------------
# Nomes de territórios: o MAI e a Wikidata escrevem-nos de maneiras diferentes
# ---------------------------------------------------------------------------

# Formas que não distinguem territórios entre si e que, por isso, se retiram
# antes de comparar nomes («União das freguesias de Aldeia do Mato e Souto» no
# MAI é «Aldeia do Mato e Souto» na Wikidata; «Freguesia de Bemposta» é
# «Bemposta»; «Região Autónoma dos Açores» é «Açores»).
_PREFIXOS = (
    "uniao das freguesias de ",
    "uniao das freguesias do ",
    "uniao de freguesias de ",
    "uniao de freguesias do ",
    "uniao das freguesias ",
    "freguesia de ",
    "freguesia do ",
    "freguesia da ",
    "municipio de ",
    "municipio do ",
    "municipio da ",
    "concelho de ",
    "concelho do ",
    "regiao autonoma da ",
    "regiao autonoma do ",
    "regiao autonoma das ",
    "regiao autonoma dos ",
)

# Partículas de ligação, que não distinguem terras entre si.
_PARTICULAS = {"de", "da", "do", "das", "dos", "e"}

# Nomes que as duas fontes escrevem de forma irredutivelmente diferente: o MAI
# usa a designação oficial («Vila da Praia da Vitória») onde a Wikidata usa a
# corrente («Praia da Vitória»).
ALIASES_TERRITORIO = {
    "vila da praia da vitoria": "praia da vitoria",
}


def _fold(text: str) -> str:
    """Minúsculas sem acentos, para comparar nomes de territórios."""
    sem_acentos = unicodedata.normalize("NFKD", text or "")
    sem_acentos = "".join(ch for ch in sem_acentos if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sem_acentos).strip().lower()


def chave_territorio(texto: str) -> str:
    """Forma comparável de um nome de território («chave» de busca)."""
    valor = _fold(texto)
    mudou = True
    while mudou:
        mudou = False
        for prefixo in _PREFIXOS:
            if valor.startswith(prefixo):
                valor = valor[len(prefixo):].strip()
                mudou = True
    return valor


def variantes_territorio(texto: str) -> List[str]:
    """Todas as formas por que um nome pode ser reconhecido.

    O MAI distingue as terras homónimas com o concelho entre parênteses
    («Funchal (Sé) (Funchal)»), o que a Wikidata não faz; e ambas escrevem
    «A-dos-Francos» ou «A dos Francos» conforme o dia. As variantes cobrem isso.
    """
    variantes: List[str] = []

    def juntar(valor: str) -> None:
        if valor and valor not in variantes:
            variantes.append(valor)
        alias = ALIASES_TERRITORIO.get(valor)
        if alias and alias not in variantes:
            variantes.append(alias)

    base = chave_territorio(texto)
    juntar(base)
    juntar(" ".join(re.sub(r"\([^)]*\)\s*$", " ", base).split()))
    juntar(" ".join(re.sub(r"\([^)]*\)", " ", base).split()))
    sem_hifen = " ".join(base.replace("-", " ").split())
    juntar(sem_hifen)
    for entreligar in (base, sem_hifen):
        juntar(" ".join(p for p in entreligar.split() if p not in _PARTICULAS))
    return variantes


def coordenadas(nivel: str, nome: str, contexto: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Coordenadas geográficas de um concelho (`nivel='municipio'`) ou freguesia.

    `contexto` é o distrito (para concelhos) ou o concelho (para freguesias): é o
    que desfaz as homonímias, como as duas freguesias de «Sé» ou as duas vilas de
    «Lagoa» (Açores e Algarve).
    """
    dados = geo()
    if not dados:
        return None
    indice = dados.get("concelhos" if nivel == "municipio" else "freguesias") or {}
    por_nome_concelho = indice.get("por_nome_concelho") or {}
    por_nome = indice.get("por_nome") or {}

    nomes = variantes_territorio(nome)
    contextos = variantes_territorio(contexto) if contexto else []
    if contextos:
        # A Wikidata desambigua pelo pai entre parênteses («Lagoa (Açores)»).
        nomes += [f"{n} ({c})" for n in variantes_territorio(nome) for c in contextos]
        for n in nomes:
            for c in contextos:
                item = por_nome_concelho.get(f"{n}|{c}")
                if item:
                    return _ponto(item)
    for n in nomes:
        item = por_nome.get(n)
        if item:
            return _ponto(item)
    return None


def _ponto(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "lat": item.get("lat"),
        "lon": item.get("lon"),
        "wikidata": item.get("wikidata"),
        "nome_geo": item.get("nome"),
    }


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "")).strip()


# ---------------------------------------------------------------------------
# Recolha do MAI (eleitores e polígonos)
# ---------------------------------------------------------------------------

def _client() -> httpx.Client:
    return httpx.Client(
        timeout=45.0,
        headers={"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=MAI_CONCORRENCIA * 2, max_keepalive_connections=MAI_CONCORRENCIA),
    )


def _get_json(client: httpx.Client, url: str, tentativas: int = 4) -> Optional[Dict[str, Any]]:
    """Descarrega um JSON, repetindo em caso de falha transitória.

    O site do MAI está atrás do Akamai, que responde **403** quando lhe parece
    que estão a pedir-lhe depressa de mais. Nesse caso espera-se mais tempo antes
    de insistir, em vez de desistir logo do território.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            time.sleep(MAI_PAUSA)
            resp = client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            return payload if payload.get("isSuccess", True) else None
        except httpx.HTTPStatusError as exc:
            estado = exc.response.status_code
            if tentativa == tentativas:
                logger.warning("Falha a obter %s: HTTP %s", url, estado)
                return None
            time.sleep(2.0 * tentativa if estado in (403, 429) else 0.5 * tentativa)
        except Exception as exc:
            if tentativa == tentativas:
                logger.warning("Falha a obter %s: %s", url, exc)
                return None
            time.sleep(0.4 * tentativa)
    return None


def _areas(client: httpx.Client, territory_id: int) -> List[Dict[str, Any]]:
    """Polígonos dos territórios-filho (o MAI devolve-os já georreferenciados)."""
    url = MAI_COORDS_URL.format(base=MAI_BASE_URL, election=MAI_ELECTION_ID, territory=territory_id)
    payload = _get_json(client, url) or {}
    return (payload.get("data") or {}).get("mapAreas") or []


def _inscritos(client: httpx.Client, territory_id: int) -> Dict[str, Any]:
    """Inscritos, votantes e mandatos de um território."""
    url = MAI_RESULT_URL.format(
        base=MAI_BASE_URL,
        election=MAI_ELECTION_ID,
        territory=territory_id,
        organ=MAI_ORGAN_ID,
    )
    payload = _get_json(client, url) or {}
    data = payload.get("data") or {}
    resultados = data.get("currentResults") or {}
    return {
        "eleitores": resultados.get("subscribedVoters"),
        "votantes": resultados.get("totalVoters"),
        "abstencao_percentagem": (
            round(100 - resultados["percentageVoters"], 2)
            if resultados.get("percentageVoters") is not None
            else None
        ),
        "mandatos": resultados.get("totalMandates"),
        "estado": resultados.get("votingState"),
    }


def _camara_partidos(client: httpx.Client, territory_id: int) -> List[Dict[str, Any]]:
    """Votos, mandatos e presidências de cada partido na Câmara Municipal.

    É o mesmo pedido que dá os inscritos (`_inscritos`), mas do lado dos
    resultados por partido. Serve para saber quantos **vereadores** elegeu cada
    força: os mandatos da lista menos a presidência, quando a lista ganhou.
    """
    url = MAI_RESULT_URL.format(
        base=MAI_BASE_URL,
        election=MAI_ELECTION_ID,
        territory=territory_id,
        organ=MAI_ORGAN_ID,
    )
    payload = _get_json(client, url) or {}
    resultados = ((payload.get("data") or {}).get("currentResults")) or {}
    lista: List[Dict[str, Any]] = []
    for linha in resultados.get("resultsParty") or []:
        mandatos = linha.get("mandates")
        presidentes = linha.get("presidents") or 0
        lista.append({
            "sigla": linha.get("acronym"),
            "partido_id": linha.get("id"),
            "votos": linha.get("votes"),
            "percentagem": linha.get("percentage"),
            "mandatos": mandatos,
            "presidentes": presidentes,
            "vereadores": max(0, (mandatos or 0) - presidentes),
        })
    return lista


def _presidentes_camara(client: httpx.Client) -> Dict[str, Dict[str, Any]]:
    """Presidentes de câmara eleitos, por id de concelho.

    O MAI publica os eleitos em páginas nacionais (duas, para as autárquicas de
    2025), com o nome do eleito e a lista por que concorreu.
    """
    eleitos: Dict[str, Dict[str, Any]] = {}
    pagina = 1
    while pagina <= MAI_MAXIMO_PAGINAS:
        url = MAI_ELEITOS_URL.format(base=MAI_BASE_URL, election=MAI_ELECTION_ID, page=pagina)
        payload = _get_json(client, url) or {}
        data = payload.get("data") or {}
        for distrito in data.get("territories") or []:
            for concelho in distrito.get("territories") or []:
                for opcao in concelho.get("votingOptions") or []:
                    partido = opcao.get("votingOption") or {}
                    for candidato in opcao.get("candidates") or []:
                        if (candidato.get("state") or "") != MAI_ELEITOS_ESTADO_PRESIDENTE:
                            continue
                        eleitos[str(concelho.get("id"))] = {
                            "nome": candidato.get("name"),
                            "posicao": candidato.get("position"),
                            "sigla": partido.get("name"),
                            "partido": partido.get("description") or partido.get("name"),
                            "partido_id": partido.get("id"),
                        }
        total_paginas = data.get("numberOfPages") or 1
        if pagina >= total_paginas:
            break
        pagina += 1
    return eleitos


def _poligono(area: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, float]]]:
    """Junta os anéis de um território num só caminho e calcula o centroide."""
    aneis = area.get("coords")
    if isinstance(aneis, str):
        aneis = [aneis]
    pontos_x: List[float] = []
    pontos_y: List[float] = []
    for anel in aneis or []:
        valores = [v for v in str(anel).split(",") if v.strip() != ""]
        try:
            numeros = [float(v) for v in valores]
        except ValueError:
            continue
        pontos_x.extend(numeros[0::2])
        pontos_y.extend(numeros[1::2])
    if not pontos_x:
        return None, None
    caminho = ";".join(str(a) for a in (aneis or []) if a)
    centroide = {
        "x": round(min(pontos_x) + (max(pontos_x) - min(pontos_x)) / 2, 3),
        "y": round(min(pontos_y) + (max(pontos_y) - min(pontos_y)) / 2, 3),
    }
    return caminho, centroide


def _aplicar(areas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    saida = []
    for area in areas:
        caminho, centroide = _poligono(area)
        saida.append({
            "id": area.get("id"),
            "nome": _normalize_name(area.get("name") or ""),
            "poligono": caminho,
            "centroide": centroide,
        })
    return saida


class Recolha:
    """Cache da recolha do MAI, escrita à medida que avança.

    Guarda o que já foi pedido ao servidor — os polígonos por território e os
    inscritos por território — para que uma recolha possa ser retomada onde ficou
    (mesmo que tenha sido interrompida a meio dos ~3900 pedidos) e para que
    voltar a correr só peça o que falta.
    """

    def __init__(self, forcar: bool = False) -> None:
        self.forcar = forcar
        self._lock = threading.Lock()
        self._por_guardar = 0
        dados = {} if forcar else (_read_json(RECOLHA_FILE) or {})
        self.areas: Dict[str, List[Dict[str, Any]]] = dict(dados.get("areas") or {})
        self.inscritos: Dict[str, Dict[str, Any]] = dict(dados.get("inscritos") or {})
        self.camara: Dict[str, List[Dict[str, Any]]] = dict(dados.get("camara") or {})

    def areas_de(self, client: httpx.Client, territory_id: int) -> List[Dict[str, Any]]:
        chave = str(territory_id)
        with self._lock:
            gravado = self.areas.get(chave)
        if gravado is not None and not self.forcar:
            return gravado
        areas = _aplicar(_areas(client, territory_id))
        if areas:
            with self._lock:
                self.areas[chave] = areas
                self._talvez_guardar()
        return areas

    def inscritos_de(self, client: httpx.Client, territory_id: int) -> Dict[str, Any]:
        chave = str(territory_id)
        with self._lock:
            gravado = self.inscritos.get(chave)
        if gravado is not None and not self.forcar:
            return gravado
        info = _inscritos(client, territory_id)
        if info.get("eleitores") is not None:
            with self._lock:
                self.inscritos[chave] = info
                self._talvez_guardar()
        return info

    def camara_de(self, client: httpx.Client, territory_id: int) -> List[Dict[str, Any]]:
        chave = str(territory_id)
        with self._lock:
            gravado = self.camara.get(chave)
        if gravado is not None and not self.forcar:
            return gravado
        partidos = _camara_partidos(client, territory_id)
        if partidos:
            with self._lock:
                self.camara[chave] = partidos
                self._talvez_guardar()
        return partidos

    def _talvez_guardar(self) -> None:
        # Chamado com o cadeado na mão: grava de 25 em 25 pedidos, para não
        # reescrever um ficheiro de megabytes a cada resposta.
        self._por_guardar += 1
        if self._por_guardar >= 25:
            self._por_guardar = 0
            self.guardar()

    def guardar(self) -> None:
        try:
            _write_json(RECOLHA_FILE, {
                "atualizado_em": _now_iso(),
                "fonte": "MAI — Autárquicas 2025 (eleicoes.mai.gov.pt)",
                "total_areas": len(self.areas),
                "total_inscritos": len(self.inscritos),
                "total_camara": len(self.camara),
                "areas": self.areas,
                "inscritos": self.inscritos,
                "camara": self.camara,
            })
        except Exception as exc:
            logger.warning("Não foi possível guardar o progresso da recolha: %s", exc)


def collect_territories(incluir_freguesias: bool = True, forcar: bool = False) -> Dict[str, Any]:
    """Recolhe do MAI os territórios, os inscritos e os polígonos do mapa.

    Desce a árvore territorial (distrito → concelho → freguesia) e, para cada
    território, junta o número de **eleitores inscritos** com o respetivo
    polígono. Com `incluir_freguesias=False` recolhe só até ao concelho — são
    ~320 pedidos em vez de ~3900.

    É **retomável** (ver `Recolha`): o que já foi pedido fica em
    `mai_recolha.json` e só se volta a pedir o que falta, pelo que uma recolha
    interrompida continua de onde ficou. `forcar=True` pede tudo outra vez.

    Se o servidor recusar tudo (o Akamai responde 403 a quem lhe pede demasiado
    depressa), a recolha levanta `RuntimeError` em vez de **apagar** com uma
    árvore vazia o que já estava recolhido.
    """
    recolha = Recolha(forcar=forcar)
    concelhos: List[Dict[str, Any]] = []
    freguesias: List[Dict[str, Any]] = []
    distritos: List[Dict[str, Any]] = []

    with _client() as client:
        topo = recolha.areas_de(client, MAI_ROOT_TERRITORY)
        if not topo:
            recolha.guardar()
            raise RuntimeError(
                "O MAI não devolveu a lista de distritos (o servidor recusa pedidos em excesso). "
                "Nada foi substituído; o progresso ficou em mai_recolha.json — tente outra vez mais tarde."
            )

        def recolher_concelho(area: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
            distrito_id = area.get("id")
            filhos = recolha.areas_de(client, distrito_id)
            distrito = {
                "id": distrito_id,
                "nome": _normalize_name(area.get("nome") or ""),
                "poligono": area.get("poligono"),
                "centroide": area.get("centroide"),
                "concelhos": [],
                **recolha.inscritos_de(client, distrito_id),
            }
            locais: List[Dict[str, Any]] = []
            for filho in filhos:
                concelho = {
                    **filho,
                    "distrito": distrito["nome"],
                    "distrito_id": distrito_id,
                    "freguesias": [],
                    **recolha.inscritos_de(client, filho["id"]),
                }
                distrito["concelhos"].append(concelho)
                if incluir_freguesias:
                    for neto in recolha.areas_de(client, filho["id"]):
                        freguesia = {
                            **neto,
                            "distrito": distrito["nome"],
                            "distrito_id": distrito_id,
                            "concelho": concelho["nome"],
                            "concelho_id": filho["id"],
                            **recolha.inscritos_de(client, neto["id"]),
                        }
                        concelho["freguesias"].append(freguesia)
                        locais.append(freguesia)
            return distrito, locais

        with ThreadPoolExecutor(max_workers=MAI_CONCORRENCIA) as pool:
            for distrito, locais in pool.map(recolher_concelho, topo):
                distritos.append(distrito)
                concelhos.extend(distrito["concelhos"])
                freguesias.extend(locais)

    recolha.guardar()
    if not concelhos:
        raise RuntimeError(
            "A recolha não trouxe concelhos; nada foi substituído. Ver `mai_recolha.json`."
        )
    # Portugal tem 308 municípios. Uma recolha que traga claramente menos do que
    # isso significa que o servidor esteve a recusar pedidos a meio — o progresso
    # fica em `mai_recolha.json` e a próxima passagem completa o que falta, em vez
    # de se gravar uma árvore truncada como se estivesse boa.
    minimo = int(MAI_TOTAL_CONCELHOS * 0.9)
    if len(concelhos) < minimo:
        raise RuntimeError(
            f"A recolha trouxe só {len(concelhos)} de {MAI_TOTAL_CONCELHOS} concelhos "
            "(o servidor deve ter recusado pedidos a meio). Nada foi substituído; "
            "o progresso ficou em mai_recolha.json — volte a correr para continuar."
        )

    distritos.sort(key=lambda d: d["nome"])
    concelhos.sort(key=lambda c: (c["distrito"], c["nome"]))
    freguesias.sort(key=lambda f: (f["concelho"], f["nome"]))

    payload = {
        "cached_at": _now_iso(),
        "fonte": "MAI — Autárquicas 2025 (eleicoes.mai.gov.pt)",
        "fonte_url": f"{MAI_BASE_URL}/resultados",
        "eleicao": "Autárquicas 2025",
        "distritos": distritos,
        "concelhos": concelhos,
        "freguesias": freguesias,
    }
    _write_json(TERRITORIOS_FILE, payload)
    with _LOCK:
        _CACHE["territorios"] = payload
    return payload


def collect_eleitos(forcar: bool = False) -> Dict[str, Any]:
    """Recolhe os **eleitos** nas autárquicas de 2025 para cada município.

    São dois pedidos nacionais (os presidentes de câmara eleitos, com nome e
    lista) mais um pedido por concelho (os partidos na Câmara Municipal, com
    votos, mandatos e presidências). Deste último sai o número de vereadores de
    cada força: os mandatos da lista, menos a presidência quando a lista a ganhou.

    O MAI não publica os **nomes** dos vereadores — a lista de candidatos que
    disponibiliza só traz as cabeças de lista. Por isso os vereadores aparecem
    por partido, e o nome só para quem encabeça a câmara.

    É retomável como a recolha dos territórios: o que já foi pedido fica em
    `mai_recolha.json` (chave `camara`).
    """
    dados = territorios()
    concelhos = dados.get("concelhos") or []
    if not concelhos:
        raise RuntimeError(
            "Sem territórios recolhidos: corra primeiro a recolha do MAI "
            "(`collect_territories`)."
        )

    recolha = Recolha(forcar=forcar)
    with _client() as client:
        presidentes = _presidentes_camara(client)
        if not presidentes:
            recolha.guardar()
            raise RuntimeError(
                "O MAI não devolveu os presidentes de câmara eleitos. Nada foi substituído; "
                "o progresso ficou em mai_recolha.json — tente outra vez mais tarde."
            )

        def recolher(concelho: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id": concelho.get("id"),
                "nome": concelho.get("nome"),
                "distrito": concelho.get("distrito"),
                "eleitores": concelho.get("eleitores"),
                "presidente": presidentes.get(str(concelho.get("id"))),
                "camara": recolha.camara_de(client, concelho.get("id")),
            }

        with ThreadPoolExecutor(max_workers=MAI_CONCORRENCIA) as pool:
            por_concelho = list(pool.map(recolher, concelhos))

    recolha.guardar()
    com_presidente = sum(1 for c in por_concelho if c.get("presidente"))
    if com_presidente < int(MAI_TOTAL_CONCELHOS * 0.9):
        raise RuntimeError(
            f"Apenas {com_presidente} de {MAI_TOTAL_CONCELHOS} concelhos ficaram com presidente "
            "eleito identificado. Nada foi substituído; o progresso ficou em mai_recolha.json."
        )

    payload = {
        "cached_at": _now_iso(),
        "fonte": "MAI — Autárquicas 2025 (eleicoes.mai.gov.pt)",
        "fonte_url": f"{MAI_BASE_URL}/resultados",
        "eleicao": "Autárquicas 2025",
        "orgao": "Câmara Municipal",
        "nota": (
            "O MAI publica o nome do presidente de câmara eleito e os mandatos de cada "
            "lista; os nomes dos vereadores não constam dos dados abertos, pelo que os "
            "vereadores são apresentados por partido."
        ),
        "total_concelhos": len(por_concelho),
        "total_com_presidente": com_presidente,
        "concelhos": {str(c["id"]): c for c in por_concelho},
    }
    _write_json(ELEITOS_FILE, payload)
    with _LOCK:
        _CACHE["eleitos"] = payload
    return payload


def eleitos() -> Dict[str, Any]:
    """Eleitos por concelho, do ficheiro em disco (ou vazio, se não houver)."""
    with _LOCK:
        if "eleitos" in _CACHE:
            return _CACHE["eleitos"]
    payload = _read_json(ELEITOS_FILE) or {}
    with _LOCK:
        _CACHE["eleitos"] = payload
    return payload


def listar_eleitos(
    distrito: Optional[str] = None,
    q: Optional[str] = None,
    partido: Optional[str] = None,
    page: int = 1,
    size: int = 50,
) -> Dict[str, Any]:
    """Presidentes de câmara e vereadores eleitos, com os números da câmara.

    Sem recolha feita devolve uma lista vazia com a explicação em `aviso`, em vez
    de um erro: a página continua a funcionar e diz o que falta correr.
    """
    dados = eleitos()
    concelhos = list((dados.get("concelhos") or {}).values())
    if not dados:
        return {
            "total": 0,
            "page": page,
            "size": size,
            "items": [],
            "aviso": (
                "Ainda não há eleitos recolhidos. Corra `POST /remuneracoes/eleitos/recolher` "
                "para os ir buscar ao MAI."
            ),
        }

    def _perceber(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        presidente = item.get("presidente") or None
        if distrito and _fold(distrito) not in _fold(item.get("distrito") or ""):
            return None
        if partido and _fold(partido) not in _fold((presidente or {}).get("sigla") or ""):
            return None
        if q:
            termo = _fold(q)
            alvo = f"{item.get('nome') or ''} {(presidente or {}).get('nome') or ''} {(presidente or {}).get('partido') or ''}"
            if termo not in _fold(alvo):
                return None
        detalhe = eleitos_concelho(item.get("id")) or {}
        camara = (detalhe.get("vereadores") or {}).get("por_partido") or []
        return {
            "id": item.get("id"),
            "concelho": item.get("nome"),
            "distrito": item.get("distrito"),
            "eleitores": item.get("eleitores"),
            "presidente": detalhe.get("presidente"),
            "vereadores": (detalhe.get("vereadores") or {}).get("total"),
            "mandatos": (detalhe.get("vereadores") or {}).get("total_mandatos"),
            "por_partido": camara,
        }

    itens = [item for item in (_perceber(c) for c in concelhos) if item]
    itens.sort(key=lambda i: (i.get("distrito") or "", i.get("concelho") or ""))
    total = len(itens)
    from_ = max(0, (page - 1) * size)
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": itens[from_:from_ + size],
        "fonte": dados.get("fonte"),
        "fonte_url": dados.get("fonte_url"),
        "eleicao": dados.get("eleicao"),
        "nota": dados.get("nota"),
        "recolhido_em": dados.get("cached_at"),
        "facets": {
            "distritos": sorted({c.get("distrito") for c in concelhos if c.get("distrito")}),
            "partidos": sorted({
                (c.get("presidente") or {}).get("sigla")
                for c in concelhos
                if (c.get("presidente") or {}).get("sigla")
            }),
        },
    }


def eleitos_concelho(concelho_id: Any) -> Optional[Dict[str, Any]]:
    """Presidente eleito e vereadores por partido, prontos a mostrar.

    Junta o nome do presidente (do ficheiro dos eleitos) com os votos e a
    percentagem da lista (dos resultados da câmara), para que a ficha do concelho
    não tenha de cruzar as duas fontes.
    """
    dados = eleitos()
    registo = (dados.get("concelhos") or {}).get(str(concelho_id))
    if not registo:
        return None

    presidente = dict(registo.get("presidente") or {}) or None
    camara = registo.get("camara") or []
    if presidente:
        lista = next(
            (p for p in camara if p.get("sigla") and p["sigla"] == presidente.get("sigla")),
            None,
        )
        if lista:
            presidente["votos"] = lista.get("votos")
            presidente["percentagem"] = lista.get("percentagem")
            presidente["mandatos"] = lista.get("mandatos")
            presidente["vereadores"] = lista.get("vereadores")

    vereadores = sum(p.get("vereadores") or 0 for p in camara)
    return {
        "presidente": presidente,
        "vereadores": {
            "total": vereadores,
            "total_mandatos": sum(p.get("mandatos") or 0 for p in camara),
            # Só quem elegeu alguém: as listas sem mandato constam dos resultados,
            # mas não fazem parte da composição da câmara.
            "por_partido": sorted(
                (p for p in camara if (p.get("mandatos") or 0) > 0),
                key=lambda p: (-(p.get("mandatos") or 0), -(p.get("votos") or 0)),
            ),
        },
        "fonte": dados.get("fonte"),
        "fonte_url": dados.get("fonte_url"),
        "eleicao": dados.get("eleicao"),
        "nota": dados.get("nota"),
        "recolhido_em": dados.get("cached_at"),
    }


# ---------------------------------------------------------------------------
# Escalões e valores
# ---------------------------------------------------------------------------

def tabelas(nivel: Optional[str] = None, ano: Optional[int] = None) -> List[Dict[str, Any]]:
    """Tabelas de abonos disponíveis, opcionalmente filtradas."""
    saida = []
    for tabela in abonos().get("tabelas") or []:
        if nivel and tabela.get("nivel") != nivel:
            continue
        if ano and int(tabela.get("ano") or 0) != int(ano):
            continue
        saida.append(tabela)
    return saida


def tabela(nivel: str, ano: Optional[int] = None) -> Optional[Dict[str, Any]]:
    for tabela in tabelas(nivel=nivel):
        if ano is None or int(tabela.get("ano") or 0) == int(ano):
            return tabela
    return None


def escalao_por_eleitores(nivel: str, eleitores: Optional[int]) -> Optional[Dict[str, Any]]:
    """Escalão da tabela em que cai um território com este número de eleitores.

    Os escalões são percorridos por ordem decrescente de limite inferior e
    escolhe-se o primeiro cujo intervalo contém os eleitores. Quando os limites
    se sobrepõem (o escalão «7 mil eleitores e 100Km2» e o «5 mil eleitores até
    10 mil» partilham o intervalo dos 7 aos 10 mil, e ambos valem 19%), é o
    critério mais exigente — o maior número de eleitores — que decide.
    """
    if eleitores is None:
        return None
    tabela_ = tabela(nivel)
    if not tabela_:
        return None
    candidatos = [e for e in tabela_.get("escaloes") or [] if isinstance(e, dict)]
    candidatos.sort(key=lambda e: (e.get("min_eleitores") or 0), reverse=True)
    for escalao in candidatos:
        minimo = escalao.get("min_eleitores")
        maximo = escalao.get("max_eleitores")
        if minimo is not None and eleitores < minimo:
            continue
        if maximo is not None and eleitores >= maximo:
            continue
        return escalao
    return None


def _valor(rubrica: Dict[str, Any], escalao: Optional[Dict[str, Any]]) -> Optional[float]:
    if not escalao:
        return None
    return (rubrica.get("valores") or {}).get(escalao.get("id"))


def verbas(nivel: str, eleitores: Optional[int], ano: Optional[int] = None) -> List[Dict[str, Any]]:
    """Verbas da tabela aplicáveis a um território com este número de eleitores."""
    tabela_ = tabela(nivel, ano)
    if not tabela_:
        return []
    escalao = escalao_por_eleitores(nivel, eleitores)
    saida: List[Dict[str, Any]] = []
    for rubrica in tabela_.get("rubricas") or []:
        saida.append({
            "id": rubrica.get("id"),
            "regime": rubrica.get("regime"),
            "grupo": rubrica.get("grupo"),
            "cargo": rubrica.get("cargo"),
            "modalidade": rubrica.get("modalidade"),
            "natureza": rubrica.get("natureza"),
            "percentagem": (rubrica.get("percentagens") or {}).get((escalao or {}).get("id")),
            "valor": _valor(rubrica, escalao),
        })
    return saida


def _remuneracao_mensal(nivel: str, eleitores: Optional[int], ano: Optional[int] = None) -> Optional[float]:
    """Remuneração mensal do presidente (tempo inteiro, exclusividade)."""
    for verba in verbas(nivel, eleitores, ano):
        modalidade = (verba.get("modalidade") or "").lower()
        if verba.get("natureza") != "remuneracao" or verba.get("regime") != "Tempo Inteiro":
            continue
        if "exclusividade" in modalidade and "não" not in modalidade:
            return verba.get("valor")
    return None


def resumo_territorio(nivel: str, eleitores: Optional[int]) -> Dict[str, Any]:
    """O essencial de um território: escalão, remuneração mensal e verbas."""
    escalao = escalao_por_eleitores(nivel, eleitores)
    return {
        "eleitores": eleitores,
        "escalao_id": (escalao or {}).get("id"),
        "escalao": (escalao or {}).get("designacao"),
        "percentagem_pr": (escalao or {}).get("percentagem_pr"),
        "remuneracao_mensal": _remuneracao_mensal(nivel, eleitores),
        "verbas": verbas(nivel, eleitores),
    }


def _com_resumo(territorio: Dict[str, Any], nivel: str, incluir_verbas: bool = True) -> Dict[str, Any]:
    """Junta a um território o escalão, a remuneração mensal e as verbas.

    As listas longas (as 3259 freguesias de uma vez) dispensam a discriminação
    das verbas: só a remuneração mensal é mostrada, e repetir as 13 linhas da
    tabela em cada uma delas tornaria a resposta desnecessariamente grande.
    """
    doc = dict(territorio)
    doc.update(resumo_territorio(nivel, territorio.get("eleitores")))
    if not incluir_verbas:
        doc["verbas"] = []
    return doc


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def listar_concelhos(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    min_eleitores: Optional[int] = None,
    max_eleitores: Optional[int] = None,
    page: int = 1,
    size: int = 50,
) -> Dict[str, Any]:
    """Lista os concelhos com os eleitores e as remunerações que lhes cabem."""
    dados = territorios()
    concelhos = dados.get("concelhos") or []
    items = concelhos
    if q:
        termo = _fold(q)
        items = [
            c for c in items
            if termo in _fold(c.get("nome")) or termo in _fold(c.get("distrito"))
        ]
    if distrito:
        termo = _fold(distrito)
        items = [c for c in items if termo in _fold(c.get("distrito"))]
    if min_eleitores is not None:
        items = [c for c in items if (c.get("eleitores") or 0) >= min_eleitores]
    if max_eleitores is not None:
        items = [c for c in items if (c.get("eleitores") or 0) <= max_eleitores]

    total = len(items)
    from_ = max(0, (page - 1) * size)
    recorte = items[from_:from_ + size]

    # Um só dicionário para os eleitos: a lista é servida de uma vez e ir ao
    # ficheiro dos eleitos por concelho seria repetir o mesmo trabalho 308 vezes.
    eleitos_por_concelho = eleitos().get("concelhos") or {}

    def presidente_de(concelho_id: Any) -> Dict[str, Any]:
        return ((eleitos_por_concelho.get(str(concelho_id)) or {}).get("presidente")) or {}

    return {
        "total": total,
        "page": page,
        "size": size,
        "tabela": {k: v for k, v in (tabela("municipio") or {}).items() if k != "rubricas"},
        "items": [
            {
                "id": c.get("id"),
                "nome": c.get("nome"),
                "distrito": c.get("distrito"),
                "eleitores": c.get("eleitores"),
                "votantes": c.get("votantes"),
                "mandatos": c.get("mandatos"),
                "presidente": presidente_de(c.get("id")).get("nome"),
                "partido": presidente_de(c.get("id")).get("sigla"),
                "escalao_id": (escalao_por_eleitores("municipio", c.get("eleitores")) or {}).get("id"),
                "escalao": (escalao_por_eleitores("municipio", c.get("eleitores")) or {}).get("designacao"),
                "remuneracao_mensal": _remuneracao_mensal("municipio", c.get("eleitores")),
                "lat": (coordenadas("municipio", c.get("nome") or "", c.get("distrito")) or {}).get("lat"),
                "lon": (coordenadas("municipio", c.get("nome") or "", c.get("distrito")) or {}).get("lon"),
                "total_freguesias": len(c.get("freguesias") or []),
                "total_eleitores_freguesias": sum(
                    (f.get("eleitores") or 0) for f in (c.get("freguesias") or [])
                ),
            }
            for c in recorte
        ],
        "facets": {
            "distritos": sorted({c.get("distrito") for c in concelhos if c.get("distrito")}),
            "escaloes": [
                e.get("designacao")
                for e in ((tabela("municipio") or {}).get("escaloes") or [])
            ],
        },
    }


def _encontrar_concelho(concelho: str) -> Optional[Dict[str, Any]]:
    dados = territorios()
    termo = _fold(concelho)
    for c in dados.get("concelhos") or []:
        if str(c.get("id")) == str(concelho) or _fold(c.get("nome")) == termo:
            return c
    for c in dados.get("concelhos") or []:
        if termo in _fold(c.get("nome")):
            return c
    return None


def concelho_detail(concelho: str) -> Dict[str, Any]:
    """Ficha de um concelho: eleitores, escalão, abonos e as suas freguesias."""
    dados = territorios()
    encontrado = _encontrar_concelho(concelho)
    if not encontrado:
        return {"error": "Concelho não encontrado", "concelho": concelho}

    doc = _com_resumo(encontrado, "municipio")
    doc.update(_ponto(coordenadas("municipio", encontrado.get("nome") or "", encontrado.get("distrito")) or {}))

    freguesias_doc = []
    for freguesia in encontrado.get("freguesias") or []:
        resolvida = _com_resumo(freguesia, "freguesia")
        resolvida.update(
            _ponto(
                coordenadas("freguesia", freguesia.get("nome") or "", freguesia.get("concelho")) or {}
            )
        )
        freguesias_doc.append(resolvida)

    doc["freguesias"] = freguesias_doc
    doc["total_freguesias"] = len(freguesias_doc)
    doc["freguesias_sem_coordenadas"] = [
        f.get("nome") for f in freguesias_doc if f.get("lat") is None
    ]
    doc["total_eleitores_freguesias"] = sum((f.get("eleitores") or 0) for f in freguesias_doc)
    doc["remuneracoes_freguesias"] = _agregado_freguesias(freguesias_doc)
    doc["eleitos"] = eleitos_concelho(encontrado.get("id"))
    doc["fonte"] = dados.get("fonte")
    doc["fonte_url"] = dados.get("fonte_url")
    doc["fonte_geo"] = (geo() or {}).get("fonte")
    doc["recolhido_em"] = dados.get("cached_at")
    return doc


def _agregado_freguesias(freguesias: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Quantas freguesias em cada escalão e quanto pesa a despesa mensal."""
    por_escalao: Dict[str, Dict[str, Any]] = {}
    total_mensal = 0.0
    for freguesia in freguesias:
        chave = freguesia.get("escalao_id") or "sem-escalao"
        entrada = por_escalao.setdefault(chave, {
            "escalao_id": chave,
            "escalao": freguesia.get("escalao"),
            "freguesias": 0,
            "eleitores": 0,
            "remuneracao_mensal": freguesia.get("remuneracao_mensal"),
            "total_mensal": 0.0,
        })
        entrada["freguesias"] += 1
        entrada["eleitores"] += freguesia.get("eleitores") or 0
        if freguesia.get("remuneracao_mensal") is not None:
            entrada["total_mensal"] = round(
                entrada["total_mensal"] + freguesia["remuneracao_mensal"], 2
            )
            total_mensal += freguesia["remuneracao_mensal"]
    return {
        "por_escalao": sorted(por_escalao.values(), key=lambda e: -(e.get("eleitores") or 0)),
        "total_mensal_presidentes": round(total_mensal, 2),
    }


def mapa(
    nivel: str = "municipio",
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    q: Optional[str] = None,
) -> Dict[str, Any]:
    """As peças do mapa: cada território com as coordenadas, os eleitores e o abono.

    `nivel='municipio'` devolve os 308 concelhos (o mapa do país);
    `nivel='freguesia'` devolve as freguesias — todas, ou só as de um concelho,
    que é o que o mapa de um município mostra.
    """
    dados = territorios()
    if nivel == "freguesia":
        itens = list(dados.get("freguesias") or [])
        tabela_nivel = "freguesia"
        prefixo = "freguesia"
    else:
        nivel = "municipio"
        itens = list(dados.get("concelhos") or [])
        tabela_nivel = "municipio"
        prefixo = "concelho"

    if distrito:
        termo = _fold(distrito)
        itens = [i for i in itens if termo in _fold(i.get("distrito"))]
    if concelho and nivel == "freguesia":
        termo = _fold(concelho)
        itens = [i for i in itens if termo == _fold(i.get("concelho"))]
    if q:
        termo = _fold(q)
        itens = [i for i in itens if termo in _fold(i.get("nome"))]

    features = []
    sem_coordenadas = []
    for item in itens:
        ponto = coordenadas(
            nivel,
            item.get("nome") or "",
            item.get("distrito") if nivel == "municipio" else item.get("concelho"),
        )
        escalao = escalao_por_eleitores(tabela_nivel, item.get("eleitores"))
        if not ponto:
            sem_coordenadas.append(item.get("nome"))
        features.append({
            "id": item.get("id"),
            "nome": item.get("nome"),
            "distrito": item.get("distrito"),
            "concelho": item.get("nome") if nivel == "municipio" else item.get("concelho"),
            "nivel": prefixo,
            "eleitores": item.get("eleitores"),
            "votantes": item.get("votantes"),
            "mandatos": item.get("mandatos"),
            "escalao_id": (escalao or {}).get("id"),
            "escalao": (escalao or {}).get("designacao"),
            "remuneracao_mensal": _remuneracao_mensal(tabela_nivel, item.get("eleitores")),
            "lat": (ponto or {}).get("lat"),
            "lon": (ponto or {}).get("lon"),
            "wikidata": (ponto or {}).get("wikidata"),
        })

    valores = [f["eleitores"] for f in features if f.get("eleitores")]
    return {
        "nivel": prefixo,
        "total": len(features),
        "sem_coordenadas": sem_coordenadas,
        "min_eleitores": min(valores) if valores else None,
        "max_eleitores": max(valores) if valores else None,
        "tabela": {k: v for k, v in (tabela(tabela_nivel) or {}).items() if k != "rubricas"},
        "features": features,
        "fonte": dados.get("fonte"),
        "fonte_geo": (geo() or {}).get("fonte"),
    }


def freguesias(
    q: Optional[str] = None,
    concelho: Optional[str] = None,
    distrito: Optional[str] = None,
    escalao_id: Optional[str] = None,
    page: int = 1,
    size: int = 100,
) -> Dict[str, Any]:
    """Pesquisa freguesias pelos eleitores, escalão e abonos que lhes cabem."""
    items = territorios().get("freguesias") or []
    if q:
        termo = _fold(q)
        items = [f for f in items if termo in _fold(f.get("nome"))]
    if concelho:
        termo = _fold(concelho)
        items = [f for f in items if termo in _fold(f.get("concelho"))]
    if distrito:
        termo = _fold(distrito)
        items = [f for f in items if termo in _fold(f.get("distrito"))]

    # As listas não precisam da geometria (nem das verbas): a freguesia é
    # identificada pelo nome e pelos números, e os polígonos seriam a maior parte
    # da resposta.
    resolvidas = []
    for freguesia in items:
        doc = _com_resumo(freguesia, "freguesia", incluir_verbas=False)
        doc.pop("poligono", None)
        doc.pop("centroide", None)
        resolvidas.append(doc)
    if escalao_id:
        resolvidas = [f for f in resolvidas if f.get("escalao_id") == escalao_id]

    resolvidas.sort(key=lambda f: -(f.get("eleitores") or 0))
    total = len(resolvidas)
    from_ = max(0, (page - 1) * size)
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": resolvidas[from_:from_ + size],
        "tabela": {k: v for k, v in (tabela("freguesia") or {}).items() if k != "rubricas"},
    }


def stats() -> Dict[str, Any]:
    """Volumetria do que está recolhido: territórios, eleitores e escalões."""
    dados = territorios()
    concelhos = dados.get("concelhos") or []
    freguesias_lista = dados.get("freguesias") or []

    def _contar(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        contagem: Dict[str, Dict[str, Any]] = {}
        for item in items:
            escalao = escalao_por_eleitores("freguesia", item.get("eleitores"))
            chave = (escalao or {}).get("id") or "sem-escalao"
            entrada = contagem.setdefault(chave, {
                "escalao_id": chave,
                "escalao": (escalao or {}).get("designacao"),
                "count": 0,
                "eleitores": 0,
            })
            entrada["count"] += 1
            entrada["eleitores"] += item.get("eleitores") or 0
        return sorted(contagem.values(), key=lambda e: -e["count"])

    return {
        "recolhido_em": dados.get("cached_at"),
        "fonte": dados.get("fonte"),
        "fonte_geo": (geo() or {}).get("fonte"),
        "fonte_geo_url": (geo() or {}).get("fonte_url"),
        "total_distritos": len(dados.get("distritos") or []),
        "total_concelhos": len(concelhos),
        "total_freguesias": len(freguesias_lista),
        "total_eleitores_concelhos": sum((c.get("eleitores") or 0) for c in concelhos),
        "total_eleitores_freguesias": sum((f.get("eleitores") or 0) for f in freguesias_lista),
        "com_poligono": sum(1 for c in concelhos if c.get("poligono")),
        "concelhos_com_coordenadas": sum(
            1
            for c in concelhos
            if coordenadas("municipio", c.get("nome") or "", c.get("distrito"))
        ),
        "freguesias_com_coordenadas": sum(
            1
            for f in freguesias_lista
            if coordenadas("freguesia", f.get("nome") or "", f.get("concelho"))
        ),
        "tabelas": [
            {
                "ano": t.get("ano"),
                "nivel": t.get("nivel"),
                "titulo": t.get("titulo"),
                "estado": t.get("estado"),
                "total_escaloes": len(t.get("escaloes") or []),
                "total_rubricas": len(t.get("rubricas") or []),
            }
            for t in abonos().get("tabelas") or []
        ],
        "freguesias_por_escalao": _contar(freguesias_lista),
        "eleitos": {
            "recolhido_em": (eleitos() or {}).get("cached_at"),
            "total_concelhos": (eleitos() or {}).get("total_concelhos") or 0,
            "com_presidente": (eleitos() or {}).get("total_com_presidente") or 0,
            "total_vereadores": sum(
                p.get("vereadores") or 0
                for registo in ((eleitos() or {}).get("concelhos") or {}).values()
                for p in (registo.get("camara") or [])
            ),
            "partidos_com_presidente": len({
                (registo.get("presidente") or {}).get("sigla")
                for registo in ((eleitos() or {}).get("concelhos") or {}).values()
                if (registo.get("presidente") or {}).get("sigla")
            }),
        },
        "fonte_tabela": (abonos().get("fonte") or {}).get("documento"),
    }


# ---------------------------------------------------------------------------
# Importação e indexação
# ---------------------------------------------------------------------------

def importar_tabela(tabela_nova: Dict[str, Any]) -> Dict[str, Any]:
    """Importa/substitui uma tabela de abonos (ex.: a dos municípios).

    A tabela é identificada por `ano` + `nivel`; importar a mesma combinação
    substitui a anterior, para que uma reimportação corrija em vez de duplicar.
    """
    nivel = (tabela_nova.get("nivel") or "").strip().lower()
    if nivel not in ("municipio", "freguesia"):
        return {"error": "`nivel` tem de ser `municipio` ou `freguesia`", "imported": 0}
    if "ano" not in tabela_nova:
        return {"error": "`ano` é obrigatório", "imported": 0}
    if not tabela_nova.get("escaloes"):
        return {"error": "A tabela tem de trazer pelo menos um escalão", "imported": 0}

    atual = abonos()
    tabelas_atuais = [t for t in (atual.get("tabelas") or [])]
    tabela_nova = {**tabela_nova, "ano": int(tabela_nova["ano"]), "nivel": nivel}
    tabela_nova.setdefault("estado", "importada")
    tabelas_atuais = [
        t for t in tabelas_atuais
        if not (int(t.get("ano") or 0) == tabela_nova["ano"] and t.get("nivel") == nivel)
    ]
    tabelas_atuais.append(tabela_nova)
    atual["tabelas"] = sorted(tabelas_atuais, key=lambda t: (-int(t.get("ano") or 0), t.get("nivel") or ""))
    atual["gerado_em"] = _now_iso()
    _write_json(TABELA_FILE, atual)
    with _LOCK:
        _CACHE["abonos"] = atual

    indexado = indexar(apenas_tabelas=True)
    return {
        "imported": 1,
        "ano": tabela_nova["ano"],
        "nivel": nivel,
        "total_escaloes": len(tabela_nova.get("escaloes") or []),
        "total_rubricas": len(tabela_nova.get("rubricas") or []),
        "indexado": indexado,
    }


def _docs_tabela() -> List[Dict[str, Any]]:
    """Uma linha da tabela de abonos por documento."""
    documentos: List[Dict[str, Any]] = []
    fonte = abonos().get("fonte") or {}
    for tabela_ in abonos().get("tabelas") or []:
        escaloes = {e.get("id"): e for e in (tabela_.get("escaloes") or []) if e.get("id")}
        for rubrica in tabela_.get("rubricas") or []:
            valores = []
            for escalao_id, escalao in escaloes.items():
                valores.append({
                    "escalao_id": escalao_id,
                    "escalao": escalao.get("designacao"),
                    "min_eleitores": escalao.get("min_eleitores"),
                    "max_eleitores": escalao.get("max_eleitores"),
                    "percentagem_pr": escalao.get("percentagem_pr"),
                    "valor": (rubrica.get("valores") or {}).get(escalao_id),
                    "percentagem": (rubrica.get("percentagens") or {}).get(escalao_id),
                })
            documentos.append({
                "doc_id": rubrica.get("id"),
                "ano": tabela_.get("ano"),
                "nivel": tabela_.get("nivel"),
                "tabela_titulo": tabela_.get("titulo"),
                "regime": rubrica.get("regime"),
                "grupo": rubrica.get("grupo"),
                "cargo": rubrica.get("cargo"),
                "modalidade": rubrica.get("modalidade"),
                "natureza": rubrica.get("natureza"),
                "base_legal": fonte.get("base_legal"),
                "fonte": fonte.get("documento"),
                "valores": valores,
            })
    return documentos


def _docs_territorios() -> List[Dict[str, Any]]:
    """O direito aplicado a cada concelho e a cada freguesia."""
    dados = territorios()
    recolhido = dados.get("cached_at")
    fonte = dados.get("fonte")
    fonte_url = dados.get("fonte_url")
    documentos: List[Dict[str, Any]] = []

    def _doc(territorio: Dict[str, Any], nivel: str, prefixo: str) -> Dict[str, Any]:
        resumo = resumo_territorio(nivel, territorio.get("eleitores"))
        concelho = territorio.get("nome") if prefixo == "concelho" else territorio.get("concelho")
        ponto = coordenadas(
            nivel, territorio.get("nome") or "", territorio.get("distrito" if prefixo == "concelho" else "concelho")
        ) or {}
        eleitos_doc = eleitos_concelho(territorio.get("id")) if prefixo == "concelho" else None
        presidente = (eleitos_doc or {}).get("presidente") or {}
        return {
            "doc_id": f"{prefixo}-{territorio.get('id')}",
            "territory_id": territorio.get("id"),
            "nome": territorio.get("nome"),
            "nome_keyword": territorio.get("nome"),
            "nivel": nivel,
            "tipo_territorio": MAI_TIPO_CONCELHO if prefixo == "concelho" else MAI_TIPO_FREGUESIA,
            "distrito": territorio.get("distrito"),
            "distrito_keyword": territorio.get("distrito"),
            "concelho": concelho,
            "concelho_keyword": concelho,
            "concelho_id": territorio.get("id") if prefixo == "concelho" else territorio.get("concelho_id"),
            "eleitores": territorio.get("eleitores"),
            "votantes": territorio.get("votantes"),
            "abstencao_percentagem": territorio.get("abstencao_percentagem"),
            "mandatos": territorio.get("mandatos"),
            "presidente": presidente.get("nome"),
            "partido": presidente.get("sigla"),
            "partido_descricao": presidente.get("partido"),
            "vereadores": ((eleitos_doc or {}).get("vereadores") or {}).get("total"),
            "camara": [
                {
                    "sigla": p.get("sigla"),
                    "votos": p.get("votos"),
                    "percentagem": p.get("percentagem"),
                    "mandatos": p.get("mandatos"),
                    "presidentes": p.get("presidentes"),
                    "vereadores": p.get("vereadores"),
                }
                for p in ((eleitos_doc or {}).get("vereadores") or {}).get("por_partido") or []
            ],
            "escalao_id": resumo.get("escalao_id"),
            "escalao": resumo.get("escalao"),
            "remuneracao_mensal": resumo.get("remuneracao_mensal"),
            "verbas": [
                {k: v for k, v in verba.items() if k != "percentagem"}
                for verba in resumo.get("verbas") or []
            ],
            "poligono": territorio.get("poligono"),
            "poligono_pontos": len((territorio.get("poligono") or "").split(",")),
            "centroide": territorio.get("centroide"),
            "lat": ponto.get("lat"),
            "lon": ponto.get("lon"),
            "localizacao": (
                {"lat": ponto["lat"], "lon": ponto["lon"]}
                if ponto.get("lat") is not None and ponto.get("lon") is not None
                else None
            ),
            "fonte": fonte,
            "fonte_url": fonte_url,
            "recolhido_em": recolhido,
        }

    for concelho in dados.get("concelhos") or []:
        documentos.append(_doc(concelho, "municipio", "concelho"))
    for freguesia in dados.get("freguesias") or []:
        documentos.append(_doc(freguesia, "freguesia", "freguesia"))
    return documentos


def indexar(apenas_tabelas: bool = False) -> Dict[str, Any]:
    """Indexa a tabela de abonos e (salvo `apenas_tabelas`) os territórios."""
    try:
        from api.elasticsearch_client import (
            get_es_client,
            index_remuneracoes_bulk,
            index_remuneracoes_territorios_bulk,
        )
    except Exception as exc:  # pragma: no cover - import sempre disponível
        return {"error": str(exc)}

    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    saida = {"tabela": index_remuneracoes_bulk(_docs_tabela(), es=client)}
    if not apenas_tabelas:
        saida["territorios"] = index_remuneracoes_territorios_bulk(_docs_territorios(), es=client)
    return saida


def refresh(
    incluir_freguesias: bool = True,
    reindexar: bool = True,
    forcar: bool = False,
    incluir_eleitos: bool = True,
) -> Dict[str, Any]:
    """Recolhe tudo o que o módulo precisa e reindexa.

    São três fontes independentes: o **recenseamento** e a cartografia do MAI
    (eleitores e polígonos), as **coordenadas** da Wikidata (as que servem o
    OpenStreetMap) e os **eleitos** das autárquicas de 2025 (presidente da câmara
    e vereadores por partido). Uma falha numa não impede as outras — e a
    georreferenciação só se repete quando ainda não há coordenadas, porque a
    Wikidata muda ainda menos do que o recenseamento.

    A recolha do MAI é retomável: só volta a pedir o que falta (`forcar=True`
    obriga a pedir tudo outra vez).
    """
    dados = collect_territories(incluir_freguesias=incluir_freguesias, forcar=forcar)
    resultado: Dict[str, Any] = {
        "recolhido_em": dados.get("cached_at"),
        "total_distritos": len(dados.get("distritos") or []),
        "total_concelhos": len(dados.get("concelhos") or []),
        "total_freguesias": len(dados.get("freguesias") or []),
        "sem_eleitores": sum(
            1
            for registo in (dados.get("concelhos") or []) + (dados.get("freguesias") or [])
            if registo.get("eleitores") is None
        ),
    }

    if incluir_eleitos:
        try:
            eleitos_recolhidos = collect_eleitos(forcar=forcar)
            resultado["eleitos"] = {
                "total_concelhos": eleitos_recolhidos.get("total_concelhos"),
                "com_presidente": eleitos_recolhidos.get("total_com_presidente"),
            }
        except Exception as exc:
            resultado["eleitos"] = {"error": str(exc)}

    if forcar or not geo():
        try:
            geo_novos = georreferenciar()
            resultado["geo"] = {
                "concelhos": len(geo_novos["concelhos"]["por_nome"])
                + len(geo_novos["concelhos"]["por_nome_concelho"]),
                "freguesias": len(geo_novos["freguesias"]["por_nome"])
                + len(geo_novos["freguesias"]["por_nome_concelho"]),
            }
        except Exception as exc:
            resultado["geo"] = {"error": str(exc)}

    if reindexar:
        resultado["indexado"] = indexar()
    return resultado


def limpar_cache() -> None:
    """Esquece o que está em memória (útil nos testes)."""
    with _LOCK:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# Georreferenciação (Wikidata → OpenStreetMap)
# ---------------------------------------------------------------------------

# As classes da própria Wikidata para Portugal.
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_CLASSE_MUNICIPIO = "Q13217644"
WIKIDATA_CLASSE_FREGUESIA = "Q1131296"

# Casos em que as duas fontes não casam por nome nenhum: a Wikidata guarda o
# município de **Lagoa (Açores)** como `Q564759` sem o ligar à região autónoma
# (o pai do item não é «Açores»), pelo que nem o nome nem o distrito aproximam as
# duas entradas. O QID foi confirmado à mão e a chave é «nome|distrito» do MAI.
_CORRECOES_GEO = {
    ("lagoa", "acores"): "Q564759",
}


def _wikidata(consulta: str, tentativas: int = 3) -> List[Dict[str, Any]]:
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = httpx.get(
                WIKIDATA_ENDPOINT,
                params={"query": consulta, "format": "json"},
                headers={
                    "User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)",
                    "Accept": "application/sparql-results+json",
                },
                timeout=180.0,
            )
            resposta.raise_for_status()
            return resposta.json()["results"]["bindings"]
        except Exception as exc:
            if tentativa == tentativas:
                logger.warning("Falha a consultar a Wikidata: %s", exc)
                return []
            time.sleep(5 * tentativa)
    return []


def _divisoes_wikidata(classe: str) -> List[Dict[str, Any]]:
    """Divisões administrativas **atuais** de uma classe (municípios ou freguesias).

    As extintas têm data de dissolução (`P576`) e ficam de fora; e exige-se que o
    item esteja **dentro de** outro (`P131`), para não trazer coordenadas de
    sítios que não interessam.
    """
    consulta = f"""
SELECT DISTINCT ?item ?itemLabel ?coord ?paiLabel WHERE {{
  ?item wdt:P31 wd:{classe} ;
        wdt:P625 ?coord ;
        wdt:P131 ?pai .
  FILTER NOT EXISTS {{ ?item wdt:P576 [] }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
}}
"""
    saida: List[Dict[str, Any]] = []
    vistos: set = set()
    for linha in _wikidata(consulta):
        # `?coord` vem como "Point(lon lat)" em WKT.
        coord = linha["coord"]["value"]
        dentro = coord[coord.find("(") + 1:coord.find(")")].split()
        if len(dentro) != 2:
            continue
        qid = linha["item"]["value"].rsplit("/", 1)[-1]
        if qid in vistos:
            continue
        vistos.add(qid)
        lon, lat = float(dentro[0]), float(dentro[1])
        saida.append({
            "wikidata": qid,
            "nome": linha["itemLabel"]["value"],
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "pai": (linha.get("paiLabel") or {}).get("value"),
        })
    return saida


def _indexar_geo(
    itens: List[Dict[str, Any]],
    correcoes: Optional[Dict[tuple, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Índice de busca em duas camadas.

    Como há muitas freguesias com o mesmo nome («Sé», «Santa Maria», «São Pedro»):

    * ``por_nome_concelho`` — «nome|concelho»: é o que decide, porque o concelho
      desfaz a ambiguidade (aqui cabem as variantes todas, incluindo as que
      ignoram hífenes e partículas de ligação);
    * ``por_nome`` — só nomes **inequívocos**: um nome repetido não entra, para
      não se correr o risco de pôr a freguesia no concelho errado.
    """
    por_nome_concelho: Dict[str, Dict[str, Any]] = {}
    por_nome: Dict[str, Dict[str, Any]] = {}
    ambiguos: set = set()
    for item in itens:
        for chave in variantes_territorio(item["nome"]):
            if chave in por_nome:
                ambiguos.add(chave)
            por_nome.setdefault(chave, item)
            for pai in variantes_territorio(item["pai"]) if item.get("pai") else []:
                por_nome_concelho.setdefault(f"{chave}|{pai}", item)
    for chave in ambiguos:
        por_nome.pop(chave, None)
    if correcoes:
        por_qid = {item["wikidata"]: item for item in itens}
        for (nome, contexto), qid in correcoes.items():
            item = por_qid.get(qid)
            if item:
                por_nome_concelho[f"{nome}|{contexto}"] = item
    return {"por_nome": por_nome, "por_nome_concelho": por_nome_concelho}


def georreferenciar() -> Dict[str, Any]:
    """Vai buscar à Wikidata as coordenadas dos concelhos e das freguesias.

    O MAI não publica latitude/longitude — os polígonos que serve vivem no sistema
    de coordenadas do seu próprio mapa. Sem estas coordenadas, o mapa do
    OpenStreetMap não sabe onde fica cada concelho. O resultado fica em
    `geo_territorios.json` (re-descarregável, como a árvore do MAI).
    """
    municipios = _divisoes_wikidata(WIKIDATA_CLASSE_MUNICIPIO)
    freguesias = _divisoes_wikidata(WIKIDATA_CLASSE_FREGUESIA)
    payload = {
        "gerado_em": _now_iso(),
        "fonte": "Wikidata (coordenadas que servem o OpenStreetMap)",
        "fonte_url": WIKIDATA_ENDPOINT,
        "licenca": "CC0",
        "classes": {"municipio": WIKIDATA_CLASSE_MUNICIPIO, "freguesia": WIKIDATA_CLASSE_FREGUESIA},
        "concelhos": _indexar_geo(municipios, _CORRECOES_GEO),
        "freguesias": _indexar_geo(freguesias),
    }
    _write_json(GEO_FILE, payload)
    with _LOCK:
        _CACHE["geo"] = payload
    return payload
