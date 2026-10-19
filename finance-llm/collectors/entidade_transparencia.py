"""Recolha e normalização da **Entidade para a Transparência** (EPT).

A plataforma pública (`entidadetransparencia.pt`) é uma SPA Vue que fala com
`api.entidadetransparencia.pt`. Os dados abertos que ela expõe — e que este
módulo recolhe — são:

- o **catálogo** de entidades, cargos, órgãos e titulares;
- as **titularidades** (entidade × cargo × titular, com datas);
- as **declarações únicas** de cada titular (natureza, estado, entidade, cargo,
  datas de entrega) e o respetivo conteúdo estruturado.

O fluxo usado pela própria plataforma é hierárquico e é o mesmo que este
coletor segue: **entidade → cargo → nome do titular**. `getallroles` aceita
`EntityId`/`HolderId`/`BoardId` e `getallholders` aceita `EntityId`/`RoleId`/
`BoardId`, pelo que a cascata é feita no servidor.

Este módulo é **só de leitura e normalização**: não guarda estado nem fala com
o Elasticsearch. A recolha completa (pausa entre pedidos, JSONL e indexação) é
orquestrada por `api/entidade_transparencia_service.py`.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
import unicodedata
from typing import Any, Dict, Iterable, Iterator, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_WEB = "https://entidadetransparencia.pt"
BASE_API = "https://api.entidadetransparencia.pt"

PATH_ENTITIES = "/publicquery/getallentities"
PATH_ROLES = "/publicquery/getallroles"
PATH_BOARDS = "/publicquery/getallboards"
PATH_HOLDERS = "/publicquery/getallholders"
PATH_POSITIONS = "/publicquery"
PATH_DECLARATIONS = "/publicquery/search"
PATH_DECLARATION = "/publicquery/getdeclaration"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": BASE_WEB,
    "Referer": f"{BASE_WEB}/",
    "X-Language": "PT",
}

#: Tamanho de página máximo observado na API pública.
PAGE_SIZE = 1000
#: Pausa entre pedidos (segundos) — a API é pública e não documentada.
PAUSA = 0.4
TENTATIVAS = 4
TIMEOUT = 60.0


class EptError(RuntimeError):
    """Resposta inesperada da API da Entidade para a Transparência."""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def make_client(timeout: float = TIMEOUT) -> httpx.Client:
    """Cliente HTTP com cabeçalhos de browser (a API exige `Origin`)."""
    return httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True)


def post_json(
    client: httpx.Client,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    tentativas: int = TENTATIVAS,
    pausa: float = PAUSA,
) -> Dict[str, Any]:
    """POST JSON com recuo exponencial em 429/5xx/timeout.

    A API devolve sempre o envelope `{code, description, data}`; um `code`
    diferente de zero é um erro de negócio e é levantado como `EptError`.
    """
    import time

    url = f"{BASE_API}{path}"
    corpo = payload or {}
    ultimo: Optional[Exception] = None
    for tentativa in range(max(1, tentativas)):
        try:
            resposta = client.post(url, json=corpo)
        except httpx.HTTPError as exc:  # rede: repetir
            ultimo = exc
        else:
            if resposta.status_code == 429 or resposta.status_code >= 500:
                ultimo = EptError(f"HTTP {resposta.status_code} em {path}")
            elif resposta.status_code >= 400:
                detalhe = resposta.text[:400]
                raise EptError(f"HTTP {resposta.status_code} em {path}: {detalhe}")
            else:
                try:
                    dados = resposta.json()
                except ValueError as exc:
                    raise EptError(f"Resposta não-JSON em {path}") from exc
                codigo = dados.get("code")
                if codigo not in (0, None):
                    raise EptError(
                        f"{path}: code={codigo} {dados.get('description') or dados.get('externalMessageId') or ''}".strip()
                    )
                return dados
        if tentativa + 1 < max(1, tentativas):
            time.sleep(pausa * (2**tentativa))
    raise EptError(f"Não foi possível obter {path}: {ultimo}")


def _opcoes(dados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Converte `[{value,label}]` em `[{id,nome}]`, sem duplicados."""
    vistos: set[tuple[str, str]] = set()
    itens: List[Dict[str, Any]] = []
    for entrada in dados.get("data") or []:
        if not isinstance(entrada, dict):
            continue
        valor = entrada.get("value")
        rotulo = (entrada.get("label") or "").strip()
        if valor in (None, "", -1) or not rotulo:
            continue
        chave = (str(valor), rotulo)
        if chave in vistos:
            continue
        vistos.add(chave)
        itens.append({"id": str(valor), "nome": rotulo})
    itens.sort(key=lambda item: _chave_ordenacao(item["nome"]))
    return itens


def _chave_ordenacao(valor: str) -> str:
    return normalize_text(valor)


def normalize_text(valor: Optional[str]) -> str:
    """Minúsculas sem acentos, para ordenar e comparar nomes."""
    if not valor:
        return ""
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", texto).strip().lower()


def normalize_name(valor: Optional[str]) -> str:
    """Chave de comparação de nomes de pessoas (sem acentos nem pontuação)."""
    texto = normalize_text(valor)
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


# ---------------------------------------------------------------------------
# Catálogo e cascata entidade → cargo → titular
# ---------------------------------------------------------------------------


def fetch_entities(client: httpx.Client) -> List[Dict[str, Any]]:
    """Todas as entidades/órgãos com titularidades declaradas."""
    return _opcoes(post_json(client, PATH_ENTITIES, {}))


def fetch_roles(
    client: httpx.Client,
    *,
    entity_id: Optional[str] = None,
    holder_id: Optional[str] = None,
    board_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Cargos, opcionalmente limitados pela entidade, titular ou órgão."""
    payload = _filtros(EntityId=entity_id, HolderId=holder_id, BoardId=board_id)
    return _opcoes(post_json(client, PATH_ROLES, payload))


def fetch_boards(
    client: httpx.Client,
    *,
    entity_id: Optional[str] = None,
    role_id: Optional[str] = None,
    holder_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Órgãos, opcionalmente limitados pela entidade, cargo ou titular."""
    payload = _filtros(EntityId=entity_id, RoleId=role_id, HolderId=holder_id)
    return _opcoes(post_json(client, PATH_BOARDS, payload))


def fetch_holders(
    client: httpx.Client,
    *,
    entity_id: Optional[str] = None,
    role_id: Optional[str] = None,
    board_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Titulares (nomes), opcionalmente limitados pela entidade/cargo/órgão.

    É este o passo «nome do titular» da cascata da plataforma.
    """
    payload = _filtros(EntityId=entity_id, RoleId=role_id, BoardId=board_id)
    return _opcoes(post_json(client, PATH_HOLDERS, payload))


def _filtros(**kwargs: Any) -> Dict[str, Any]:
    filtros: Dict[str, Any] = {}
    for chave, valor in kwargs.items():
        if valor in (None, "", 0, "0", -1, "-1", "all"):
            continue
        try:
            filtros[chave] = int(valor)
        except (TypeError, ValueError):
            continue
    return filtros


def fetch_positions(
    client: httpx.Client,
    *,
    page: int = 1,
    size: int = PAGE_SIZE,
) -> Dict[str, Any]:
    """Uma página de titularidades (todas as entidades × cargos × titulares)."""
    dados = post_json(
        client,
        PATH_POSITIONS,
        {"pageNumber": max(1, int(page)), "pageSize": max(1, int(size))},
    )
    data = dados.get("data") or {}
    itens = [_position(item) for item in (data.get("items") or []) if isinstance(item, dict)]
    return {
        "items": itens,
        "page": int(data.get("pageNumber") or page),
        "size": int(data.get("pageSize") or size),
        "pages": int(data.get("pageCount") or 1),
        "total": int(data.get("total") or len(itens)),
    }


def _position(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "titularidade_id": str(item.get("id") or ""),
        "titular_id": _str_id(item.get("holderId")),
        "titular": item.get("holder"),
        "entidade_id": _str_id(item.get("entityId")),
        "entidade": item.get("entity"),
        "cargo_id": _str_id(item.get("roleId")),
        "cargo": item.get("role"),
        "inicio": _iso_date(item.get("beginDate")),
        "fim": _iso_date(item.get("endDate")),
    }


def iter_positions(
    client: httpx.Client,
    *,
    size: int = PAGE_SIZE,
    pausa: float = 0.0,
) -> Iterator[Dict[str, Any]]:
    """Percorre todas as titularidades, página a página."""
    import time

    primeira = fetch_positions(client, page=1, size=size)
    yield from primeira["items"]
    for pagina in range(2, int(primeira["pages"]) + 1):
        if pausa:
            time.sleep(pausa)
        yield from fetch_positions(client, page=pagina, size=size)["items"]


# ---------------------------------------------------------------------------
# Declarações
# ---------------------------------------------------------------------------


def fetch_declarations(
    client: httpx.Client,
    holder_id: str,
    *,
    size: int = 100,
) -> List[Dict[str, Any]]:
    """Todas as declarações de um titular (metadados, sem o conteúdo)."""
    itens: List[Dict[str, Any]] = []
    pagina = 1
    while True:
        dados = post_json(
            client,
            PATH_DECLARATIONS,
            {"HolderId": int(holder_id), "pageNumber": pagina, "pageSize": max(1, int(size))},
        )
        data = dados.get("data") or {}
        lote = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        itens.extend(_declaration_meta(item) for item in lote)
        paginas = int(data.get("pageCount") or 1)
        if pagina >= paginas or not lote:
            break
        pagina += 1
    return itens


def _declaration_meta(item: Dict[str, Any]) -> Dict[str, Any]:
    natureza_codigo = item.get("natureTypeId")
    estado_codigo = item.get("stateTypeId")
    return {
        "declaracao_id": str(item.get("id") or ""),
        "titular_id": _str_id(item.get("holderId")),
        "titular": item.get("holder"),
        "ano": int(item.get("year") or 0),
        "natureza_codigo": natureza_codigo,
        # A API devolve o rótulo em inglês (`Cessation`); o código é a fonte
        # fiável para o rótulo português usado no índice e na interface.
        "natureza": NATUREZAS.get(natureza_codigo) or item.get("natureType"),
        "estado_codigo": estado_codigo,
        "estado": ESTADOS.get(estado_codigo) or item.get("stateType"),
        "entidade": item.get("entity"),
        "orgao": item.get("board"),
        "cargo": item.get("role"),
        "inicio": _iso_date(item.get("startDate")),
        "fim": _iso_date(item.get("endDate")),
        "entrega": _iso_date(item.get("deliveryDate")),
        "relacionada_id": _str_id(item.get("relatedDeclarationId")),
    }


def fetch_declaration(client: httpx.Client, declaration_id: str) -> Dict[str, Any]:
    """Conteúdo completo de uma declaração (árvore de secções)."""
    dados = post_json(client, PATH_DECLARATION, {"Id": int(declaration_id)})
    return dados.get("data") or {}


# ---------------------------------------------------------------------------
# Rótulos (derivados do modelo oficial e da própria aplicação)
# ---------------------------------------------------------------------------

#: Tipo de declaração (`declarationNatureTypeEnum`).
NATUREZAS: Dict[int, str] = {
    1: "Inicial",
    2: "Alteração",
    4: "Cessação",
    8: "Final",
    16: "Substituição",
    32: "Recondução/Reeleição",
}

#: Estado da declaração (`declarationStateTypeEnum`).
ESTADOS: Dict[int, str] = {
    1: "Rascunho",
    2: "Pendente de verificação",
    4: "Não publicada",
    8: "Publicada",
    16: "Anulada",
    32: "Alterada",
    64: "Substituída",
}

#: Secções de topo do modelo da declaração única.
SECOES: Dict[str, str] = {
    "dab5b2ca-921a-4c8a-950a-5413e46625aa": "Anexos",
    "358af850-b811-494a-8a38-81eadaf9d695": "Facto determinante da declaração",
    "7df770a3-e06b-4448-b5ac-c1b162c80fcc": "Dados pessoais, morada e contactos",
    "ecc58cb2-0808-4d2f-bb2b-64b87617a4ac": "Rendimentos",
    "1a24058c-9ebe-4c14-9876-e5181310fb19": "Ativo patrimonial",
    "ba17cce1-b542-42a8-a22a-d6a541428858": "Passivo",
    "2a52ac1f-dac3-4d82-83cb-18d2a4b98be2": "Promessa de vantagem patrimonial",
    "97941562-f066-4520-bf07-fc3330832c68": "Outras declarações",
    "1483a8d1-adca-4f39-8038-98cc6f728fcb": "Registo de interesses",
    "a8dbe47f-c740-4edb-8605-451ed9fe6c87": "Versão do modelo",
}

#: Subsecções que valem um bloco próprio na ficha.
SUBSECOES: Dict[str, str] = {
    "56786e7c-a8bb-43aa-9250-eaf8fa82002f": "Dados pessoais",
    "6a3c614b-2c9e-42f3-b5af-49cc8b078204": "Morada",
    "b437d8f1-e201-4fc0-a304-e5f78ca1a063": "Contactos",
    "45b8a3d2-374f-4531-b167-ac62b950ad6b": "Rendimentos",
    "888d8680-77d1-40ef-8fac-d69586bf37ba": "Ativo patrimonial — Portugal",
    "90df628b-64cd-46db-bd1e-427897977b63": "Ativo patrimonial — Estrangeiro",
    "bf6dcb0a-19de-4c77-8ff6-76e57f93ceef": "Passivo — Portugal",
    "142f6497-9e25-44e9-a79a-f19acade29b9": "Passivo — Estrangeiro",
    "88ff2a6e-3702-4687-9f05-2738f70ccbd0": "Registo de interesses",
    "16a24d4d-5846-46f3-89b6-2427ca329dd4": "Outras declarações",
    "05d711d3-08cd-4944-8be9-dc5f40a201fc": "Aplicações e depósitos",
}

#: Campos escalares com rótulo conhecido (extraídos dos templates e do i18n).
CAMPOS: Dict[str, str] = {
    "f649defc-e001-4866-9c2b-01ed9fa80eef": "Natureza da declaração",
    "d34934dc-dc8f-4515-abc3-eb2a16d58ed1": "Titular (código)",
    "d34723dc-dc8f-4515-abc3-eb2a16d58ed1": "Titular",
    "c83b94a8-5d7a-4061-a001-0c3522d2e533": "Entidade",
    "21cdd43f-aebd-43c1-8b47-0eafedb644c8": "Órgão",
    "5a4b3e2d-c82c-49f8-a1c0-5ad86ddb0d67": "Cargo/Função",
    "418cdc5e-7f77-4922-b0b7-3ab6b2f84c6f": "Data de início de funções",
    "5783eba6-4662-4e01-a1ab-14dbe7bb693c": "Data de cessação de funções",
    "b8de313d-cc0d-445d-b211-368794d7a2df": "Exercício de funções em regime de exclusividade",
    "c0a2f813-fb84-4923-b7a1-55cef0c5fc1b": "Nome completo",
    "54854c64-5845-40bb-a536-8c03da55420a": "Sexo",
    "a5bf96eb-8af0-4c05-bb76-a15f57f8490d": "Naturalidade",
    "25fa81a1-70d2-4fca-8292-4717ba2e8cdb": "Data de nascimento",
    "ed9a8413-b9f0-4d32-89bd-03593c826211": "Estado civil",
    "ed9a8413-b9f0-4d32-89bd-03593c826212": "Regime de bens",
    "ed9a8413-b9f0-4d32-89bd-03593c826213": "Nome do cônjuge ou unido/a de facto",
    "37b963d3-b73a-4da7-9a78-cb417f92214a": "Morada",
    "38cffadd-0893-47ef-b261-84007c381639": "Código postal",
    "308ccc8a-452a-4ed7-94e5-5ca17a1667fe": "Localidade",
    "2b75bfd8-392e-49d7-866f-1353a5e765c3": "Concelho",
    "77902677-0143-437c-ae9b-b3e54642a080": "Freguesia",
    "d3fd512b-65e8-4550-90d9-018a5ef91c0d": "E-mail",
    "67d71fd5-100a-42dd-a6a8-44d40ce2ba50": "Telefone",
    "8b022aca-fdf8-4391-8d49-73abc4e63128": "Telemóvel",
    "929796f8-a63c-49b4-b2de-56191668dfa0": "Trabalho independente",
    "ff035b46-8c60-4ffb-9307-9b348210c7dd": "Comerciais e industriais",
    "4863ec0b-2061-4bed-a88f-6803547d839b": "Agrícolas",
    "a4f13529-fc7b-4a8d-a57d-4c6a04c5de32": "Capitais",
    "90848b4c-9530-44f3-82c3-5cabd86f936a": "Mais-valias",
    "fb030f7e-bb87-49b6-8d67-65dfa01699c0": "Pensões",
    "548797e6-8cbd-4e2e-8aff-b6bed1c7ed6e": "Outros rendimentos",
    "1d9eb246-99b3-41c1-9ef4-473925b77296": "Prediais",
    "51240498-fcab-4342-8522-2bf14c84ed39": "Outras declarações",
    "97ac10fd-3e8e-4fa8-a7f2-991bb3d13a0e": "Número de identificação civil",
    "d155af2b-21e9-475f-be81-8e42bc5a5641": "Número de identificação fiscal",
}

#: Tabelas (listas de registos) e o nome que lhes damos.
TABELAS: Dict[str, str] = {
    "da9c415a-e950-4ce9-ab58-5ce1c1b5af53": "Trabalho dependente",
    "e516635f-aeb6-4e1f-aa9c-d77bf888ec36": "Trabalho independente",
    "112c6561-4a51-4f79-b637-bbd8d2c0c74c": "Património imobiliário (Portugal)",
    "252ba9e4-bbba-4660-be9e-470b263c4832": "Património imobiliário (Estrangeiro)",
    "70fdd906-58d5-4682-967d-90ae90805436": "Quotas, ações e outras partes sociais (Portugal)",
    "cdeffda1-efd5-44c7-b256-1822dd5bafe0": "Quotas, ações e outras partes sociais (Estrangeiro)",
    "53168cfb-433e-41e6-9b23-33c1eac7fa6f": "Barcos, aeronaves e veículos (Portugal)",
    "05d989a9-7824-459d-aeb3-cc13f1f70c00": "Barcos, aeronaves e veículos (Estrangeiro)",
    "1a5d2580-aaf3-4874-9e20-68ce10671263": "Carteiras de títulos (Portugal)",
    "4a8f53d5-34c2-4bda-b3ea-ec2b157efe67": "Carteiras de títulos (Estrangeiro)",
    "e498015f-062e-4fcd-93a8-c5f1393f568b": "Contas bancárias a prazo (Portugal)",
    "9d7b601c-dc39-4460-a3ab-3bc1178cbae7": "Contas bancárias a prazo (Estrangeiro)",
    "7bf6ccdd-f797-4339-8c76-18a248882016": "Aplicações financeiras (Portugal)",
    "5eea74fb-2cdc-4897-8f04-ce31341f7296": "Aplicações financeiras (Estrangeiro)",
    "873b46af-f3a5-4329-9aa0-a04fd1114467": "Contas bancárias à ordem (Portugal)",
    "151ea0ca-b4a5-4764-a461-67d0c300c915": "Contas bancárias à ordem (Estrangeiro)",
    "58adafd6-226e-4978-a48c-66f53affd3ac": "Direitos de crédito (Portugal)",
    "f4838f1a-b32e-43bd-9f3e-6de9ff72526d": "Direitos de crédito (Estrangeiro)",
    "8a7cfdae-1d47-41f9-a366-5ba020c1b90f": "Outros elementos do ativo patrimonial (Portugal)",
    "ea846529-712c-4b47-953f-5b39015c4f17": "Outros elementos do ativo patrimonial (Estrangeiro)",
    "27bb57dd-0fd8-4595-aaca-53bf1634ca87": "Passivo (Portugal)",
    "50117239-0a0b-427d-9c23-f33c766b2b3a": "Passivo (Estrangeiro)",
    "ffd1a4f7-c19e-4e75-b722-11c6e3fae511": "Garantias patrimoniais (Portugal)",
    "3737df7d-c0e0-4a24-8bce-346a479971f5": "Garantias patrimoniais (Estrangeiro)",
    "60c13abc-b075-475c-86c5-fa69a7cae259": "Promessa de vantagem patrimonial",
    "2c6d9562-dea5-488b-9afe-42519c636daf": "Atividades profissionais, cargos e funções",
    "cd0e811a-d9bb-49ee-b0f0-1dae0680eb22": "Filiação ou participação em entidades associativas",
    "62fb0107-a68d-4ba2-822b-bc8adc54369b": "Apoios ou benefícios",
    "b1f8c095-fe0c-4bb3-b493-902dc0c31232": "Serviços prestados",
    "9b58c917-b14c-4eed-9b3c-40c3d99d45da": "Sociedades",
    "fd85f91f-2803-41bc-b315-ede3a4a66d4e": "Outras situações",
}

#: Colunas das tabelas em que o significado está confirmado pelo modelo/i18n.
COLUNAS: Dict[str, Dict[str, str]] = {
    "da9c415a-e950-4ce9-ab58-5ce1c1b5af53": {
        "col1": "Valor monetário",
        "col2": "Designação da entidade pagadora",
        "col3": "NIF/NIPC",
        "col4": "Rendimento obtido no estrangeiro?",
    },
    "2c6d9562-dea5-488b-9afe-42519c636daf": {
        "col1": "Cargo/Função/Atividade",
        "col2": "Entidade",
        "col3": "Natureza e área de atuação da entidade",
        "col4": "Local da sede",
        "col5": "Remuneração (se aplicável)",
        "col6": "Data de início",
        "col7": "Data de termo",
        "col9": "NIF/NIPC",
    },
    "cd0e811a-d9bb-49ee-b0f0-1dae0680eb22": {
        "col1": "Cargo/Função/Atividade",
        "col2": "Entidade",
        "col3": "Natureza e área de atuação da entidade",
        "col4": "Local da sede",
        "col5": "Remuneração (se aplicável)",
        "col6": "Data de início",
        "col7": "Data de termo",
        "col8": "NIF/NIPC",
    },
}

#: Enums por campo/coluna.
ENUMS: Dict[str, Dict[Any, str]] = {
    "sim_nao": {0: "Não", 1: "Sim", "0": "Não", "1": "Sim"},
    "sexo": {"M": "Masculino", "F": "Feminino"},
    "estado_civil": {
        0: "Solteiro(a)",
        1: "Casado(a)",
        2: "Divorciado(a)",
        3: "Viúvo(a)",
        4: "Casado(a), mas separado(a) de pessoas e bens",
        5: "Unido(a) de facto",
    },
    "natureza": NATUREZAS,
    "estado": ESTADOS,
}

#: (tabela, coluna) → enum.
ENUMS_COLUNAS: Dict[tuple[str, str], str] = {
    ("da9c415a-e950-4ce9-ab58-5ce1c1b5af53", "col4"): "sim_nao",
    ("2c6d9562-dea5-488b-9afe-42519c636daf", "col5"): "sim_nao",
    ("cd0e811a-d9bb-49ee-b0f0-1dae0680eb22", "col5"): "sim_nao",
}

ENUMS_CAMPOS: Dict[str, str] = {
    "54854c64-5845-40bb-a536-8c03da55420a": "sexo",
    "ed9a8413-b9f0-4d32-89bd-03593c826211": "estado_civil",
    "f649defc-e001-4866-9c2b-01ed9fa80eef": "natureza",
    "b8de313d-cc0d-445d-b211-368794d7a2df": "sim_nao",
}

#: Campos que só repetem, em código, o que já vem nos metadados da declaração.
CAMPOS_IGNORAR = {
    "c83b94a8-5d7a-4061-a001-0c3522d2e533",
    "21cdd43f-aebd-43c1-8b47-0eafedb644c8",
    "5a4b3e2d-c82c-49f8-a1c0-5ad86ddb0d67",
    "d34934dc-dc8f-4515-abc3-eb2a16d58ed1",
    "d34723dc-dc8f-4515-abc3-eb2a16d58ed1",
}


def _enum(valor: Any, tipo: Optional[str]) -> Any:
    if not tipo or valor in (None, ""):
        return valor
    return ENUMS.get(tipo, {}).get(valor, valor)


def _str_id(valor: Any) -> Optional[str]:
    if valor in (None, "", 0, "0", -1, "-1"):
        return None
    return str(valor)


def _iso_date(valor: Any) -> Optional[str]:
    """Data/hora em ISO-8601 (a API usa `2026-01-27T13:55:00Z`)."""
    if not valor:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    # `Z` é aceite pelo Elasticsearch; só normalizamos espaços.
    texto = texto.replace(" ", "T", 1) if " " in texto and "T" not in texto else texto
    try:
        _dt.datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return texto


# ---------------------------------------------------------------------------
# Normalização da declaração
# ---------------------------------------------------------------------------


def normalize_declaration(
    payload: Dict[str, Any],
    *,
    recolhido_em: Optional[str] = None,
) -> Dict[str, Any]:
    """Achata a árvore de secções da API num documento indexável.

    A resposta é uma árvore de `{key: uuid, value: [...]}`. A normalização
    preserva a estrutura (secções → campos/tabelas/subsecções), dá rótulos
    legíveis aos campos conhecidos e agrega todo o texto num campo `texto`.
    """
    data = payload
    envelope = payload.get("data")
    # `payload` pode ser a resposta completa (`{code, data: {...}}`) ou já o
    # objeto da declaração (que tem, ele próprio, uma chave `data` com a árvore).
    if isinstance(envelope, dict) and ("holderId" in envelope or "holder" in envelope):
        data = envelope
    declaracao_id = _str_id(data.get("id")) or ""
    meta = _declaration_meta({**data, "id": declaracao_id})
    meta.update(
        {
            "titular_id": _str_id(data.get("holderId")),
            "titular": data.get("holder"),
            "titular_normalizado": normalize_name(data.get("holder")),
            "entidade_id": _str_id(data.get("entityId")),
            "entidade": data.get("entity"),
            "orgao_id": _str_id(data.get("boardId")),
            "orgao": data.get("board"),
            "cargo_id": _str_id(data.get("roleId")),
            "cargo": data.get("role"),
            "nif_entidade": data.get("nif"),
            "natureza_codigo": data.get("natureType"),
            "natureza": NATUREZAS.get(data.get("natureType"), data.get("natureType")),
            "estado_codigo": data.get("stateType"),
            "estado": ESTADOS.get(data.get("stateType"), data.get("stateType")),
            "inicio": _iso_date(data.get("startDate")),
            "fim": _iso_date(data.get("endDate")),
            "entrega": _iso_date(data.get("submitedDate")),
            "relacionada_id": _str_id(data.get("relatedDeclarationId")),
            "secoes_inacessiveis": data.get("unavailableSections") or [],
        }
    )

    raiz = data.get("data") or {}
    secoes: List[Dict[str, Any]] = []
    if isinstance(raiz, dict):
        for no in raiz.get("value") or []:
            if not isinstance(no, dict):
                continue
            secao = _normaliza_secao(no)
            if secao:
                secoes.append(secao)

    interesses = _extrai_interesses(secoes)
    texto = _texto_das_secoes(secoes)

    documento = {
        **meta,
        "declaracao_id": declaracao_id,
        "doc_id": f"ept:{declaracao_id}",
        "secoes": secoes,
        "interesses": interesses,
        "tem_registo_interesses": bool(interesses),
        "texto": texto,
        "fonte": "entidade-transparencia",
        "fonte_url": BASE_WEB,
        "url_publica": f"{BASE_WEB}/#/consultardeclaracaopublica",
        "recolhido_em": recolhido_em or _agora(),
        "ingested_at": recolhido_em or _agora(),
        "raw": payload,
    }
    return documento


def _agora() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _normaliza_secao(no: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    chave = str(no.get("key") or "")
    if not chave:
        return None
    titulo = SECOES.get(chave) or SUBSECOES.get(chave)
    if titulo:
        return _bloco(chave, titulo, no.get("value"))
    # Nó sem rótulo conhecido: se só tem subsecções, sobe-se um nível para não
    # esconder dados atrás de um UUID.
    filhos = [filho for filho in (no.get("value") or []) if isinstance(filho, dict)]
    if filhos and _tipo_no(chave, filhos) == "grupo":
        blocos = [bloco for bloco in (_normaliza_secao(filho) for filho in filhos) if bloco]
        if len(blocos) == 1:
            return blocos[0]
        return {
            "chave": chave,
            "titulo": SUBSECOES.get(chave) or "Secção",
            "campos": [],
            "tabelas": [],
            "subsecoes": blocos,
        }
    return _bloco(chave, titulo or "Secção", no.get("value"))


def _tipo_no(chave: str, filhos: List[Dict[str, Any]]) -> str:
    if not filhos:
        return "vazio"
    if all(str(filho.get("key") or "").startswith(f"{chave}_") for filho in filhos):
        return "tabela"
    if all(not isinstance(filho.get("value"), list) or filho.get("value") is None for filho in filhos):
        return "campos"
    return "grupo"


def _bloco(chave: str, titulo: str, valor: Any) -> Dict[str, Any]:
    filhos = [filho for filho in (valor or []) if isinstance(filho, dict)] if isinstance(valor, list) else []
    tipo = _tipo_no(chave, filhos)
    bloco: Dict[str, Any] = {"chave": chave, "titulo": titulo, "campos": [], "tabelas": [], "subsecoes": []}
    if tipo == "campos":
        bloco["campos"] = [
            _campo(filho)
            for filho in filhos
            if _visivel(filho) and str(filho.get("key") or "") not in CAMPOS_IGNORAR
        ]
    elif tipo == "tabela":
        bloco["tabelas"] = [_tabela(chave, filhos)]
    elif tipo == "grupo":
        for filho in filhos:
            if SUBSECOES.get(str(filho.get("key") or "")):
                sub = _normaliza_secao(filho)
                if sub:
                    bloco["subsecoes"].append(sub)
            else:
                sub_tipo = _tipo_no(str(filho.get("key") or ""), [
                    item for item in (filho.get("value") or []) if isinstance(item, dict)
                ])
                if sub_tipo == "tabela":
                    bloco["tabelas"].append(_tabela(str(filho.get("key") or ""), [
                        item for item in (filho.get("value") or []) if isinstance(item, dict)
                    ]))
                elif sub_tipo == "campos":
                    bloco["campos"].extend(
                        _campo(item)
                        for item in (filho.get("value") or [])
                        if isinstance(item, dict)
                        and _visivel(item)
                        and str(item.get("key") or "") not in CAMPOS_IGNORAR
                    )
                else:
                    sub = _normaliza_secao(filho)
                    if sub:
                        bloco["subsecoes"].append(sub)
    elif isinstance(valor, (str, int, float)) and not isinstance(valor, bool):
        bloco["campos"] = [_campo({"key": chave, "value": valor})]
    return bloco


def _visivel(no: Dict[str, Any]) -> bool:
    return no.get("isVisible", True) is not False


def _campo(no: Dict[str, Any]) -> Dict[str, Any]:
    chave = str(no.get("key") or "")
    valor = no.get("value")
    if isinstance(valor, list):
        valor = None
    if valor == -1:  # sentinela de «não aplicável» da própria plataforma
        valor = None
    valor = _enum(valor, ENUMS_CAMPOS.get(chave))
    return {
        "chave": chave,
        "rotulo": CAMPOS.get(chave) or "",
        "valor": valor,
    }


def _tabela(chave: str, linhas: List[Dict[str, Any]]) -> Dict[str, Any]:
    nome = TABELAS.get(chave) or SUBSECOES.get(chave) or "Registos"
    rotulos = COLUNAS.get(chave) or {}
    registos: List[Dict[str, Any]] = []
    for linha in linhas:
        campos = [item for item in (linha.get("value") or []) if isinstance(item, dict)]
        registo: Dict[str, str] = {}
        for campo in campos:
            chave_col = str(campo.get("key") or "")
            coluna = f"col{chave_col.split('-col')[-1]}" if "-col" in chave_col else chave_col
            rotulo = rotulos.get(coluna) or f"Coluna {coluna}"
            valor = campo.get("value")
            if isinstance(valor, list):
                continue
            if valor in (None, ""):
                continue
            valor = _enum(valor, ENUMS_COLUNAS.get((chave, coluna)))
            registo[rotulo] = valor if isinstance(valor, str) else str(valor)
        if registo:
            registos.append(registo)
    return {"chave": chave, "nome": nome, "colunas": rotulos, "registos": registos, "total": len(registos)}


def _extrai_interesses(secoes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tabelas do «Registo de interesses» com os valores já rotulados."""
    interesses: List[Dict[str, Any]] = []
    for secao in secoes:
        if secao.get("chave") != "1483a8d1-adca-4f39-8038-98cc6f728fcb":
            for sub in secao.get("subsecoes") or []:
                interesses.extend(_extrai_interesses([sub]))
            continue
        for bloco in _percorre_blocos(secao):
            for tabela in bloco.get("tabelas") or []:
                for registo in tabela.get("registos") or []:
                    interesses.append({"tipo": tabela.get("nome"), "valores": registo})
    return interesses


def _percorre_blocos(bloco: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    yield bloco
    for sub in bloco.get("subsecoes") or []:
        yield from _percorre_blocos(sub)


def _texto_das_secoes(secoes: Iterable[Dict[str, Any]]) -> str:
    partes: List[str] = []
    for secao in secoes:
        partes.append(str(secao.get("titulo") or ""))
        for campo in secao.get("campos") or []:
            if campo.get("valor") not in (None, ""):
                partes.append(f"{campo.get('rotulo') or ''}: {campo.get('valor')}")
        for tabela in secao.get("tabelas") or []:
            partes.append(str(tabela.get("nome") or ""))
            for registo in tabela.get("registos") or []:
                partes.extend(f"{chave}: {valor}" for chave, valor in registo.items())
        partes.append(_texto_das_secoes(secao.get("subsecoes") or []))
    return "\n".join(parte for parte in partes if parte).strip()


# ---------------------------------------------------------------------------
# Normalização do catálogo / titularidades
# ---------------------------------------------------------------------------


def titular_document(
    titular_id: str,
    nome: str,
    declaracoes: Iterable[Dict[str, Any]],
    *,
    posicoes: Optional[Iterable[Dict[str, Any]]] = None,
    recolhido_em: Optional[str] = None,
) -> Dict[str, Any]:
    """Documento de índice de um titular, com o resumo das suas declarações."""
    declaracoes = list(declaracoes)
    anos = sorted({int(item.get("ano") or 0) for item in declaracoes if item.get("ano")})
    naturezas = sorted({str(item.get("natureza") or "") for item in declaracoes if item.get("natureza")})
    entidades: List[str] = []
    cargos: List[str] = []
    orgaos: List[str] = []
    for item in list(posicoes or []) + declaracoes:
        for chave, destino in (("entidade", entidades), ("cargo", cargos), ("orgao", orgaos)):
            valor = item.get(chave)
            if valor and valor not in destino:
                destino.append(str(valor))
    return {
        "titular_id": str(titular_id),
        "nome": nome,
        "nome_normalizado": normalize_name(nome),
        "declaracoes_total": len(declaracoes),
        "anos": anos,
        "naturezas": [natureza for natureza in naturezas if natureza],
        "entidades": entidades,
        "cargos": cargos,
        "orgaos": orgaos,
        "ultima_declaracao": max((item.get("entrega") or "" for item in declaracoes), default=None),
        "recolhido_em": recolhido_em or _agora(),
        "ingested_at": recolhido_em or _agora(),
        "fonte": "entidade-transparencia",
    }
