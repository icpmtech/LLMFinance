"""Rotas do módulo **MiroFish** (`/mirofish/*`) — simulações com dados do sistema.

O MiroFish é um motor de previsão por **enxame de agentes**: recebe material-semente
e um pedido de previsão, constrói um grafo de conhecimento (Zep), gera personas,
corre a simulação em duas plataformas paralelas e escreve um relatório.

Estas rotas ligam-no aos dados do IQ OS:

- `GET  /mirofish/meta`             — estado do serviço, fontes de dados e valores por omissão
- `GET  /mirofish/status`           — serviço + projetos/simulações já existentes no MiroFish
- `POST /mirofish/seed`             — compõe o documento-semente (Markdown) a partir de uma fonte
- `POST /mirofish/seed/office`      — o mesmo, guardado como documento do Office
- `POST /mirofish/simulations`      — arranca a simulação (projeto → grafo → personas → execução)
- `GET  /mirofish/jobs`             — trabalhos recentes
- `GET  /mirofish/jobs/{job_id}`    — progresso e registo de um trabalho

Todas exigem sessão: a semente contém dados de negócio (contratos, pessoas,
insolvências) e a simulação consome créditos do LLM/Zep configurados no MiroFish.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import mirofish_service as service
from api import mirofish_settings as settings_service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mirofish", tags=["mirofish"])

Session = Annotated[CurrentSession, Depends(require_session)]


class SeedPayload(BaseModel):
    """Fonte de dados e parâmetros do documento-semente."""

    source: str = Field(
        "sistema",
        description="Fonte: `empresa` (NIF), `tema` (Pesquisa 360), `noticias` (leitor RSS), "
        "`documento` (Office) ou `sistema` (panorama global)",
    )
    params: Dict[str, Any] = Field(default_factory=dict, description="Parâmetros da fonte escolhida")
    requirement: Optional[str] = Field(None, description="Pedido de previsão; vazio usa o sugerido pela fonte")


class SeedOfficePayload(SeedPayload):
    """Semente guardada como documento do Office."""

    title: Optional[str] = Field(None, description="Título do documento (por omissão o da semente)")
    folder_id: Optional[str] = Field(None, description="Pasta do Office onde guardar")
    tags: List[str] = Field(default_factory=list, description="Etiquetas do documento")


class SimulationPayload(SeedPayload):
    """Pedido de simulação completa no MiroFish."""

    title: Optional[str] = Field(None, description="Título curto do trabalho (para a listagem)")
    project_name: Optional[str] = Field(None, description="Nome do projeto dentro do MiroFish")
    max_rounds: Optional[int] = Field(None, ge=1, le=500, description="Rondas de simulação (cada ronda chama o LLM por agente)")
    platform: str = Field("parallel", pattern="^(parallel|twitter|reddit)$", description="Plataformas a simular")
    steps: Dict[str, bool] = Field(
        default_factory=dict,
        description="Passos a executar: `graph`, `prepare`, `run`, `report` (por omissão: grafo+preparação+execução)",
    )


class SettingsPayload(BaseModel):
    """Definições das chaves do MiroFish (as chaves em branco mantêm-se)."""

    llm_provider: Optional[str] = Field(None, description="Fornecedor da plataforma a usar como LLM (ex.: `deepseek`)")
    llm_model: Optional[str] = Field(None, description="Modelo a usar (vazio = o predefinido do fornecedor)")
    llm_base_url: Optional[str] = Field(None, description="Base URL da API compatível com OpenAI (vazio = a do fornecedor)")
    llm_api_key: Optional[str] = Field(None, description="Chave personalizada de LLM (alternativa a um fornecedor da plataforma)")
    zep_api_key: Optional[str] = Field(None, description="Chave do Zep Cloud (obrigatória para o MiroFish arrancar)")
    apply: bool = Field(False, description="Escrever já no `.env` e recriar o contentor do MiroFish")
    recreate: bool = Field(True, description="Ao aplicar, recriar o contentor (senão só escreve o `.env`)")


@router.get("/meta")
def meta(session: Session) -> Dict[str, Any]:
    """Estado do serviço e catálogo de fontes de dados do sistema."""
    return {
        "service": service.health(),
        "public_url": service.public_url(),
        "sources": service.SOURCES,
        "defaults": {
            "source": "sistema",
            "platform": "parallel",
            "steps": {"graph": True, "prepare": True, "run": True, "report": False},
        },
        "notes": [
            "O backend do MiroFish só arranca com `LLM_API_KEY` e `ZEP_API_KEY` definidas em `.env`.",
            "Cada ronda de simulação chama o LLM por agente — comece com poucas rondas e poucos agentes.",
        ],
    }


@router.get("/status")
def status(session: Session) -> Dict[str, Any]:
    """Estado do serviço e o que já existe lá dentro (projetos e simulações)."""
    info = service.health()
    if not info.get("available"):
        return {"service": info, "projects": [], "simulations": []}
    import httpx

    try:
        with httpx.Client(base_url=service.base_url(), timeout=60) as client:
            projects = service.list_projects(client)
            simulations = service.list_simulations(client)
    except Exception as exc:  # serviço a meio de um arranque, por exemplo
        return {"service": {**info, "available": False, "detail": f"{type(exc).__name__}: {exc}"}, "projects": [], "simulations": []}
    return {"service": info, "projects": projects[:20], "simulations": simulations[:20]}


@router.get("/settings")
def get_settings(session: Session) -> Dict[str, Any]:
    """Estado das chaves: fornecedores com chave na plataforma, `.env` e comandos.

    As chaves nunca são devolvidas — só máscaras (`sk-…4f2a`).
    """
    return settings_service.settings_view(getattr(session.user, "id", None))


@router.put("/settings")
async def put_settings(payload: SettingsPayload, session: Session) -> Dict[str, Any]:
    """Guarda as chaves e, a pedido, escreve o `.env` e recria o contentor."""
    user_id = getattr(session.user, "id", None)
    actor = getattr(session.user, "email", None) or getattr(session.user, "name", None)
    patch: Dict[str, Any] = {}
    if payload.llm_provider is not None:
        patch["llm_provider"] = str(payload.llm_provider).strip()
    if payload.llm_model is not None:
        patch["llm_model"] = str(payload.llm_model).strip()
    if payload.llm_base_url is not None:
        patch["llm_base_url"] = str(payload.llm_base_url).strip()
    if payload.llm_api_key is not None:
        patch["llm_custom_key"] = str(payload.llm_api_key).strip()
    if payload.zep_api_key is not None:
        patch["zep_api_key"] = str(payload.zep_api_key).strip()
    settings_service.save_settings(patch, actor=actor)
    view = settings_service.settings_view(user_id)
    if not payload.apply:
        return {"applied": None, "settings": view["settings"], "env": view["env"]}
    try:
        applied = await run_in_threadpool(settings_service.apply_settings, user_id, recreate=payload.recreate)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"applied": applied, **settings_service.settings_view(user_id)}


@router.post("/settings/apply")
async def apply_settings(session: Session, recreate: bool = Query(True)) -> Dict[str, Any]:
    """Escreve no `.env` as chaves guardadas e recria o contentor do MiroFish."""
    try:
        applied = await run_in_threadpool(settings_service.apply_settings, getattr(session.user, "id", None), recreate=recreate)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"applied": applied, **settings_service.settings_view(getattr(session.user, "id", None))}


@router.get("/diagnose")
def diagnose(session: Session) -> Dict[str, Any]:
    """Diagnóstico: serviço, chaves esperadas, comandos e último erro.

    Existe porque a falha típica (um `502` do MiroFish por causa de um 401 do
    fornecedor de LLM) não diz ao utilizador **que chave** lhe falta.
    """
    return service.diagnose()


@router.post("/seed")
async def build_seed(payload: SeedPayload, session: Session) -> Dict[str, Any]:
    """Compõe o documento-semente a partir dos dados do sistema (sem simular)."""
    try:
        return await service.build_seed(payload.source, payload.params, session=session)
    except service.MiroFishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/seed/office")
async def save_seed_to_office(payload: SeedOfficePayload, session: Session) -> Dict[str, Any]:
    """Guarda a semente como documento do Office (para rever, editar ou partilhar)."""
    try:
        seed = await service.build_seed(payload.source, payload.params, session=session)
    except service.MiroFishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _save() -> Dict[str, Any]:
        from api import office_store

        return office_store.save_document(
            {
                "title": payload.title or f"Semente MiroFish — {seed['title']}",
                "kind": "dossier",
                "markdown": seed["markdown"],
                "folder_id": payload.folder_id,
                "tags": list(payload.tags) + ["mirofish", "semente"],
                "source": "mirofish",
            },
            author=getattr(session.user, "email", None) or getattr(session.user, "name", None),
            force_new=True,
        )

    document = await run_in_threadpool(_save)
    return {"document": {key: document.get(key) for key in ("id", "title", "kind", "words", "updated_at")}, "seed": {key: seed[key] for key in ("source", "title", "chars", "words")}}


@router.post("/simulations")
async def start_simulation(payload: SimulationPayload, session: Session) -> Dict[str, Any]:
    """Arranca a simulação: semente → ontologia → grafo → personas → execução."""
    info = service.health()
    if not info.get("available"):
        raise HTTPException(
            status_code=503,
            detail=(
                f"MiroFish indisponível em {info.get('base_url')} ({info.get('detail') or 'sem resposta'}). "
                "Arranque o serviço (`docker compose --profile mirofish up -d`) e confirme as chaves "
                "MIROFISH_ZEP_API_KEY e MIROFISH_LLM_API_KEY no .env."
            ),
        )
    body = payload.model_dump()
    return service.start_simulation_job(body, session=session)


@router.get("/jobs")
def list_jobs(session: Session, limit: int = Query(10, ge=1, le=service.MAX_JOBS)) -> Dict[str, Any]:
    """Trabalhos de simulação recentes (mais recentes primeiro)."""
    return {"jobs": service.list_jobs(limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: Session) -> Dict[str, Any]:
    """Progresso e registo de um trabalho de simulação."""
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"trabalho não encontrado: {job_id}")
    return job


# ---------------------------------------------------------------------------
# Simulador IQ OS — resultados das simulações
#
# A página «Simulador IQ OS» serve-se daqui: catálogo de simulações, retrato de
# uma execução (rondas, ações, elenco, ontologia), relatório e entrevistas.
# ---------------------------------------------------------------------------
class InterviewPayload(BaseModel):
    """Entrevista a um agente do enxame (ou a todos)."""

    prompt: str = Field(..., min_length=3, description="Pergunta a colocar aos agentes")
    agent_id: Optional[int] = Field(None, description="Agente a entrevistar; vazio entrevista todos")
    platform: Optional[str] = Field(None, pattern="^(twitter|reddit)$", description="Plataforma (vazio = as duas)")
    timeout: int = Field(180, ge=10, le=900, description="Tempo máximo de espera da resposta, em segundos")


class ReportPayload(BaseModel):
    """Pedido de relatório da simulação."""

    force: bool = Field(False, description="Regenerar mesmo que já exista um relatório")


class ReportChatPayload(BaseModel):
    """Pergunta ao agente que escreveu o relatório."""

    message: str = Field(..., min_length=2, description="Pergunta em linguagem natural")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="Conversa anterior (`[{role, content}]`)")


class InterviewBatchPayload(BaseModel):
    """A mesma pergunta a vários agentes (o `interview/batch` do MiroFish)."""

    prompt: str = Field(..., min_length=3, description="Pergunta a colocar aos agentes")
    agents: List[Any] = Field(
        default_factory=list,
        min_length=1,
        description="Identificadores (`agent_id`) ou nomes dos agentes a entrevistar",
    )
    platform: Optional[str] = Field(None, pattern="^(twitter|reddit)$", description="Plataforma (vazio = as duas)")
    timeout: int = Field(300, ge=10, le=900, description="Tempo máximo de espera por resposta, em segundos")


class StartRunPayload(BaseModel):
    """Arranque ou reinício da execução de uma simulação já preparada."""

    max_rounds: Optional[int] = Field(None, ge=1, le=500, description="Rondas a simular (vazio = as da configuração)")
    platform: str = Field("parallel", pattern="^(parallel|twitter|reddit)$", description="Plataformas a simular")
    force: bool = Field(True, description="Reiniciar mesmo que já exista execução anterior")
    memory_update: bool = Field(False, description="Atualizar o grafo do Zep durante a execução (mais caro)")


class GraphSearchPayload(BaseModel):
    """Pesquisa no grafo de conhecimento da simulação."""

    query: str = Field(..., min_length=2, description="Pergunta a procurar nos factos do grafo")
    limit: int = Field(10, ge=1, le=50, description="Número de factos a devolver")


def _unavailable(detail: str) -> HTTPException:
    return HTTPException(status_code=503, detail=detail)


def _guard() -> Dict[str, Any]:
    """Serviço em baixo → 503 com o endereço e a razão (em vez de um erro confuso)."""
    info = service.health()
    if not info.get("available"):
        raise _unavailable(
            f"MiroFish indisponível em {info.get('base_url')} ({info.get('detail') or 'sem resposta'}). "
            "Arranque o serviço (`docker compose --profile mirofish up -d`) e confirme as chaves."
        )
    return info


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/runs")
def list_runs(session: Session, limit: int = Query(20, ge=1, le=60), enrich: int = Query(6, ge=0, le=20)) -> Dict[str, Any]:
    """Simulações conhecidas (MiroFish + trabalhos da plataforma que as lançaram)."""
    _guard()
    try:
        return service.runs(limit=limit, enrich=enrich)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}")
def run_overview(simulation_id: str, session: Session, actions: int = Query(30, ge=0, le=200)) -> Dict[str, Any]:
    """Retrato da execução: estado, rondas, ações, elenco, ontologia e relatório."""
    _guard()
    try:
        return service.run_overview(simulation_id, actions=actions)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}/actions")
def run_actions(
    simulation_id: str,
    session: Session,
    limit: int = Query(60, ge=1, le=300),
    offset: int = Query(0, ge=0),
    platform: Optional[str] = Query(None, pattern="^(twitter|reddit)$"),
    agent_id: Optional[int] = Query(None, ge=0),
    round_num: Optional[int] = Query(None, ge=0),
) -> Dict[str, Any]:
    """Feed de ações do enxame (publicações e comentários), com filtros."""
    _guard()
    try:
        return service.run_feed(
            simulation_id,
            limit=limit,
            offset=offset,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num,
        )
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}/agents")
def run_agents(simulation_id: str, session: Session) -> Dict[str, Any]:
    """Elenco: quem são os agentes, o que representam e quantas ações fizeram."""
    _guard()
    try:
        return service.run_cast(simulation_id)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}/graph")
def run_graph(
    simulation_id: str,
    session: Session,
    nodes: int = Query(150, ge=10, le=400, description="Nós a desenhar (os mais ligados)"),
    edges: int = Query(500, ge=10, le=2000, description="Factos a desenhar"),
) -> Dict[str, Any]:
    """Grafo de conhecimento (Zep): nós por tipo de entidade e factos entre eles."""
    _guard()
    try:
        return service.run_graph(simulation_id, max_nodes=nodes, max_edges=edges)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/stop")
def stop_run(simulation_id: str, session: Session) -> Dict[str, Any]:
    """Interrompe a execução (liberta o relatório com o que já foi simulado)."""
    _guard()
    try:
        return service.stop_run(simulation_id)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/interview")
def interview(simulation_id: str, payload: InterviewPayload, session: Session) -> Dict[str, Any]:
    """Pergunta aos agentes: «o que esperas que aconteça nos próximos meses?»."""
    _guard()
    try:
        return service.ask_agents(
            simulation_id,
            payload.prompt,
            agent_id=payload.agent_id,
            platform=payload.platform,
            timeout=payload.timeout,
        )
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


# ---------------------------------------------------------------------------
# Ações na simulação (o que o motor deixa fazer a meio e no fim)
#
# Espelham a página de interação do MiroFish: estado/fecho do ambiente,
# arrancar ou reiniciar a execução, entrevistar agentes em lote, ler as
# publicações e comentários do mundo simulado, seguir o registo do relatório e
# usar as ferramentas do grafo (pesquisa e estatísticas).
# ---------------------------------------------------------------------------
@router.get("/runs/{simulation_id}/environment")
def environment(simulation_id: str, session: Session) -> Dict[str, Any]:
    """Estado do ambiente: está vivo (aceita entrevistas)? Que plataformas respondem?"""
    _guard()
    try:
        return service.run_environment(simulation_id)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/environment/close")
def close_environment(simulation_id: str, session: Session, timeout: int = Query(30, ge=5, le=300)) -> Dict[str, Any]:
    """Fecha o ambiente da simulação (os dados ficam guardados)."""
    _guard()
    try:
        return service.close_environment(simulation_id, timeout=timeout)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/start")
def start_run(simulation_id: str, payload: StartRunPayload, session: Session) -> Dict[str, Any]:
    """Arranca (ou reinicia) a execução de uma simulação já preparada."""
    _guard()
    try:
        return service.restart_run(
            simulation_id,
            max_rounds=payload.max_rounds,
            platform=payload.platform,
            force=payload.force,
            memory_update=payload.memory_update,
        )
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/interview/batch")
async def interview_batch(simulation_id: str, payload: InterviewBatchPayload, session: Session) -> Dict[str, Any]:
    """Entrevista vários agentes de uma vez (uma pergunta, muitas respostas)."""
    _guard()
    try:
        return await run_in_threadpool(
            service.interview_many,
            simulation_id,
            payload.agents,
            payload.prompt,
            platform=payload.platform,
            timeout=payload.timeout,
        )
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}/posts")
def run_posts(
    simulation_id: str,
    session: Session,
    platform: Optional[str] = Query(None, pattern="^(twitter|reddit)$"),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Publicações do mundo simulado (por plataforma, paginadas)."""
    _guard()
    try:
        return service.run_posts(simulation_id, platform=platform, limit=limit, offset=offset)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}/comments")
def run_comments(
    simulation_id: str,
    session: Session,
    platform: Optional[str] = Query(None, pattern="^(twitter|reddit)$"),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Comentários do mundo simulado."""
    _guard()
    try:
        return service.run_comments(simulation_id, platform=platform, limit=limit, offset=offset)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}/report/logs")
def report_log(
    simulation_id: str,
    session: Session,
    kind: str = Query("console", pattern="^(console|agent)$"),
    from_line: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Registo do relatório (consola do motor ou ações do agente)."""
    _guard()
    try:
        return service.report_log(simulation_id, kind=kind, from_line=from_line)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/graph/search")
async def graph_search(simulation_id: str, payload: GraphSearchPayload, session: Session) -> Dict[str, Any]:
    """Pesquisa no grafo da simulação (a ferramenta que o agente de relatório usa)."""
    _guard()
    try:
        return await run_in_threadpool(service.search_in_graph, simulation_id, payload.query, limit=payload.limit)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.get("/runs/{simulation_id}/graph/statistics")
def graph_statistics(simulation_id: str, session: Session) -> Dict[str, Any]:
    """Estatísticas do grafo (nós, factos, tipos de entidade)."""
    _guard()
    try:
        return service.graph_stats(simulation_id)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc



@router.get("/runs/{simulation_id}/report")
def get_run_report(simulation_id: str, session: Session) -> Dict[str, Any]:
    """Estado do relatório (existe? em que ponto está?) sem o gerar."""
    _guard()
    try:
        return service.run_report(simulation_id)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/report")
async def generate_run_report(simulation_id: str, payload: ReportPayload, session: Session) -> Dict[str, Any]:
    """Pede o relatório ao MiroFish (a escrita é assíncrona lá dentro)."""
    _guard()
    try:
        return await run_in_threadpool(service.run_report, simulation_id, generate=True, force=payload.force)
    except service.MiroFishError as exc:
        raise _fail(exc) from exc


@router.post("/runs/{simulation_id}/report/chat")
async def chat_with_report(simulation_id: str, payload: ReportChatPayload, session: Session) -> Dict[str, Any]:
    """Conversa com o agente de relatório (responde a partir do grafo da simulação)."""
    _guard()
    try:
        return await run_in_threadpool(
            service.ask_report,
            simulation_id,
            payload.message,
            history=payload.history,
        )
    except service.MiroFishError as exc:
        raise _fail(exc) from exc
