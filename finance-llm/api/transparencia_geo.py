"""Geocodificação do «Local da sede» das entidades e empresas das declarações EPT.

A Entidade para a Transparência publica, no registo de interesses, uma coluna
**Local da sede** em texto livre («Lisboa», «Avenida da Liberdade 180A»,
«Rua da Palma, 268, 1100-394 Lisboa», «Bruxelas»). Não publica coordenadas nem
código postal em campos próprios — é preciso interpretar aquele texto.

A resolução é **offline**, pela ordem de precisão decrescente:

1. ``postal`` — código postal português (``NNNN-NNN``) na tabela do GeoNames;
2. ``alias`` — edifícios e sedes institucionais conhecidos (Palácio de S. Bento…);
3. ``cidade`` — nome da cidade/concelho, com tolerância a acentos, hífenes,
   caixa, palavras de rua à frente e gralhas (``LlSBOA``);
4. ``estrangeiro`` — cidades e países fora de Portugal (Bruxelas, Madrid…).

Sem resultado, o registo fica **sem ponto**: o mapa não inventa uma posição.
A tabela portuguesa é a mesma do módulo GLEIF (``data/gleif/geo/pt.json``, do
GeoNames e construída por ``_gleif_geo_build.py``).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

from api.gleif_geo import tables as _tabelas_geo

#: Precisões possíveis (usadas na interface e no rodapé do mapa).
PRECISAO_LABELS: Dict[str, str] = {
    "postal": "Código postal",
    "alias": "Sede institucional",
    "cidade": "Concelho/cidade",
    "estrangeiro": "Cidade estrangeira",
}

#: Edifícios e sedes institucionais que não são nomes de concelhos.
#: A chave é comparada com o texto normalizado (sem acentos, minúsculas).
ALIASES: Dict[str, Tuple[str, float, float]] = {
    "palacio de sao bento": ("Lisboa", 38.7139, -9.1535),
    "palacio de s bento": ("Lisboa", 38.7139, -9.1535),
    "sao bento": ("Lisboa", 38.7139, -9.1535),
    "assembleia da republica": ("Lisboa", 38.7139, -9.1535),
    "presidencia do conselho de ministros": ("Lisboa", 38.7078, -9.1523),
    "presidencia da republica": ("Lisboa", 38.7071, -9.1523),
    "campus xxi": ("Lisboa", 38.7223, -9.1393),
    "belem": ("Lisboa", 38.6979, -9.2063),
    "participacoes publicas": ("Lisboa", 38.7223, -9.1393),
    "infante d henrique": ("Lisboa", 38.7071, -9.1376),
    "joao crisostomo": ("Lisboa", 38.7310, -9.1465),
    # Siglas usadas nas declarações.
    "pcm": ("Lisboa", 38.7078, -9.1523),
    "presidencia republica": ("Lisboa", 38.7071, -9.1523),
    # RAM = Região Autónoma da Madeira.
    "ram": ("Funchal", 32.6669, -16.9241),
    "lixa": ("Lixa", 41.3233, -8.1697),
}

#: Cidades e países fora de Portugal com coordenadas conhecidas.
#: Evita que «Bruxelas» ou «Angola» fiquem fora do mapa.
ESTRANGEIRO: Dict[str, Tuple[str, float, float]] = {
    "bruxelas": ("Bruxelas", 50.8503, 4.3517),
    "brussels": ("Bruxelas", 50.8503, 4.3517),
    "estrasburgo": ("Estrasburgo", 48.5734, 7.7521),
    "strasbourg": ("Estrasburgo", 48.5734, 7.7521),
    "madrid": ("Madrid", 40.4168, -3.7038),
    "barcelona": ("Barcelona", 41.3874, 2.1686),
    "paris": ("Paris", 48.8566, 2.3522),
    "lyon": ("Lyon", 45.7640, 4.8357),
    "londres": ("Londres", 51.5074, -0.1278),
    "london": ("Londres", 51.5074, -0.1278),
    "amesterdao": ("Amesterdão", 52.3676, 4.9041),
    "amsterdam": ("Amesterdão", 52.3676, 4.9041),
    "luxemburgo": ("Luxemburgo", 49.6116, 6.1319),
    "luxembourg": ("Luxemburgo", 49.6116, 6.1319),
    "genebra": ("Genebra", 46.2044, 6.1432),
    "geneva": ("Genebra", 46.2044, 6.1432),
    "zurique": ("Zurique", 47.3769, 8.5417),
    "berlim": ("Berlim", 52.5200, 13.4050),
    "munique": ("Munique", 48.1351, 11.5820),
    "roma": ("Roma", 41.9028, 12.4964),
    "milao": ("Milão", 45.4642, 9.1900),
    "viena": ("Viena", 48.2082, 16.3738),
    "dublin": ("Dublin", 53.3498, -6.2603),
    "nova iorque": ("Nova Iorque", 40.7128, -74.0060),
    "new york": ("Nova Iorque", 40.7128, -74.0060),
    "washington": ("Washington", 38.9072, -77.0369),
    "brasilia": ("Brasília", -15.7939, -47.8828),
    "sao paulo": ("São Paulo", -23.5505, -46.6333),
    "rio de janeiro": ("Rio de Janeiro", -22.9068, -43.1729),
    "luanda": ("Luanda", -8.8390, 13.2894),
    "maputo": ("Maputo", -25.9692, 32.5732),
    "praia": ("Praia", 14.9330, -23.5133),
    "bissau": ("Bissau", 11.8817, -15.6178),
    "macau": ("Macau", 22.1987, 113.5439),
    "dili": ("Díli", -8.5569, 125.5603),
    "tallinn": ("Tallinn", 59.4370, 24.7536),
    "narvamnts": ("Tallinn", 59.4370, 24.7536),
    # Países (centroide aproximado).
    "angola": ("Angola", -11.2027, 17.8739),
    "mocambique": ("Moçambique", -18.6657, 35.5296),
    "espanha": ("Espanha", 40.4637, -3.7492),
    "franca": ("França", 46.2276, 2.2137),
    "belgica": ("Bélgica", 50.5039, 4.4699),
    "reino unido": ("Reino Unido", 55.3781, -3.4360),
    "brasil": ("Brasil", -14.2350, -51.9253),
    "suica": ("Suíça", 46.8182, 8.2275),
    "alemanha": ("Alemanha", 51.1657, 10.4515),
    "italia": ("Itália", 41.8719, 12.5674),
    "holanda": ("Países Baixos", 52.1326, 5.2913),
    "paises baixos": ("Países Baixos", 52.1326, 5.2913),
    "emirados arabes unidos": ("Emirados Árabes Unidos", 23.4241, 53.8478),
    "emirados arabes": ("Emirados Árabes Unidos", 23.4241, 53.8478),
    "emiratos arabes unidos": ("Emirados Árabes Unidos", 23.4241, 53.8478),
    "emiratos arabes": ("Emirados Árabes Unidos", 23.4241, 53.8478),
    "sao marino": ("São Marino", 43.9424, 12.4578),
    "venezuela": ("Venezuela", 6.4238, -66.5897),
    "finlandia": ("Finlândia", 61.9241, 25.7482),
    "jyvaskyla": ("Jyväskylä", 62.2426, 25.7473),
    "leipzig": ("Leipzig", 51.3397, 12.3731),
    "suecia": ("Suécia", 60.1282, 18.6435),
    "sweden": ("Suécia", 60.1282, 18.6435),
    "estados unidos": ("Estados Unidos", 37.0902, -95.7129),
    "eua": ("Estados Unidos", 37.0902, -95.7129),
    "canada": ("Canadá", 56.1304, -106.3468),
    "china": ("China", 35.8617, 104.1954),
    "japao": ("Japão", 36.2048, 138.2529),
    "india": ("Índia", 20.5937, 78.9629),
    "cabo verde": ("Cabo Verde", 16.5388, -23.0418),
    "guine-bissau": ("Guiné-Bissau", 11.8037, -15.1804),
    "timor-leste": ("Timor-Leste", -8.8742, 125.7275),
}

_POSTAL_RE = re.compile(r"\b(\d{4})-?(\d{3})\b")
_NUMERO_RE = re.compile(r"\b\d{3,}\b")


def _fold(value: Any) -> str:
    """Minúsculas sem acentos, com hífenes e pontuação convertidos em espaço."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    stripped = re.sub(r"[^a-zA-Z0-9\s-]", " ", stripped)
    stripped = stripped.replace("-", " ")
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _titulo(value: str) -> str:
    """Apresenta um nome de local com maiúsculas iniciais (respeita «da», «de»)."""
    minusculas = {"da", "das", "de", "do", "dos", "e", "a", "o", "as", "os", "em"}
    palavras = [p for p in re.split(r"\s+", value.strip()) if p]
    return " ".join(
        p if (i and p.lower() in minusculas) else (p[:1].upper() + p[1:].lower() if p.isupper() or p.islower() else p)
        for i, p in enumerate(palavras)
    )


@lru_cache(maxsize=1)
def _indice_cidades() -> Dict[str, Tuple[float, float]]:
    """Tabela ``cidade normalizada → (lat, lon)`` (GeoNames, Portugal)."""
    tabela = _tabelas_geo("PT") or {}
    indice: Dict[str, Tuple[float, float]] = {}
    for chave, ponto in (tabela.get("city") or {}).items():
        normalizada = _fold(chave)
        if normalizada and ponto:
            indice[normalizada] = (float(ponto[0]), float(ponto[1]))
    return indice


@lru_cache(maxsize=1)
def _indice_postal() -> Dict[str, Tuple[float, float]]:
    """Tabela ``código postal → (lat, lon)`` (GeoNames, Portugal)."""
    tabela = _tabelas_geo("PT") or {}
    indice: Dict[str, Tuple[float, float]] = {}
    for chave, ponto in (tabela.get("postal") or {}).items():
        if ponto:
            indice[str(chave).upper().replace(" ", "")] = (float(ponto[0]), float(ponto[1]))
    return indice


@lru_cache(maxsize=64)
def _por_prefixo(letra: str) -> Dict[str, Tuple[float, float]]:
    return {k: v for k, v in _indice_cidades().items() if k.startswith(letra)}


def _gralha(palavra: str) -> Optional[Tuple[str, Tuple[float, float]]]:
    """Última tentativa: corrige gralhas óbvias contra as cidades conhecidas."""
    if len(palavra) < 5:
        return None
    candidatos = _por_prefixo(palavra[0])
    if not candidatos:
        return None
    # «LlSBOA» é «Lisboa» com o «i» lido como «l» — confusão típica de OCR.
    variantes = [palavra]
    if palavra.startswith("ll"):
        variantes.append("li" + palavra[2:])
    for variante in variantes:
        semelhantes = difflib.get_close_matches(variante, list(candidatos), n=1, cutoff=0.86)
        if semelhantes:
            escolhida = semelhantes[0]
            return escolhida, candidatos[escolhida]
    return None


def _pontos_da_frase(frase: str) -> Optional[Tuple[str, Tuple[float, float], str]]:
    """Procura uma cidade em n-gramas da frase (do mais longo para o mais curto)."""
    cidades = _indice_cidades()
    palavras = frase.split()
    for inicio in range(len(palavras)):
        for tamanho in range(min(5, len(palavras) - inicio), 0, -1):
            chave = " ".join(palavras[inicio : inicio + tamanho])
            ponto = cidades.get(chave)
            if ponto:
                return chave, ponto, "cidade"
    for palavra in palavras:
        encontrada = _gralha(palavra)
        if encontrada:
            chave, ponto = encontrada
            return chave, ponto, "cidade"
    return None


def resolver_local(local: Any) -> Optional[Dict[str, Any]]:
    """Resolve «Local da sede» num ponto com precisão declarada.

    Devolve ``{local, concelho, lat, lon, precisao}`` ou ``None``. ``local`` é o
    texto original (para a ficha), ``concelho`` a forma apresentável do sítio
    encontrado (chave de agrupamento no mapa).
    """
    bruto = str(local or "").strip()
    if not bruto:
        return None
    normalizado = _fold(bruto)

    # 1. Código postal português.
    for match in _POSTAL_RE.finditer(bruto):
        codigo = f"{match.group(1)}-{match.group(2)}"
        ponto = _indice_postal().get(codigo) or _indice_postal().get(match.group(1))
        if ponto:
            return {"local": bruto, "concelho": codigo, "lat": ponto[0], "lon": ponto[1], "precisao": "postal"}

    # 2. Sedes institucionais e edifícios conhecidos.
    for alias, (nome, lat, lon) in ALIASES.items():
        if re.search(rf"(^|\s){re.escape(alias)}(\s|$)", normalizado):
            return {"local": bruto, "concelho": nome, "lat": lat, "lon": lon, "precisao": "alias"}

    # 3. Cidades e países estrangeiros.
    for chave, (nome, lat, lon) in ESTRANGEIRO.items():
        if re.search(rf"(^|\s){re.escape(chave)}(\s|$)", normalizado):
            return {"local": bruto, "concelho": nome, "lat": lat, "lon": lon, "precisao": "estrangeiro"}

    # 4. Cidades/concelhos portugueses: do segmento mais específico para o geral.
    segmentos = [parte for parte in re.split(r"[;,/]", bruto) if parte.strip()]
    for segmento in [bruto, *reversed(segmentos)]:
        limpo = _NUMERO_RE.sub(" ", segmento)
        encontrado = _pontos_da_frase(_fold(limpo))
        if encontrado:
            chave, (lat, lon), precisao = encontrado
            label = _titulo(chave)
            # Mantém a grafia da declaração quando o segmento é só o nome do local.
            original = segmento.strip(" .;,")
            if _fold(original) == chave:
                label = original
            return {"local": bruto, "concelho": label, "lat": lat, "lon": lon, "precisao": precisao}
    return None


__all__ = ["ALIASES", "ESTRANGEIRO", "PRECISAO_LABELS", "resolver_local"]
