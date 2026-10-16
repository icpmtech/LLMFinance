"""CMS IQ OS — páginas, conteúdos, blog, media, menus e publicação.

O CMS é a oficina do **site** da plataforma: constrói páginas por **blocos**,
escreve **artigos de blog** com taxonomia (categorias e etiquetas), guarda
**media**, reutiliza **conteúdos** (blocos com nome, para não repetir o mesmo
texto em várias páginas), define **menus** e **aparência**, e **publica** —
imediatamente ou agendado.

Tudo vive num único documento JSON (`data/cms/cms.json`) com escrita atómica: o
ficheiro é a fonte de verdade e pode ser versionado. Os binários dos media ficam
em `data/cms/media/`; as imagens da marca (logótipo, favicon, capas e
ilustrações) vivem em `api/site_assets/`, para viajarem com o código — o deploy
incremental não envia a pasta `data/` (ver `SEED_MEDIA`).

Estados de publicação (`status`):

* `rascunho` — só visível na plataforma;
* `agendado` — publica sozinho quando `scheduled_at` chega (ver `_apply_schedule`,
  chamado a cada leitura: não é preciso um processo à parte);
* `publicado` — visível no site público (`/site/...`);
* `arquivado` — fora do site, guardado no arquivo.

Toda a escrita passa por `save_item`/`publish_item`, que registam **revisão**
(histórico com restauro) e **atividade** (auditoria legível).
"""
from __future__ import annotations

import base64
import binascii
import copy
import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from api import cms_editorial as editorial
from api import indexnow

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CMS_DIR = ROOT / "data" / "cms"
CMS_PATH = CMS_DIR / "cms.json"
MEDIA_DIR = CMS_DIR / "media"
#: Imagens que viajam com o código (logótipo, favicon, capas e ilustrações).
#: Ficam aqui, e não em `data/`, porque o deploy incremental de código não envia
#: `data/`: sem isto, uma instalação nova ficava sem biblioteca de imagem nenhuma.
SITE_ASSETS_DIR = Path(__file__).resolve().parent / "site_assets"
CMS_VERSION = 1

# Entidades do CMS: as listas dentro do documento.
ENTITIES: Tuple[str, ...] = ("pages", "posts", "municipios", "pesquisas", "remuneracoes", "contents", "media", "categories", "templates", "menus", "contactos")
SINGULAR: Dict[str, str] = {entity: entity.rstrip("s") if entity not in ("media",) else "media" for entity in ENTITIES}
SINGULAR["categories"] = "categoria"

#: Entidades que se **publicam** (têm estado, agendamento e endereço no site).
PUBLISHABLE: Tuple[str, ...] = ("pages", "posts", "municipios", "pesquisas", "remuneracoes")

#: Entidades cujo conteúdo é **privado**: a leitura exige sessão (ao contrário
#: das restantes, que o site público mostra de qualquer maneira). Os contactos
#: têm dados pessoais de quem escreve — nome e email não podem ficar à vista.
PRIVATE_ENTITIES: Tuple[str, ...] = ("contactos",)

#: Estados de um contacto recebido pelo formulário do site.
CONTACTOS_ESTADOS: Tuple[Tuple[str, str], ...] = (
    ("novo", "Novo"),
    ("em_curso", "Em curso"),
    ("tratado", "Tratado"),
)
CONTACTOS_ESTADO_IDS = {estado for estado, _ in CONTACTOS_ESTADOS}

#: Campos do formulário de contacto e o limite de caracteres de cada um.
CONTACTO_LIMITES: Dict[str, int] = {
    "nome": 120,
    "email": 160,
    "organizacao": 160,
    "assunto": 160,
    "mensagem": 4000,
}

#: Rótulo de cada entidade publicável, para listagens e para o `overview`.
ENTITY_LABELS: Dict[str, str] = {
    "pages": "página",
    "posts": "artigo",
    "municipios": "município",
    "pesquisas": "pesquisa",
    "remuneracoes": "remuneração",
}

#: As secções do **modelo de remunerações**: o que a página mostra além do texto
#: e dos blocos editoriais. Cada uma tem um título e um subtítulo que o editor
#: pode reescrever (`seccoes`) e uma ordem (`ordem`); a lista é também a ordem
#: por omissão da página.
SECCOES_REMUNERACOES: Tuple[Tuple[str, str, str], ...] = (
    ("kpis", "O quadro em números", "BRAP, níveis da TRU, posições remuneratórias e cargos dirigentes"),
    ("niveis", "Tabela Remuneratória Única", "remuneração base mensal de cada nível"),
    ("serie", "Base Remuneratória da Administração Pública", "nível 5 da TRU (BRAP), ano a ano"),
    ("carreiras", "Carreiras e posições remuneratórias", "posição remuneratória e remuneração base mensal"),
    ("dirigentes", "Cargos dirigentes e equiparados", "índice, nível da TRU e remuneração base"),
    ("simulador", "Simulador de posição remuneratória", "escolha um nível da TRU ou um cargo dirigente"),
    ("notas", "Notas da DGAEP", "o que o quadro publica, secção a secção"),
    ("parametros", "Base legal", "estrutura da carreira, estrutura remuneratória e outras componentes"),
)
SECCOES_REMUNERACOES_IDS: Tuple[str, ...] = tuple(chave for chave, _, _ in SECCOES_REMUNERACOES)
SECCOES_REMUNERACOES_PADRAO: Dict[str, Dict[str, str]] = {
    chave: {"titulo": titulo, "sub": sub} for chave, titulo, sub in SECCOES_REMUNERACOES
}
#: Limites dos textos das secções (um título é uma linha; o subtítulo, uma frase).
LIMITE_TITULO_SECCAO = 120
LIMITE_SUB_SECCAO = 240

#: O que a página do **modelo de remunerações** mostra. Chave e rótulo de cada
#: secção — o rótulo é o título por omissão, que o editor pode substituir.
MOSTRAR_REMUNERACOES: Tuple[Tuple[str, str], ...] = tuple(
    (chave, titulo) for chave, titulo, _ in SECCOES_REMUNERACOES
)
MOSTRAR_REMUNERACOES_IDS = {chave for chave, _ in MOSTRAR_REMUNERACOES}

#: Como as secções da página se apresentam (o editor escolhe um destes).
ESTILOS_REMUNERACOES: Tuple[Tuple[str, str], ...] = (
    ("cartoes", "Cartões — cada secção numa superfície"),
    ("plano", "Plano — só linhas de separação"),
    ("destaque", "Destaque — cabeçalhos em faixa"),
)
ESTILOS_REMUNERACOES_IDS = {chave for chave, _ in ESTILOS_REMUNERACOES}
ESTILO_REMUNERACOES_PADRAO = "cartoes"


def _mostrar_da_pagina(valor: Any) -> Dict[str, bool]:
    """Que partes do modelo a página mostra (por omissão, todas)."""
    dados = valor if isinstance(valor, dict) else {}
    return {chave: bool(dados.get(chave, True)) for chave, _ in MOSTRAR_REMUNERACOES}


def _seccoes_da_pagina(valor: Any) -> Dict[str, Dict[str, str]]:
    """Títulos e subtítulos das secções, com os do modelo onde o editor não mexeu.

    Guarda **todas** as secções conhecidas (e não só as reescritas): assim a
    página não muda de cabeçalho quando o modelo ganha uma secção nova.
    """
    guardado = valor if isinstance(valor, dict) else {}
    seccoes: Dict[str, Dict[str, str]] = {}
    for chave in SECCOES_REMUNERACOES_IDS:
        atual = guardado.get(chave) if isinstance(guardado.get(chave), dict) else {}
        padrao = SECCOES_REMUNERACOES_PADRAO[chave]
        seccoes[chave] = {
            "titulo": str(atual.get("titulo") or padrao["titulo"]).strip()[:LIMITE_TITULO_SECCAO],
            "sub": str(atual.get("sub") or padrao["sub"]).strip()[:LIMITE_SUB_SECCAO],
        }
    return seccoes


def _ordem_das_seccoes(valor: Any) -> List[str]:
    """Ordem das secções: as conhecidas sem repetições, e as que faltarem no fim."""
    ordem: List[str] = []
    if isinstance(valor, list):
        for item in valor:
            chave = str(item)
            if chave in SECCOES_REMUNERACOES_IDS and chave not in ordem:
                ordem.append(chave)
    ordem.extend(chave for chave in SECCOES_REMUNERACOES_IDS if chave not in ordem)
    return ordem


def _estilo_da_pagina(valor: Any) -> str:
    """Estilo visual da página (`cartoes`, `plano` ou `destaque`)."""
    estilo = str(valor or "").strip().lower()
    return estilo if estilo in ESTILOS_REMUNERACOES_IDS else ESTILO_REMUNERACOES_PADRAO


def _ano_valido(valor: Any, alternativa: Any = None) -> Optional[int]:
    """Ano do quadro (inteiro entre 2000 e 2100), ou o alternativo."""
    for candidato in (valor, alternativa):
        try:
            ano = int(str(candidato).strip()[:4])
        except (TypeError, ValueError, AttributeError):
            continue
        if 2000 <= ano <= 2100:
            return ano
    return None


def _resumo_do_modelo(dados: Dict[str, Any]) -> str:
    """Resumo factual do modelo, para o excerto e para a IA."""
    if not isinstance(dados, dict) or not dados:
        return ""
    contagens = dados.get("contagens") or {}
    parametros = dados.get("parametros") or {}
    partes = [f"{contagens.get('niveis', 0)} níveis da TRU"]
    if parametros.get("brap"):
        partes.append(f"BRAP {str(round(float(parametros['brap']), 2)).replace('.', ',')} €")
    partes.append(f"{contagens.get('carreiras', 0)} carreiras")
    partes.append(f"{contagens.get('dirigentes', 0)} cargos dirigentes")
    return f"Quadro da DGAEP de {dados.get('ano')}: " + ", ".join(partes) + "."


#: Filtros de uma pesquisa (municípios) que se podem congelar numa página.
FILTROS_PESQUISA: Dict[str, Any] = {
    "q": "",
    "distrito": "",
    "nuts": "",
    "ano_contratos": None,
    "ordenar": "despesas",
    "ordem": "desc",
    "min_despesas": None,
    "limite": 25,
}

STATUSES: Tuple[str, ...] = ("rascunho", "agendado", "publicado", "arquivado")
STATUS_LABELS: Dict[str, str] = {
    "rascunho": "Rascunho",
    "agendado": "Agendado",
    "publicado": "Publicado",
    "arquivado": "Arquivado",
}
STATUS_STYLE: Dict[str, str] = {
    "rascunho": "slate",
    "agendado": "amber",
    "publicado": "emerald",
    "arquivado": "zinc",
}

# Tipos de bloco que o editor de páginas sabe desenhar (e o site sabe renderizar).
BLOCK_TYPES: List[Dict[str, Any]] = [
    {"id": "hero", "label": "Destaque (hero)", "hint": "Título grande, subtítulo, imagem e botão", "icon": "Sparkles"},
    {"id": "texto", "label": "Texto", "hint": "Parágrafos em Markdown", "icon": "AlignLeft"},
    {"id": "imagem", "label": "Imagem", "hint": "Uma imagem com legenda", "icon": "Image"},
    {"id": "galeria", "label": "Galeria", "hint": "Conjunto de imagens em grelha", "icon": "Images"},
    {"id": "destaques", "label": "Cartões", "hint": "Cartões de destaque em grelha, com ícone opcional", "icon": "LayoutGrid"},
    {"id": "numeros", "label": "Números", "hint": "Indicadores em tiras (valor, etiqueta e nota)", "icon": "Gauge"},
    {"id": "cta", "label": "Chamada à ação", "hint": "Faixa com botão principal e botões secundários", "icon": "MousePointerClick"},
    {"id": "faq", "label": "Perguntas frequentes", "hint": "Perguntas e respostas", "icon": "HelpCircle"},
    {"id": "passos", "label": "Passos", "hint": "Sequência numerada", "icon": "ListOrdered"},
    {"id": "tabela", "label": "Tabela", "hint": "Tabela de dados simples", "icon": "Table"},
    {
        "id": "grafico",
        "label": "Gráfico",
        "hint": "Barras horizontais a partir de uma lista de valores (opcionalmente duas séries)",
        "icon": "BarChart3",
    },
    {"id": "citacao", "label": "Citação", "hint": "Frase destacada com autor", "icon": "Quote"},
    {"id": "aviso", "label": "Aviso", "hint": "Nota, atenção ou sucesso", "icon": "AlertTriangle"},
    {"id": "codigo", "label": "Código", "hint": "Bloco de código ou comando", "icon": "Code2"},
    {"id": "contactos", "label": "Contactos", "hint": "Email, telefone e morada", "icon": "Phone"},
    {"id": "formulario", "label": "Formulário", "hint": "Formulário de contacto (as respostas ficam no CMS)", "icon": "MailPlus"},
    {"id": "blog", "label": "Últimos artigos", "hint": "Lista os artigos publicados", "icon": "Newspaper"},
    {
        "id": "relatorios",
        "label": "Relatórios e documentos",
        "hint": "Lista os relatórios do catálogo e os documentos já gerados, por área de trabalho",
        "icon": "FileText",
    },
    {"id": "conteudo", "label": "Conteúdo reutilizado", "hint": "Insere um conteúdo guardado no CMS", "icon": "Recycle"},
    {"id": "divisor", "label": "Divisor", "hint": "Linha de separação", "icon": "Minus"},
]
BLOCK_IDS = {block["id"] for block in BLOCK_TYPES}

# Tipos de conteúdo reutilizável («conteúdos»).
CONTENT_KINDS: List[Dict[str, str]] = [
    {"id": "texto", "label": "Texto"},
    {"id": "hero", "label": "Destaque"},
    {"id": "cta", "label": "Chamada à ação"},
    {"id": "faq", "label": "Perguntas frequentes"},
    {"id": "aviso", "label": "Aviso"},
    {"id": "citacao", "label": "Citação"},
    {"id": "tabela", "label": "Tabela"},
    {"id": "contactos", "label": "Contactos"},
    {"id": "rodape", "label": "Rodapé"},
]
CONTENT_KIND_IDS = {kind["id"] for kind in CONTENT_KINDS}

TEMPLATES_KINDS: List[Dict[str, str]] = [
    {"id": "page", "label": "Página"},
    {"id": "post", "label": "Artigo de blog"},
]

#: Modelo da **biblioteca de relatórios** (página pública com os relatórios
#: gratuitos e os documentos já gerados, por área de trabalho). Vive aqui, e não
#: só na semente, porque uma instalação já em uso precisa de o receber pelo
#: `instalar_templates_editoriais()` — o deploy de código não leva a pasta `data/`.
TEMPLATE_BIBLIOTECA: Dict[str, Any] = {
    "id": "tpl_biblioteca",
    "name": "Biblioteca de relatórios",
    "kind": "page",
    "description": "Hero, números, relatórios gratuitos e documentos por área, e chamada à ação.",
    "builtin": True,
    "blocks": [
        {
            "id": "b1",
            "type": "hero",
            "data": {
                "title": "Relatórios gratuitos e documentos já gerados",
                "subtitle": "O que a plataforma já produziu, por área de trabalho.",
                "cta_label": "Ver o catálogo",
                "cta_href": "/reports",
                "align": "esquerda",
            },
        },
        {"id": "b2", "type": "numeros", "data": {"title": "O que já está disponível", "items": []}},
        {"id": "b3", "type": "relatorios", "data": {"title": "Por área de trabalho", "limit": 24, "free_only": False}},
        {
            "id": "b4",
            "type": "cta",
            "data": {
                "title": "Precisa de um relatório à medida?",
                "text": "Diga-nos a empresa ou o setor e montamos o relatório.",
                "button_label": "Pedir um relatório",
                "button_href": "/reports",
            },
        },
    ],
}

#: Modelos que toda a instalação deve ter (usados pelo instalador acima).
TEMPLATES_GARANTIDOS: Tuple[Dict[str, Any], ...] = (TEMPLATE_BIBLIOTECA,)

MENU_LOCATIONS: List[Dict[str, str]] = [
    {"id": "header", "label": "Cabeçalho"},
    {"id": "footer", "label": "Rodapé"},
]

#: Temas de apresentação do menu público. Cada tema pode levar um conjunto de
#: variações (templates) com pequenas diferenças visuais.
MENU_THEMES: List[Dict[str, Any]] = [
    {
        "id": "pastilhas",
        "label": "Pastilhas",
        "templates": [
            {"id": "padrao", "label": "Padrão"},
            {"id": "contorno", "label": "Contorno"},
            {"id": "preenchido", "label": "Preenchido"},
        ],
    },
    {
        "id": "linha",
        "label": "Linha simples",
        "templates": [
            {"id": "padrao", "label": "Padrão"},
            {"id": "subtil", "label": "Subtil"},
        ],
    },
    {
        "id": "central",
        "label": "Centrado",
        "templates": [
            {"id": "padrao", "label": "Padrão"},
            {"id": "grande", "label": "Grande"},
        ],
    },
]

#: Template por omissão para cada tema.
DEFAULT_MENU_TEMPLATE: Dict[str, str] = {theme["id"]: theme["templates"][0]["id"] for theme in MENU_THEMES}


def menu_themes() -> List[Dict[str, Any]]:
    """Temas e templates disponíveis para o menu público."""
    return copy.deepcopy(MENU_THEMES)

MAX_MEDIA_BYTES = 12 * 1024 * 1024
MAX_REVISIONS = 30
MAX_ACTIVITY = 400

MIME_EXT: Dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    "application/pdf": ".pdf",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "text/plain": ".txt",
}
EXT_MIME: Dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".txt": "text/plain",
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "site_name": "Sabemos Studio",
    "tagline": "Inteligência financeira e contratual",
    "description": "Plataforma de inteligência financeira: contratos públicos, empresas, mercado e investigação assistida.",
    "base_url": "",
    "language": "pt-PT",
    "home_page_id": "",
    "blog_page_id": "",
    "posts_per_page": 9,
    "theme": "claro",
    "accent": "#0ea5a4",
    "radius": 14,
    "header_menu_theme": "pastilhas",
    "header_menu_template": "padrao",
    "footer_menu_theme": "pastilhas",
    "footer_menu_template": "padrao",
    "footer_text": "© Sabemos Studio — todos os direitos reservados.",
    "logo_id": None,
    "favicon_id": None,
    "social": {"email": "", "linkedin": "", "x": "", "github": ""},
    "seo": {"title": "", "description": "", "image_id": None, "keywords": []},
    "robots": "index, follow",
    "analytics_id": "",
}

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[int] = None


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _slug(value: str, fallback: str = "conteudo") -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-+", "-", text)
    return text[:72] or fallback


def _keywords(value: Any) -> List[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,\n;]", value) if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _words(text: str) -> int:
    plain = re.sub(r"[#*`>_\-\[\]()!|]", " ", text or "")
    return len([word for word in re.split(r"\s+", plain) if word.strip()])


def reading_minutes(text: str) -> int:
    """Tempo de leitura estimado (200 palavras por minuto, mínimo 1)."""
    return max(1, round(_words(text) / 200))


def post_reading_minutes(markdown: str, blocks: Iterable[Dict[str, Any]]) -> int:
    """Tempo de leitura de um artigo: o Markdown **e** os blocos.

    Um artigo com gráficos e tabelas lê-se em mais tempo do que o texto sozinho,
    e é este número que aparece no índice do blog.
    """
    return reading_minutes(f"{markdown or ''} {_blocks_text(blocks)}")


def _excerpt(text: str, limit: int = 220) -> str:
    plain = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"[#*`>_|]", " ", plain)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit]


def _empty_settings() -> Dict[str, Any]:
    return copy.deepcopy(DEFAULT_SETTINGS)


def _empty_store() -> Dict[str, Any]:
    store: Dict[str, Any] = {"version": CMS_VERSION}
    for entity in ENTITIES:
        store[entity] = []
    store["revisions"] = []
    store["activity"] = []
    store["settings"] = _empty_settings()
    store["updated_at"] = _now()
    return store


def _read_store() -> Dict[str, Any]:
    if not CMS_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(CMS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro do CMS ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    for entity in ENTITIES + ("revisions", "activity"):
        value = raw.get(entity)
        if isinstance(value, list):
            store[entity] = [item for item in value if isinstance(item, dict)]
    settings = raw.get("settings")
    if isinstance(settings, dict):
        store["settings"].update({key: value for key, value in settings.items() if value is not None})
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache, _cache_mtime
    store["version"] = CMS_VERSION
    store["updated_at"] = _now()
    CMS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2, default=str)
    tmp = CMS_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(CMS_PATH)
    _cache = store
    _cache_mtime = _file_mtime()
    # Toda a escrita pública (publicar, despublicar, agendar, editar) passa por
    # aqui: é o ponto único para avisar os motores de busca do que mudou. Sem
    # chave do IndexNow configurada isto não faz nada.
    indexnow.anunciar_em_fundo("escrita do CMS")


def _file_mtime() -> Optional[int]:
    """Data de alteração do ficheiro (para detetar escritas de outros processos)."""
    try:
        return CMS_PATH.stat().st_mtime_ns
    except OSError:
        return None


def _load() -> Dict[str, Any]:
    """Documento do CMS, com publicação automática dos agendamentos vencidos.

    Se o ficheiro mudou fora deste processo (CLI, testes, edição manual), a
    cópia em memória é descartada — sem isto, a próxima escrita repunha dados
    antigos por cima dos novos.
    """
    global _cache, _cache_mtime
    stamp = _file_mtime()
    if _cache is not None and stamp != _cache_mtime:
        _cache = None
    if _cache is None:
        _cache = _read_store()
        if not _cache["pages"] and not _cache["posts"] and not _cache["templates"]:
            _seed(_cache)
            _write_store(_cache)
        else:
            _cache_mtime = _file_mtime()
    if _apply_schedule(_cache):
        _write_store(_cache)
    return _cache


def _store() -> Dict[str, Any]:
    return _load()


# --------------------------------------------------------------------------
# Revisões e atividade
# --------------------------------------------------------------------------
def _snapshot(store: Dict[str, Any], entity: str, doc: Dict[str, Any], author: str = "", note: str = "") -> None:
    revision = {
        "id": _new_id("rev"),
        "entity": entity,
        "entity_id": doc.get("id") or "",
        "title": doc.get("title") or doc.get("name") or "",
        "snapshot": copy.deepcopy(doc),
        "author": author or doc.get("updated_by") or "",
        "note": note,
        "at": _now(),
    }
    revisions = store["revisions"]
    revisions.insert(0, revision)
    same = [item for item in revisions if item.get("entity") == entity and item.get("entity_id") == revision["entity_id"]]
    for extra in same[MAX_REVISIONS:]:
        revisions.remove(extra)


def _log(store: Dict[str, Any], action: str, entity: str, doc: Dict[str, Any], actor: str = "", detail: str = "") -> None:
    store["activity"].insert(
        0,
        {
            "id": _new_id("act"),
            "at": _now(),
            "action": action,
            "entity": entity,
            "entity_id": doc.get("id") or "",
            "label": doc.get("title") or doc.get("name") or "",
            "actor": actor or "plataforma",
            "detail": detail,
        },
    )
    del store["activity"][MAX_ACTIVITY:]


def activity(limit: int = 40) -> List[Dict[str, Any]]:
    return _load()["activity"][: max(1, min(limit, MAX_ACTIVITY))]


def revisions_of(entity: str, entity_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    _check_entity(entity)
    store = _load()
    items = [rev for rev in store["revisions"] if rev.get("entity") == entity and rev.get("entity_id") == entity_id]
    return [
        {key: value for key, value in item.items() if key != "snapshot"} | {"fields": sorted((item.get("snapshot") or {}).keys())}
        for item in items[:limit]
    ]


def get_revision(revision_id: str) -> Dict[str, Any]:
    store = _load()
    for revision in store["revisions"]:
        if revision.get("id") == revision_id:
            return revision
    raise KeyError(f"Revisão {revision_id} não encontrada.")


def restore_revision(revision_id: str, author: str = "") -> Dict[str, Any]:
    store = _load()
    revision = get_revision(revision_id)
    entity = revision["entity"]
    entity_id = revision["entity_id"]
    current = _find(store, entity, entity_id)
    if current is None:
        raise KeyError(f"{entity}/{entity_id} já não existe.")
    _snapshot(store, entity, current, author, note=f"antes de restaurar {revision_id}")
    restored = copy.deepcopy(revision["snapshot"])
    restored["id"] = entity_id
    restored["updated_at"] = _now()
    restored["updated_by"] = author
    index = store[entity].index(current)
    store[entity][index] = restored
    _after_write(store, entity, restored)
    _log(store, "restaurar", entity, restored, author, f"revisão {revision_id}")
    _write_store(store)
    return restored


# --------------------------------------------------------------------------
# Índices e normalização
# --------------------------------------------------------------------------
def _check_entity(entity: str) -> None:
    if entity not in ENTITIES:
        raise KeyError(f"Entidade desconhecida: {entity}. Válidas: {', '.join(ENTITIES)}.")


def _find(store: Dict[str, Any], entity: str, item_id: str) -> Optional[Dict[str, Any]]:
    _check_entity(entity)
    for item in store[entity]:
        if item.get("id") == item_id:
            return item
    return None


def _unique(store: Dict[str, Any], entity: str, slug: str, ignore_id: Optional[str] = None) -> str:
    taken = {item.get("slug") for item in store[entity] if item.get("id") != ignore_id}
    candidate = slug
    index = 2
    while candidate in taken:
        candidate = f"{slug}-{index}"
        index += 1
    return candidate


def _normalise_blocks(value: Any) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    if not isinstance(value, list):
        return blocks
    for raw in value:
        if not isinstance(raw, dict):
            continue
        block_type = str(raw.get("type") or "texto").strip()
        if block_type not in BLOCK_IDS:
            block_type = "texto"
        data = raw.get("data")
        blocks.append(
            {
                "id": str(raw.get("id") or _new_id("blk")),
                "type": block_type,
                "hidden": bool(raw.get("hidden")),
                "data": copy.deepcopy(data) if isinstance(data, dict) else {},
            }
        )
    return blocks


def _normalise_seo(value: Any) -> Dict[str, Any]:
    seo = value if isinstance(value, dict) else {}
    return {
        "title": str(seo.get("title") or "").strip(),
        "description": str(seo.get("description") or "").strip(),
        "keywords": _keywords(seo.get("keywords")),
        "image_id": seo.get("image_id") or None,
        "noindex": bool(seo.get("noindex")),
    }


def _status(value: Any, fallback: str = "rascunho") -> str:
    status = str(value or fallback).strip().lower()
    return status if status in STATUSES else fallback


def _cor(value: Any) -> str:
    """Cor de destaque (#rrggbb). Vazio ou inválida = usar a do site."""
    texto = str(value or "").strip()
    if not texto:
        return ""
    if not texto.startswith("#"):
        texto = f"#{texto}"
    return texto if re.fullmatch(r"#[0-9a-fA-F]{6}", texto) else ""


def normalizar_filtros(value: Any) -> Dict[str, Any]:
    """Filtros de uma pesquisa: só os conhecidos, com tipos certos."""
    filtros = value if isinstance(value, dict) else {}
    limpo: Dict[str, Any] = {}
    for campo, padrao in FILTROS_PESQUISA.items():
        actual = filtros.get(campo, padrao)
        if campo in ("ano_contratos", "min_despesas"):
            try:
                limpo[campo] = int(float(actual)) if actual not in (None, "") else None
            except (TypeError, ValueError):
                limpo[campo] = None
        elif campo == "limite":
            try:
                limpo[campo] = max(1, min(200, int(float(actual))))
            except (TypeError, ValueError):
                limpo[campo] = int(FILTROS_PESQUISA["limite"])
        elif campo == "ordem":
            limpo[campo] = "asc" if str(actual).lower() == "asc" else "desc"
        else:
            limpo[campo] = str(actual or "").strip()
    return limpo


def _page_path(store: Dict[str, Any], doc: Dict[str, Any]) -> str:
    """Caminho de uma página: os slugs dos ascendentes + o próprio.

    A página registada em `settings.home_page_id` vive na **raiz** do site
    (`/site`), pelo que o seu slug não entra no caminho.
    """
    home_id = str((store.get("settings") or {}).get("home_page_id") or "")
    parts: List[str] = []
    seen = set()
    current: Optional[Dict[str, Any]] = doc
    while current is not None:
        is_home = bool(home_id) and current.get("id") == home_id
        slug = "" if is_home else str(current.get("slug") or "").strip()
        if slug:
            parts.insert(0, slug)
        parent_id = current.get("parent_id")
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        current = _find(store, "pages", str(parent_id))
    return "/".join(parts)


def _refresh_page_paths(store: Dict[str, Any]) -> None:
    for page in store["pages"]:
        path = _page_path(store, page)
        if page.get("path") != path:
            page["path"] = path


def _after_write(store: Dict[str, Any], entity: str, doc: Dict[str, Any]) -> None:
    """Ajustes derivados depois de gravar (caminhos das páginas, uso dos conteúdos)."""
    if entity == "pages":
        _refresh_page_paths(store)
        # Uma página pode passar a usar (ou deixar de usar) um conteúdo reutilizável.
        _refresh_content_usage(store)
    if entity == "contents":
        _refresh_content_usage(store)


def _refresh_content_usage(store: Dict[str, Any]) -> None:
    usage: Dict[str, int] = {item.get("id") or "": 0 for item in store["contents"]}
    for page in store["pages"]:
        for block in page.get("blocks") or []:
            if block.get("type") == "conteudo":
                content_id = str((block.get("data") or {}).get("content_id") or "")
                if content_id in usage:
                    usage[content_id] += 1
    for content in store["contents"]:
        content["uses"] = usage.get(content.get("id") or "", 0)


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------
def _summary(entity: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Versão leve de um documento para listagens."""
    item = {key: value for key, value in doc.items() if key not in ("blocks", "markdown", "data", "dados", "intro")}
    # `entity_label` e não `kind`: nos conteúdos e nos media `kind` é um campo real.
    item["entity"] = entity
    item["entity_label"] = ENTITY_LABELS.get(entity, entity)
    if entity in ("pages", "municipios", "pesquisas", "remuneracoes"):
        item["blocks_count"] = len(doc.get("blocks") or [])
    if entity == "posts":
        item["reading_minutes"] = doc.get("reading_minutes") or reading_minutes(doc.get("markdown") or "")
        item["markdown_words"] = _words(doc.get("markdown") or "")
        item["has_markdown"] = bool(doc.get("markdown"))
    if entity == "contents":
        item["preview"] = _excerpt(doc.get("body") or "")
    return item


def list_items(
    entity: str,
    status: Optional[str] = None,
    query: Optional[str] = None,
    category_id: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 200,
    with_blocks: bool = True,
) -> Dict[str, Any]:
    """Lista uma entidade, com filtros por estado, pesquisa, categoria e etiqueta."""
    _check_entity(entity)
    store = _load()
    items: List[Dict[str, Any]] = list(store[entity])

    if status and status != "all":
        wanted = {part.strip() for part in status.split(",") if part.strip()}
        items = [item for item in items if str(item.get("status")) in wanted]

    if category_id:
        items = [item for item in items if category_id in (item.get("category_ids") or [])]

    if tag:
        items = [item for item in items if tag in (item.get("tags") or [])]

    if query:
        needle = query.strip().lower()
        def matches(item: Dict[str, Any]) -> bool:
            haystack = " ".join(
                str(item.get(field) or "")
                for field in ("title", "name", "slug", "path", "excerpt", "markdown", "body", "alt", "filename", "description")
            )
            haystack += " " + " ".join(str(tag) for tag in (item.get("tags") or []))
            return needle in haystack.lower()
        items = [item for item in items if matches(item)]

    items.sort(key=lambda item: (str(item.get("updated_at") or item.get("created_at") or "")), reverse=True)
    total = len(items)
    items = items[: max(1, min(limit, 500))]

    if with_blocks:
        payload_items = [copy.deepcopy(item) for item in items]
        # As listagens não levam o corpo dos artigos: quem abre um artigo pede-o
        # por `get_item` (o Markdown de 200 artigos não faz sentido num índice).
        if entity == "posts":
            for item in payload_items:
                item.pop("markdown", None)
        if entity in ("pages", "municipios"):
            # O número de blocos é o que a listagem mostra; `_summary` só o conta
            # nas listagens leves.
            for item in payload_items:
                item["blocks_count"] = len(item.get("blocks") or [])
    else:
        payload_items = [_summary(entity, item) for item in items]

    return {"total": total, "count": len(payload_items), "items": payload_items}


def get_item(entity: str, item_id: str) -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    return copy.deepcopy(doc)


def resolve_page_by_path(path: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    store = _load()
    wanted = (path or "").strip("/").lower()
    for page in store["pages"]:
        if published_only and page.get("status") != "publicado":
            continue
        if str(page.get("path") or "").lower() == wanted or (not wanted and str(page.get("path") or "").lower() == ""):
            return copy.deepcopy(page)
    return None


def resolve_post_by_slug(slug: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    store = _load()
    wanted = (slug or "").strip().lower()
    for post in store["posts"]:
        if published_only and post.get("status") != "publicado":
            continue
        if str(post.get("slug") or "").lower() == wanted:
            return copy.deepcopy(post)
    return None


def post_by_news_id(news_id: str) -> Optional[Dict[str, Any]]:
    """O artigo de blog criado a partir de uma notícia do índice (`news_id`).

    A ligação vive no artigo e não numa etiqueta: uma etiqueta interna acaba
    publicada na página, nas palavras-chave e nos índices de etiquetas, como se
    fosse um tema do artigo.
    """
    if not news_id:
        return None
    store = _load()
    for post in store["posts"]:
        if str(post.get("news_id") or "") == str(news_id):
            return copy.deepcopy(post)
    return None


def published_pages() -> List[Dict[str, Any]]:
    store = _load()
    items = [page for page in store["pages"] if page.get("status") == "publicado"]
    items.sort(key=lambda item: (int(item.get("menu_order") or 0), str(item.get("title") or "").lower()))
    return copy.deepcopy(items)


def published_posts(category_id: Optional[str] = None, tag: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    store = _load()
    items = [post for post in store["posts"] if post.get("status") == "publicado"]
    if category_id:
        items = [item for item in items if category_id in (item.get("category_ids") or [])]
    if tag:
        items = [item for item in items if tag in (item.get("tags") or [])]
    items.sort(key=lambda item: str(item.get("published_at") or item.get("created_at") or ""), reverse=True)
    return copy.deepcopy(items[:limit])


def category_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    store = _load()
    for category in store["categories"]:
        if str(category.get("slug") or "").lower() == (slug or "").lower():
            return copy.deepcopy(category)
    return None


def municipio_by_slug(slug: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    """Ficha de município pelo endereço público (`/municipio/{slug}`)."""
    store = _load()
    wanted = (slug or "").strip().lower()
    for item in store["municipios"]:
        if published_only and item.get("status") != "publicado":
            continue
        if str(item.get("slug") or "").lower() == wanted:
            return copy.deepcopy(item)
    return None


def municipio_by_name(nome: str) -> Optional[Dict[str, Any]]:
    """Ficha já existente de um município (evita duas fichas do mesmo concelho)."""
    store = _load()
    wanted = _slug(nome or "")
    if not wanted:
        return None
    for item in store["municipios"]:
        if _slug(str(item.get("municipio") or "")) == wanted:
            return copy.deepcopy(item)
    return None


def published_municipios() -> List[Dict[str, Any]]:
    """Fichas de município publicadas (mais recentes primeiro)."""
    store = _load()
    items = [item for item in store["municipios"] if item.get("status") == "publicado"]
    items.sort(key=lambda item: str(item.get("published_at") or item.get("created_at") or ""), reverse=True)
    return copy.deepcopy(items)


def municipio_path(doc: Dict[str, Any]) -> str:
    """Caminho público da ficha de um município (`/municipio/{slug}`)."""
    slug = str(doc.get("slug") or "").strip("/")
    return f"/municipio/{slug}" if slug else ""


def pesquisa_by_slug(slug: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    """Página de pesquisa pelo endereço público (`/pesquisa/{slug}`)."""
    store = _load()
    wanted = (slug or "").strip().lower()
    for item in store["pesquisas"]:
        if published_only and item.get("status") != "publicado":
            continue
        if str(item.get("slug") or "").lower() == wanted:
            return copy.deepcopy(item)
    return None


def published_pesquisas() -> List[Dict[str, Any]]:
    """Páginas de pesquisa publicadas (mais recentes primeiro)."""
    store = _load()
    items = [item for item in store["pesquisas"] if item.get("status") == "publicado"]
    items.sort(key=lambda item: str(item.get("published_at") or item.get("created_at") or ""), reverse=True)
    return copy.deepcopy(items)


def pesquisa_path(doc: Dict[str, Any]) -> str:
    """Caminho público de uma página de pesquisa (`/pesquisa/{slug}`)."""
    slug = str(doc.get("slug") or "").strip("/")
    return f"/pesquisa/{slug}" if slug else ""


def remuneracao_by_slug(slug: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    """Página do modelo de remunerações pelo endereço (`/remuneracoes/{slug}`)."""
    store = _load()
    wanted = (slug or "").strip().lower()
    for item in store["remuneracoes"]:
        if published_only and item.get("status") != "publicado":
            continue
        if str(item.get("slug") or "").lower() == wanted:
            return copy.deepcopy(item)
    return None


def published_remuneracoes() -> List[Dict[str, Any]]:
    """Páginas do modelo de remunerações publicadas (mais recentes primeiro)."""
    store = _load()
    items = [item for item in store["remuneracoes"] if item.get("status") == "publicado"]
    items.sort(key=lambda item: str(item.get("published_at") or item.get("created_at") or ""), reverse=True)
    return copy.deepcopy(items)


def remuneracao_path(doc: Dict[str, Any]) -> str:
    """Caminho público de uma página do modelo (`/remuneracoes/{slug}`)."""
    slug = str(doc.get("slug") or "").strip("/")
    return f"/remuneracoes/{slug}" if slug else ""


def media_url(media_id: Optional[str]) -> str:
    return f"/cms/media/{media_id}/raw" if media_id else ""


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------
def _normalise(entity: str, payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Campos conhecidos de cada entidade (o resto é ignorado)."""
    existing = existing or {}
    doc: Dict[str, Any] = copy.deepcopy(existing)

    def pick(field: str, default: Any = None) -> Any:
        return payload[field] if field in payload else existing.get(field, default)

    if entity in PUBLISHABLE:
        title = str(pick("title") or "").strip()
        doc["title"] = title
        doc["slug"] = _slug(str(pick("slug") or title))
        doc["status"] = _status(pick("status"))
        doc["scheduled_at"] = pick("scheduled_at") or None
        doc["updated_by"] = payload.get("updated_by") or existing.get("updated_by") or ""
        doc["seo"] = _normalise_seo(pick("seo"))

    if entity == "pages":
        doc["parent_id"] = pick("parent_id") or None
        doc["template"] = str(pick("template") or "pagina-padrao")
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["show_in_menu"] = bool(pick("show_in_menu", True))
        doc["menu_order"] = int(pick("menu_order", 0) or 0)
        doc["menu_label"] = str(pick("menu_label") or "")
        doc["excerpt"] = str(pick("excerpt") or "") or _excerpt(_blocks_text(doc["blocks"]))
        doc["path"] = str(existing.get("path") or "")

    if entity == "posts":
        doc["excerpt"] = str(pick("excerpt") or "")
        doc["markdown"] = str(pick("markdown") or "")
        if not doc["excerpt"]:
            doc["excerpt"] = _excerpt(doc["markdown"])
        doc["cover_id"] = pick("cover_id") or None
        doc["category_ids"] = [str(item) for item in (pick("category_ids", []) or []) if item]
        doc["tags"] = _keywords(pick("tags", []))
        # Notícia do índice `finance_news` que deu origem ao artigo (vazio nos
        # artigos escritos à mão). É por aqui que a publicação de notícias
        # reconhece o que já publicou, sem deixar uma etiqueta interna à vista.
        doc["news_id"] = str(pick("news_id") or "")
        doc["author"] = str(pick("author") or existing.get("author") or "")
        doc["featured"] = bool(pick("featured", False))
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["reading_minutes"] = post_reading_minutes(doc["markdown"], doc["blocks"])

    if entity == "municipios":
        # Ficha pública de um município: o texto e os blocos são editoriais, e o
        # `dados` é a fotografia da ficha das despesas/contratação no momento em
        # que foi lida (refresca-se com `POST /cms/municipios/{id}/dados`).
        dados = pick("dados")
        doc["municipio"] = str(pick("municipio") or "").strip()
        doc["geocod"] = pick("geocod") or existing.get("geocod")
        doc["excerpt"] = str(pick("excerpt") or "")
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["dados"] = copy.deepcopy(dados) if isinstance(dados, dict) else {}
        if not doc["excerpt"]:
            doc["excerpt"] = _excerpt(_blocks_text(doc["blocks"]))

    if entity == "pesquisas":
        # Página de uma **pesquisa congelada**: os filtros sobre os municípios
        # ficam no documento e os números são a fotografia lida quando o editor
        # os mandou ler (`POST /cms/pesquisas/{id}/dados`). A marca (cor, logótipo
        # e imagem de capa) é do documento, não das definições do site.
        dados = pick("dados")
        doc["filtros"] = normalizar_filtros(pick("filtros"))
        doc["descricao_filtros"] = str(pick("descricao_filtros") or "")
        doc["intro"] = str(pick("intro") or "")
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["dados"] = copy.deepcopy(dados) if isinstance(dados, dict) else {}
        doc["capa_id"] = pick("capa_id") or None
        doc["logo_id"] = pick("logo_id") or None
        doc["cor"] = _cor(pick("cor"))
        doc["excerpt"] = str(pick("excerpt") or "") or _excerpt(doc["intro"] or doc["descricao_filtros"])

    if entity == "remuneracoes":
        # Página do **modelo de remunerações da Administração Pública**: o ano do
        # quadro da DGAEP fica no documento e o `dados` é a fotografia desse ano
        # (níveis da TRU, carreiras, dirigentes e base legal), lida quando o
        # editor a mandou ler (`POST /cms/remuneracoes/{id}/modelo`). O que a
        # página mostra, com que cabeçalhos e por que ordem, escolhe-se aqui; a
        # marca (cor, logótipo, imagens e estilo das secções) é do documento.
        dados = pick("dados")
        doc["ano"] = _ano_valido(pick("ano", existing.get("ano")))
        doc["intro"] = str(pick("intro") or "")
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["dados"] = copy.deepcopy(dados) if isinstance(dados, dict) else {}
        doc["mostrar"] = _mostrar_da_pagina(pick("mostrar"))
        doc["seccoes"] = _seccoes_da_pagina(pick("seccoes"))
        doc["ordem"] = _ordem_das_seccoes(pick("ordem"))
        doc["destacar"] = [str(valor) for valor in (pick("destacar", []) or []) if str(valor).strip()][:12]
        doc["capa_id"] = pick("capa_id") or None
        doc["logo_id"] = pick("logo_id") or None
        doc["cor"] = _cor(pick("cor"))
        doc["estilo"] = _estilo_da_pagina(pick("estilo"))
        # Artigo de blog criado a partir desta página (`POST …/artigo`), para o
        # editor não o perder de vista nem o criar duas vezes.
        doc["artigo_id"] = str(pick("artigo_id") or "").strip() or None
        doc["excerpt"] = str(pick("excerpt") or "") or _excerpt(doc["intro"] or _resumo_do_modelo(doc["dados"]))

    if entity == "contactos":
        # Mensagens do formulário do site: dados pessoais de quem escreve, por
        # isso não têm estado de publicação nem endereço — só um estado de
        # seguimento («novo», «em curso», «tratado»).
        for campo, limite in CONTACTO_LIMITES.items():
            doc[campo] = str(pick(campo) or "").strip()[:limite]
        estado = str(pick("estado") or "novo").strip().lower()
        doc["estado"] = estado if estado in CONTACTOS_ESTADO_IDS else "novo"
        doc["notas"] = str(pick("notas") or "").strip()[:2000]
        doc["origem"] = str(pick("origem") or "site")[:120]
        doc["consentimento"] = bool(pick("consentimento", False))

    if entity == "contents":
        doc["title"] = str(pick("title") or "").strip()
        kind = str(pick("kind") or "texto").strip()
        doc["kind"] = kind if kind in CONTENT_KIND_IDS else "texto"
        doc["body"] = str(pick("body") or "")
        data = pick("data", {})
        doc["data"] = copy.deepcopy(data) if isinstance(data, dict) else {}
        doc["tags"] = _keywords(pick("tags", []))
        doc["notes"] = str(pick("notes") or "")

    if entity == "categories":
        name = str(pick("name") or "").strip()
        doc["name"] = name
        doc["slug"] = _slug(str(pick("slug") or name), "categoria")
        doc["description"] = str(pick("description") or "")
        doc["parent_id"] = pick("parent_id") or None
        doc["color"] = str(pick("color") or "")

    if entity == "templates":
        name = str(pick("name") or "").strip()
        doc["name"] = name
        doc["kind"] = str(pick("kind") or "page") if str(pick("kind") or "page") in {"page", "post"} else "page"
        doc["description"] = str(pick("description") or "")
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["builtin"] = bool(existing.get("builtin", False))

    if entity == "media":
        doc["title"] = str(pick("title") or existing.get("title") or "")
        doc["alt"] = str(pick("alt") or "")
        doc["caption"] = str(pick("caption") or "")
        doc["credit"] = str(pick("credit") or "")
        doc["tags"] = _keywords(pick("tags", []))

    if entity == "menus":
        doc["name"] = str(pick("name") or "Menu principal").strip()
        doc["location"] = str(pick("location") or "header")
        if doc["location"] not in {item["id"] for item in MENU_LOCATIONS}:
            doc["location"] = "header"
        valid_themes = {theme["id"] for theme in MENU_THEMES}
        doc["menu_theme"] = str(pick("menu_theme") or "pastilhas").strip()
        if doc["menu_theme"] not in valid_themes:
            doc["menu_theme"] = "pastilhas"
        template_id = str(pick("menu_template") or "").strip()
        valid_templates = {
            template["id"]
            for theme in MENU_THEMES
            if theme["id"] == doc["menu_theme"]
            for template in theme["templates"]
        }
        doc["menu_template"] = template_id if template_id in valid_templates else DEFAULT_MENU_TEMPLATE.get(doc["menu_theme"], "padrao")
        doc["items"] = _normalise_menu_items(pick("items", []))

    return doc


def _normalise_menu_items(value: Any, depth: int = 0) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or depth > 2:
        return []
    items: List[Dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        href = str(raw.get("href") or "").strip()
        page_id = raw.get("page_id") or None
        if not label and not href and not page_id:
            continue
        item: Dict[str, Any] = {
            "id": str(raw.get("id") or _new_id("mi")),
            "label": label,
            "href": href,
            "page_id": page_id,
            "new_tab": bool(raw.get("new_tab")),
        }
        children = _normalise_menu_items(raw.get("children"), depth + 1)
        if children:
            item["children"] = children
        items.append(item)
    return items


def _blocks_text(blocks: Iterable[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for block in blocks or []:
        data = block.get("data") or {}
        for key in ("title", "subtitle", "text", "body", "markdown", "quote", "text_value"):
            value = data.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
        for item in data.get("items") or []:
            if isinstance(item, dict):
                parts.extend(str(item.get(key) or "") for key in ("title", "text", "question", "answer"))
    return " ".join(parts)


def save_item(entity: str, payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    """Cria ou altera um documento do CMS (com revisão e registo de atividade)."""
    _check_entity(entity)
    store = _load()
    item_id = payload.get("id")
    existing = _find(store, entity, str(item_id)) if item_id else None
    if item_id and existing is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")

    doc = _normalise(entity, {**payload, "updated_by": author or payload.get("updated_by")}, existing)
    if entity in PUBLISHABLE and not doc.get("title"):
        raise ValueError("O título é obrigatório.")
    if entity == "municipios" and not doc.get("municipio"):
        raise ValueError("O município é obrigatório.")
    if entity == "contents" and not doc.get("title"):
        raise ValueError("O nome do conteúdo é obrigatório.")
    if entity == "categories" and not doc.get("name"):
        raise ValueError("O nome da categoria é obrigatório.")
    if entity == "templates" and not doc.get("name"):
        raise ValueError("O nome do modelo é obrigatório.")
    if entity == "menus" and not doc.get("name"):
        raise ValueError("O nome do menu é obrigatório.")

    if entity in PUBLISHABLE:
        ignore = str(existing.get("id")) if existing else None
        doc["slug"] = _unique(store, entity, doc["slug"], ignore_id=ignore)

    if entity == "pages":
        if doc.get("parent_id") and doc.get("id") and str(doc["parent_id"]) == str(doc["id"]):
            raise ValueError("Uma página não pode ser sua própria ascendente.")
        if doc.get("parent_id") and _is_descendant(store, str(doc.get("id") or ""), str(doc["parent_id"])):
            raise ValueError("Não é possível mover uma página para dentro de uma sua descendente.")

    if entity == "categories":
        ignore = str(existing.get("id")) if existing else None
        doc["slug"] = _unique(store, entity, doc["slug"], ignore_id=ignore)

    if existing:
        _snapshot(store, entity, existing, author, note="antes de guardar")
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or _now()
        doc["updated_at"] = _now()
        store[entity][store[entity].index(existing)] = doc
        action = "alterar"
    else:
        doc["id"] = doc.get("id") or _new_id(_id_prefix(entity))
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        if entity in PUBLISHABLE:
            doc["published_at"] = existing.get("published_at") if existing else None  # type: ignore[union-attr]
            if doc.get("status") == "publicado":
                doc["published_at"] = _now()
        store[entity].insert(0, doc)
        action = "criar"

    _after_write(store, entity, doc)
    _log(store, action, entity, doc, author)
    _write_store(store)
    return copy.deepcopy(doc)


def _id_prefix(entity: str) -> str:
    return {
        "pages": "pag",
        "posts": "post",
        "municipios": "mun",
        "pesquisas": "pes",
        "remuneracoes": "rem",
        "contents": "ctd",
        "media": "med",
        "categories": "cat",
        "templates": "tpl",
        "menus": "menu",
        "contactos": "ctt",
    }.get(entity, "item")


def _is_descendant(store: Dict[str, Any], page_id: str, candidate_parent: str) -> bool:
    """Verdadeiro se `candidate_parent` estiver dentro da subárvore de `page_id`."""
    if not page_id or not candidate_parent:
        return False
    stack = [candidate_parent]
    seen = set()
    while stack:
        current = stack.pop()
        if current == page_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        parent = _find(store, "pages", current)
        if parent and parent.get("parent_id"):
            stack.append(str(parent["parent_id"]))
    return False


def delete_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    _snapshot(store, entity, doc, author, note="antes de apagar")
    store[entity].remove(doc)
    if entity == "pages":
        for page in store["pages"]:
            if page.get("parent_id") == item_id:
                page["parent_id"] = None
        _refresh_page_paths(store)
    if entity == "categories":
        for post in store["posts"]:
            if item_id in (post.get("category_ids") or []):
                post["category_ids"] = [value for value in post["category_ids"] if value != item_id]
    if entity == "media":
        target = _media_file(doc)
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:  # pragma: no cover - disco
            logger.warning("Não foi possível apagar o ficheiro do media %s (%s)", item_id, exc)
    if entity == "menus":
        pass
    settings = store["settings"]
    for key in ("home_page_id", "blog_page_id"):
        if settings.get(key) == item_id:
            settings[key] = ""
    for key in ("logo_id", "favicon_id"):
        if settings.get(key) == item_id:
            settings[key] = None
    if (settings.get("seo") or {}).get("image_id") == item_id:
        settings["seo"]["image_id"] = None
    _refresh_content_usage(store)
    _log(store, "apagar", entity, doc, author)
    _write_store(store)
    return {"deleted": True, "id": item_id}


def duplicate_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    clone = copy.deepcopy(doc)
    clone["id"] = _new_id(_id_prefix(entity))
    clone["created_at"] = _now()
    clone["updated_at"] = _now()
    clone["updated_by"] = author
    if entity in ("pages", "posts"):
        base = str(doc.get("title") or "")
        clone["title"] = f"{base} (cópia)"
        clone["slug"] = _unique(store, entity, _slug(f"{doc.get('slug') or base}-copia"), ignore_id=None)
        clone["status"] = "rascunho"
        clone["published_at"] = None
        clone["scheduled_at"] = None
    if entity == "pages":
        clone["show_in_menu"] = False
        clone["path"] = ""
    if entity in ("categories", "templates", "contents"):
        base = str(doc.get("name") or doc.get("title") or "")
        if entity == "contents":
            clone["title"] = f"{base} (cópia)"
        else:
            clone["name"] = f"{base} (cópia)"
        if entity == "categories":
            clone["slug"] = _unique(store, entity, _slug(f"{doc.get('slug') or base}-copia"), ignore_id=None)
    store[entity].insert(0, clone)
    _after_write(store, entity, clone)
    _log(store, "duplicar", entity, clone, author, f"a partir de {item_id}")
    _write_store(store)
    return copy.deepcopy(clone)


# --------------------------------------------------------------------------
# Publicação
# --------------------------------------------------------------------------
def _apply_schedule(store: Dict[str, Any]) -> bool:
    """Publica tudo o que está agendado e já venceu. Devolve True se mudou algo."""
    now = datetime.now(timezone.utc)
    changed = False
    for entity in PUBLISHABLE:
        for doc in store[entity]:
            if doc.get("status") != "agendado":
                continue
            stamp = doc.get("scheduled_at")
            if not stamp:
                continue
            try:
                when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when <= now:
                doc["status"] = "publicado"
                doc["published_at"] = doc.get("published_at") or _now()
                doc["updated_at"] = _now()
                _log(store, "publicar (agendado)", entity, doc, "agendador")
                changed = True
    if changed:
        _refresh_page_paths(store)
    return changed


def publish_item(entity: str, item_id: str, author: str = "", at: Optional[str] = None) -> Dict[str, Any]:
    """Publica agora, ou agenda para `at` (ISO 8601)."""
    _check_entity(entity)
    if entity not in PUBLISHABLE:
        raise ValueError("Só páginas, artigos e municípios têm estado de publicação.")
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    _snapshot(store, entity, doc, author, note="antes de publicar")
    if at:
        doc["status"] = "agendado"
        doc["scheduled_at"] = at
        action = "agendar"
    else:
        doc["status"] = "publicado"
        doc["scheduled_at"] = None
        doc["published_at"] = doc.get("published_at") or _now()
        action = "publicar"
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    _refresh_page_paths(store)
    _log(store, action, entity, doc, author, f"para {at}" if at else "")
    _write_store(store)
    return copy.deepcopy(doc)


def unpublish_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    if entity not in PUBLISHABLE:
        raise ValueError("Só páginas, artigos e municípios têm estado de publicação.")
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    doc["status"] = "rascunho"
    doc["scheduled_at"] = None
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    _log(store, "despublicar", entity, doc, author)
    _write_store(store)
    return copy.deepcopy(doc)


def set_status(entity: str, item_id: str, status: str, author: str = "") -> Dict[str, Any]:
    value = _status(status)
    if value == "publicado":
        return publish_item(entity, item_id, author)
    if value == "agendado":
        store = _load()
        doc = _find(store, entity, item_id)
        if doc is None:
            raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
        return publish_item(entity, item_id, author, at=str(doc.get("scheduled_at") or _now()))
    if value == "arquivado":
        _check_entity(entity)
        store = _load()
        doc = _find(store, entity, item_id)
        if doc is None:
            raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
        doc["status"] = "arquivado"
        doc["updated_at"] = _now()
        _log(store, "arquivar", entity, doc, author)
        _write_store(store)
        return copy.deepcopy(doc)
    return unpublish_item(entity, item_id, author)


# --------------------------------------------------------------------------
# Media
# --------------------------------------------------------------------------
def _media_file(doc: Dict[str, Any]) -> Path:
    extension = str(doc.get("extension") or "")
    return MEDIA_DIR / f"{doc.get('id')}{extension}"


def media_file(item_id: str) -> Tuple[Path, str]:
    doc = get_item("media", item_id)
    path = _media_file(doc)
    if not path.is_file():
        raise KeyError(f"Ficheiro do media {item_id} não encontrado no disco.")
    return path, str(doc.get("mime") or "application/octet-stream")


def save_media(payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    """Guarda um ficheiro (imagem, PDF, …) enviado em base64 ou por URL externo."""
    store = _load()
    item_id = payload.get("id")
    existing = _find(store, "media", str(item_id)) if item_id else None
    if item_id and existing is None:
        raise KeyError(f"Media {item_id} não encontrado.")

    data = str(payload.get("data") or "")
    external_url = str(payload.get("url") or "").strip()
    doc: Dict[str, Any] = copy.deepcopy(existing) if existing else {}

    if data:
        if "," in data[:80] and data.strip().startswith("data:"):
            header, _, data = data.partition(",")
            if not payload.get("mime"):
                payload["mime"] = header[5:].split(";")[0]
        try:
            blob = base64.b64decode(data)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Conteúdo base64 inválido: {exc}") from exc
        if len(blob) > MAX_MEDIA_BYTES:
            raise ValueError(f"Ficheiro demasiado grande (máximo {MAX_MEDIA_BYTES // (1024 * 1024)} MB).")
        filename = str(payload.get("filename") or existing.get("filename") if existing else payload.get("filename") or "ficheiro")
        mime = str(payload.get("mime") or (existing or {}).get("mime") or EXT_MIME.get(Path(filename).suffix.lower(), ""))
        extension = MIME_EXT.get(mime) or Path(filename).suffix.lower() or ".bin"
        media_id = (existing or {}).get("id") or _new_id("med")
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        target = MEDIA_DIR / f"{media_id}{extension}"
        target.write_bytes(blob)
        doc.update(
            {
                "id": media_id,
                "filename": Path(filename).name,
                "mime": mime or "application/octet-stream",
                "extension": extension,
                "size": len(blob),
                "storage": "ficheiro",
                "url": f"/cms/media/{media_id}/raw",
            }
        )
    elif external_url:
        doc.update(
            {
                "id": (existing or {}).get("id") or _new_id("med"),
                "filename": Path(external_url.split("?")[0]).name or external_url,
                "mime": str(payload.get("mime") or "image/*"),
                "extension": "",
                "size": 0,
                "storage": "externo",
                "url": external_url,
            }
        )
    else:
        raise ValueError("É preciso enviar o ficheiro (`data` em base64) ou um `url` externo.")

    doc["title"] = str(payload.get("title") or doc.get("title") or doc.get("filename") or "")
    doc["alt"] = str(payload.get("alt") or doc.get("alt") or "")
    doc["caption"] = str(payload.get("caption") or doc.get("caption") or "")
    doc["credit"] = str(payload.get("credit") or doc.get("credit") or "")
    doc["tags"] = _keywords(payload.get("tags") if "tags" in payload else doc.get("tags") or [])
    doc["kind"] = "imagem" if str(doc.get("mime") or "").startswith("image/") else "documento"
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    if existing:
        doc["created_at"] = existing.get("created_at") or _now()
        store["media"][store["media"].index(existing)] = doc
        action = "alterar"
    else:
        doc["created_at"] = _now()
        store["media"].insert(0, doc)
        action = "carregar"
    _log(store, action, "media", doc, author)
    _write_store(store)
    return copy.deepcopy(doc)


def media_usage(media_id: str) -> List[Dict[str, str]]:
    """Onde é que este media é usado (páginas, artigos e definições)."""
    store = _load()
    usage: List[Dict[str, str]] = []
    for page in store["pages"]:
        for block in page.get("blocks") or []:
            data = block.get("data") or {}
            if data.get("media_id") == media_id or media_id in (data.get("media_ids") or []):
                usage.append({"entity": "pages", "id": page["id"], "title": page.get("title") or "", "where": "bloco"})
                break
        if page.get("seo", {}).get("image_id") == media_id:
            usage.append({"entity": "pages", "id": page["id"], "title": page.get("title") or "", "where": "SEO"})
    for post in store["posts"]:
        if post.get("cover_id") == media_id or post.get("seo", {}).get("image_id") == media_id:
            usage.append({"entity": "posts", "id": post["id"], "title": post.get("title") or "", "where": "capa/SEO"})
    for pesquisa in store["pesquisas"]:
        if pesquisa.get("capa_id") == media_id:
            usage.append({"entity": "pesquisas", "id": pesquisa["id"], "title": pesquisa.get("title") or "", "where": "capa"})
        if pesquisa.get("logo_id") == media_id:
            usage.append({"entity": "pesquisas", "id": pesquisa["id"], "title": pesquisa.get("title") or "", "where": "logótipo"})
        if pesquisa.get("seo", {}).get("image_id") == media_id:
            usage.append({"entity": "pesquisas", "id": pesquisa["id"], "title": pesquisa.get("title") or "", "where": "SEO"})
    for modelo in store["remuneracoes"]:
        for block in modelo.get("blocks") or []:
            data = block.get("data") or {}
            if data.get("media_id") == media_id or media_id in (data.get("media_ids") or []):
                usage.append({"entity": "remuneracoes", "id": modelo["id"], "title": modelo.get("title") or "", "where": "bloco"})
                break
        if modelo.get("capa_id") == media_id:
            usage.append({"entity": "remuneracoes", "id": modelo["id"], "title": modelo.get("title") or "", "where": "capa"})
        if modelo.get("logo_id") == media_id:
            usage.append({"entity": "remuneracoes", "id": modelo["id"], "title": modelo.get("title") or "", "where": "logótipo"})
        if modelo.get("seo", {}).get("image_id") == media_id:
            usage.append({"entity": "remuneracoes", "id": modelo["id"], "title": modelo.get("title") or "", "where": "SEO"})
    if (store["settings"].get("seo") or {}).get("image_id") == media_id:
        usage.append({"entity": "settings", "id": "settings", "title": "Definições do site", "where": "imagem"})
    return usage


# --------------------------------------------------------------------------
# Contactos (formulário do site)
# --------------------------------------------------------------------------
#: Um formulário público é alvo de robôs: o limite por IP é grosseiro de
#: propósito (não substitui uma proteção a sério, evita o pior).
CONTACTO_JANELA_SEGUNDOS = 3600
CONTACTO_MAX_POR_JANELA = 5
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

_contactos_por_ip: Dict[str, List[float]] = {}


def contacto_permitido(ip: str) -> bool:
    """Conta a tentativa e diz se ainda está dentro do limite por IP."""
    agora = time.monotonic()
    with _lock:
        marcas = [marca for marca in _contactos_por_ip.get(ip or "-", []) if agora - marca < CONTACTO_JANELA_SEGUNDOS]
        if len(marcas) >= CONTACTO_MAX_POR_JANELA:
            return False
        marcas.append(agora)
        _contactos_por_ip[ip or "-"] = marcas
    return True


def validar_contacto(payload: Dict[str, Any]) -> Dict[str, str]:
    """Erros por campo de uma mensagem do formulário (vazio = pode entrar)."""
    erros: Dict[str, str] = {}
    for campo, limite in CONTACTO_LIMITES.items():
        if len(str(payload.get(campo) or "")) > limite:
            erros[campo] = f"Máximo de {limite} caracteres."
    if not str(payload.get("nome") or "").strip():
        erros["nome"] = "Indique o seu nome."
    email = str(payload.get("email") or "").strip()
    if not email:
        erros["email"] = "Indique um email, para podermos responder."
    elif not EMAIL_RE.match(email):
        erros["email"] = "Esse email não parece válido."
    if not str(payload.get("mensagem") or "").strip():
        erros["mensagem"] = "Escreva a mensagem."
    if not payload.get("consentimento"):
        erros["consentimento"] = "Precisa de autorizar o contacto para enviar."
    return erros


def contactos_por_estado() -> Dict[str, int]:
    """Contagem dos contactos por estado (para o painel)."""
    store = _load()
    contagem = {estado: 0 for estado, _ in CONTACTOS_ESTADOS}
    for item in store["contactos"]:
        estado = str(item.get("estado") or "novo")
        contagem[estado] = contagem.get(estado, 0) + 1
    return contagem


# --------------------------------------------------------------------------
# Menus, aparência e catálogo
# --------------------------------------------------------------------------
def get_settings() -> Dict[str, Any]:
    store = _load()
    settings = copy.deepcopy(store["settings"])
    for key, value in DEFAULT_SETTINGS.items():
        settings.setdefault(key, copy.deepcopy(value))
    # Garantir chaves de tema/template do menu, mesmo em instalações antigas.
    for location in ("header", "footer"):
        theme_key = f"{location}_menu_theme"
        template_key = f"{location}_menu_template"
        settings.setdefault(theme_key, "pastilhas")
        settings.setdefault(template_key, "padrao")
    return settings


def save_settings(payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    store = _load()
    settings = store["settings"]
    for key in DEFAULT_SETTINGS:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        settings[key] = copy.deepcopy(value)
    settings["posts_per_page"] = max(1, min(int(settings.get("posts_per_page") or 9), 48))
    settings["language"] = str(settings.get("language") or "pt-PT")
    settings["theme"] = str(settings.get("theme") or "claro")
    settings["accent"] = str(settings.get("accent") or DEFAULT_SETTINGS["accent"])
    settings["radius"] = max(0, min(int(settings.get("radius") or 14), 32))
    for location in ("header", "footer"):
        theme_key = f"{location}_menu_theme"
        template_key = f"{location}_menu_template"
        valid_themes = {theme["id"] for theme in MENU_THEMES}
        settings[theme_key] = str(settings.get(theme_key) or "pastilhas").strip()
        if settings[theme_key] not in valid_themes:
            settings[theme_key] = "pastilhas"
        valid_templates = {
            template["id"]
            for theme in MENU_THEMES
            if theme["id"] == settings[theme_key]
            for template in theme["templates"]
        }
        settings[template_key] = str(settings.get(template_key) or "").strip()
        if settings[template_key] not in valid_templates:
            settings[template_key] = DEFAULT_MENU_TEMPLATE.get(settings[theme_key], "padrao")
    settings["robots"] = str(settings.get("robots") or "index, follow")
    if not isinstance(settings.get("social"), dict):
        settings["social"] = copy.deepcopy(DEFAULT_SETTINGS["social"])
    if not isinstance(settings.get("seo"), dict):
        settings["seo"] = copy.deepcopy(DEFAULT_SETTINGS["seo"])
    settings["seo"]["keywords"] = _keywords((settings.get("seo") or {}).get("keywords"))
    settings["updated_at"] = _now()
    settings["updated_by"] = author
    # A página inicial vive na raiz: mudar a escolha muda os caminhos públicos.
    _refresh_page_paths(store)
    _log(store, "alterar", "settings", {"id": "settings", "title": "Definições do site"}, author)
    _write_store(store)
    return get_settings()


def list_menus() -> List[Dict[str, Any]]:
    """Menus guardados (cabeçalho, rodapé, …), tal como estão no documento."""
    return copy.deepcopy(_load()["menus"])


def get_menu(menu_id: str) -> Dict[str, Any]:
    """Um menu pelo identificador."""
    store = _load()
    for menu in store["menus"]:
        if menu.get("id") == menu_id:
            return copy.deepcopy(menu)
    raise KeyError(f"Menu {menu_id} não encontrado.")


def menu_for(location: str = "header") -> Dict[str, Any]:
    """Menu de um local (`header`/`footer`), resolvido: as páginas viram links."""
    store = _load()
    menus = [menu for menu in store["menus"] if menu.get("location") == location]
    pages_by_id = {page.get("id"): page for page in store["pages"]}
    if menus:
        menu = copy.deepcopy(menus[0])
    else:
        menu = {
            "id": f"menu-{location}",
            "name": "Menu principal" if location == "header" else "Menu de rodapé",
            "location": location,
            "menu_theme": "pastilhas",
            "menu_template": "padrao",
            "items": _default_menu_items(store, location),
        }
    menu.setdefault("menu_theme", "pastilhas")
    menu.setdefault("menu_template", "padrao")
    resolved: List[Dict[str, Any]] = []

    def walk(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in items or []:
            page = pages_by_id.get(item.get("page_id"))
            href = item.get("href") or (f"/site/{page.get('path')}" if page else "")
            label = item.get("label") or (page.get("menu_label") or page.get("title") if page else "")
            children = walk(item.get("children") or [])
            if page and page.get("status") != "publicado":
                # A página ainda é rascunho: o item desaparece, mas os submenus
                # já publicados ficam, como rótulo de grupo — senão o rascunho do
                # item que abre o submenu levava o submenu inteiro com ele.
                if label and children:
                    out.append({"label": label, "href": "", "new_tab": False, "page_id": None, "children": children})
                continue
            # Um item sem destino próprio é o rótulo de um submenu (agrupa, não navega).
            if not label or (not href and not children):
                continue
            out.append(
                {
                    "label": label,
                    "href": href,
                    "new_tab": bool(item.get("new_tab")),
                    "page_id": item.get("page_id"),
                    "children": children,
                }
            )
        return out

    menu["items"] = walk(menu.get("items") or [])
    if location == "header":
        _acrescentar_submenus_derivados(menu, store)
    return menu


def _href_da_pagina(page: Dict[str, Any]) -> str:
    path = str(page.get("path") or "").strip("/")
    return f"/site/{path}" if path else "/site"


def _item_da_pagina(page: Dict[str, Any]) -> Dict[str, Any]:
    """Item de menu de uma página: o texto é o rótulo do editor ou, sem ele, o título."""
    return {
        "label": str(page.get("menu_label") or page.get("title") or "").strip(),
        "href": _href_da_pagina(page),
        "page_id": page.get("id"),
        "new_tab": False,
    }


def _pagina_da_biblioteca(pages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Página publicada que mostra a biblioteca de relatórios (a que tem o bloco)."""
    for page in pages:
        if str(page.get("status") or "") != "publicado":
            continue
        for block in page.get("blocks") or []:
            if isinstance(block, dict) and str(block.get("type")) == "relatorios":
                return page
    return None


def _aponta_para_a_pagina(item: Dict[str, Any], page: Dict[str, Any]) -> bool:
    """O item de menu abre esta página? Pela página ligada ou pela URL escrita."""
    if item.get("page_id") and str(item.get("page_id")) == str(page.get("id")):
        return True
    return str(item.get("href") or "").rstrip("/") == _href_da_pagina(page).rstrip("/")


def _submenus_das_filhas(item: Dict[str, Any], pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """As páginas filhas publicadas da página que este item abre.

    Manda o `show_in_menu` do editor de páginas: uma subpágina aparece (e
    desaparece) do menu sem se mexer no editor de menus. A ordem é a do CMS —
    `menu_order` e, depois, o título — a mesma da lista de páginas.
    """
    page_id = str(item.get("page_id") or "")
    if not page_id:
        return []
    filhas = [
        page
        for page in pages
        if str(page.get("parent_id") or "") == page_id
        and str(page.get("status") or "") == "publicado"
        and page.get("show_in_menu") is not False
    ]
    filhas.sort(key=lambda page: (int(page.get("menu_order") or 0), str(page.get("title") or "").lower()))
    return [submenu for submenu in (_item_da_pagina(page) for page in filhas) if submenu["label"]]


def _acrescentar_submenus_derivados(menu: Dict[str, Any], store: Dict[str, Any]) -> None:
    """Acrescenta ao menu do cabeçalho os submenus que saem dos dados, não do editor.

    Duas origens, ambas derivadas a cada leitura — publicar muda o menu sem
    ninguém voltar ao editor de menus:

    * as **páginas filhas** publicadas com «Mostrar no menu», no item que abre a
      página-mãe (é o caso dos estudos de benchmark sob «Benchmarks»);
    * o que está **publicado no Estúdio**, agrupado por área de trabalho, no item
      que abre a biblioteca de relatórios (`reports_library.areas_for_menu`) —
      gratuito descarrega, pago vai para o catálogo.

    Só o cabeçalho: no rodapé os submenus são uma fila de links
    (`cms_render._footer_links`) e o rodapé inteiro ficava com os títulos todos.
    Submenus escritos à mão no editor ficam à frente destes.
    """
    pages = store.get("pages") or []
    biblioteca = _pagina_da_biblioteca(pages)
    areas: List[Dict[str, Any]] = []
    if biblioteca is not None:
        # Import tardio: a loja de relatórios é grande e esta leitura corre em
        # todas as páginas do site.
        from api import reports_library  # noqa: PLC0415

        areas = [
            {
                "label": str(area["label"]),
                "href": "",
                "page_id": None,
                "new_tab": False,
                "children": [
                    {"label": str(doc["label"]), "href": str(doc["href"]), "page_id": None, "new_tab": False}
                    for doc in area["documents"]
                ],
            }
            for area in reports_library.areas_for_menu()
        ]
    for item in menu.get("items") or []:
        submenus = _submenus_das_filhas(item, pages)
        if areas and biblioteca is not None and _aponta_para_a_pagina(item, biblioteca):
            # As áreas agrupam: agem como rótulo (não navegam).
            submenus = submenus + areas
        if submenus:
            item["children"] = list(item.get("children") or []) + submenus


def itens_de_menu(location: str, store: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Itens de um menu, pela ordem definida no conteúdo editorial.

    Uma página que não exista na instalação é simplesmente saltada — é o que
    permite o mesmo menu servir instalações com páginas diferentes.
    """
    store = store or _load()
    especificacao = editorial.MENU_RODAPE if location == "footer" else editorial.MENU_PRINCIPAL
    por_caminho = {str(page.get("path") or ""): page for page in store["pages"] if page.get("status") == "publicado"}
    itens: List[Dict[str, Any]] = []
    for etiqueta, caminho in especificacao:
        pagina = por_caminho.get(caminho)
        if pagina is not None:
            itens.append({"id": _new_id("mi"), "label": etiqueta, "href": "", "page_id": pagina.get("id"), "new_tab": False})
            continue
        # Links directos para fora do site (login, loja, URL externa).
        if caminho.startswith(("/", "http://", "https://")):
            itens.append({"id": _new_id("mi"), "label": etiqueta, "href": caminho, "page_id": None, "new_tab": False})
    return itens


def _default_menu_items(store: Dict[str, Any], location: str) -> List[Dict[str, Any]]:
    return itens_de_menu(location, store)


def page_tree(published_only: bool = False) -> List[Dict[str, Any]]:
    """Árvore de páginas (ascendentes → descendentes)."""
    store = _load()
    pages = [
        copy.deepcopy(page)
        for page in store["pages"]
        if not published_only or page.get("status") == "publicado"
    ]
    by_id = {page.get("id"): page for page in pages}
    for page in pages:
        page["children"] = []
    roots: List[Dict[str, Any]] = []
    for page in pages:
        parent = by_id.get(page.get("parent_id"))
        if parent is not None and parent is not page:
            parent["children"].append(page)
        else:
            roots.append(page)

    def sort(nodes: List[Dict[str, Any]]) -> None:
        nodes.sort(key=lambda item: (int(item.get("menu_order") or 0), str(item.get("title") or "").lower()))
        for node in nodes:
            sort(node["children"])

    sort(roots)
    return roots


def taxonomy() -> Dict[str, Any]:
    """Categorias e etiquetas com contagem de artigos publicados."""
    store = _load()
    published = [post for post in store["posts"] if post.get("status") == "publicado"]
    categories = []
    for category in sorted(store["categories"], key=lambda item: str(item.get("name") or "").lower()):
        count = len([post for post in published if category.get("id") in (post.get("category_ids") or [])])
        categories.append({**copy.deepcopy(category), "posts": count})
    tags: Dict[str, int] = {}
    for post in published:
        for tag in post.get("tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
    return {
        "categories": categories,
        "tags": [{"tag": tag, "posts": count} for tag, count in sorted(tags.items(), key=lambda item: (-item[1], item[0]))],
    }


def catalogue() -> Dict[str, Any]:
    """Tudo o que o frontend precisa para desenhar o editor."""
    store = _load()
    settings = get_settings()
    return {
        "block_types": BLOCK_TYPES,
        "content_kinds": CONTENT_KINDS,
        "template_kinds": TEMPLATES_KINDS,
        "menu_locations": MENU_LOCATIONS,
        "statuses": [{"id": item, "label": STATUS_LABELS[item], "style": STATUS_STYLE[item]} for item in STATUSES],
        "entities": list(ENTITIES),
        "pages_index": [
            {"id": page.get("id"), "title": page.get("title"), "path": page.get("path"), "status": page.get("status"), "parent_id": page.get("parent_id")}
            for page in store["pages"]
        ],
        "categories_index": [
            {"id": category.get("id"), "name": category.get("name"), "slug": category.get("slug")}
            for category in sorted(store["categories"], key=lambda item: str(item.get("name") or "").lower())
        ],
        "media_index": [
            {
                "id": media.get("id"),
                "title": media.get("title") or media.get("filename"),
                "url": media.get("url"),
                "kind": media.get("kind"),
                "mime": media.get("mime"),
                "size": media.get("size"),
                "storage": media.get("storage"),
            }
            for media in store["media"]
        ],
        "contents_index": [
            {"id": content.get("id"), "title": content.get("title"), "kind": content.get("kind")}
            for content in store["contents"]
        ],
        "templates_index": [
            {"id": template.get("id"), "name": template.get("name"), "kind": template.get("kind"), "builtin": template.get("builtin")}
            for template in store["templates"]
        ],
        "menu_themes": MENU_THEMES,
        "blog_url": "/site/blog",
        "site_url": "/site",
        "home_page_id": settings.get("home_page_id") or "",
        "blog_page_id": settings.get("blog_page_id") or "",
    }


def overview() -> Dict[str, Any]:
    """Panorama do CMS: contagens, publicações recentes e atividade."""
    store = _load()

    def counts(entity: str) -> Dict[str, int]:
        by_status: Dict[str, int] = {status: 0 for status in STATUSES}
        for item in store[entity]:
            status = str(item.get("status") or "rascunho")
            if status in by_status:
                by_status[status] += 1
        return by_status

    pages = counts("pages")
    posts = counts("posts")
    municipios = counts("municipios")
    remuneracoes = counts("remuneracoes")
    pesquisas = counts("pesquisas")
    published_pages = [page for page in store["pages"] if page.get("status") == "publicado"]
    published_posts = [post for post in store["posts"] if post.get("status") == "publicado"]
    scheduled = [
        {
            "id": item.get("id"),
            "entity": entity,
            "title": item.get("title") or item.get("municipio"),
            "slug": item.get("slug"),
            "at": item.get("scheduled_at"),
        }
        for entity in PUBLISHABLE
        for item in store[entity]
        if item.get("status") == "agendado"
    ]
    scheduled.sort(key=lambda item: str(item.get("at") or ""))
    recent = sorted(
        [
            {"id": item.get("id"), "entity": entity, "title": item.get("title") or item.get("municipio"), "slug": item.get("slug"), "at": item.get("updated_at"), "status": item.get("status"), "by": item.get("updated_by")}
            for entity in PUBLISHABLE
            for item in store[entity]
        ],
        key=lambda item: str(item.get("at") or ""),
        reverse=True,
    )[:8]
    words = sum(_words(post.get("markdown") or "") for post in store["posts"])
    return {
        "pages": {"total": len(store["pages"]), "by_status": pages, "published": pages["publicado"]},
        "posts": {"total": len(store["posts"]), "by_status": posts, "published": posts["publicado"]},
        "municipios": {"total": len(store["municipios"]), "by_status": municipios, "published": municipios["publicado"]},
        "pesquisas": {"total": len(store["pesquisas"]), "by_status": pesquisas, "published": pesquisas["publicado"]},
        "remuneracoes": {
            "total": len(store["remuneracoes"]),
            "by_status": remuneracoes,
            "published": remuneracoes["publicado"],
        },
        "contents": len(store["contents"]),
        "media": {"total": len(store["media"]), "bytes": sum(int(item.get("size") or 0) for item in store["media"])},
        "categories": len(store["categories"]),
        "templates": len(store["templates"]),
        # Contactos recebidos pelo formulário do site, por estado de seguimento.
        "contactos": contactos_por_estado(),
        "words": words,
        "scheduled": scheduled,
        "recent": recent,
        "activity": store["activity"][:12],
        "site": {
            "home": next((page.get("path") for page in published_pages if page.get("id") == store["settings"].get("home_page_id")), ""),
            "pages": len(published_pages),
            "posts": len(published_posts),
            "settings": get_settings(),
        },
    }


def search(query: str, limit: int = 30) -> Dict[str, Any]:
    """Pesquisa global no CMS (páginas, artigos, conteúdos, media e categorias)."""
    needle = (query or "").strip().lower()
    if not needle:
        return {"query": query, "total": 0, "items": []}
    store = _load()
    hits: List[Dict[str, Any]] = []
    for entity in ("pages", "posts", "municipios", "pesquisas", "contents", "media", "categories", "templates"):
        for doc in store[entity]:
            haystack = " ".join(
                str(doc.get(field) or "")
                for field in ("title", "name", "municipio", "slug", "path", "excerpt", "markdown", "body", "description", "alt", "filename", "notes")
            ).lower()
            if needle not in haystack:
                continue
            hits.append(
                {
                    "entity": entity,
                    "id": doc.get("id"),
                    "title": doc.get("title") or doc.get("name") or "",
                    "subtitle": doc.get("path") or doc.get("slug") or doc.get("filename") or "",
                    "status": doc.get("status") or "",
                    "updated_at": doc.get("updated_at") or doc.get("created_at") or "",
                }
            )
    hits.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"query": query, "total": len(hits), "items": hits[:limit]}


# --------------------------------------------------------------------------
# Imagens de marca
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Imagens de marca
# --------------------------------------------------------------------------
def _dimensoes_svg(blob: bytes) -> Dict[str, int]:
    """Largura e altura declaradas num SVG (vazio se não as tiver).

    Ficam na ficha do media para o site poder reservar o espaço da figura antes
    de ela carregar: sem isto, num telefone a página salta inteira quando a
    imagem aparece.
    """
    cabeca = blob[:800].decode("utf-8", "ignore")
    tag = re.search(r"<svg\b[^>]*>", cabeca, re.I)
    if not tag:
        return {}
    largura = re.search(r'\bwidth="(\d+(?:\.\d+)?)', tag.group(0), re.I)
    altura = re.search(r'\bheight="(\d+(?:\.\d+)?)', tag.group(0), re.I)
    if largura and altura:
        return {"width": int(float(largura.group(1))), "height": int(float(altura.group(1)))}
    vista = re.search(
        r'viewBox="[-\d.]+[ ,]+[-\d.]+[ ,]+(\d+(?:\.\d+)?)[ ,]+(\d+(?:\.\d+)?)', tag.group(0), re.I
    )
    if vista:
        return {"width": int(float(vista.group(1))), "height": int(float(vista.group(2)))}
    return {}


def _instalar_media(store: Dict[str, Any]) -> Dict[str, str]:
    """Acrescenta à biblioteca as imagens que vêm com o código (`editorial.SEED_MEDIA`).

    Idempotente: um ficheiro que já esteja na biblioteca reaproveita o media
    existente, por isso chamar isto duas vezes não duplica nada. Devolve
    `{ficheiro: id}` para quem monta o conteúdo as poder referenciar.
    """
    ids: Dict[str, str] = {}
    for filename, title, alt, caption in (*editorial.SEED_MEDIA, *editorial.SEED_MEDIA_LOJA):
        existente = next((item for item in store["media"] if item.get("filename") == filename), None)
        if existente is not None:
            # Medidas de quem entrou na biblioteca antes desta informação
            # existir: é o que evita o salto da página ao carregar a figura.
            if not existente.get("width"):
                origem = SITE_ASSETS_DIR / filename
                try:
                    existente.update(_dimensoes_svg(origem.read_bytes()))
                except OSError:
                    pass
            ids[filename] = str(existente.get("id"))
            continue
        origem = SITE_ASSETS_DIR / filename
        try:
            blob = origem.read_bytes()
        except OSError:
            logger.warning("Imagem de marca em falta: %s", origem)
            continue
        mime = EXT_MIME.get(origem.suffix.lower(), "application/octet-stream")
        extension = MIME_EXT.get(mime) or origem.suffix.lower()
        media_id = _new_id("med")
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR / f"{media_id}{extension}").write_bytes(blob)
        store["media"].insert(
            0,
            {
                "id": media_id,
                "filename": filename,
                "mime": mime,
                "extension": extension,
                "size": len(blob),
                "storage": "ficheiro",
                "url": f"/cms/media/{media_id}/raw",
                "title": title,
                "alt": alt,
                "caption": caption,
                "credit": "",
                "tags": [],
                "kind": "imagem",
                **_dimensoes_svg(blob),
                "created_at": _now(),
                "updated_at": _now(),
                "updated_by": "sistema",
            },
        )
        ids[filename] = media_id
    return ids


def instalar_media_de_marca() -> Dict[str, str]:
    """Instala as imagens de marca numa instalação já em uso e grava a loja.

    O primeiro arranque já as instala pela semente; isto serve as instalações
    que já existiam, porque o deploy de código não leva a pasta `data/`.
    """
    with _lock:
        store = _load()
        ids = _instalar_media(store)
        _write_store(store)
    return ids


def instalar_templates_editoriais() -> List[str]:
    """Acrescenta os modelos de página que faltam numa instalação já em uso.

    Idempotente: um modelo que já exista (pelo `id`) fica como está — quem o
    tenha editado não o perde. Devolve os `id` dos modelos acrescentados.
    """
    with _lock:
        store = _load()
        existentes = {str(item.get("id")) for item in store["templates"]}
        novos: List[str] = []
        for modelo in TEMPLATES_GARANTIDOS:
            if str(modelo["id"]) in existentes:
                continue
            store["templates"].append(
                {**copy.deepcopy(modelo), "created_at": _now(), "updated_at": _now()}
            )
            novos.append(str(modelo["id"]))
        if novos:
            _write_store(store)
    return novos


# --------------------------------------------------------------------------
# Sementes (primeiro arranque)
# --------------------------------------------------------------------------
def _seed(store: Dict[str, Any]) -> None:
    """Conteúdo inicial para o CMS não aparecer vazio."""
    now = _now()
    media = _instalar_media(store)
    home_id = "pag_inicio"
    sobre_id = "pag_sobre"
    blog_id = "pag_blog"
    store["pages"] = [
        {
            "id": home_id,
            "title": "Início",
            "slug": "inicio",
            "path": "",
            "parent_id": None,
            "template": "pagina-inicial",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "show_in_menu": True,
            "menu_order": 1,
            "menu_label": "Início",
            "excerpt": editorial.INICIO_EXCERPT,
            "blocks": editorial.conteudo_da_inicio(media),
            "seo": {**editorial.INICIO_SEO, "image_id": media.get("capa-sabemos-studio.svg")},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
        {
            "id": sobre_id,
            "title": "Sobre",
            "slug": "sobre",
            "path": "sobre",
            "parent_id": None,
            "template": "pagina-padrao",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "show_in_menu": True,
            "menu_order": 6,
            "menu_label": "",
            "excerpt": "Como trabalhamos os dados abertos e o que pode esperar da plataforma.",
            "blocks": editorial.conteudo_da_sobre(media),
            "seo": editorial.SOBRE_SEO,
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
        {
            "id": blog_id,
            "title": "Blog",
            "slug": "blog",
            "path": "blog",
            "parent_id": None,
            "template": "lista-de-artigos",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "show_in_menu": True,
            "menu_order": 4,
            "menu_label": "Blog",
            "excerpt": "Análises, notas de método e novidades da plataforma.",
            "blocks": [
                {"id": "blk_blog_01_hero", "type": "hero", "data": {"title": "Blog", "subtitle": "Análises, método e novidades.", "align": "esquerda"}},
                {"id": "blk_blog_02_blog", "type": "blog", "data": {"title": "", "limit": 12}},
            ],
            "seo": {"title": "Blog", "description": "Análises, notas de método e novidades da plataforma.", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
    ] + [
        {**pagina, "published_at": now, "created_at": now, "updated_at": now, "updated_by": "sistema"}
        for pagina in editorial.paginas_do_site(media)
    ]

    analytics_id = "cat_analises"
    market_id = "cat_mercado"
    product_id = "cat_produto"
    store["categories"] = [
        {"id": analytics_id, "name": "Análises", "slug": "analises", "description": "Leituras de dados e tendências.", "parent_id": None, "color": "#0ea5a4", "created_at": now, "updated_at": now},
        {"id": market_id, "name": "Mercado", "slug": "mercado", "description": "Empresas, setores e mercado.", "parent_id": None, "color": "#6366f1", "created_at": now, "updated_at": now},
        {"id": product_id, "name": "Produto", "slug": "produto", "description": "Novidades da plataforma.", "parent_id": None, "color": "#f59e0b", "created_at": now, "updated_at": now},
    ]

    artigo_contratos = editorial.artigo_contratos_2026()
    store["posts"] = [
        {
            "id": "post_bemvindo",
            "title": "Bem-vindo ao blog do Sabemos Studio",
            "slug": "bem-vindo-ao-blog",
            "excerpt": "O que vai encontrar aqui: análises de contratos públicos, notas sobre empresas e o método por detrás dos números.",
            "markdown": (
                "## Porquê um blog\n\n"
                "Os dados só valem quando se sabe **de onde vêm** e **o que dizem**. Aqui escrevemos as duas coisas: a leitura dos números e o método que a sustenta.\n\n"
                "### O que vai encontrar\n\n"
                "1. **Análises** de contratos públicos em Portugal e Espanha.\n"
                "2. **Notas de mercado** sobre empresas, setores e concentração.\n"
                "3. **Novidades do produto**, sempre com exemplos reais.\n\n"
                "> Cada artigo pode citar contratos, empresas e dossiês da plataforma.\n\n"
                "Se procura um tema, comece pela pesquisa 360."
            ),
            "blocks": [],
            "cover_id": media.get("capa-post-bemvindo.svg"),
            "category_ids": [analytics_id],
            "tags": ["contratos públicos", "método"],
            "author": "Equipa Sabemos Studio",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "featured": True,
            "reading_minutes": 3,
            "seo": {"title": "", "description": "", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
        {
            "id": "post_contratos_2026",
            "title": "Contratos públicos em 2026: o que os dados mostram",
            "slug": editorial.ARTIGO_CONTRATOS_2026_SLUG,
            "excerpt": editorial.ARTIGO_CONTRATOS_2026_EXCERPT,
            "markdown": artigo_contratos["markdown"],
            "blocks": artigo_contratos["blocks"],
            "cover_id": media.get("capa-post-contratos-2026.svg"),
            "category_ids": [analytics_id, market_id],
            "tags": ["contratos públicos", "2026", "mercado", "CPV"],
            "author": "Equipa Sabemos Studio",
            "status": "publicado",
            "published_at": (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(),
            "scheduled_at": None,
            "featured": False,
            "reading_minutes": post_reading_minutes(artigo_contratos["markdown"], artigo_contratos["blocks"]),
            "seo": {"title": "", "description": "", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
    ]

    store["templates"] = [
        {
            "id": "tpl_pagina_padrao",
            "name": "Página padrão",
            "kind": "page",
            "description": "Hero, texto, cartões e chamada à ação.",
            "builtin": True,
            "blocks": [
                {"id": "t1", "type": "hero", "data": {"title": "Título da página", "subtitle": "Uma frase que diz o essencial.", "align": "esquerda"}},
                {"id": "t2", "type": "texto", "data": {"title": "Secção", "markdown": "Escreva aqui o corpo da página em Markdown."}},
                {"id": "t3", "type": "cta", "data": {"title": "Próximo passo", "text": "Explique o que o leitor deve fazer.", "button_label": "Saber mais", "button_href": "#"}},
            ],
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "tpl_landing",
            "name": "Landing de captação",
            "kind": "page",
            "description": "Hero, cartões de valor, prova e chamada à ação.",
            "builtin": True,
            "blocks": [
                {"id": "l1", "type": "hero", "data": {"title": "Uma promessa clara", "subtitle": "Para quem é e o que resolve.", "cta_label": "Começar", "cta_href": "#", "align": "centro"}},
                {"id": "l2", "type": "destaques", "data": {"title": "Porque é diferente", "items": [{"title": "Ponto 1", "text": "Explicação curta."}, {"title": "Ponto 2", "text": "Explicação curta."}, {"title": "Ponto 3", "text": "Explicação curta."}]}},
                {"id": "l3", "type": "faq", "data": {"title": "Perguntas frequentes", "items": [{"question": "Pergunta?", "answer": "Resposta."}]}},
                {"id": "l4", "type": "cta", "data": {"title": "Pronto para começar?", "text": "", "button_label": "Falar connosco", "button_href": "#"}},
            ],
            "created_at": now,
            "updated_at": now,
        },
        {**TEMPLATE_BIBLIOTECA, "created_at": now, "updated_at": now},
        {
            "id": "tpl_artigo",
            "name": "Artigo de blog",
            "kind": "post",
            "description": "Estrutura de um artigo com introdução, secções e fecho.",
            "builtin": True,
            "blocks": [],
            "created_at": now,
            "updated_at": now,
        },
    ]

    store["contents"] = [
        {
            "id": "ctd_rodape",
            "title": "Rodapé institucional",
            "kind": "rodape",
            "body": "**IQ OS** — inteligência financeira e contratual.\n\nDados de fontes abertas, com rasto e evidência.",
            "data": {},
            "tags": ["institucional"],
            "notes": "Usado nos rodapés das páginas.",
            "uses": 0,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "ctd_contactos",
            "title": "Contactos gerais",
            "kind": "contactos",
            "body": "Fale connosco para propostas, dados ou imprensa.",
            "data": {"email": "geral@iqos.pt", "phone": "", "address": ""},
            "tags": ["institucional"],
            "notes": "",
            "uses": 0,
            "created_at": now,
            "updated_at": now,
        },
    ]

    store["settings"].update(
        {
            "home_page_id": home_id,
            "blog_page_id": blog_id,
            "site_name": "Sabemos Studio",
            "tagline": "Inteligência financeira e contratual",
            "logo_id": media.get("logo-sabemos-studio.svg"),
            "favicon_id": media.get("icone-sabemos-studio.svg"),
            "seo": {
                "title": "",
                "description": "Sabemos Studio: contratos públicos, empresas e investigação a partir de dados abertos.",
                "image_id": media.get("capa-sabemos-studio.svg"),
                "keywords": ["Sabemos Studio", "contratos públicos", "dados abertos"],
            },
        }
    )

    store["menus"] = [
        {"id": "menu_header", "name": "Menu principal", "location": "header", "menu_theme": "pastilhas", "menu_template": "padrao", "items": _default_menu_items(store, "header"), "created_at": now, "updated_at": now},
        {"id": "menu_footer", "name": "Menu de rodapé", "location": "footer", "menu_theme": "pastilhas", "menu_template": "padrao", "items": _default_menu_items(store, "footer"), "created_at": now, "updated_at": now},
    ]

    store["activity"] = [
        {
            "id": _new_id("act"),
            "at": now,
            "action": "criar",
            "entity": "settings",
            "entity_id": "settings",
            "label": "Site inicial",
            "actor": "sistema",
            "detail": "conteúdo de exemplo do CMS",
        }
    ]


def reset_seed() -> Dict[str, Any]:
    """Repõe o conteúdo de exemplo (usado nos testes)."""
    global _cache
    with _lock:
        store = _empty_store()
        _seed(store)
        _refresh_page_paths(store)
        _write_store(store)
    return overview()