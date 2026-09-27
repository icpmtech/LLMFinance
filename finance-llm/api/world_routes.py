"""Rotas do World Model (`/world/*`) — do dado público ao relatório de investigação.

Pipeline servido por este router (a mesma ordem do diagrama):

1. **Public Data** — `GET /world/sources` (fontes, índices e volumetria).
2. **World Model** — `POST /world/rebuild` (estado + eventos + relações),
   `GET /world/status`, `GET /world/entities`, `GET /world/entities/{ref}`,
   `GET /world/events`, `GET /world/relations`.
3. **Dynamic Neural Network** — `POST /world/network/train`, `GET /world/network`,
   `GET /world/network/graph` (a rede **como grafo**), `GET /world/network/history`,
   `GET /world/network/recall/{ref}`.
4. **Graph / Temporal Engine** — `GET /world/graph`, `GET /world/centrality`,
   `GET /world/paths`, `GET /world/temporal`, `GET /world/causality`.
5. **Future Simulator** — `POST /world/simulate`, `GET /world/simulations`.
6. **Investigation Agent** — `POST /world/investigate`, `GET /world/investigations`.

Leitura: pública. Escrita (reconstruir, treinar, simular, investigar, agendar):
exige sessão.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import world_agent as agent
from api import world_graph as graph
from api import world_investigation as investigation
from api import world_jobs as jobs
from api import world_model as model
from api import world_neural as neural
from api import world_scheduler as scheduler
from api import world_simulator as simulator
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/world", tags=["world"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ------------------------------------------------------------------ modelos
class RebuildRequest(BaseModel):
    """Parâmetros da reconstrução do mundo (amostras e tetos)."""

    entity_limit: Optional[int] = Field(None, ge=100, le=20000, description="Entidades por papel/país (teto da agregação)")
    contract_sample: Optional[int] = Field(None, ge=100, le=20000, description="Contratos lidos por país para relações e eventos")
    insolvency_sample: Optional[int] = Field(None, ge=0, le=20000, description="Processos CIRE na amostra")
    people_sample: Optional[int] = Field(None, ge=0, le=20000, description="Cargos (PessoasIQ) na amostra")
    year_from: Optional[int] = Field(None, ge=1900, le=2100, description="Ano mínimo dos contratos (omissão: todos)")
    delete_stale: Optional[bool] = Field(None, description="Apagar o estado de versões anteriores")
    wait: bool = Field(False, description="Esperar pelo fim e devolver o resumo (omissão: segundo plano com `job_id`)")


class TrainRequest(BaseModel):
    """Parâmetros do ciclo da rede dinâmica."""

    max_nodes: Optional[int] = Field(None, ge=20, le=5000, description="Nós máximos no ciclo")
    node_limit: Optional[int] = Field(None, ge=50, le=20000, description="Entidades candidatas lidas do mundo")
    edge_limit: Optional[int] = Field(None, ge=50, le=50000, description="Relações candidatas lidas do mundo")
    decay: Optional[float] = Field(None, gt=0, le=1, description="Decaimento do peso das arestas por ciclo")
    prune_threshold: Optional[float] = Field(None, ge=0, le=1, description="Limiar de poda das arestas")
    memory_size: Optional[int] = Field(None, ge=4, le=512, description="Padrões de memória (máximo)")
    memory_match: Optional[float] = Field(None, ge=0, le=1, description="Semelhança mínima para reutilizar um padrão")
    seed: Optional[int] = Field(None, description="Semente (reprodutibilidade)")
    wait: bool = Field(False, description="Esperar pelo fim (omissão: segundo plano)")


class SimulateRequest(BaseModel):
    """Parâmetros do simulador de futuro."""

    subject: Optional[str] = Field(None, description="Entidade (ref ou NIF); em falta simula o mundo inteiro")
    horizon: int = Field(4, ge=1, le=12, description="Número de passos (t0 → t{horizon})")
    step_months: int = Field(3, ge=1, le=12, description="Meses por passo")
    samples: int = Field(300, ge=20, le=2000, description="Amostras de Monte Carlo")
    seed: Optional[int] = Field(None, description="Semente (reprodutibilidade)")


class InvestigateRequest(BaseModel):
    """Pergunta para o agente de investigação."""

    question: str = Field(..., min_length=3, description="Pergunta em linguagem natural")
    subject: Optional[str] = Field(None, description="Entidade (ref ou NIF), se já se souber")
    horizon: int = Field(4, ge=1, le=12, description="Passos da simulação anexada")
    samples: int = Field(200, ge=20, le=2000, description="Amostras de Monte Carlo")
    simulate: bool = Field(True, description="Correr o simulador de futuro no ciclo")


class AgentRunRequest(BaseModel):
    """Execução do agente que decide a partir da rede neuronal."""

    question: str = Field(..., min_length=3, description="Pergunta em linguagem natural")
    subject: Optional[str] = Field(
        None,
        description="Entidade (ref ou NIF). Em falta, o agente usa a **anomalia mais alta** da rede como alvo.",
    )
    horizon: int = Field(4, ge=1, le=12, description="Passos da simulação")
    samples: int = Field(300, ge=20, le=2000, description="Amostras de Monte Carlo")
    simulate: bool = Field(True, description="Correr cenários no ciclo do agente")


class ScheduleRequest(BaseModel):
    """Agendamento (cron) da reconstrução do mundo."""

    enabled: Optional[bool] = Field(None, description="Ligar/desligar a reconstrução automática")
    cron: Optional[str] = Field(None, description="Cron de 5 campos (ex.: «0 4 * * *»)")
    timezone: Optional[str] = Field(None, description="Fuso horário (ex.: «Europe/Lisbon»)")
    train_network: Optional[bool] = Field(None, description="Correr também um ciclo da rede depois de reconstruir")


class ConfigRequest(BaseModel):
    """Configuração do módulo (parcial)."""

    entity_limit: Optional[int] = Field(None, ge=100, le=20000)
    contract_sample: Optional[int] = Field(None, ge=100, le=20000)
    insolvency_sample: Optional[int] = Field(None, ge=0, le=20000)
    people_sample: Optional[int] = Field(None, ge=0, le=20000)
    source_sample: Optional[int] = Field(None, ge=0, le=200000, description="Registos lidos por fonte adicional")
    year_from: Optional[int] = Field(None, ge=1900, le=2100)
    risk_medium: Optional[float] = Field(None, ge=0, le=1)
    risk_high: Optional[float] = Field(None, ge=0, le=1)
    delete_stale: Optional[bool] = None
    schedule_enabled: Optional[bool] = None
    schedule_cron: Optional[str] = None
    schedule_timezone: Optional[str] = None
    schedule_train_network: Optional[bool] = None
    sources: Optional[List[str]] = Field(None, description="Fontes do sistema associadas ao Public Data")


class SourcesRequest(BaseModel):
    """Fontes do sistema associadas à camada Public Data."""

    ids: List[str] = Field(default_factory=list, description="Ids do catálogo (`GET /world/sources`)")


# ------------------------------------------------------------------ metadados
@router.get("/meta")
def world_meta() -> Dict[str, Any]:
    """Metadados do módulo: índices, fontes públicas, tipos de evento, arquitetura e último rebuild."""
    return model.meta()


@router.get("/architecture")
def world_architecture() -> Dict[str, Any]:
    """O pipeline (Public Data → … → Investigation Agent) como dados, para o diagrama da UI."""
    return {"architecture": model.ARCHITECTURE}


@router.get("/pipeline/graph")
def world_pipeline_graph() -> Dict[str, Any]:
    """**Grafo de execução do pipeline**: camadas, artefactos, volumetria ao vivo e Mermaid."""
    return model.pipeline_graph()


@router.get("/sources")
def world_sources_availability() -> Dict[str, Any]:
    """**Fontes do sistema** que podem alimentar o Public Data: volumetria, junção e o que está associado."""
    return model.source_overview()


@router.put("/sources")
def world_sources_save(payload: SourcesRequest, session: Session = None) -> Dict[str, Any]:
    """Associa/desassocia fontes do sistema no Public Data (é preciso reconstruir para aplicar)."""
    result = model.save_sources(payload.ids)
    # Uma só leitura do catálogo: a resposta já traz o estado gravado.
    overview = model.source_overview()
    overview["unknown"] = result["unknown"]
    return overview


@router.get("/status")
def world_status() -> Dict[str, Any]:
    """Volumetria e distribuições do estado, eventos e relações; configuração e último rebuild."""
    return model.status()


@router.get("/schedule")
def world_schedule() -> Dict[str, Any]:
    """Agendamento cron da reconstrução (estado e próxima execução)."""
    return scheduler.schedule()


# ------------------------------------------------------------------ jobs
@router.get("/jobs")
def world_jobs_list() -> Dict[str, Any]:
    """Execuções em curso e recentes (reconstrução e treino da rede)."""
    return {"jobs": jobs.list_jobs()}


@router.get("/jobs/{job_id}")
def world_job(job_id: str) -> Dict[str, Any]:
    """Estado de uma execução."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return job


# ------------------------------------------------------------------ world model
@router.post("/rebuild")
def world_rebuild(payload: RebuildRequest = RebuildRequest(), session: Session = None) -> Dict[str, Any]:
    """Reconstrói o mundo a partir dos dados públicos (estado + eventos + relações)."""
    params = {k: v for k, v in payload.model_dump(exclude={"wait"}).items() if v is not None}
    if payload.wait:
        try:
            return model.rebuild(params=params)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)[:400]) from exc
    job = jobs.submit("rebuild", model.rebuild, params)
    return {"job_id": job["job_id"], "status": job["status"], "job": job}


@router.get("/entities")
def world_entities(
    q: Optional[str] = Query(None, description="Designação, NIF/NIPC"),
    type: Optional[str] = Query(None, description="Tipo: empresa, entidade_publica, pessoa"),
    country: Optional[str] = Query(None, description="País"),
    risk: Optional[str] = Query(None, description="Risco: baixo, médio, elevado"),
    role: Optional[str] = Query(None, description="Papel: adjudicante, adjudicatario, insolvente, …"),
    insolvent: Optional[bool] = Query(None, description="Só entidades com insolvência"),
    sort: str = Query("relevance", description="Ordenação: relevance, value, contracts, risk, activity, relations, recent, name"),
    size: int = Query(20, ge=1, le=200),
    page: int = Query(1, ge=1),
) -> Dict[str, Any]:
    """Pesquisa entidades do mundo (estado materializado)."""
    return model.search_entities(
        q=q,
        entity_type=type,
        country=country,
        risk_label=risk,
        role=role,
        insolvent=insolvent,
        sort=sort,
        size=size,
        from_=(page - 1) * size,
    )


@router.get("/entities/{entity_ref}")
def world_entity(entity_ref: str) -> Dict[str, Any]:
    """Ficha de uma entidade do mundo (por `entity:<nif>`, NIF/NIPC ou id)."""
    entity = model.get_entity(entity_ref)
    if not entity:
        raise HTTPException(status_code=404, detail="Entidade não encontrada no World Model")
    return {
        "entity": entity,
        "prediction": neural.node_prediction(entity.get("entity_ref")),
        "relations": model.relations(entity_ref=entity.get("entity_ref"), size=30).get("relations", []),
        "timeline": model.timeline(entity_ref=entity.get("entity_ref"), size=30).get("events", []),
    }


@router.get("/entities/{entity_ref}/timeline")
def world_entity_timeline(
    entity_ref: str,
    kind: Optional[str] = Query(None, description="Tipos de evento (separados por vírgula)"),
    size: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Linha temporal de uma entidade."""
    return model.timeline(entity_ref=entity_ref, kind=kind, size=size)


@router.get("/events")
def world_events(
    entity_ref: Optional[str] = Query(None, description="Filtra por entidade"),
    kind: Optional[str] = Query(None, description="Tipos de evento (separados por vírgula)"),
    year_from: Optional[int] = Query(None, description="Ano mínimo"),
    year_to: Optional[int] = Query(None, description="Ano máximo"),
    size: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Eventos do mundo (mais recentes primeiro)."""
    return model.timeline(entity_ref=entity_ref, kind=kind, year_from=year_from, year_to=year_to, size=size)


@router.get("/events/stats")
def world_events_stats() -> Dict[str, Any]:
    """Distribuições de eventos (tipo, ano, severidade)."""
    return model.event_stats()


@router.get("/relations")
def world_relations(
    entity_ref: Optional[str] = Query(None, description="Filtra por entidade"),
    kind: Optional[str] = Query(None, description="Tipo de relação: adjudicou, cargo_em"),
    size: int = Query(100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Relações do grafo (arestas)."""
    return model.relations(entity_ref=entity_ref, kind=kind, size=size)


@router.get("/relations/stats")
def world_relations_stats() -> Dict[str, Any]:
    """Distribuições de relações e valor agregado."""
    return model.relation_stats()


# ------------------------------------------------------------------ estado temporal
@router.get("/history/series")
def world_history_series(
    grain: str = Query("quarter", description="Granularidade: quarter, month ou year"),
    limit: int = Query(40, ge=1, le=200, description="Períodos mais recentes a devolver"),
) -> Dict[str, Any]:
    """Série agregada do mundo por período (contratos, valor, contrapartes novas)."""
    return model.history_series(grain=grain, limit=limit)


@router.get("/history")
def world_history(
    grain: Optional[str] = Query(None, description="Filtra por granularidade"),
    limit: int = Query(200, ge=1, le=2000),
) -> Dict[str, Any]:
    """Estado temporal (documentos por entidade e período)."""
    return model.history(grain=grain, limit=limit)


@router.get("/history/{entity_ref}")
def world_entity_history(
    entity_ref: str,
    grain: Optional[str] = Query(None, description="Granularidade"),
    limit: int = Query(60, ge=1, le=500),
) -> Dict[str, Any]:
    """Série temporal de uma entidade (o «como chegou a este estado»)."""
    return model.history(entity_ref=entity_ref, grain=grain, limit=limit)


# ------------------------------------------------------------------ grafo / tempo
@router.get("/graph/dimensions")
def world_graph_dimensions() -> Dict[str, Any]:
    """Dimensões disponíveis para construir grafos."""
    return {"dimensions": graph.GRAPH_DIMENSIONS}


@router.get("/graph")
def world_graph_build(
    entity_ref: Optional[str] = Query(None, description="Centro do grafo (ego-rede); em falta usa as mais centrais"),
    depth: int = Query(1, ge=1, le=4, description="Níveis de expansão"),
    kind: Optional[str] = Query(None, description="Tipo de relação: adjudicou, cargo_em"),
    nodes: int = Query(120, ge=2, le=400, description="Nós máximos"),
    edges: int = Query(400, ge=1, le=2000, description="Arestas máximas"),
) -> Dict[str, Any]:
    """Subgrafo do mundo (nós e arestas prontos a desenhar)."""
    return graph.build_graph(entity_ref=entity_ref, depth=depth, kind=kind, node_limit=nodes, edge_limit=edges)


@router.get("/centrality")
def world_centrality(kind: Optional[str] = Query(None), top: int = Query(20, ge=1, le=200)) -> Dict[str, Any]:
    """Entidades mais centrais no grafo (por grau)."""
    return graph.centrality(kind=kind, top=top)


@router.get("/paths")
def world_paths(
    source: str = Query(..., description="Entidade de origem (ref ou NIF)"),
    target: str = Query(..., description="Entidade de destino (ref ou NIF)"),
    max_depth: int = Query(4, ge=1, le=6, description="Profundidade máxima do BFS"),
    kind: Optional[str] = Query(None, description="Tipo de relação"),
) -> Dict[str, Any]:
    """Caminhos mais curtos entre duas entidades no grafo de relações."""
    return graph.paths(source=source, target=target, max_depth=max_depth, kind=kind)


@router.get("/temporal")
def world_temporal(
    entity_ref: Optional[str] = Query(None, description="Série de uma entidade"),
    kind: Optional[str] = Query(None, description="Tipos de evento"),
    years: int = Query(8, ge=1, le=30, description="Janela em anos"),
    interval: str = Query("month", description="Intervalo: month ou year"),
) -> Dict[str, Any]:
    """Série temporal de eventos e valores."""
    return graph.temporal_profile(entity_ref=entity_ref, kind=kind, years=years, interval=interval)


@router.get("/causality")
def world_causality(
    entity_ref: Optional[str] = Query(None, description="Limita a uma entidade"),
    window_days: int = Query(45, ge=1, le=365, description="Janela máxima entre eventos (dias)"),
    limit: int = Query(60, ge=1, le=500, description="Ligações devolvidas"),
) -> Dict[str, Any]:
    """Influências temporais candidatas entre eventos de entidades ligadas."""
    return graph.causality(entity_ref=entity_ref, window_days=window_days, limit=limit)


# ------------------------------------------------------------------ rede dinâmica
@router.post("/network/train")
def world_network_train(payload: TrainRequest = TrainRequest(), session: Session = None) -> Dict[str, Any]:
    """Corre um ciclo da rede dinâmica (crescimento, poda, memória e previsão)."""
    params = {k: v for k, v in payload.model_dump(exclude={"wait"}).items() if v is not None}
    if payload.wait:
        try:
            return neural.train(params=params)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)[:400]) from exc
    job = jobs.submit("network", neural.train, params)
    return {"job_id": job["job_id"], "status": job["status"], "job": job}


@router.get("/network")
def world_network(version: Optional[int] = Query(None, description="Versão do ciclo (omissão: o mais recente)")) -> Dict[str, Any]:
    """Estado da rede dinâmica (nós, arestas, memória, métricas e previsões)."""
    state = neural.state(version=version)
    if not state:
        return {"trained": False, "message": "A rede ainda não foi treinada (POST /world/network/train)."}
    return state


@router.get("/network/graph")
def world_network_graph(
    limit: int = Query(90, ge=10, le=200, description="Nós (entidades) no grafo"),
    memory: bool = Query(True, description="Incluir os padrões de memória como nós"),
    entity_ref: Optional[str] = Query(None, description="Ego-rede de uma entidade"),
    version: Optional[int] = Query(None, description="Versão do ciclo"),
) -> Dict[str, Any]:
    """A rede dinâmica como grafo: nós (entidades/padrões) e arestas (relações/sinapses)."""
    return neural.network_graph(limit=limit, include_memory=memory, entity_ref=entity_ref, version=version)


@router.get("/network/history")
def world_network_history(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Histórico de ciclos da rede (métricas por versão)."""
    return {"history": neural.history(limit=limit)}


@router.get("/network/recall/{entity_ref}")
def world_network_recall(entity_ref: str) -> Dict[str, Any]:
    """Padrões de memória mais próximos das features de uma entidade."""
    return neural.recall(entity_ref)


@router.get("/network/anomalies")
def world_network_anomalies(
    limit: int = Query(60, ge=1, le=200),
    entity_ref: Optional[str] = Query(None, description="Filtra por entidade"),
) -> Dict[str, Any]:
    """Anomalias detetadas pela rede (padrões face ao histórico próprio de cada entidade)."""
    return neural.anomalies(limit=limit, entity_ref=entity_ref)


@router.get("/network/transition")
def world_network_transition() -> Dict[str, Any]:
    """Modelo de transição latente `z_t → z_{t+1}` da última versão da rede."""
    return neural.transition()


@router.get("/network/transition/{entity_ref}")
def world_network_transition_entity(
    entity_ref: str,
    steps: int = Query(4, ge=1, le=24),
) -> Dict[str, Any]:
    """Trajetória projetada de uma entidade pela transição ajustada.

    Não ter histórico **não é erro**: a maioria das entidades tem poucos períodos.
    Devolve-se 200 com `available: false` e o motivo, para a página mostrar a
    ausência de trajetória sem a tratar como falha (404 enchia a consola).
    """
    forecast = neural.transition_forecast(entity_ref, steps=steps)
    if not forecast:
        return {
            "available": False,
            "entity_ref": entity_ref,
            "steps": [],
            "reason": "Sem transição ajustada ou sem histórico suficiente para esta entidade.",
        }
    return {"available": True, **forecast}


# ------------------------------------------------------------------ simulador
@router.post("/simulate")
def world_simulate(payload: SimulateRequest = SimulateRequest(), session: Session = None) -> Dict[str, Any]:
    """Simula o futuro (t0 → t{horizon}) para uma entidade ou para o mundo inteiro."""
    try:
        return simulator.run(
            subject=payload.subject,
            params={
                "horizon": payload.horizon,
                "step_months": payload.step_months,
                "samples": payload.samples,
                **({"seed": payload.seed} if payload.seed is not None else {}),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)[:400]) from exc


@router.get("/simulations")
def world_simulations(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Últimas simulações."""
    return {"simulations": simulator.list_runs(limit=limit)}


@router.get("/simulations/{run_id}")
def world_simulation(run_id: str) -> Dict[str, Any]:
    """Uma simulação completa (passos, cenários e distribuições)."""
    run = simulator.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulação não encontrada")
    return run


# ------------------------------------------------------------------ investigação
@router.post("/investigate")
def world_investigate(payload: InvestigateRequest, session: Session = None) -> Dict[str, Any]:
    """Corre o agente: Observe → Hypothesize → Search → Validate → Simulate → Report."""
    try:
        return investigation.investigate(
            payload.question,
            subject=payload.subject,
            params={"horizon": payload.horizon, "samples": payload.samples},
            simulate=payload.simulate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)[:400]) from exc


@router.get("/investigations")
def world_investigations(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Últimas investigações (resumo)."""
    return {"investigations": investigation.list_runs(limit=limit)}


@router.get("/investigations/{run_id}")
def world_investigation(run_id: str) -> Dict[str, Any]:
    """Uma investigação completa (passos, hipóteses, evidência, validação e relatório)."""
    run = investigation.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Investigação não encontrada")
    return run


# ------------------------------------------------------------------ AGENTE
@router.get("/agent/catalog")
def world_agent_catalog() -> Dict[str, Any]:
    """Roster de agentes e fluxo de dados entre eles (com Mermaid)."""
    return agent.catalog()


@router.get("/agent/targets")
def world_agent_targets(limit: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
    """Alvos que a **rede** sugere investigar (anomalias por ordem de score)."""
    return agent.network_targets(limit=limit)


@router.post("/agent/run")
def world_agent_run(payload: AgentRunRequest, session: Session = None) -> Dict[str, Any]:
    """Corre o agente sobre a rede: plano dinâmico, evidência, cenários e três grafos."""
    try:
        return agent.run(
            payload.question,
            subject=payload.subject,
            params={"horizon": payload.horizon, "samples": payload.samples},
            simulate=payload.simulate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)[:400]) from exc


@router.get("/agent/runs")
def world_agent_runs(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Últimas execuções do agente (resumo)."""
    return {"runs": agent.list_runs(limit=limit)}


@router.get("/agent/runs/{run_id}")
def world_agent_run_detail(run_id: str) -> Dict[str, Any]:
    """Execução completa: passos, grafos (execução/evidências/relações), relatório."""
    run = agent.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return run


# ------------------------------------------------------------------ configuração
@router.put("/config")
def world_config(payload: ConfigRequest, session: Session = None) -> Dict[str, Any]:
    """Atualiza a configuração do módulo (parcial)."""
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    config = model.save_config(patch)
    if any(key.startswith("schedule_") for key in patch):
        scheduler.reload_jobs()
    return {"config": config, "schedule": scheduler.status()}


@router.put("/schedule")
def world_schedule_update(payload: ScheduleRequest, session: Session = None) -> Dict[str, Any]:
    """Liga/desliga e define o cron da reconstrução automática do mundo."""
    patch: Dict[str, Any] = {}
    if payload.enabled is not None:
        patch["schedule_enabled"] = payload.enabled
    if payload.cron is not None:
        patch["schedule_cron"] = payload.cron
    if payload.timezone is not None:
        patch["schedule_timezone"] = payload.timezone
    if payload.train_network is not None:
        patch["schedule_train_network"] = payload.train_network
    model.save_config(patch)
    return scheduler.reload_jobs()


@router.get("/config")
def world_config_get() -> Dict[str, Any]:
    """Configuração atual do módulo."""
    return {"config": model.load_config()}
