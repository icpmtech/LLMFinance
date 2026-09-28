"""Registo de **regras de deteção** do módulo de padrões.

As regras são editáveis na página (`/padroes`, separador «Regras») e ficam num
documento único (`data/padroes/regras.json`, escrita atómica como no leitor RSS).
Cada regra é uma condição (ou várias, com `E`/`OU`) sobre os campos derivados de
um contrato — por isso é **avaliável**, não é só documentação:

- `desvio_preco_alto`: `ratio_base > 1,2`
- `baixa_concorrencia`: `n_concorrentes <= 1` **e** `valor >= 25 000`
- `ajuste_direto_atipico`: `ajuste_direto == 1` **e**
  `taxa_ajuste_direto_cpv < taxa_ajuste_direto_global × 0,6`

Uma condição pode comparar com **outro campo** (`{"campo": "x", "fator": 0.6}`),
o que permite regras relativas (o «normal» do CPV, não um número fixo).

Além das regras editáveis existe o catálogo dos padrões que dependem de modelos,
do grafo ou das notícias — esses não são avaliáveis por regra e são marcados como
`editavel: false` (aparecem na UI a título informativo).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "padroes"
#: Caminho do documento (o teste aponta-o para um ficheiro temporário).
PATH = Path(os.environ.get("PADROES_REGRAS_PATH") or (DIR / "regras.json"))
VERSION = 1
MAX_REGRAS = 200
MAX_TEMPLATES = 40

DOC_ID = "padroes_regras"
_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[int] = None


# ---------------------------------------------------------------------------
# Catálogo de campos, operadores e severidades
# ---------------------------------------------------------------------------
#: Campos derivados disponíveis numa regra. `escopo` diz se o valor vem do
#: contrato, do seu CPV ou do conjunto analisado.
CAMPOS: List[Dict[str, Any]] = [
    {"id": "valor", "label": "Valor do contrato", "tipo": "numero", "unidade": "€", "escopo": "contrato"},
    {"id": "preco_base", "label": "Preço base do procedimento", "tipo": "numero", "unidade": "€", "escopo": "contrato"},
    {"id": "ratio_base", "label": "Adjudicado ÷ preço base", "tipo": "numero", "unidade": "rácio", "escopo": "contrato"},
    {"id": "ratio_efetivo", "label": "Valor efetivo ÷ contratado (aditivo)", "tipo": "numero", "unidade": "rácio", "escopo": "contrato"},
    {"id": "dias_decisao", "label": "Dias entre publicação e decisão", "tipo": "numero", "unidade": "dias", "escopo": "contrato"},
    {"id": "dias_assinatura", "label": "Dias entre decisão e assinatura", "tipo": "numero", "unidade": "dias", "escopo": "contrato"},
    {"id": "dias_publicacao", "label": "Dias entre assinatura e publicação", "tipo": "numero", "unidade": "dias", "escopo": "contrato"},
    {"id": "prazo_execucao", "label": "Prazo de execução", "tipo": "numero", "unidade": "dias", "escopo": "contrato"},
    {"id": "n_concorrentes", "label": "Nº de concorrentes", "tipo": "numero", "unidade": "nº", "escopo": "contrato"},
    {"id": "ajuste_direto", "label": "Sem concurso (ajuste direto)", "tipo": "numero", "unidade": "0/1", "escopo": "contrato"},
    {"id": "ano", "label": "Ano do contrato", "tipo": "numero", "unidade": "ano", "escopo": "contrato"},
    {"id": "cpv", "label": "CPV (código)", "tipo": "texto", "unidade": "", "escopo": "contrato"},
    {"id": "cpv_grupo", "label": "CPV (grupo de 2 dígitos)", "tipo": "texto", "unidade": "", "escopo": "contrato"},
    {"id": "procedimento", "label": "Procedimento", "tipo": "texto", "unidade": "", "escopo": "contrato"},
    {"id": "adjudicante", "label": "Adjudicante (nome ou NIF)", "tipo": "texto", "unidade": "", "escopo": "contrato"},
    {"id": "adjudicataria", "label": "Adjudicatária (nome ou NIF)", "tipo": "texto", "unidade": "", "escopo": "contrato"},
    {"id": "z_cpv", "label": "Desvio robusto face ao CPV (σ)", "tipo": "numero", "unidade": "σ", "escopo": "cpv"},
    {"id": "taxa_ajuste_direto_cpv", "label": "Taxa de ajuste direto no CPV", "tipo": "numero", "unidade": "0–1", "escopo": "cpv"},
    {"id": "taxa_aditivo_cpv", "label": "Taxa de aditivos no CPV", "tipo": "numero", "unidade": "0–1", "escopo": "cpv"},
    {"id": "taxa_ajuste_direto_global", "label": "Taxa de ajuste direto global", "tipo": "numero", "unidade": "0–1", "escopo": "global"},
    {"id": "contratos_do_cpv", "label": "Contratos no CPV (amostra)", "tipo": "numero", "unidade": "nº", "escopo": "cpv"},
]

CAMPO_BY_ID = {campo["id"]: campo for campo in CAMPOS}

OPERADORES: List[Dict[str, Any]] = [
    {"id": ">", "label": "maior que", "tipos": ["numero"]},
    {"id": ">=", "label": "maior ou igual a", "tipos": ["numero"]},
    {"id": "<", "label": "menor que", "tipos": ["numero"]},
    {"id": "<=", "label": "menor ou igual a", "tipos": ["numero"]},
    {"id": "==", "label": "igual a", "tipos": ["numero", "texto"]},
    {"id": "!=", "label": "diferente de", "tipos": ["numero", "texto"]},
    {"id": "contem", "label": "contém", "tipos": ["texto"]},
    {"id": "comeca", "label": "começa por", "tipos": ["texto"]},
]

OPERADOR_IDS = {operador["id"] for operador in OPERADORES}

SEVERIDADES: List[Dict[str, str]] = [
    {"id": "info", "label": "Informação"},
    {"id": "aviso", "label": "Aviso"},
    {"id": "alerta", "label": "Alerta"},
]
SEVERIDADE_IDS = {severidade["id"] for severidade in SEVERIDADES}

#: Padrões que **não** são avaliáveis por regra (dependem de modelo, grafo ou
#: notícias). Ficam no catálogo para a UI os poder mostrar com a explicação.
PADROES_NAO_AVALIAVEIS: List[Dict[str, Any]] = [
    {
        "id": "contrato_atipico",
        "label": "Contrato atípico (consenso dos detetores)",
        "tipo": "não supervisionado",
        "metodo": "Isolation Forest + LOF + K-Means + One-Class SVM + DBSCAN",
        "descricao": "Isolado pelo consenso dos detetores em várias dimensões — não se expressa por uma condição simples.",
    },
    {
        "id": "rede_pessoas",
        "label": "Laço societário entre adjudicatárias",
        "tipo": "grafo",
        "metodo": "PessoasIQ (órgãos sociais) × contratos",
        "descricao": "Depende das relações entre pessoas e empresas.",
    },
    {
        "id": "insolvencia",
        "label": "Adjudicatária em insolvência",
        "tipo": "regra externa",
        "metodo": "join por NIF com o CIRE",
        "descricao": "Cruzamento com o índice de insolvências.",
    },
    {
        "id": "noticias_negativas",
        "label": "Menções em notícias",
        "tipo": "texto",
        "metodo": "pesquisa de menções + sentimento",
        "descricao": "Depende do leitor RSS, da recolha e das redes sociais.",
    },
    {
        "id": "risco_aditivo",
        "label": "Risco de aditivo (modelo)",
        "tipo": "supervisionado",
        "metodo": "Gradient Boosting Classifier",
        "descricao": "Probabilidade estimada pelo modelo treinado com o rótulo do portal.",
    },
]


def _uid(prefixo: str = "regra") -> str:
    return f"{prefixo}_{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower().strip()


# ---------------------------------------------------------------------------
# Regras predefinidas
# ---------------------------------------------------------------------------
#: As predefinições reproduzem exatamente a lógica que o motor já aplicava
#: (é a «régua de fábrica»): repor predefinições devolve este conjunto.
REGRAS_DEFAULT: List[Dict[str, Any]] = [
    {
        "id": "desvio_preco_alto",
        "label": "Adjudicação acima do preço base",
        "descricao": "O valor adjudicado fica muito acima do preço base do procedimento.",
        "severidade": "aviso",
        "modo": "todas",
        "condicoes": [{"campo": "ratio_base", "operador": ">", "valor": 1.2}],
    },
    {
        "id": "desvio_preco_baixo",
        "label": "Adjudicação muito abaixo do preço base",
        "descricao": "Proposta anormalmente baixa — risco de incumprimento e de aditivos futuros.",
        "severidade": "aviso",
        "modo": "todas",
        "condicoes": [{"campo": "ratio_base", "operador": "<", "valor": 0.75}],
    },
    {
        "id": "aditivo_valor",
        "label": "Valor efetivo acima do contratual (aditivo)",
        "descricao": "O valor pago acabou acima do contratado — indicador clássico de desvio orçamental.",
        "severidade": "alerta",
        "modo": "todas",
        "condicoes": [{"campo": "ratio_efetivo", "operador": ">", "valor": 1.15}],
    },
    {
        "id": "publicacao_tardia",
        "label": "Transparência tardia",
        "descricao": "Contrato publicado muito depois de ser assinado (ou antes de o ser).",
        "severidade": "aviso",
        "modo": "todas",
        "condicoes": [{"campo": "dias_publicacao", "operador": ">", "valor": 180}],
    },
    {
        "id": "publicacao_incoerente",
        "label": "Publicado antes de assinado",
        "descricao": "A data de publicação é anterior à celebração do contrato — inconsistência documental.",
        "severidade": "alerta",
        "modo": "todas",
        "condicoes": [{"campo": "dias_publicacao", "operador": "<", "valor": 0}],
    },
    {
        "id": "assinatura_tardia",
        "label": "Assinatura tardia após a decisão",
        "descricao": "Mais de seis meses entre a decisão de adjudicação e a celebração do contrato.",
        "severidade": "aviso",
        "modo": "todas",
        "condicoes": [{"campo": "dias_assinatura", "operador": ">", "valor": 180}],
    },
    {
        "id": "decisao_muito_anterior",
        "label": "Decisão publicada com grande atraso",
        "descricao": "A decisão de adjudicação só foi publicada mais de seis meses depois.",
        "severidade": "aviso",
        "modo": "todas",
        "condicoes": [{"campo": "dias_decisao", "operador": "<", "valor": -180}],
    },
    {
        "id": "baixa_concorrencia",
        "label": "Baixa concorrência em contrato relevante",
        "descricao": "Um só concorrente (ou nenhum) num contrato de valor relevante.",
        "severidade": "info",
        "modo": "todas",
        "condicoes": [
            {"campo": "n_concorrentes", "operador": "<=", "valor": 1},
            {"campo": "valor", "operador": ">=", "valor": 25000},
        ],
    },
    {
        "id": "sem_concorrentes",
        "label": "Sem concorrentes registados",
        "descricao": "O portal não registou qualquer concorrente no procedimento.",
        "severidade": "aviso",
        "modo": "todas",
        "condicoes": [{"campo": "n_concorrentes", "operador": "==", "valor": 0}],
    },
    {
        "id": "ajuste_direto_atipico",
        "label": "Ajuste direto atípico no CPV",
        "descricao": "Ajuste direto num CPV onde o concurso público é a norma (menos de 60 % da taxa global).",
        "severidade": "info",
        "modo": "todas",
        "condicoes": [
            {"campo": "ajuste_direto", "operador": "==", "valor": 1},
            {"campo": "taxa_ajuste_direto_cpv", "operador": "<", "valor": {"campo": "taxa_ajuste_direto_global", "fator": 0.6}},
        ],
    },
    {
        "id": "valor_atipico",
        "label": "Valor atípico para o CPV (σ robusto)",
        "descricao": "Valor (ou prazo) muito distante da mediana do próprio CPV.",
        "severidade": "aviso",
        "modo": "todas",
        "condicoes": [{"campo": "z_cpv", "operador": ">", "valor": 3.5}],
    },
    {
        "id": "prazo_execucao_longo",
        "label": "Prazo de execução muito longo",
        "descricao": "Contrato com prazo de execução superior a três anos — acompanhar até ao fim.",
        "severidade": "info",
        "modo": "todas",
        "condicoes": [{"campo": "prazo_execucao", "operador": ">", "valor": 1095}],
    },
]

#: Templates de regras prontos (conjuntos temáticos). `regras` são os ids das
#: regras a ativar ao aplicar o template.
TEMPLATES_DEFAULT: List[Dict[str, Any]] = [
    {
        "id": "tpl_essencial",
        "nome": "Essencial",
        "descricao": "Os sinais com menos ruído: aditivos, incoerências documentais e valores atípicos no CPV.",
        "regras": ["aditivo_valor", "publicacao_incoerente", "valor_atipico"],
    },
    {
        "id": "tpl_preco",
        "nome": "Preço e aditivos",
        "descricao": "Foco no desvio entre preço base, adjudicado e valor efetivo.",
        "regras": ["desvio_preco_alto", "desvio_preco_baixo", "aditivo_valor"],
    },
    {
        "id": "tpl_procedimento",
        "nome": "Procedimento e concorrência",
        "descricao": "Ajuste direto fora do padrão do setor e falta de concorrência.",
        "regras": ["ajuste_direto_atipico", "baixa_concorrencia", "sem_concorrentes"],
    },
    {
        "id": "tpl_prazos",
        "nome": "Prazos e transparência",
        "descricao": "Publicação e assinatura tardias, decisões com grande atraso.",
        "regras": ["publicacao_tardia", "publicacao_incoerente", "assinatura_tardia", "decisao_muito_anterior"],
    },
    {
        "id": "tpl_rigor",
        "nome": "Rigor máximo",
        "descricao": "Todas as regras predefinidas ativas — mais sensibilidade e mais ruído.",
        "regras": [regra["id"] for regra in REGRAS_DEFAULT],
    },
]


def _default_regra(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Completa uma regra predefinida com os campos de estado."""
    regra = dict(payload)
    regra.setdefault("ativo", True)
    regra.setdefault("origem", "predefinida")
    regra.setdefault("criado_em", _now())
    regra["tipo"] = "regra"
    return regra


def _estado_default() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "id": DOC_ID,
        "regras": [_default_regra(regra) for regra in REGRAS_DEFAULT],
        "templates": [dict(template, origem="predefinido", criado_em=_now()) for template in TEMPLATES_DEFAULT],
        "updated_at": _now(),
    }


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------
def _file_mtime() -> Optional[int]:
    try:
        return int(PATH.stat().st_mtime)
    except OSError:
        return None


def _read() -> Dict[str, Any]:
    if not PATH.is_file():
        return _estado_default()
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Regras de padrões ilegíveis (%s); a usar as predefinidas.", exc)
        return _estado_default()
    return _normalizar(raw)


def _normalizar(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _estado_default()
    estado = _estado_default()
    regras = raw.get("regras")
    if isinstance(regras, list):
        limpas: List[Dict[str, Any]] = []
        for item in regras:
            try:
                limpas.append(validar(item, parcial=True))
            except ValueError as exc:
                logger.debug("Regra ignorada (%s): %s", exc, str(item)[:120])
        if limpas:
            estado["regras"] = limpas[:MAX_REGRAS]
    templates = raw.get("templates")
    if isinstance(templates, list):
        limpos: List[Dict[str, Any]] = []
        for item in templates:
            if not isinstance(item, dict) or not item.get("id") or not item.get("nome"):
                continue
            # Versões antigas guardavam os ids em `ativas`; normaliza-se para
            # `regras` (a chave que o resto do módulo usa).
            if item.get("regras") is None and item.get("ativas") is not None:
                item = {**item, "regras": item.get("ativas")}
            limpos.append({**item, "regras": [str(valor) for valor in item.get("regras") or []]})
        if limpos:
            estado["templates"] = limpos[:MAX_TEMPLATES]
    estado["updated_at"] = str(raw.get("updated_at") or _now())
    return estado


def _write(estado: Dict[str, Any]) -> Dict[str, Any]:
    global _cache, _cache_mtime
    estado["version"] = VERSION
    estado["id"] = DOC_ID
    estado["updated_at"] = _now()
    PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(estado, ensure_ascii=False, indent=2, default=str)
    tmp = PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    last: Optional[OSError] = None
    for attempt in range(5):
        try:
            tmp.replace(PATH)
            break
        except PermissionError as exc:  # pragma: no cover - depende do sistema
            last = exc
            time.sleep(0.08 * (attempt + 1))
    else:  # pragma: no cover - depende do sistema
        raise last if last else OSError(f"Não foi possível gravar {PATH}.")
    _cache = estado
    _cache_mtime = _file_mtime()
    return estado


def _estado() -> Dict[str, Any]:
    """Estado atual (cache em memória invalidada pela data do ficheiro)."""
    global _cache, _cache_mtime
    with _lock:
        mtime = _file_mtime()
        if _cache is not None and mtime is not None and mtime == _cache_mtime:
            return _cache
        estado = _read()
        if not PATH.is_file():
            # Primeiro arranque: materializa as predefinições no disco.
            try:
                estado = _write(estado)
            except OSError as exc:  # pragma: no cover - depende do sistema
                logger.warning("Não foi possível gravar as regras predefinidas: %s", exc)
        _cache = estado
        _cache_mtime = _file_mtime()
        return estado


def reset_state_cache() -> None:
    """Invalida a cache em memória (usado pelos testes)."""
    global _cache, _cache_mtime
    with _lock:
        _cache = None
        _cache_mtime = None


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------
def _valor_normalizado(valor: Any, tipo: str) -> Any:
    if isinstance(valor, dict):
        campo = str(valor.get("campo") or "")
        if campo not in CAMPO_BY_ID:
            raise ValueError(f"campo de comparação desconhecido: {campo}")
        fator = valor.get("fator", 1.0)
        try:
            fator = float(fator)
        except (TypeError, ValueError) as exc:
            raise ValueError("fator inválido") from exc
        return {"campo": campo, "fator": fator}
    if tipo == "numero":
        if valor is None or valor == "":
            raise ValueError("valor numérico em falta")
        try:
            return float(valor)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"valor não numérico: {valor!r}") from exc
    return str(valor or "")


def validar(payload: Dict[str, Any], *, parcial: bool = False) -> Dict[str, Any]:
    """Valida e normaliza uma regra (levanta `ValueError` se for inválida)."""
    if not isinstance(payload, dict):
        raise ValueError("regra tem de ser um objeto")
    regra: Dict[str, Any] = dict(payload)

    label = str(regra.get("label") or "").strip()
    if not label and not parcial:
        raise ValueError("a regra precisa de um nome")
    if not str(regra.get("id") or "").strip():
        regra["id"] = _uid()

    condicoes_raw = regra.get("condicoes")
    if condicoes_raw is None:
        if parcial and regra.get("tipo") != "regra":
            # Entradas legadas (sem condições) ficam como documentação.
            regra["condicoes"] = []
            regra["editavel"] = False
            regra.setdefault("modo", "todas")
            regra.setdefault("severidade", "info")
            return regra
        raise ValueError("a regra precisa de pelo menos uma condição")
    if not isinstance(condicoes_raw, list) or not condicoes_raw:
        raise ValueError("a regra precisa de pelo menos uma condição")

    condicoes: List[Dict[str, Any]] = []
    for item in condicoes_raw:
        if not isinstance(item, dict):
            raise ValueError("condição inválida")
        campo_id = str(item.get("campo") or "").strip()
        campo = CAMPO_BY_ID.get(campo_id)
        if campo is None:
            raise ValueError(f"campo desconhecido: {campo_id}")
        operador = str(item.get("operador") or "").strip()
        if operador not in OPERADOR_IDS:
            raise ValueError(f"operador desconhecido: {operador}")
        if campo["tipo"] not in {
            tipo for definicao in OPERADORES if definicao["id"] == operador for tipo in definicao["tipos"]
        }:
            raise ValueError(f"o operador «{operador}» não se aplica a «{campo['label']}»")
        condicoes.append(
            {
                "campo": campo_id,
                "operador": operador,
                "valor": _valor_normalizado(item.get("valor"), campo["tipo"]),
            }
        )

    modo = str(regra.get("modo") or "todas")
    if modo not in {"todas", "alguma"}:
        raise ValueError("modo tem de ser «todas» (E) ou «alguma» (OU)")
    severidade = str(regra.get("severidade") or "aviso")
    if severidade not in SEVERIDADE_IDS:
        raise ValueError(f"severidade desconhecida: {severidade}")

    regra.update(
        {
            "id": re.sub(r"[^A-Za-z0-9_]+", "_", str(regra["id"]))[:64],
            "label": label or str(regra["id"]),
            "descricao": str(regra.get("descricao") or "").strip(),
            "severidade": severidade,
            "modo": modo,
            "condicoes": condicoes,
            "ativo": bool(regra.get("ativo", True)),
            "tipo": "regra",
            "editavel": True,
            "origem": str(regra.get("origem") or "utilizador"),
            "criado_em": str(regra.get("criado_em") or _now()),
        }
    )
    return regra


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def catalogo() -> Dict[str, Any]:
    """Campos, operadores, severidades e os padrões não avaliáveis."""
    return {
        "campos": CAMPOS,
        "operadores": OPERADORES,
        "severidades": SEVERIDADES,
        "padroes_nao_avaliaveis": PADROES_NAO_AVALIAVEIS,
    }


def listar() -> Dict[str, Any]:
    estado = _estado()
    return {
        "regras": estado["regras"],
        "templates": estado["templates"],
        "updated_at": estado.get("updated_at"),
        **catalogo(),
        "limites": {"regras": MAX_REGRAS, "templates": MAX_TEMPLATES},
    }


def regras_ativas() -> List[Dict[str, Any]]:
    """Regras ativas e avaliáveis (as que o motor aplica à amostra)."""
    return [regra for regra in _estado()["regras"] if regra.get("ativo") and regra.get("condicoes")]


def guardar(payload: Dict[str, Any], *, origem: str = "utilizador") -> Dict[str, Any]:
    """Cria ou atualiza uma regra (por `id`)."""
    with _lock:
        estado = dict(_estado())
        regras = list(estado["regras"])
        identificador = str(payload.get("id") or "").strip()
        existente = next((regra for regra in regras if regra.get("id") == identificador), None) if identificador else None
        base = {**(existente or {}), **payload}
        base["origem"] = base.get("origem") or origem
        regra = validar(base)
        if existente:
            regras = [regra if item.get("id") == regra["id"] else item for item in regras]
        else:
            if len(regras) >= MAX_REGRAS:
                raise ValueError(f"limite de {MAX_REGRAS} regras atingido")
            if any(item.get("id") == regra["id"] for item in regras):
                regra["id"] = _uid()
            regras.append(regra)
        estado["regras"] = regras
        _write(estado)
    return regra


def alternar(regra_id: str, ativo: Optional[bool] = None) -> Dict[str, Any]:
    """Liga/desliga uma regra (sem apagar a definição)."""
    with _lock:
        estado = dict(_estado())
        regras = list(estado["regras"])
        alvo = next((regra for regra in regras if regra.get("id") == regra_id), None)
        if alvo is None:
            raise KeyError(regra_id)
        alvo["ativo"] = (not alvo.get("ativo", True)) if ativo is None else bool(ativo)
        estado["regras"] = regras
        _write(estado)
        return alvo


def duplicar(regra_id: str) -> Dict[str, Any]:
    with _lock:
        estado = dict(_estado())
        regras = list(estado["regras"])
        alvo = next((regra for regra in regras if regra.get("id") == regra_id), None)
        if alvo is None:
            raise KeyError(regra_id)
        copia = {**alvo, "id": _uid(), "label": f"{alvo.get('label')} (cópia)", "origem": "utilizador", "criado_em": _now()}
        if len(regras) >= MAX_REGRAS:
            raise ValueError(f"limite de {MAX_REGRAS} regras atingido")
        regras.append(copia)
        estado["regras"] = regras
        _write(estado)
        return copia


def apagar(regra_id: str) -> bool:
    with _lock:
        estado = dict(_estado())
        regras = [regra for regra in estado["regras"] if regra.get("id") != regra_id]
        if len(regras) == len(estado["regras"]):
            return False
        estado["regras"] = regras
        _write(estado)
        return True


def repor_default(*, manter_personalizadas: bool = False) -> Dict[str, Any]:
    """Repõe as regras predefinidas (o «estado de fábrica»).

    `manter_personalizadas=True` mantém as regras criadas pelo utilizador e
    apenas reescreve as predefinidas que tenham sido alteradas.
    """
    with _lock:
        estado = dict(_estado())
        if manter_personalizadas:
            personalizadas = [regra for regra in estado["regras"] if regra.get("origem") != "predefinida"]
            outras = [regra for regra in estado["regras"] if regra.get("origem") == "predefinida"]
            ids_default = {regra["id"] for regra in REGRAS_DEFAULT}
            extras = [regra for regra in personalizadas if regra.get("id") not in ids_default]
            regras = [_default_regra(regra) for regra in REGRAS_DEFAULT] + extras
            faltam = len(regras) - len(outras) - len(extras)
        else:
            regras = [_default_regra(regra) for regra in REGRAS_DEFAULT]
            faltam = len(REGRAS_DEFAULT) - len(estado["regras"])
        estado["regras"] = regras[:MAX_REGRAS]
        estado["templates"] = [dict(t, origem="predefinido", criado_em=_now()) for t in TEMPLATES_DEFAULT]
        _write(estado)
        return {"regras": len(estado["regras"]), "templates": len(estado["templates"]), "diferenca": faltam}


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def guardar_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria um template a partir do estado atual (ou de uma lista de ids)."""
    with _lock:
        estado = dict(_estado())
        template_id = str(payload.get("id") or "").strip() or _uid("tpl")
        nome = str(payload.get("nome") or "").strip()
        if not nome:
            raise ValueError("o template precisa de um nome")
        ids = payload.get("regras")
        if ids is None:
            ids = [regra["id"] for regra in estado["regras"] if regra.get("ativo") and regra.get("condicoes")]
        ids = [str(item) for item in ids if item]
        conhecidos = {regra["id"] for regra in estado["regras"]}
        desconhecidos = [item for item in ids if item not in conhecidos]
        if desconhecidos:
            raise ValueError(f"regras desconhecidas no template: {', '.join(desconhecidos[:5])}")
        template = {
            "id": template_id,
            "nome": nome,
            "descricao": str(payload.get("descricao") or "").strip(),
            "regras": ids,
            "origem": "utilizador",
            "criado_em": _now(),
        }
        templates = [item for item in estado["templates"] if item.get("id") != template_id]
        templates.append(template)
        if len(templates) > MAX_TEMPLATES:
            templates = templates[-MAX_TEMPLATES:]
        estado["templates"] = templates
        _write(estado)
        return template


def apagar_template(template_id: str) -> bool:
    with _lock:
        estado = dict(_estado())
        templates = [item for item in estado["templates"] if item.get("id") != template_id]
        if len(templates) == len(estado["templates"]):
            return False
        estado["templates"] = templates
        _write(estado)
        return True


def aplicar_template(template_id: str) -> Dict[str, Any]:
    """Aplica um template: ativa as suas regras e desliga as restantes."""
    with _lock:
        estado = dict(_estado())
        template = next((item for item in estado["templates"] if item.get("id") == template_id), None)
        if template is None:
            raise KeyError(template_id)
        ativas = {str(item) for item in template.get("regras") or template.get("ativas") or []}
        for regra in estado["regras"]:
            regra["ativo"] = regra.get("id") in ativas
        _write(estado)
        return {
            "template": template_id,
            "nome": template.get("nome"),
            "ativas": sorted(ativas),
            "total_regras": len(estado["regras"]),
        }


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------
def _comparar(esquerda: Any, operador: str, direita: Any, tipo: str) -> bool:
    if isinstance(direita, dict):
        direita = direita.get("valor") if "valor" in direita else direita
    if esquerda is None or direita is None:
        return False
    if tipo == "numero":
        try:
            a, b = float(esquerda), float(direita)
        except (TypeError, ValueError):
            return False
        if operador == ">":
            return a > b
        if operador == ">=":
            return a >= b
        if operador == "<":
            return a < b
        if operador == "<=":
            return a <= b
        if operador == "==":
            return abs(a - b) < 1e-9
        if operador == "!=":
            return abs(a - b) >= 1e-9
        return False
    texto = _fold(esquerda)
    alvo = _fold(direita)
    if operador == "==":
        return texto == alvo
    if operador == "!=":
        return texto != alvo
    if operador == "contem":
        return alvo in texto
    if operador == "comeca":
        return texto.startswith(alvo)
    return False


def _resolver(valor: Any, contexto: Dict[str, Any]) -> Any:
    """Resolve o lado direito de uma condição (número, texto ou outro campo)."""
    if isinstance(valor, dict) and "campo" in valor:
        referencia = contexto.get(str(valor["campo"]))
        fator = float(valor.get("fator", 1.0) or 1.0)
        if referencia is None:
            return None
        try:
            return float(referencia) * fator
        except (TypeError, ValueError):
            return referencia
    return valor


def avaliar(contexto: Dict[str, Any], regras: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Devolve as regras cumpridas por um contrato (com o detalhe legível)."""
    cumpridas: List[Dict[str, Any]] = []
    for regra in regras:
        condicoes = regra.get("condicoes") or []
        if not condicoes:
            continue
        resultados: List[Tuple[bool, Dict[str, Any], Any]] = []
        for condicao in condicoes:
            campo = condicao.get("campo")
            definicao = CAMPO_BY_ID.get(str(campo))
            if definicao is None:
                resultados.append((False, condicao, None))
                continue
            esquerda = contexto.get(str(campo))
            direita = _resolver(condicao.get("valor"), contexto)
            resultados.append((_comparar(esquerda, condicao.get("operador", ""), direita, definicao["tipo"]), condicao, esquerda))

        todos = all(item[0] for item in resultados)
        algum = any(item[0] for item in resultados)
        if (todos if regra.get("modo") != "alguma" else algum):
            cumpridas.append(
                {
                    "padrao": regra.get("id"),
                    "label": regra.get("label"),
                    "severidade": regra.get("severidade") or "aviso",
                    "origem": "regra",
                    "detalhe": ", ".join(
                        f"{CAMPO_BY_ID.get(c['campo'], {}).get('label', c['campo'])} {c['operador']} "
                        f"{_formatar_valor(_resolver(c.get('valor'), contexto), c['campo'])}"
                        f" (valor: {_formatar_valor(valor, c['campo'])})"
                        for ok, c, valor in resultados
                        if ok
                    )
                    or regra.get("descricao")
                    or regra.get("label"),
                }
            )
    return cumpridas


def _formatar_valor(valor: Any, campo: str) -> str:
    if valor is None:
        return "—"
    definicao = CAMPO_BY_ID.get(str(campo)) or {}
    tipo = definicao.get("tipo")
    unidade = definicao.get("unidade") or ""
    if tipo == "numero":
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            return str(valor)
        if unidade == "€":
            return f"{numero:,.0f} €".replace(",", " ")
        if unidade == "0–1":
            return f"{numero * 100:.0f} %"
        texto = f"{numero:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
        return f"{texto}{(' ' + unidade) if unidade and unidade not in {'0/1', 'ano'} else ''}"
    return str(valor)


def resumo_regras(regras: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Descrição legível das regras (para a UI e para o relatório)."""
    saida: List[Dict[str, Any]] = []
    for regra in regras:
        partes = []
        for condicao in regra.get("condicoes") or []:
            definicao = CAMPO_BY_ID.get(str(condicao.get("campo"))) or {}
            direito = condicao.get("valor")
            if isinstance(direito, dict):
                fator = float(direito.get("fator", 1) or 1)
                outro = CAMPO_BY_ID.get(str(direito.get("campo"))) or {}
                direito_txt = (f"{fator:g} × " if fator != 1 else "") + f"{outro.get('label', direito.get('campo'))}"
            else:
                direito_txt = _formatar_valor(direito, str(condicao.get("campo")))
            partes.append(f"{definicao.get('label', condicao.get('campo'))} {condicao.get('operador')} {direito_txt}")
        saida.append(
            {
                "id": regra.get("id"),
                "label": regra.get("label"),
                "descricao": regra.get("descricao"),
                "severidade": regra.get("severidade"),
                "ativo": bool(regra.get("ativo")),
                "origem": regra.get("origem"),
                "condicao": (" E " if regra.get("modo") != "alguma" else " OU ").join(partes),
                "condicoes": regra.get("condicoes") or [],
            }
        )
    return saida
