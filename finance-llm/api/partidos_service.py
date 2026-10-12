"""Partidos políticos e as suas contas (Tribunal Constitucional + CNE).

O módulo junta duas fontes oficiais e complementares:

* **Tribunal Constitucional — Financiamento Partidário**
  (`tribunalconstitucional.pt/tc/contas_eleicoes-partidos.html`). Para cada ano
  (2004→) a página anual publica, em secções fixas, os documentos da Entidade
  das Contas e Financiamentos Políticos (ECFP):

  | Âncora | Secção | Conteúdo |
  |-------|--------|----------|
  | 1104 | `lista_acoes` | Lista de ações e meios de propaganda política por partido |
  | 1111 | `contas_anuais` | Contas anuais (balanço e demonstração de resultados) |
  | 1112 | `relatorios_ecfp` | Relatórios da ECFP |
  | 1114 | `acordaos` | Acórdãos sobre as contas anuais |
  | 1115 | `decisoes_ecfp` | Decisões da ECFP |

  Cada entrada é `nome do partido` + `sigla` + (quando existe) o PDF. Quando o
  partido não cumpriu, a sigla traz o motivo entre parênteses — «(Não entregou)»,
  «(não comunicou)», «(não apresentou contas)» — e o registo fica com
  `entregou=False`.

* **CNE — Partidos Políticos** (`cne.pt/content/partidos-politicos-1`). É o
  **registo oficial**: denominação, sigla, data de inscrição, situação
  (inscrito/extinto), sítio na Internet, símbolo e descrição. Serve de chave
  para ligar as contas ao partido (`partido_chave` ↔ `siglas`), que é o que
  permite a ficha do partido juntar o registo da CNE com os documentos do TC.

O que fica gravado, por recolha:

* as páginas HTML em `data/partidos/paginas` e `data/partidos/cne`;
* os PDF em `data/partidos/pdf/<ano>/`;
* um **JSONL por ano** (`data/partidos/_normalized/tc-<ano>.jsonl`) e um para o
  registo da CNE (`cne.jsonl`), com o **texto extraído** de cada PDF quando ele
  existe;
* os documentos indexados em `finance_partidos`, o registo da CNE em
  `finance_partidos_registo` e o histórico das recolhas em
  `finance_partidos_recolhas`.

**Atenção ao texto dos PDF.** Os relatórios e as decisões da ECFP são digitais e
dão texto para pesquisa integral; as **contas anuais** e as **listas de ações**
são digitalizações sem camada de texto — dessas fica o número de páginas
(`paginas`), o `pdf_sha256` e o indicador `pdf_digitalizado`, mas não há texto a
indexar (seria preciso OCR, que este módulo não faz).

O site do TC limita pedidos agressivos (HTTP 429), pelo que todos os pedidos
passam por `_pedir()`, que repete com recuo exponencial; e o que já está em
disco (mesmo `sha256`) não se volta a descarregar.
"""
from __future__ import annotations

import hashlib
import html as _html
import io
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urljoin, urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fontes
# ---------------------------------------------------------------------------

TC_BASE = "https://www.tribunalconstitucional.pt/tc"
#: Página-índice do financiamento partidário (tem a lista de anos publicados).
TC_INDICE_URL = f"{TC_BASE}/contas_eleicoes-partidos.html"
#: Página de um ano (`contas_eleicoes-partidos-2024.html`).
TC_ANO_URL = TC_BASE + "/contas_eleicoes-partidos-{ano}.html"
#: Primeiro ano com página própria nesta série.
TC_ANO_MINIMO = 2004

CNE_BASE = "https://www.cne.pt"
CNE_LISTA_URL = f"{CNE_BASE}/content/partidos-politicos-1"

#: Cabeçalhos dos pedidos. O TC responde 429 a clientes sem `User-Agent`.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) IQ-OS/1.0",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}

#: Pausa entre pedidos ao mesmo sítio (segundos) — o TC limita rajadas.
PAUSA_PEDIDOS = 1.5
#: Tentativas por pedido (429/5xx/timeout) com recuo exponencial.
TENTATIVAS = 5

# ---------------------------------------------------------------------------
# Secções da página anual
# ---------------------------------------------------------------------------

#: Âncora da página anual → (id, rótulo). O `id` é o que fica indexado.
SECOES: Dict[str, Tuple[str, str]] = {
    "1104": ("lista_acoes", "Lista de ações e meios de propaganda política"),
    "1111": ("contas_anuais", "Contas anuais dos partidos políticos"),
    "1112": ("relatorios_ecfp", "Relatórios da ECFP"),
    "1114": ("acordaos", "Acórdãos sobre as contas anuais"),
    "1115": ("decisoes_ecfp", "Decisões da ECFP"),
}

#: Rótulo legível de cada secção (para a interface e para as facetas).
SECOES_LABEL = {identificador: rotulo for identificador, rotulo in SECOES.values()}


def _secao_da_ancora(ancora: str, titulo: str) -> str:
    """Id da secção a partir da âncora; sem âncora conhecida, do título."""
    if ancora in SECOES:
        return SECOES[ancora][0]
    return _slug(titulo) or f"secao_{ancora}"


# ---------------------------------------------------------------------------
# Pastas e manifesto
# ---------------------------------------------------------------------------

DATA_DIR_ENV = "PARTIDOS_DATA_DIR"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "partidos"
_NORMALIZED_DIRNAME = "_normalized"
_MANIFEST = "_manifest.json"

#: Trabalhos (recolha e indexação) em segundo plano.
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 20
_RUNNING = "running"

#: Tipos de trabalho aceites por `start_job`.
TIPOS_JOB = ("recolher", "indexar")

#: Tamanho máximo do texto guardado por documento (PDF de contas podem ser
#: longos: anexos, notas às contas, relatórios de auditoria).
MAX_TEXTO_CHARS = 400_000
#: Ficheiro PDF acima deste tamanho não é descarregado (protege a pasta).
MAX_PDF_BYTES = 40 * 1024 * 1024


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


def _texto(fragmento: str) -> str:
    """Texto simples de um fragmento HTML (sem etiquetas, sem acentos mexidos)."""
    return _ESPACOS.sub(" ", _html.unescape(_TAG.sub(" ", fragmento))).replace("\xa0", " ").strip()


def _sem_acentos(valor: str) -> str:
    """Maiúsculas e sem acentos, para chaves de comparação."""
    decomposto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(caractere for caractere in decomposto if not unicodedata.combining(caractere)).upper().strip()


def _slug(valor: str) -> str:
    """Identificador legível a partir de um título (`a-b-c`)."""
    base = _sem_acentos(valor).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base


def _chave_partido(valor: str) -> str:
    """Chave de ligação entre as fontes: só letras e dígitos, sem acentos.

    «CDS-PP» → `CDSPP`, «PPD/PSD» → `PPDPSD`, «B.E.» → `BE`.
    """
    return re.sub(r"[^A-Z0-9]", "", _sem_acentos(valor))


def _chaves_partido(valor: str) -> List[str]:
    """Chaves alternativas de uma sigla/denominação, para o cruzamento das fontes.

    «CDS-PP» → `["CDSPP", "CDS", "PP"]` — é o que permite ligar o `CDS-PP` da CNE
    ao `CDS` que a página de 2008 do TC publica.
    """
    completa = _chave_partido(valor)
    if not completa:
        return []
    chaves = [completa]
    for parte in re.split(r"[-/.\s]+", _sem_acentos(valor)):
        limpa = re.sub(r"[^A-Z0-9]", "", parte)
        if len(limpa) >= 2 and limpa not in chaves:
            chaves.append(limpa)
    return chaves


def _normalizar_texto_pdf(texto: str) -> str:
    """Limpa o texto saído do PDF sem colar linhas nem perder parágrafos."""
    linhas: List[str] = []
    for linha in str(texto or "").replace("\xa0", " ").splitlines():
        limpa = _ESPACOS.sub(" ", linha).strip()
        if limpa:
            linhas.append(limpa)
    return "\n".join(linhas)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _data_iso(valor: str) -> Optional[str]:
    """`26/12/1974` → `1974-12-26` (o que a CNE publica vem em `dd/mm/aaaa`)."""
    achado = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", str(valor or "").strip())
    if not achado:
        return None
    dia, mes, ano = achado.groups()
    return f"{ano}-{mes}-{dia}"


# ---------------------------------------------------------------------------
# Pastas
# ---------------------------------------------------------------------------


def data_dir() -> Path:
    """Pasta do módulo (configurável por `PARTIDOS_DATA_DIR`)."""
    return Path(os.getenv(DATA_DIR_ENV) or _DEFAULT_DATA_DIR)


def paginas_dir() -> Path:
    return data_dir() / "paginas"


def cne_dir() -> Path:
    return data_dir() / "cne"


def pdf_dir(ano: Optional[int] = None) -> Path:
    raiz = data_dir() / "pdf"
    return raiz / str(int(ano)) if ano is not None else raiz


def normalized_dir() -> Path:
    return data_dir() / _NORMALIZED_DIRNAME


def _manifest_path() -> Path:
    return data_dir() / _MANIFEST


def read_manifest() -> Dict[str, Any]:
    caminho = _manifest_path()
    if not caminho.exists():
        return {"anos": {}, "cne": {}}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - um manifesto corrompido não trava o módulo
        logger.warning("Manifesto de partidos ilegível; a recomeçar")
        return {"anos": {}, "cne": {}}
    dados.setdefault("anos", {})
    dados.setdefault("cne", {})
    return dados


def _write_manifest(manifest: Dict[str, Any]) -> None:
    caminho = _manifest_path()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    manifest["atualizado_em"] = _now()
    caminho.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


# ---------------------------------------------------------------------------
# Pedidos HTTP (com recuo — o TC responde 429 a rajadas)
# ---------------------------------------------------------------------------


def _pedir(url: str, *, timeout: int = 90, tentativas: int = TENTATIVAS, pausa: float = PAUSA_PEDIDOS) -> bytes:
    """Descarrega um URL, repetindo com recuo exponencial em 429/5xx/timeout."""
    import requests

    ultimo: Optional[Exception] = None
    for tentativa in range(max(1, tentativas)):
        try:
            resposta = requests.get(url, timeout=timeout, headers=HEADERS)
        except Exception as exc:  # noqa: BLE001 - rede: repetir
            ultimo = exc
        else:
            if resposta.status_code == 429 or resposta.status_code >= 500:
                ultimo = RuntimeError(f"HTTP {resposta.status_code} em {url}")
            elif resposta.status_code >= 400:
                raise RuntimeError(f"HTTP {resposta.status_code} em {url}")
            else:
                return resposta.content
        if tentativa + 1 < max(1, tentativas):
            time.sleep(pausa * (2**tentativa))
    raise RuntimeError(f"Não foi possível obter {url}: {ultimo}")


# ---------------------------------------------------------------------------
# Leitura das páginas do Tribunal Constitucional
# ---------------------------------------------------------------------------

#: Secção da página anual: `<a name="1104"></a>` (…) `<h4>Título</h4>`.
_MARCA_SECAO = re.compile(r'<a name="(\d+)"[^>]*>\s*</a>.*?<h4>(.*?)</h4>', re.S)
#: Entrada de uma secção (`<li class="list">`).
_ITEM = re.compile(r"(?s)<li[^>]*\bclass=\"list\"[^>]*>(.*?)</li>")
#: Ligação a documento (o TC marca os PDF com `target="_pdf"`).
_LIGACAO = re.compile(r"(?s)<a\s+([^>]*)>(.*?)</a>")
_ATRIBUTO = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')
#: Sigla publicada a seguir ao nome.
_SPAN_LINKS = re.compile(r"(?s)<span[^>]*\bclass=\"links\"[^>]*>(.*?)</span>")
#: Parênteses finais do nome/sigla («(Não entregou)», «(Balanço rectificado…)»): os
#: motivos que o TC usa para dizer que o partido não cumpriu.
_NAO_CUMPRIU = re.compile(r"n[ãa]o\s+(?:entregou|comunicou|apresentou|remeteu|enviou|deu)", re.I)
#: «PCP - Partido Comunista Português» (o nome traz a sigla à frente, sem `<span>`).
_SIGLA_NO_NOME = re.compile(r"^(?P<sigla>[A-ZÀ-Ý][A-ZÀ-Ý0-9./)]{1,9})\s+-\s+(?P<nome>.+)$")
#: Âncora de um único ano na página-índice.
_ANO_NA_INDICE = re.compile(r"contas_eleicoes-partidos-(\d{4})\.html")


def _artigo(html_texto: str) -> str:
    """Só o corpo da página (entre `<article>` e `</article>`)."""
    inicio = html_texto.find("<article>")
    if inicio < 0:
        return html_texto
    fim = html_texto.find("</article>", inicio)
    return html_texto[inicio : fim if fim > 0 else len(html_texto)]


def _ligacao_pdf(fragmento: str) -> Optional[Dict[str, Any]]:
    """Primeira ligação com `target="_pdf"` do fragmento (URL, título, texto)."""
    for atributos, corpo in _LIGACAO.findall(fragmento):
        valores = {chave.lower(): _html.unescape(valor) for chave, valor in _ATRIBUTO.findall(atributos)}
        if valores.get("target", "").lower() != "_pdf":
            continue
        return {
            "href": valores.get("href") or "",
            "titulo": _texto(valores.get("title") or ""),
            "texto": _texto(corpo),
        }
    return None


def _grupos_finais(valor: str) -> Tuple[str, List[str]]:
    """Separa os grupos entre parênteses/parênteses retos no fim.

    `'PCP [versão retificada em 8.06.2022 (a pedido do partido)]'` →
    `('PCP', ['versão retificada em 8.06.2022 (a pedido do partido)'])`.
    """
    texto = (valor or "").strip()
    notas: List[str] = []
    while texto and texto[-1] in ")]":
        fecho = texto[-1]
        abre = "(" if fecho == ")" else "["
        nivel = 0
        indice = len(texto) - 1
        while indice >= 0:
            if texto[indice] == fecho:
                nivel += 1
            elif texto[indice] == abre:
                nivel -= 1
                if nivel == 0:
                    break
            indice -= 1
        if indice < 0:
            break
        nota = _ESPACOS.sub(" ", texto[indice + 1 : -1]).strip()
        if nota:
            notas.insert(0, nota)
        texto = texto[:indice].strip()
    return texto, notas


#: Sufixo entre aspas (`PPD/PSD "Retificou em 13/04/2016"`).
_ASPAS_FINAIS = re.compile(r'\s*"[^"]*"\s*$')
#: Grupo por fechar no fim (`PAN (Retificadas em 03-04-2014`) — gralha na página.
_GRUPO_ABERTO = re.compile(r"\s*[\(\[]\s*[^\)\]]*$")
#: `SIGLA - Explicação em prosa` (mas não `CDS - PP`, que é a própria sigla).
_SIGLA_TRACO = re.compile(r"^(?P<sigla>[A-ZÀ-Ý0-9][A-ZÀ-Ý0-9./)]{0,11})\s+-\s*(?P<resto>.+)$")
#: Palavras claramente de prosa (minúsculas, três letras ou mais).
_PALAVRA_PROSA = re.compile(r"\b[a-zà-ÿ]{3,}\b")


def _separar_notas(valor: str) -> Tuple[str, List[str]]:
    """Separa de um nome/sigla os sufixos que são anotações e não a sigla.

    O TC escreve o mesmo de várias maneiras: `PCP (não comunicou)`,
    `PXXI - Contas entregues fora de prazo`, `PAN (Retificadas em 03-04-2014`
    (parêntese por fechar na página) e `PPD/PSD "Retificou em 13/04/2016"`.
    """
    texto = (valor or "").strip()
    notas: List[str] = []
    mudou = True
    while texto and mudou:
        mudou = False
        base, extras = _grupos_finais(texto)
        if extras:
            notas = extras + notas
            texto = base
            continue
        achado = _ASPAS_FINAIS.search(texto)
        if achado:
            nota = achado.group(0).strip().strip('"').strip()
            if nota:
                notas.insert(0, nota)
            texto = texto[: achado.start()].strip()
            continue
        achado = _GRUPO_ABERTO.search(texto)
        if achado:
            nota = achado.group(0).strip().strip("([").strip()
            if nota:
                notas.insert(0, nota)
            texto = texto[: achado.start()].strip()
            continue
    achado = _SIGLA_TRACO.match(texto)
    if achado and _PALAVRA_PROSA.search(achado.group("resto")):
        notas.insert(0, _ESPACOS.sub(" ", achado.group("resto")).strip())
        texto = achado.group("sigla").strip()
    return texto, [nota for nota in notas if nota]


#: O que não aparece numa sigla de partido (sobra de prosa ou de referências).
_SIGLA_INVALIDA = re.compile(r"[\[\]{};,:!?\n]")


def _parece_sigla(valor: str) -> bool:
    """Diz se um texto se pode ler como sigla (`PCP`, `PPD/PSD`, `A)T`, `B.E.`).

    Rejeita prosa que apareça em `<span class="links">` em vez da sigla — é o
    caso dos acórdãos de 2008 («[Publicado no Diário da República…]») e das
    decisões agregadas de 2014 («Decisão da ECFP relativa aos…»).
    """
    texto = (valor or "").strip()
    if not texto or len(texto) > 32 or _SIGLA_INVALIDA.search(texto):
        return False
    palavras = texto.split()
    if len(palavras) > 3:
        return False
    # Uma sigla não tem palavras em minúsculas («Decisão da ECFP», «Partido da
    # Terra»); tem maiúsculas, dígitos e pontuação («PCP», «PPD/PSD», «B.E.»).
    return not any(palavra.islower() and len(palavra) >= 2 for palavra in palavras)


def _entrada_do_item(bruto: str, ordem: int) -> Optional[Dict[str, Any]]:
    """Normaliza uma entrada (`<li>`) de uma secção da página anual.

    Devolve `None` para entradas vazias. Notas da secção (texto corrido sem
    ligação nem sigla) ficam marcadas com `nota=True` para não se confundirem
    com um partido.
    """
    ligacao = _ligacao_pdf(bruto)
    achado_sigla = _SPAN_LINKS.search(bruto)
    sigla, notas_sigla = _separar_notas(_texto(achado_sigla.group(1)) if achado_sigla else "")
    if sigla and not _parece_sigla(sigla):
        # O `<span class="links">` trazia prosa: fica como anotação da entrada.
        notas_sigla.append(sigla)
        sigla = ""

    nome_bruto = (ligacao or {}).get("texto") or ""
    if not nome_bruto:
        nome_bruto = _texto(bruto.split("<br", 1)[0])
    nome, notas_nome = _separar_notas(nome_bruto)

    # Sem `<span class="links">` (anos mais antigos), a sigla vem no próprio nome:
    # «PCP - Partido Comunista Português», ou o nome curto inteiro («PCTP/MRPP»).
    if not sigla:
        achado = _SIGLA_NO_NOME.match(nome)
        if achado:
            sigla = achado.group("sigla").strip()
            nome = achado.group("nome").strip()
    if not sigla and _parece_sigla(nome):
        sigla = nome

    if not ligacao and not sigla:
        texto = _texto(bruto)
        if not texto:
            return None
        return {
            "ordem": ordem,
            "nota": True,
            "documento": False,
            "agregado": False,
            "entregou": None,
            "partido_nome": None,
            "partido_sigla": None,
            "partido_chave": None,
            "motivo": None,
            "observacao": None,
            "texto": texto,
            "ficheiro": None,
            "pdf_url": None,
            "pdf_titulo": None,
            "href": None,
        }

    # «(Não entregou)» é o motivo do incumprimento; o resto dos sufixos
    # («Balanço rectificado em 17 de junho de 2011») são observações.
    notas = [*notas_sigla, *notas_nome]
    motivo = next((nota for nota in notas if _NAO_CUMPRIU.search(nota)), None)
    observacoes = [nota for nota in notas if nota != motivo]
    observacao = " · ".join(observacoes) or None

    tema = sigla or nome
    return {
        "ordem": ordem,
        "nota": False,
        "documento": bool(ligacao),
        # Entrada que publica um documento agregado (a lista de todas as forças
        # políticas) e não um partido: fica sem chave de partido.
        "agregado": bool(ligacao) and not sigla,
        "entregou": bool(ligacao),
        "partido_nome": nome or None,
        "partido_sigla": sigla or None,
        "partido_chave": (None if (ligacao and not sigla) else (_chave_partido(tema) or None)),
        "motivo": motivo,
        "observacao": observacao,
        "texto": None,
        "ficheiro": None,
        "pdf_url": None,
        "pdf_titulo": (ligacao or {}).get("titulo") or None,
        "href": (ligacao or {}).get("href") or None,
    }


def parse_pagina_ano(html_texto: str, ano: int) -> Dict[str, Any]:
    """Extrai as secções e as entradas de uma página anual do TC.

    Não toca na rede nem no disco: recebe o HTML e devolve a estrutura, para
    poder ser testado com páginas sintéticas.
    """
    artigo = _artigo(html_texto)
    marcas = list(_MARCA_SECAO.finditer(artigo))
    secoes: List[Dict[str, Any]] = []
    for indice, marca in enumerate(marcas):
        fim = marcas[indice + 1].start() if indice + 1 < len(marcas) else len(artigo)
        corpo = artigo[marca.end() : fim]
        ancora, titulo = marca.group(1), _texto(marca.group(2))
        itens: List[Dict[str, Any]] = []
        for posicao, bruto in enumerate(_ITEM.findall(corpo)):
            entrada = _entrada_do_item(bruto, posicao)
            if entrada is None:
                continue
            entrada["href"] = _url_do_pdf(entrada.get("href"))
            itens.append(entrada)
        secoes.append(
            {
                "ancora": ancora,
                "secao": _secao_da_ancora(ancora, titulo),
                "titulo": titulo or SECOES.get(ancora, ("", ""))[1],
                "itens": itens,
            }
        )
    return {"ano": int(ano), "secoes": secoes}


def _url_do_pdf(href: Optional[str]) -> Optional[str]:
    """URL absoluto do documento publicado (`file/…` é relativo a `/tc/`)."""
    if not href:
        return None
    return urljoin(f"{TC_BASE}/", href.strip())


def _ficheiro_do_href(href: str) -> Optional[str]:
    """Nome do ficheiro de um `href` (`file/4_CA2025_PCP_…pdf?src=1` → o ficheiro)."""
    if not href:
        return None
    caminho = urlparse(href).path
    nome = Path(unquote(caminho)).name
    return nome or None


def anos_na_pagina_indice(html_texto: str) -> List[int]:
    """Anos com página própria, lidos da página-índice do financiamento partidário."""
    anos = {int(achado) for achado in _ANO_NA_INDICE.findall(html_texto or "")}
    return sorted(anos)


# ---------------------------------------------------------------------------
# Leitura das páginas da CNE
# ---------------------------------------------------------------------------

_TABELA = re.compile(r"(?s)<table.*?</table>")
_LINHA_TABELA = re.compile(r"(?s)<tr[^>]*>(.*?)</tr>")
_CELULA = re.compile(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>")
_IMAGEM = re.compile(r'(?s)<img[^>]*\bsrc="([^"]+)"')
#: Rótulo da situação, publicado imediatamente antes de cada tabela.
_ROTULO_SITUACAO = re.compile(r"\b(Inscritos|Extintos)\b", re.I)


def parse_cne_lista(html_texto: str) -> Dict[str, List[Dict[str, Any]]]:
    """Partidos inscritos e extintos da listagem da CNE.

    A página traz duas tabelas com as mesmas colunas (`Denominação`, `Símbolo`,
    `Sigla`, `Data da inscrição`): a dos partidos **inscritos** e a dos
    **extintos** (estes sem data de inscrição). A situação é a do rótulo
    «Inscritos»/«Extintos» que precede cada tabela.
    """
    documento = html_texto or ""
    resultado: Dict[str, List[Dict[str, Any]]] = {"inscritos": [], "extintos": []}
    vistos: set[str] = set()
    for tabela in _TABELA.findall(documento):
        linhas = _LINHA_TABELA.findall(tabela)
        if not linhas:
            continue
        cabecalho = [_sem_acentos(_texto(celula)) for celula in _CELULA.findall(linhas[0])]
        if "DENOMINACAO" not in " ".join(cabecalho):
            continue
        # O último «Inscritos»/«Extintos» antes da tabela é o rótulo dela.
        anterior = _texto(documento[max(0, documento.find(tabela) - 600) : documento.find(tabela)])
        rotulos = list(_ROTULO_SITUACAO.finditer(anterior))
        extintos = bool(rotulos) and rotulos[-1].group(1).lower().startswith("extint")
        destino = "extintos" if extintos else "inscritos"
        for linha in linhas:
            brutas = _CELULA.findall(linha)
            celulas = [_texto(celula) for celula in brutas]
            if len(celulas) < 3 or _sem_acentos(celulas[0]) == "DENOMINACAO":
                continue
            denominacao = celulas[0]
            if not denominacao or denominacao in vistos:
                continue
            vistos.add(denominacao)
            # Colunas: 0 denominação, 1 símbolo, 2 sigla, 3 data de inscrição.
            simbolo = _IMAGEM.search(brutas[1]).group(1) if len(brutas) > 1 and _IMAGEM.search(brutas[1]) else None
            ligacao = _LIGACAO.search(brutas[0])
            atributos = _ATRIBUTO.findall(ligacao.group(1)) if ligacao else []
            url = next((valor for nome, valor in atributos if nome.lower() == "href"), None)
            resultado[destino].append(
                {
                    "denominacao": denominacao,
                    "sigla": celulas[2] or None,
                    "data_inscricao": _data_iso(celulas[3]) if len(celulas) > 3 else None,
                    "logotipo_url": urljoin(CNE_BASE, _html.unescape(simbolo)) if simbolo else None,
                    "url": urljoin(CNE_BASE, _html.unescape(url)) if url else None,
                    "situacao": destino[:-1],
                }
            )
    return resultado


#: Campos da ficha de partido da CNE, com o rótulo que os precede na página.
_CAMPOS_CNE = (
    ("denominacao", "Denomina"),
    ("sigla", "Sigla"),
)


def parse_cne_partido(html_texto: str) -> Dict[str, Any]:
    """Ficha de um partido na CNE: denominação, sigla, site, símbolo e descrição."""
    documento = html_texto or ""
    campos: Dict[str, Any] = {}
    for chave, rotulo in _CAMPOS_CNE:
        # O rótulo vem seguido de `&nbsp;` e o valor na `div.field-item` seguinte.
        achado = re.search(
            r'field-label">\s*' + re.escape(rotulo) + r'[^<]*</div>\s*<div class="field-items">\s*<div[^>]*>(.*?)</div>',
            documento,
            re.S,
        )
        campos[chave] = _texto(achado.group(1)) if achado else None

    site = None
    achado_site = re.search(r'field-name-field-http.*?<a\s+href="([^"]+)"', documento, re.S)
    if achado_site:
        site = _html.unescape(achado_site.group(1))

    logotipo = None
    achado_logo = re.search(r'field-name-field-pp-logo.*?<img[^>]*\bsrc="([^"]+)"', documento, re.S)
    if achado_logo:
        logotipo = urljoin(CNE_BASE, _html.unescape(achado_logo.group(1)))

    descricao = None
    achado_corpo = re.search(r'property="content:encoded">(.*?)(?:</div>\s*){3}', documento, re.S)
    if achado_corpo:
        # Mantém os parágrafos do corpo (uma linha por `<p>`).
        paragrafos = re.findall(r"(?s)<p[^>]*>(.*?)</p>", achado_corpo.group(1))
        partes = [_texto(paragrafo) for paragrafo in paragrafos] if paragrafos else [_texto(achado_corpo.group(1))]
        descricao = "\n".join(parte for parte in partes if parte) or None

    return {
        "denominacao": campos.get("denominacao"),
        "sigla": campos.get("sigla"),
        "site": site,
        "logotipo_url": logotipo,
        "descricao": descricao,
    }


# ---------------------------------------------------------------------------
# Extração de texto dos PDF
# ---------------------------------------------------------------------------


def extrair_texto_pdf(conteudo: bytes, *, maximo_caracteres: int = MAX_TEXTO_CHARS) -> Dict[str, Any]:
    """Texto de um PDF (com o número de páginas). Nunca levanta: devolve o erro."""
    import pymupdf

    try:
        with pymupdf.open(stream=io.BytesIO(conteudo), filetype="pdf") as documento:
            paginas = int(documento.page_count)
            partes: List[str] = []
            total = 0
            for indice in range(paginas):
                try:
                    texto = documento[indice].get_text("text") or ""
                except Exception:  # noqa: BLE001 - uma página má não invalida o resto
                    continue
                partes.append(texto)
                total += len(texto)
                if total >= maximo_caracteres:
                    break
        return {
            "paginas": paginas,
            "texto": _normalizar_texto_pdf("\n".join(partes))[:maximo_caracteres],
            "truncado": total > maximo_caracteres,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - o documento fica sem texto, não sem registo
        logger.warning("Partidos: texto do PDF não extraído (%s)", exc)
        return {"paginas": None, "texto": "", "truncado": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------


def anos_disponiveis(*, refrescar: bool = False) -> List[int]:
    """Anos com página própria no TC (lidos da página-índice, com cache em disco)."""
    caminho = paginas_dir() / "indice.html"
    if refrescar or not caminho.exists():
        try:
            conteudo = _pedir(TC_INDICE_URL)
        except Exception as exc:  # noqa: BLE001 - sem rede, usa-se o que está em disco
            logger.warning("Partidos: página-índice do TC indisponível (%s)", exc)
            if not caminho.exists():
                return list(range(TC_ANO_MINIMO, date.today().year + 1))
        else:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(conteudo)
    html_texto = caminho.read_text(encoding="utf-8", errors="replace")
    anos = anos_na_pagina_indice(html_texto)
    if not anos:
        anos = list(range(TC_ANO_MINIMO, date.today().year + 1))
    return anos


def _pagina_do_ano(ano: int, *, forcar: bool = False) -> Tuple[str, Dict[str, Any]]:
    """HTML da página anual (do disco quando já lá está) + metadados da leitura."""
    caminho = paginas_dir() / f"{ano}.html"
    if caminho.exists() and not forcar:
        conteudo = caminho.read_bytes()
        origem = "disco"
    else:
        conteudo = _pedir(TC_ANO_URL.format(ano=ano))
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        origem = "rede"
        time.sleep(PAUSA_PEDIDOS)
    return conteudo.decode("utf-8", errors="replace"), {
        "ano": int(ano),
        "url": TC_ANO_URL.format(ano=ano),
        "fonte": "tc",
        "bytes": len(conteudo),
        "sha256": _sha256(conteudo),
        "origem": origem,
    }


def _pdf_do_documento(
    href: Optional[str],
    ano: int,
    *,
    forcar: bool = False,
    max_bytes: int = MAX_PDF_BYTES,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Descarrega (ou reaproveita) o PDF e extrai-lhe o texto."""
    vazio = {"ficheiro": None, "pdf_bytes": None, "pdf_sha256": None, "paginas": None, "texto": "", "texto_truncado": False, "erro": None}
    if not href:
        return vazio
    nome = _ficheiro_do_href(href)
    if not nome:
        return vazio
    destino = pdf_dir(ano) / nome
    conteudo: Optional[bytes] = None
    if destino.exists() and not forcar:
        conteudo = destino.read_bytes()
    else:
        if progresso is not None:
            progresso["current"] = nome
        try:
            conteudo = _pedir(href, timeout=180)
        except Exception as exc:  # noqa: BLE001 - um PDF que falha não trava o ano
            logger.warning("Partidos: PDF %s não descarregado (%s)", href, exc)
            return {**vazio, "ficheiro": nome, "erro": f"{type(exc).__name__}: {exc}"}
        time.sleep(PAUSA_PEDIDOS)
        if len(conteudo) > max_bytes:
            return {**vazio, "ficheiro": nome, "erro": f"ficheiro com {len(conteudo)} bytes (> limite {max_bytes})"}
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)

    extraido = extrair_texto_pdf(conteudo)
    return {
        "ficheiro": nome,
        "pdf_bytes": len(conteudo),
        "pdf_sha256": _sha256(conteudo),
        "paginas": extraido.get("paginas"),
        "texto": extraido.get("texto") or "",
        "texto_truncado": bool(extraido.get("truncado")),
        "erro": extraido.get("error"),
    }


def _documento_do_item(
    item: Dict[str, Any],
    *,
    ano: int,
    secao: str,
    secao_titulo: str,
    ancora: str,
    pagina_url: str,
    recolhido_em: str,
    dados_pdf: Dict[str, Any],
) -> Dict[str, Any]:
    """Documento indexável de uma entrada da página anual."""
    chave = item.get("partido_chave") or ("nota" if item.get("nota") else "agregado")
    documento = {
        "doc_id": f"{ano}:{secao}:{chave}:{item.get('ordem')}",
        "ano": int(ano),
        "secao": secao,
        "secao_titulo": secao_titulo,
        "ancora": ancora,
        "ordem": int(item.get("ordem") or 0),
        "partido_nome": item.get("partido_nome"),
        "partido_sigla": item.get("partido_sigla"),
        "partido_chave": item.get("partido_chave"),
        "entregou": item.get("entregou"),
        "motivo": item.get("motivo"),
        "observacao": item.get("observacao"),
        "nota": bool(item.get("nota")),
        "agregado": bool(item.get("agregado")),
        "documento": bool(item.get("documento")),
        "ficheiro": dados_pdf.get("ficheiro"),
        "ficheiro_kb": round((dados_pdf.get("pdf_bytes") or 0) / 1024) or None,
        "pdf_url": item.get("href"),
        "pdf_titulo": item.get("pdf_titulo"),
        "pdf_sha256": dados_pdf.get("pdf_sha256"),
        "paginas": dados_pdf.get("paginas"),
        "texto": dados_pdf.get("texto") or item.get("texto") or "",
        "texto_extraido": bool(dados_pdf.get("texto")),
        # As contas anuais e as listas de ações são **digitalizações** (sem
        # camada de texto): ficam com o número de páginas e sem texto. Os
        # relatórios e decisões da ECFP são digitais e dão texto.
        "pdf_digitalizado": (bool(dados_pdf.get("paginas")) and not dados_pdf.get("texto")) if dados_pdf.get("ficheiro") else None,
        "fonte": "tc",
        "pagina_url": pagina_url,
        "recolhido_em": recolhido_em,
    }
    documento["texto_chars"] = len(documento["texto"])
    if dados_pdf.get("erro"):
        documento["erro_pdf"] = dados_pdf["erro"]
    return documento


def recolher(
    anos: Optional[Iterable[int]] = None,
    *,
    com_pdf: bool = True,
    secoes: Optional[Iterable[str]] = None,
    forcar: bool = False,
    com_cne: bool = True,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recolhe as páginas do TC (e o registo da CNE) para JSONL.

    Cada ano gera `data/partidos/_normalized/tc-<ano>.jsonl`; o registo da CNE,
    `data/partidos/_normalized/cne.jsonl`. Quando `com_pdf` é falso a recolha é
    rápida (só metadados: quem entregou, que documento e o tamanho publicado).
    """
    filtro_secoes = {str(valor) for valor in secoes} if secoes else None
    disponiveis = anos_disponiveis()
    publicados = set(disponiveis)
    if anos:
        # Pedir um ano que o TC não publica não pode virar «recolhe tudo»: só se
        # recolhe o que foi mesmo pedido, e o resto fica assinalado.
        pedidos = [int(ano) for ano in anos]
        alvo = sorted({ano for ano in pedidos if ano in publicados})
        ignorados = sorted({ano for ano in pedidos if ano not in publicados})
    else:
        alvo = sorted(publicados)
        ignorados = []
    recolhido_em = _now()
    manifesto = read_manifest()

    resultado: Dict[str, Any] = {"anos": {}, "cne": None, "errors": [], "ignorados": ignorados}
    if ignorados:
        resultado["errors"].append(
            {"ano": None, "error": f"Ano(s) sem página no Tribunal Constitucional: {', '.join(str(ano) for ano in ignorados)}"}
        )
    if progresso is not None:
        progresso.update({"phase": "a recolher as páginas anuais", "anos_total": len(alvo), "anos_done": 0, "current": None})

    for ano in alvo:
        try:
            html_texto, meta = _pagina_do_ano(ano, forcar=forcar)
            analise = parse_pagina_ano(html_texto, ano)
        except Exception as exc:  # noqa: BLE001 - um ano que falha não trava os outros
            logger.exception("Partidos: ano %s falhou", ano)
            resultado["errors"].append({"ano": ano, "error": f"{type(exc).__name__}: {exc}"})
            if progresso is not None:
                progresso["anos_done"] = progresso.get("anos_done", 0) + 1
            continue

        documentos: List[Dict[str, Any]] = []
        for secao in analise["secoes"]:
            if filtro_secoes and secao["secao"] not in filtro_secoes:
                continue
            for item in secao["itens"]:
                dados_pdf: Dict[str, Any] = {
                    "ficheiro": _ficheiro_do_href(item.get("href") or ""),
                    "pdf_bytes": None,
                    "pdf_sha256": None,
                    "paginas": None,
                    "texto": "",
                    "erro": None,
                }
                if com_pdf and item.get("href"):
                    dados_pdf = _pdf_do_documento(item["href"], ano, forcar=forcar, progresso=progresso)
                documentos.append(
                    _documento_do_item(
                        item,
                        ano=ano,
                        secao=secao["secao"],
                        secao_titulo=secao["titulo"],
                        ancora=secao["ancora"],
                        pagina_url=meta["url"],
                        recolhido_em=recolhido_em,
                        dados_pdf=dados_pdf,
                    )
                )

        caminho_jsonl = normalized_dir() / f"tc-{ano}.jsonl"
        caminho_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with caminho_jsonl.open("w", encoding="utf-8") as ficheiro:
            for documento in documentos:
                ficheiro.write(json.dumps(documento, ensure_ascii=False) + "\n")

        partidos = {documento["partido_chave"] for documento in documentos if documento.get("partido_chave") and not documento.get("nota")}
        resumo_ano = {
            **meta,
            "jsonl": caminho_jsonl.name,
            "secoes": sorted({documento["secao"] for documento in documentos}),
            "itens": len(documentos),
            "notas": sum(1 for documento in documentos if documento["nota"]),
            "documentos": sum(1 for documento in documentos if documento["documento"]),
            "partidos": len(partidos),
            "pdfs": sum(1 for documento in documentos if documento.get("ficheiro")),
            "com_texto": sum(1 for documento in documentos if documento.get("texto_extraido")),
            "digitalizados": sum(1 for documento in documentos if documento.get("pdf_digitalizado")),
            "sem_documento": sum(1 for documento in documentos if not documento["nota"] and not documento["documento"]),
            "recolhido_em": recolhido_em,
            "indexados": 0,
        }
        manifesto["anos"][str(ano)] = resumo_ano
        resultado["anos"][str(ano)] = resumo_ano
        _write_manifest(manifesto)
        if progresso is not None:
            progresso["anos_done"] = progresso.get("anos_done", 0) + 1
            progresso["registos"] = int(progresso.get("registos") or 0) + len(documentos)
        logger.info("Partidos: ano %s lido (%d entradas)", ano, len(documentos))

    if com_cne:
        if progresso is not None:
            progresso.update({"phase": "a recolher o registo da CNE", "current": "partidos-politicos-1"})
        try:
            resultado["cne"] = recolher_cne(manifest=manifesto, forcar=forcar, recolhido_em=recolhido_em, progresso=progresso)
        except Exception as exc:  # noqa: BLE001 - a CNE é complementar: o TC não se perde
            logger.exception("Partidos: registo da CNE falhou")
            resultado["errors"].append({"ano": None, "fonte": "cne", "error": f"{type(exc).__name__}: {exc}"})

    if progresso is not None:
        progresso["current"] = None
        progresso["phase"] = "lido"
    _write_manifest(manifesto)
    resultado["anos_lidos"] = len(resultado["anos"])
    return resultado


def recolher_cne(
    *,
    manifest: Optional[Dict[str, Any]] = None,
    forcar: bool = False,
    recolhido_em: Optional[str] = None,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Registo oficial da CNE: listagem + ficha de cada partido, para JSONL."""
    manifesto = manifest if manifest is not None else read_manifest()
    recolhido_em = recolhido_em or _now()
    caminho_lista = cne_dir() / "partidos.html"
    if caminho_lista.exists() and not forcar:
        conteudo = caminho_lista.read_bytes()
    else:
        conteudo = _pedir(CNE_LISTA_URL)
        caminho_lista.parent.mkdir(parents=True, exist_ok=True)
        caminho_lista.write_bytes(conteudo)
        time.sleep(PAUSA_PEDIDOS)
    listagem = parse_cne_lista(conteudo.decode("utf-8", errors="replace"))

    partidos: List[Dict[str, Any]] = []
    for situacao in ("inscritos", "extintos"):
        for entrada in listagem[situacao]:
            ficha: Dict[str, Any] = {}
            url = entrada.get("url")
            if url:
                slug = Path(urlparse(url).path).name or _slug(entrada["denominacao"])
                caminho_ficha = cne_dir() / f"{situacao[:-1]}-{slug}.html"
                try:
                    if caminho_ficha.exists() and not forcar:
                        ficha = parse_cne_partido(caminho_ficha.read_text(encoding="utf-8", errors="replace"))
                    else:
                        if progresso is not None:
                            progresso["current"] = entrada["denominacao"]
                        bruto = _pedir(url)
                        caminho_ficha.parent.mkdir(parents=True, exist_ok=True)
                        caminho_ficha.write_bytes(bruto)
                        ficha = parse_cne_partido(bruto.decode("utf-8", errors="replace"))
                        time.sleep(PAUSA_PEDIDOS)
                except Exception as exc:  # noqa: BLE001 - a ficha é um extra; a linha fica na mesma
                    logger.warning("Partidos: ficha CNE de %s falhou (%s)", entrada.get("denominacao"), exc)
                    ficha = {"erro": f"{type(exc).__name__}: {exc}"}
            sigla = ficha.get("sigla") or entrada.get("sigla")
            denominacao = ficha.get("denominacao") or entrada["denominacao"]
            partidos.append(
                {
                    "chave": _chave_partido(sigla or denominacao),
                    "denominacao": denominacao,
                    "sigla": sigla,
                    # Chaves alternativas: é por aqui que os documentos do TC
                    # (que usam «CDS», «B.E.»…) encontram o partido da CNE. Os
                    # sub-tokens saem só da sigla — das palavras da denominação
                    # («Partido», «Popular») não, que ligariam partidos errados.
                    "siglas": sorted({*_chaves_partido(sigla or ""), _chave_partido(denominacao)}),
                    "situacao": entrada.get("situacao"),
                    "data_inscricao": entrada.get("data_inscricao"),
                    "site": ficha.get("site"),
                    "logotipo_url": ficha.get("logotipo_url") or entrada.get("logotipo_url"),
                    "descricao": ficha.get("descricao"),
                    "url": entrada.get("url"),
                    "fonte": "cne",
                    "erro": ficha.get("erro"),
                    "recolhido_em": recolhido_em,
                }
            )

    caminho_jsonl = normalized_dir() / "cne.jsonl"
    caminho_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with caminho_jsonl.open("w", encoding="utf-8") as ficheiro:
        for partido in partidos:
            ficheiro.write(json.dumps(partido, ensure_ascii=False) + "\n")

    resumo = {
        "url": CNE_LISTA_URL,
        "fonte": "cne",
        "bytes": len(conteudo),
        "sha256": _sha256(conteudo),
        "jsonl": caminho_jsonl.name,
        "inscritos": sum(1 for partido in partidos if partido["situacao"] == "inscrito"),
        "extintos": sum(1 for partido in partidos if partido["situacao"] == "extinto"),
        "registos": len(partidos),
        "com_descricao": sum(1 for partido in partidos if partido.get("descricao")),
        "com_site": sum(1 for partido in partidos if partido.get("site")),
        "com_erro": sum(1 for partido in partidos if partido.get("erro")),
        "recolhido_em": recolhido_em,
        "indexados": 0,
    }
    manifesto["cne"] = {**resumo, "partidos": [partido["chave"] for partido in partidos]}
    resultado = resumo
    _write_manifest(manifesto)
    if progresso is not None:
        progresso["current"] = None
    logger.info("Partidos: CNE lida (%d partidos)", len(partidos))
    return resultado


# ---------------------------------------------------------------------------
# Indexação no Elasticsearch
# ---------------------------------------------------------------------------

_TAMANHO_LOTE_ES = 500


def _iter_jsonl(caminho: Path) -> Iterator[Dict[str, Any]]:
    with caminho.open("r", encoding="utf-8") as ficheiro:
        for linha in ficheiro:
            linha = linha.strip()
            if not linha:
                continue
            try:
                yield json.loads(linha)
            except Exception:  # noqa: BLE001 - uma linha má não trava a indexação
                continue


def _jsonl_do_ano(ano: int) -> Path:
    return normalized_dir() / f"tc-{ano}.jsonl"


def _jsonl_cne() -> Path:
    return normalized_dir() / "cne.jsonl"


def indexar(
    anos: Optional[Iterable[int]] = None,
    *,
    forcar: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Indexa os JSONL lidos: documentos em `finance_partidos`, CNE no registo."""
    from api import elasticsearch_client as esc

    cliente = es or esc.get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "indexados": 0, "ficheiros": 0}
    esc.ensure_indices(cliente)

    from elasticsearch.helpers import bulk

    manifesto = read_manifest()
    anos_manifesto = manifesto.get("anos") or {}
    filtro = {int(ano) for ano in anos} if anos else None
    alvo = sorted(
        (int(ano) for ano in anos_manifesto if filtro is None or int(ano) in filtro),
        reverse=True,
    )

    resultado: Dict[str, Any] = {"indexados": 0, "ficheiros": 0, "items": [], "errors": []}
    if progresso is not None:
        progresso.update({"phase": "a indexar os anos", "ficheiros_total": len(alvo) + 1, "ficheiros_done": 0, "current": None})

    for ano in alvo:
        caminho = _jsonl_do_ano(ano)
        entrada = anos_manifesto.get(str(ano)) or {}
        if not caminho.exists():
            resultado["errors"].append({"ano": ano, "error": "JSONL não encontrado (leia o ano de novo)"})
            continue
        if progresso is not None:
            progresso["current"] = caminho.name
        enviados = 0
        acoes: List[Dict[str, Any]] = []
        try:
            for documento in _iter_jsonl(caminho):
                documento = {chave: valor for chave, valor in documento.items() if chave != "erro_pdf"} | {"ingested_at": _now()}
                acoes.append({"_index": esc.PARTIDOS_INDEX, "_id": str(documento.get("doc_id")), "_source": documento})
                if len(acoes) >= _TAMANHO_LOTE_ES:
                    bulk(cliente, acoes, refresh=False, raise_on_error=False)
                    enviados += len(acoes)
                    acoes = []
            if acoes:
                bulk(cliente, acoes, refresh=False, raise_on_error=False)
                enviados += len(acoes)
        except Exception as exc:  # noqa: BLE001 - um ano mau não trava os restantes
            logger.exception("Partidos: falha a indexar %s", caminho)
            resultado["errors"].append({"ano": ano, "error": f"{type(exc).__name__}: {exc}"})
            continue

        entrada.update({"indexados": enviados, "indexado_em": _now()})
        anos_manifesto[str(ano)] = entrada
        manifesto["anos"] = anos_manifesto
        _write_manifest(manifesto)
        resultado["indexados"] += enviados
        resultado["ficheiros"] += 1
        resultado["items"].append({"ano": ano, "ficheiro": caminho.name, "indexados": enviados})
        if progresso is not None:
            progresso["ficheiros_done"] = progresso.get("ficheiros_done", 0) + 1
            progresso["registos"] = resultado["indexados"]
            progresso["current"] = None

    # Registo oficial dos partidos (CNE).
    caminho_cne = _jsonl_cne()
    if caminho_cne.exists():
        if progresso is not None:
            progresso["current"] = caminho_cne.name
        enviados = 0
        try:
            acoes = []
            for partido in _iter_jsonl(caminho_cne):
                documento = {chave: valor for chave, valor in partido.items() if chave != "erro"} | {"ingested_at": _now()}
                acoes.append({"_index": esc.PARTIDOS_REGISTO_INDEX, "_id": str(documento.get("chave")), "_source": documento})
                if len(acoes) >= _TAMANHO_LOTE_ES:
                    bulk(cliente, acoes, refresh=False, raise_on_error=False)
                    enviados += len(acoes)
                    acoes = []
            if acoes:
                bulk(cliente, acoes, refresh=False, raise_on_error=False)
                enviados += len(acoes)
            cne = dict(manifesto.get("cne") or {})
            cne.update({"indexados": enviados, "indexado_em": _now()})
            manifesto["cne"] = cne
            _write_manifest(manifesto)
            resultado["indexados"] += enviados
            resultado["registos_indexados"] = enviados
        except Exception as exc:  # noqa: BLE001
            logger.exception("Partidos: falha a indexar o registo da CNE")
            resultado["errors"].append({"ano": None, "fonte": "cne", "error": f"{type(exc).__name__}: {exc}"})
        if progresso is not None:
            progresso["ficheiros_done"] = progresso.get("ficheiros_done", 0) + 1
            progresso["registos"] = resultado["indexados"]
            progresso["current"] = None

    _indexar_recolhas(cliente, manifesto)
    for indice in (esc.PARTIDOS_INDEX, esc.PARTIDOS_REGISTO_INDEX, esc.PARTIDOS_RECOLHAS_INDEX):
        try:
            cliente.indices.refresh(index=indice)
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh de %s ignorado: %s", indice, exc)

    if progresso is not None:
        progresso["phase"] = "indexado"
        progresso["current"] = None
    return resultado


def _indexar_recolhas(cliente: Any, manifesto: Dict[str, Any]) -> int:
    """Regista em `finance_partidos_recolhas` o que está em disco e indexado."""
    from api import elasticsearch_client as esc

    enviados = 0
    for chave_ano, entrada in sorted((manifesto.get("anos") or {}).items()):
        documento = {**entrada, "recolha_id": f"tc-{chave_ano}", "fonte": "tc", "ingested_at": _now()}
        try:
            cliente.index(index=esc.PARTIDOS_RECOLHAS_INDEX, id=documento["recolha_id"], document=documento, refresh=False)
            enviados += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("Partidos: recolha %s não registada (%s)", chave_ano, exc)
    cne = manifesto.get("cne")
    if cne:
        documento = {**{k: v for k, v in cne.items() if k != "partidos"}, "recolha_id": "cne", "fonte": "cne", "ingested_at": _now()}
        try:
            cliente.index(index=esc.PARTIDOS_RECOLHAS_INDEX, id="cne", document=documento, refresh=False)
            enviados += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("Partidos: recolha da CNE não registada (%s)", exc)
    return enviados


# ---------------------------------------------------------------------------
# Pesquisa
# ---------------------------------------------------------------------------


def _cliente(es: Any = None) -> Any:
    from api import elasticsearch_client as esc

    return es or esc.get_es_client()


def _filtros_search(
    *,
    ano: Optional[int],
    secao: Optional[str],
    partido_chave: Optional[str],
    sigla: Optional[str],
    entregou: Optional[bool],
) -> List[Dict[str, Any]]:
    filtros: List[Dict[str, Any]] = []
    if ano:
        filtros.append({"term": {"ano": int(ano)}})
    if secao:
        filtros.append({"term": {"secao": secao}})
    if partido_chave:
        filtros.append({"term": {"partido_chave": _chave_partido(partido_chave) or partido_chave}})
    if sigla:
        filtros.append({"term": {"partido_sigla": sigla}})
    if entregou is not None:
        filtros.append({"term": {"entregou": bool(entregou)}})
    return filtros


def search(
    q: Optional[str] = None,
    *,
    ano: Optional[int] = None,
    secao: Optional[str] = None,
    partido: Optional[str] = None,
    sigla: Optional[str] = None,
    entregou: Optional[bool] = None,
    com_documento: Optional[bool] = None,
    digitalizado: Optional[bool] = None,
    sort: str = "relevancia",
    order: str = "desc",
    page: int = 1,
    size: int = 25,
    es: Any = None,
) -> Dict[str, Any]:
    """Pesquisa nos documentos do financiamento partidário, com facetas.

    `q` procura no nome do partido, no título da secção e **no texto extraído do
    PDF** — é o que permite encontrar, por exemplo, «demonstração de resultados»
    nos relatórios e decisões da ECFP (as contas anuais são digitalizações e não
    têm texto).
    """
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}, "kpis": {}}
    esc.ensure_indices(cliente)

    filtros = _filtros_search(ano=ano, secao=secao, partido_chave=partido, sigla=sigla, entregou=entregou)
    if com_documento is not None:
        filtros.append({"term": {"documento": bool(com_documento)}})
    if digitalizado is not None:
        filtros.append({"term": {"pdf_digitalizado": bool(digitalizado)}})
    must: List[Dict[str, Any]] = []
    termo = (q or "").strip()
    if termo:
        chave = _chave_partido(termo)
        deve: List[Dict[str, Any]] = [
            {"multi_match": {
                "query": termo,
                "fields": ["partido_nome^4", "partido_sigla^3", "secao_titulo^2", "observacao", "texto"],
                "type": "best_fields",
            }}
        ]
        if chave:
            deve.append({"term": {"partido_chave": chave}})
        must.append({"bool": {"should": deve, "minimum_should_match": 1}})

    ordenar = {
        "relevancia": [{"_score": "desc"}, {"ano": "desc"}],
        "ano": [{"ano": order}, {"secao": "asc"}, {"ordem": "asc"}],
        "partido": [{"partido_nome.keyword": order}, {"ano": "desc"}],
        "secao": [{"secao": order}, {"ano": "desc"}],
        "paginas": [{"paginas": order}, {"ano": "desc"}],
    }.get(sort) or [{"_score": "desc"}, {"ano": "desc"}]

    corpo: Dict[str, Any] = {
        "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filtros}},
        "from": max(0, (page - 1) * size),
        "size": size,
        "sort": ordenar,
        "track_total_hits": True,
        "aggs": {
            "por_ano": {"terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}}},
            "por_secao": {"terms": {"field": "secao", "size": 10}},
            "por_partido": {"terms": {"field": "partido_chave", "size": 40}, "aggs": {"nome": {"terms": {"field": "partido_nome.keyword", "size": 1}}}},
            "entregues": {"filter": {"term": {"entregou": True}}},
            "em_falta": {"filter": {"term": {"entregou": False}}},
            "com_documento": {"filter": {"term": {"documento": True}}},
            "com_texto": {"filter": {"term": {"texto_extraido": True}}},
            "digitalizados": {"filter": {"term": {"pdf_digitalizado": True}}},
        },
    }
    try:
        resposta = cliente.search(index=esc.PARTIDOS_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pesquisa de partidos falhou")
        return {"error": str(exc), "total": 0, "items": [], "facets": {}, "kpis": {}}

    agregacoes = resposta.get("aggregations") or {}

    def _buckets(nome: str) -> List[Dict[str, Any]]:
        return list(((agregacoes.get(nome) or {}).get("buckets") or []))

    por_partido = []
    for bucket in _buckets("por_partido"):
        nomes = ((bucket.get("nome") or {}).get("buckets") or [])
        por_partido.append(
            {
                "key": bucket.get("key"),
                "nome": (nomes[0].get("key") if nomes else None),
                "count": bucket.get("doc_count"),
            }
        )

    total = (resposta.get("hits") or {}).get("total") or {}
    return {
        "total": int(total.get("value") or 0) if isinstance(total, dict) else int(total or 0),
        "items": [{**(hit.get("_source") or {}), "doc_id": hit.get("_id"), "score": hit.get("_score")} for hit in ((resposta.get("hits") or {}).get("hits") or [])],
        "page": page,
        "size": size,
        "facets": {
            "ano": [{"key": bucket.get("key"), "count": bucket.get("doc_count")} for bucket in _buckets("por_ano")],
            "secao": [
                {
                    "key": bucket.get("key"),
                    "label": SECOES_LABEL.get(str(bucket.get("key")), str(bucket.get("key"))),
                    "count": bucket.get("doc_count"),
                }
                for bucket in _buckets("por_secao")
            ],
            "partido": por_partido,
        },
        "kpis": {
            "entregues": (agregacoes.get("entregues") or {}).get("doc_count", 0),
            "em_falta": (agregacoes.get("em_falta") or {}).get("doc_count", 0),
            "com_documento": (agregacoes.get("com_documento") or {}).get("doc_count", 0),
            "com_texto": (agregacoes.get("com_texto") or {}).get("doc_count", 0),
            "digitalizados": (agregacoes.get("digitalizados") or {}).get("doc_count", 0),
        },
    }


def resumo(*, anos: Optional[Iterable[int]] = None, es: Any = None) -> Dict[str, Any]:
    """Painel do módulo: por ano, por secção, partidos e cumprimento."""
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível"}
    esc.ensure_indices(cliente)

    filtros: List[Dict[str, Any]] = []
    lista_anos = sorted({int(ano) for ano in anos}) if anos else []
    if lista_anos:
        filtros.append({"terms": {"ano": lista_anos}})
    filtro = {"bool": {"filter": filtros}} if filtros else None

    corpo: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "aggs": {
            "por_ano": {
                "terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}},
                "aggs": {
                    "secoes": {"terms": {"field": "secao", "size": 10}},
                    "partidos": {"cardinality": {"field": "partido_chave"}},
                    "documentos": {"filter": {"term": {"documento": True}}},
                    "com_texto": {"filter": {"term": {"texto_extraido": True}}},
                    "em_falta": {"filter": {"term": {"entregou": False}}},
                    "paginas": {"sum": {"field": "paginas"}},
                    "megabytes": {"sum": {"field": "ficheiro_kb"}},
                },
            },
            "por_secao": {"terms": {"field": "secao", "size": 10}},
            "top_partidos": {
                "terms": {"field": "partido_chave", "size": 40},
                "aggs": {
                    "nome": {"terms": {"field": "partido_nome.keyword", "size": 1}},
                    "documentos": {"filter": {"term": {"documento": True}}},
                    "com_texto": {"filter": {"term": {"texto_extraido": True}}},
                    "digitalizados": {"filter": {"term": {"pdf_digitalizado": True}}},
                    "em_falta": {"filter": {"term": {"entregou": False}}},
                    "paginas": {"sum": {"field": "paginas"}},
                    "megabytes": {"sum": {"field": "ficheiro_kb"}},
                },
            },
            "por_secao": {"terms": {"field": "secao", "size": 10}},
            "top_partidos": {
                "terms": {"field": "partido_chave", "size": 40},
                "aggs": {
                    "nome": {"terms": {"field": "partido_nome.keyword", "size": 1}},
                    "documentos": {"filter": {"term": {"documento": True}}},
                    "em_falta": {"filter": {"term": {"entregou": False}}},
                    "anos": {"cardinality": {"field": "ano"}},
                },
            },
            "entregues": {"filter": {"term": {"entregou": True}}},
            "em_falta": {"filter": {"term": {"entregou": False}}},
            "com_texto": {"filter": {"term": {"texto_extraido": True}}},
            "digitalizados": {"filter": {"term": {"pdf_digitalizado": True}}},
            "partidos_distintos": {"cardinality": {"field": "partido_chave"}},
            "paginas": {"sum": {"field": "paginas"}},
        },
    }
    if filtro:
        corpo["query"] = filtro
    try:
        resposta = cliente.search(index=esc.PARTIDOS_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Resumo de partidos falhou")
        return {"error": str(exc)}

    agregacoes = resposta.get("aggregations") or {}

    def _buckets(nome: str) -> List[Dict[str, Any]]:
        return list(((agregacoes.get(nome) or {}).get("buckets") or []))

    por_ano = []
    for bucket in _buckets("por_ano"):
        por_ano.append(
            {
                "ano": bucket.get("key"),
                "entradas": bucket.get("doc_count"),
                "partidos": (bucket.get("partidos") or {}).get("value", 0),
                "documentos": (bucket.get("documentos") or {}).get("doc_count", 0),
                "com_texto": (bucket.get("com_texto") or {}).get("doc_count", 0),
                "digitalizados": (bucket.get("digitalizados") or {}).get("doc_count", 0),
                "em_falta": (bucket.get("em_falta") or {}).get("doc_count", 0),
                "paginas": int((bucket.get("paginas") or {}).get("value") or 0),
                "megabytes": round(float((bucket.get("megabytes") or {}).get("value") or 0.0) / 1024, 1),
                "secoes": [
                    {
                        "secao": sub.get("key"),
                        "label": SECOES_LABEL.get(str(sub.get("key")), str(sub.get("key"))),
                        "count": sub.get("doc_count"),
                    }
                    for sub in ((bucket.get("secoes") or {}).get("buckets") or [])
                ],
            }
        )

    top_partidos = []
    for bucket in _buckets("top_partidos"):
        nomes = ((bucket.get("nome") or {}).get("buckets") or [])
        top_partidos.append(
            {
                "chave": bucket.get("key"),
                "nome": (nomes[0].get("key") if nomes else None),
                "count": bucket.get("doc_count"),
                "documentos": (bucket.get("documentos") or {}).get("doc_count", 0),
                "em_falta": (bucket.get("em_falta") or {}).get("doc_count", 0),
                "anos": (bucket.get("anos") or {}).get("value", 0),
            }
        )

    total = (resposta.get("hits") or {}).get("total") or {}
    registo = _resumo_registo(cliente)
    return {
        "total": int(total.get("value") or 0) if isinstance(total, dict) else int(total or 0),
        "partidos_distintos": (agregacoes.get("partidos_distintos") or {}).get("value", 0),
        "entregues": (agregacoes.get("entregues") or {}).get("doc_count", 0),
        "em_falta": (agregacoes.get("em_falta") or {}).get("doc_count", 0),
        "com_texto": (agregacoes.get("com_texto") or {}).get("doc_count", 0),
        "digitalizados": (agregacoes.get("digitalizados") or {}).get("doc_count", 0),
        "paginas": int((agregacoes.get("paginas") or {}).get("value") or 0),
        "por_ano": por_ano,
        "por_secao": [
            {
                "secao": bucket.get("key"),
                "label": SECOES_LABEL.get(str(bucket.get("key")), str(bucket.get("key"))),
                "count": bucket.get("doc_count"),
            }
            for bucket in _buckets("por_secao")
        ],
        "top_partidos": top_partidos,
        "registo": registo,
    }


def _resumo_registo(cliente: Any) -> Dict[str, Any]:
    """Contagens do registo oficial (CNE), tolerante à falta do índice."""
    from api import elasticsearch_client as esc

    try:
        resposta = cliente.search(
            index=esc.PARTIDOS_REGISTO_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "situacao": {"terms": {"field": "situacao", "size": 5}},
                    "com_site": {"filter": {"exists": {"field": "site"}}},
                    "com_descricao": {"filter": {"exists": {"field": "descricao"}}},
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Partidos: resumo do registo indisponível (%s)", exc)
        return {"total": 0}
    agregacoes = resposta.get("aggregations") or {}
    total = (resposta.get("hits") or {}).get("total") or {}
    return {
        "total": int(total.get("value") or 0) if isinstance(total, dict) else int(total or 0),
        "inscritos": next((bucket.get("doc_count") for bucket in ((agregacoes.get("situacao") or {}).get("buckets") or []) if bucket.get("key") == "inscrito"), 0),
        "extintos": next((bucket.get("doc_count") for bucket in ((agregacoes.get("situacao") or {}).get("buckets") or []) if bucket.get("key") == "extinto"), 0),
        "com_site": (agregacoes.get("com_site") or {}).get("doc_count", 0),
        "com_descricao": (agregacoes.get("com_descricao") or {}).get("doc_count", 0),
    }


# ---------------------------------------------------------------------------
# Fichas
# ---------------------------------------------------------------------------


def por_partido(termo: str, *, size: int = 400, es: Any = None) -> Dict[str, Any]:
    """Ficha de um partido: o que a CNE regista e o que a ECFP publica.

    O `termo` pode ser a sigla (`PCP`), a chave (`CDSPP`) ou o nome
    («Bloco de Esquerda»). Junta o registo oficial (CNE) com todos os documentos
    do Tribunal Constitucional, ano a ano, e o resumo do cumprimento.
    """
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível"}
    esc.ensure_indices(cliente)

    termo = str(termo or "").strip()
    if not termo:
        return {"error": "Indique a sigla, a chave ou o nome do partido"}
    chave = _chave_partido(termo)

    corpo: Dict[str, Any] = {
        "query": {
            "bool": {
                "should": [
                    {"term": {"partido_chave": chave}},
                    {"term": {"partido_sigla": termo}},
                    {"match_phrase": {"partido_nome": termo}},
                    {"match": {"partido_nome": {"query": termo, "operator": "and"}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "size": max(1, min(int(size), 1000)),
        "sort": [{"ano": "desc"}, {"secao": "asc"}, {"ordem": "asc"}],
        "track_total_hits": True,
        "aggs": {
            "por_ano": {
                "terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}},
                "aggs": {"secoes": {"terms": {"field": "secao", "size": 10}}, "em_falta": {"filter": {"term": {"entregou": False}}}},
            },
            "por_secao": {"terms": {"field": "secao", "size": 10}},
            "chaves": {"terms": {"field": "partido_chave", "size": 10}},
            "em_falta": {"filter": {"term": {"entregou": False}}},
            "com_texto": {"filter": {"term": {"texto_extraido": True}}},
        },
    }
    try:
        resposta = cliente.search(index=esc.PARTIDOS_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    documentos = [{**(hit.get("_source") or {}), "doc_id": hit.get("_id")} for hit in ((resposta.get("hits") or {}).get("hits") or [])]
    if not documentos:
        return {"termo": termo, "chave": chave, "encontrado": False, "documentos": [], "registo": None}
    agregacoes = resposta.get("aggregations") or {}
    nome = next((documento.get("partido_nome") for documento in documentos if documento.get("partido_nome")), None)
    sigla = next((documento.get("partido_sigla") for documento in documentos if documento.get("partido_sigla")), None)
    chaves = [bucket.get("key") for bucket in ((agregacoes.get("chaves") or {}).get("buckets") or [])]

    return {
        "termo": termo,
        "chave": chave,
        "encontrado": True,
        "partido_nome": nome,
        "partido_sigla": sigla,
        "chaves": chaves,
        "registo": registo_do_partido(termo, chaves=chaves, nome=nome, sigla=sigla, es=cliente),
        "total": int(((resposta.get("hits") or {}).get("total") or {}).get("value") or 0),
        "em_falta": (agregacoes.get("em_falta") or {}).get("doc_count", 0),
        "com_texto": (agregacoes.get("com_texto") or {}).get("doc_count", 0),
        "por_ano": [
            {
                "ano": bucket.get("key"),
                "entradas": bucket.get("doc_count"),
                "em_falta": (bucket.get("em_falta") or {}).get("doc_count", 0),
                "secoes": [
                    {"secao": sub.get("key"), "label": SECOES_LABEL.get(str(sub.get("key")), str(sub.get("key"))), "count": sub.get("doc_count")}
                    for sub in ((bucket.get("secoes") or {}).get("buckets") or [])
                ],
            }
            for bucket in ((agregacoes.get("por_ano") or {}).get("buckets") or [])
        ],
        "por_secao": [
            {"secao": bucket.get("key"), "label": SECOES_LABEL.get(str(bucket.get("key")), str(bucket.get("key"))), "count": bucket.get("doc_count")}
            for bucket in ((agregacoes.get("por_secao") or {}).get("buckets") or [])
        ],
        "documentos": documentos,
    }


def registo_do_partido(
    termo: str,
    *,
    chaves: Optional[Sequence[str]] = None,
    nome: Optional[str] = None,
    sigla: Optional[str] = None,
    es: Any = None,
) -> Optional[Dict[str, Any]]:
    """Ficha da CNE que corresponde a uma sigla, chave ou nome do TC."""
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return None
    esc.ensure_indices(cliente)
    candidatas = sorted({chave for chave in ([_chave_partido(termo), _chave_partido(sigla or ""), _chave_partido(nome or "")] + list(chaves or [])) if chave})
    deve: List[Dict[str, Any]] = [{"terms": {"siglas": candidatas}}, {"term": {"chave": candidatas[0]}}] if candidatas else []
    if nome:
        deve.append({"match_phrase": {"denominacao": nome}})
    if termo:
        deve.append({"match_phrase": {"denominacao": termo}})
    if not deve:
        return None
    try:
        resposta = cliente.search(
            index=esc.PARTIDOS_REGISTO_INDEX,
            body={"query": {"bool": {"should": deve, "minimum_should_match": 1}}, "size": 1, "sort": [{"_score": "desc"}]},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Partidos: registo não encontrado (%s)", exc)
        return None
    hits = ((resposta.get("hits") or {}).get("hits") or [])
    return {**(hits[0].get("_source") or {}), "chave_doc": hits[0].get("_id")} if hits else None


def listar_registo(
    *,
    q: Optional[str] = None,
    situacao: Optional[str] = None,
    page: int = 1,
    size: int = 50,
    es: Any = None,
) -> Dict[str, Any]:
    """Registo oficial dos partidos (CNE): inscritos e extintos."""
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}
    esc.ensure_indices(cliente)

    filtros: List[Dict[str, Any]] = []
    if situacao:
        filtros.append({"term": {"situacao": situacao}})
    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"denominacao": {"query": q, "boost": 3}}},
                        {"match": {"denominacao": {"query": q, "operator": "and"}}},
                        {"term": {"sigla": _sem_acentos(q)}},
                        {"term": {"siglas": _chave_partido(q)}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    corpo = {
        "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filtros}},
        "from": max(0, (page - 1) * size),
        "size": max(1, min(int(size), 200)),
        "sort": [{"situacao": "asc"}, {"denominacao.keyword": "asc"}],
        "track_total_hits": True,
    }
    try:
        resposta = cliente.search(index=esc.PARTIDOS_REGISTO_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "total": 0, "items": []}
    total = ((resposta.get("hits") or {}).get("total") or {}).get("value") or 0
    return {
        "total": int(total),
        "page": page,
        "size": size,
        "items": [{**(hit.get("_source") or {}), "doc_id": hit.get("_id")} for hit in ((resposta.get("hits") or {}).get("hits") or [])],
    }


# ---------------------------------------------------------------------------
# Pessoas e partidos
# ---------------------------------------------------------------------------


def _partido_da_pessoa(pessoa: Dict[str, Any]) -> Optional[str]:
    """Partido de uma pessoa, dos campos que o PessoasIQ usa para o guardar."""
    metadados = pessoa.get("metadata") if isinstance(pessoa.get("metadata"), dict) else {}
    for candidato in (
        metadados.get("party"),
        metadados.get("partido"),
        metadados.get("Party"),
        pessoa.get("party"),
        pessoa.get("partido"),
    ):
        if candidato and str(candidato).strip().lower() not in ("independent", "independente", "sem partido"):
            return str(candidato).strip()
    return None


def pessoa_e_partido(nif: str, *, es: Any = None) -> Dict[str, Any]:
    """A pessoa (PessoasIQ) e o partido dela, com as contas do partido.

    É a ponte entre os dois módulos: a ficha de uma pessoa mostra o partido que
    tem no registo e, a partir daí, as contas que a ECFP publicou para esse
    partido — sem obrigar a procurar a sigla à mão.
    """
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível"}

    pessoa = esc.get_person_by_nif(str(nif or "").strip(), es=cliente)
    if pessoa.get("error"):
        return {"nif": str(nif), "error": pessoa["error"]}

    partido = _partido_da_pessoa(pessoa) if isinstance(pessoa, dict) else None
    ficha = None
    if partido:
        ficha = por_partido(partido, size=200, es=cliente)
        if isinstance(ficha, dict) and not ficha.get("encontrado"):
            ficha = None
    return {
        "nif": str(nif),
        "pessoa": {
            "nif": pessoa.get("nif"),
            "nome": pessoa.get("name") or pessoa.get("nome"),
            "cargos": (pessoa.get("roles") or [])[:20] if isinstance(pessoa.get("roles"), list) else [],
            "fonte": pessoa.get("source"),
            "partido": partido,
            "metadata": pessoa.get("metadata") or {},
        },
        "partido": partido,
        "ficha_partido": ficha,
    }


def pessoas_do_partido(termo: str, *, size: int = 60, es: Any = None) -> Dict[str, Any]:
    """Pessoas indexadas no PessoasIQ com este partido (deputados, políticos)."""
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ficha = por_partido(termo, size=1, es=cliente)
    nome = None
    if isinstance(ficha, dict) and ficha.get("encontrado"):
        nome = ficha.get("partido_nome")
    alvo = str(termo or "").strip()
    resultado = esc.search_people(party=alvo, size=size, es=cliente)
    if not resultado.get("total") and nome and nome != alvo:
        resultado = esc.search_people(party=nome, size=size, es=cliente)
    if not resultado.get("total"):
        registro = registo_do_partido(alvo, es=cliente) or {}
        for candidato in (registro.get("denominacao"), registro.get("sigla")):
            if not candidato:
                continue
            resultado = esc.search_people(party=candidato, size=size, es=cliente)
            if resultado.get("total"):
                break
    return {
        "termo": alvo,
        "partido": nome or alvo,
        "total": resultado.get("total", 0),
        "items": [
            {
                "nif": item.get("nif"),
                "nome": item.get("name") or item.get("nome"),
                "partido": _partido_da_pessoa(item),
                "source": item.get("source"),
                "roles_count": item.get("roles_count"),
            }
            for item in (resultado.get("items") or [])
        ],
        "error": resultado.get("error"),
    }


# ---------------------------------------------------------------------------
# Documentos em disco
# ---------------------------------------------------------------------------


def caminho_documento(ano: int, ficheiro: str) -> Path:
    """Caminho do PDF guardado, validado contra saída da pasta (`path traversal`)."""
    nome = Path(str(ficheiro or "")).name
    if not nome or nome != str(ficheiro or "").strip():
        raise ValueError("Nome de ficheiro inválido")
    caminho = (pdf_dir(int(ano)) / nome).resolve()
    raiz = pdf_dir().resolve()
    if raiz not in caminho.parents:
        raise ValueError("Ficheiro fora da pasta do módulo")
    return caminho


def amostra(ano: int, *, limite: int = 50) -> Dict[str, Any]:
    """Entradas de um ano lidas do JSONL (não precisa do Elasticsearch)."""
    caminho = _jsonl_do_ano(int(ano))
    if not caminho.exists():
        return {"ano": int(ano), "total": 0, "items": [], "error": "Ano não lido (corra a recolha)"}
    itens: List[Dict[str, Any]] = []
    total = 0
    for documento in _iter_jsonl(caminho):
        total += 1
        if len(itens) < max(1, int(limite)):
            itens.append({chave: valor for chave, valor in documento.items() if chave != "texto"})
    return {"ano": int(ano), "total": total, "items": itens}


def ficheiros() -> Dict[str, Any]:
    """O que está em disco: páginas, PDF e JSONL."""
    paginas = sorted(caminho.name for caminho in paginas_dir().glob("*.html")) if paginas_dir().exists() else []
    pdfs = []
    if pdf_dir().exists():
        for pasta in sorted(pdf_dir().iterdir()):
            if not pasta.is_dir() or not pasta.name.isdigit():
                continue
            for ficheiro in sorted(pasta.glob("*.pdf")):
                pdfs.append(
                    {
                        "ano": int(pasta.name),
                        "ficheiro": ficheiro.name,
                        "bytes": ficheiro.stat().st_size,
                        "modificado_em": datetime.fromtimestamp(ficheiro.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    }
                )
    jsonl = []
    if normalized_dir().exists():
        for ficheiro in sorted(normalized_dir().glob("*.jsonl")):
            jsonl.append({"ficheiro": ficheiro.name, "bytes": ficheiro.stat().st_size})
    return {
        "dir": str(data_dir()),
        "paginas": paginas,
        "pdf": pdfs,
        "pdf_total": len(pdfs),
        "pdf_bytes": sum(item["bytes"] for item in pdfs),
        "jsonl": jsonl,
        "cne": sorted(caminho.name for caminho in cne_dir().glob("*.html")) if cne_dir().exists() else [],
    }


def fontes() -> Dict[str, Any]:
    """As fontes do módulo e o que cada uma dá."""
    return {
        "fontes": [
            {
                "id": "tc",
                "nome": "Tribunal Constitucional — Financiamento Partidário",
                "url": TC_INDICE_URL,
                "url_ano": TC_ANO_URL.format(ano="{ano}"),
                "descricao": (
                    "Páginas anuais da Entidade das Contas e Financiamentos Políticos (ECFP): "
                    "contas anuais dos partidos, listas de ações e meios de propaganda política, "
                    "relatórios, acórdãos e decisões."
                ),
                "secoes": [{"id": identificador, "ancora": ancora, "label": rotulo} for ancora, (identificador, rotulo) in SECOES.items()],
            },
            {
                "id": "cne",
                "nome": "CNE — Partidos Políticos",
                "url": CNE_LISTA_URL,
                "descricao": (
                    "Registo oficial dos partidos políticos: denominação, sigla, data de inscrição, "
                    "inscritos e extintos, sítio na Internet, símbolo e descrição."
                ),
            },
        ],
        "indices": ["finance_partidos", "finance_partidos_registo", "finance_partidos_recolhas"],
    }


def meta() -> Dict[str, Any]:
    """O que está em disco, o que está lido e o que está indexado."""
    manifesto = read_manifest()
    anos_manifesto: Dict[str, Any] = manifesto.get("anos") or {}
    em_disco = {int(caminho.stem) for caminho in paginas_dir().glob("*.html") if caminho.stem.isdigit()} if paginas_dir().exists() else set()
    anos: List[Dict[str, Any]] = []
    for chave, entrada in sorted(anos_manifesto.items(), key=lambda par: int(par[0]), reverse=True):
        anos.append(
            {
                "ano": int(chave),
                "url": entrada.get("url"),
                "sha256": entrada.get("sha256"),
                "bytes": entrada.get("bytes"),
                "secoes": entrada.get("secoes") or [],
                "itens": entrada.get("itens"),
                "notas": entrada.get("notas"),
                "documentos": entrada.get("documentos"),
                "partidos": entrada.get("partidos"),
                "pdfs": entrada.get("pdfs"),
                "com_texto": entrada.get("com_texto"),
                "sem_documento": entrada.get("sem_documento"),
                "indexados": entrada.get("indexados"),
                "recolhido_em": entrada.get("recolhido_em"),
                "indexado_em": entrada.get("indexado_em"),
                "em_disco": int(chave) in em_disco,
            }
        )
    ficheiros_disco = ficheiros()
    return {
        "dir": str(data_dir()),
        "anos": anos,
        "anos_recolhidos": len(anos),
        "anos_em_disco": sorted(em_disco, reverse=True),
        "itens": sum(int(entrada.get("itens") or 0) for entrada in anos_manifesto.values()),
        "documentos": sum(int(entrada.get("documentos") or 0) for entrada in anos_manifesto.values()),
        "pdfs": ficheiros_disco["pdf_total"],
        "pdf_bytes": ficheiros_disco["pdf_bytes"],
        "cne": manifesto.get("cne") or {},
        "fontes": fontes()["fontes"],
        "indices": ["finance_partidos", "finance_partidos_registo", "finance_partidos_recolhas"],
    }


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

CSV_CABECALHO = [
    "ano",
    "secao",
    "partido_sigla",
    "partido_nome",
    "entregou",
    "motivo",
    "observacao",
    "ficheiro",
    "paginas",
    "ficheiro_kb",
    "pdf_url",
]


def _iterar_tudo(
    *,
    filtros: Sequence[Dict[str, Any]] = (),
    must: Sequence[Dict[str, Any]] = (),
    maximo: int = 50_000,
    es: Any = None,
) -> Iterator[Dict[str, Any]]:
    """Percorre os documentos indexados (scroll), para exportar."""
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return
    corpo = {
        "query": {"bool": {"must": list(must) or [{"match_all": {}}], "filter": list(filtros)}},
        "sort": ["_doc"],
        "size": 1000,
        "_source": list(CSV_CABECALHO),
    }
    enviados = 0
    resposta = cliente.search(index=esc.PARTIDOS_INDEX, body=corpo, scroll="2m")
    while True:
        hits = ((resposta.get("hits") or {}).get("hits") or [])
        if not hits:
            break
        for hit in hits:
            yield hit.get("_source") or {}
            enviados += 1
            if enviados >= maximo:
                break
        if enviados >= maximo:
            break
        scroll_id = resposta.get("_scroll_id")
        if not scroll_id:
            break
        resposta = cliente.scroll(scroll_id=scroll_id, scroll="2m")
    scroll_id = resposta.get("_scroll_id") if isinstance(resposta, dict) else None
    if scroll_id:
        try:
            cliente.clear_scroll(scroll_id=scroll_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Partidos: clear_scroll ignorado (%s)", exc)


def csv_bytes(
    *,
    maximo: int = 50_000,
    q: Optional[str] = None,
    ano: Optional[int] = None,
    secao: Optional[str] = None,
    partido: Optional[str] = None,
    sigla: Optional[str] = None,
    entregou: Optional[bool] = None,
    es: Any = None,
) -> bytes:
    """Exportação CSV (delimitador `;`, BOM para o Excel) da pesquisa."""
    import csv as _csv

    filtros = _filtros_search(ano=ano, secao=secao, partido_chave=partido, sigla=sigla, entregou=entregou)
    must: List[Dict[str, Any]] = []
    termo = (q or "").strip()
    if termo:
        must.append(
            {
                "multi_match": {
                    "query": termo,
                    "fields": ["partido_nome^4", "partido_sigla^3", "secao_titulo^2", "observacao", "texto"],
                    "type": "best_fields",
                }
            }
        )
    buffer = io.StringIO()
    escritor = _csv.writer(buffer, delimiter=";", lineterminator="\n")
    escritor.writerow(CSV_CABECALHO)
    for registo in _iterar_tudo(filtros=filtros, must=must, maximo=maximo, es=es):
        escritor.writerow(["" if registo.get(coluna) is None else registo.get(coluna) for coluna in CSV_CABECALHO])
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Trabalhos (recolha e indexação em segundo plano)
# ---------------------------------------------------------------------------


def _prune_jobs() -> None:
    if len(_JOBS) <= _JOBS_KEEP:
        return
    antigos = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""))
    for job in antigos[: len(_JOBS) - _JOBS_KEEP]:
        if job.get("status") == _RUNNING:
            continue
        _JOBS.pop(str(job["job_id"]), None)


def start_job(tipo: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Arranca «recolher» (TC+CNE → JSONL) ou «indexar» (JSONL → Elasticsearch)."""
    if tipo not in TIPOS_JOB:
        raise ValueError(f"Tipo de trabalho desconhecido: {tipo}")
    with _JOBS_LOCK:
        for job in _JOBS.values():
            if job.get("status") == _RUNNING and job.get("tipo") == tipo:
                return {
                    "job_id": job["job_id"],
                    "tipo": tipo,
                    "status": _RUNNING,
                    "already_running": True,
                    "message": "Já existe um trabalho deste tipo a correr.",
                }
        job: Dict[str, Any] = {
            "job_id": uuid.uuid4().hex[:12],
            "tipo": tipo,
            "status": _RUNNING,
            "started_at": _now(),
            "finished_at": None,
            "payload": dict(payload or {}),
            "progress": {
                "phase": "a começar",
                "anos_total": 0,
                "anos_done": 0,
                "ficheiros_total": 0,
                "ficheiros_done": 0,
                "registos": 0,
                "current": None,
            },
            "result": None,
            "error": None,
        }
        _JOBS[job["job_id"]] = job
        _prune_jobs()
    threading.Thread(target=_run_job, args=(job,), name=f"partidos-{tipo}", daemon=True).start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    try:
        payload = job["payload"]
        progresso = job["progress"]
        anos = payload.get("anos") or None
        if job["tipo"] == "recolher":
            resultado = recolher(
                anos,
                com_pdf=bool(payload.get("com_pdf", True)),
                secoes=payload.get("secoes") or None,
                forcar=bool(payload.get("forcar")),
                com_cne=bool(payload.get("com_cne", True)),
                progresso=progresso,
            )
            if payload.get("indexar"):
                progresso["phase"] = "a indexar"
                resultado["indexacao"] = indexar(anos or resultado.get("anos", {}).keys(), forcar=True, progresso=progresso)
        else:
            resultado = indexar(anos, forcar=bool(payload.get("forcar")), progresso=progresso)
        job["result"] = resultado
        erros = resultado.get("errors") or []
        job["status"] = "error" if resultado.get("error") else "done"
        if erros:
            job["error"] = f"{len(erros)} item(ns) com erro"
        job["finished_at"] = _now()
        progresso["phase"] = "concluído"
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Trabalho de partidos falhou")
        job["status"] = "error"
        job["finished_at"] = _now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["progress"]["phase"] = "erro"
    finally:
        job["progress"]["current"] = None


def list_jobs() -> Dict[str, Any]:
    """Trabalhos de partidos (mais recentes primeiro)."""
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""), reverse=True)
        return {"total": len(jobs), "items": [dict(job) for job in jobs]}


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id))
        return dict(job) if job else None
