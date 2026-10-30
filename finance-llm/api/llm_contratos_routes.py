"""Rotas do **modelo de contratos** (`/llm/modelo/*`).

O modelo é o resultado do fine-tuning LoRA descrito em
`docs/modelo-contratos.md`: `Qwen/Qwen2.5-0.5B-Instruct` afinado com pares
extraídos dos índices `contratos`, `finance_entities` e `finance_subvencoes`.

Além do modelo, o router expõe a **memória** que o rodeia
(`api/llm_contratos_agente.py`): memórias, skills, prompts de sistema, corpus
RAG, feedback e a adaptação incremental que transforma feedback em pesos
(`api/llm_contratos_treino.py`).

Leitura é pública (ficha, matriz de pesos, catálogo de skills). Gerar uma
resposta, escrever memória/skills, dar feedback ou retreinar exige sessão.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import llm_contratos_agente as agente
from api import llm_contratos_service as service
from api import llm_contratos_soup as soup
from api import llm_contratos_treino as treino
from api.auth_routes import CurrentSession, require_session, session_from_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm/modelo", tags=["llm"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ---------------------------------------------------------------------------
# Modelos de pedido/resposta
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    instrucao: str = Field(
        ...,
        min_length=3,
        max_length=600,
        description="O que se quer saber, ex.: «Descreve este contrato público português.»",
    )
    dados: str = Field("", max_length=6000, description="O documento (campos do Elasticsearch)")
    max_tokens: int = Field(160, ge=16, le=400)
    temperatura: float = Field(0.2, ge=0.0, le=1.5)
    prompt_id: Optional[str] = Field(None, description="Prompt de sistema guardado (ex.: `auditar`)")
    sistema: Optional[str] = Field(None, max_length=6000, description="Prompt de sistema explícito (ganha ao id)")
    usar_rag: bool = Field(True, description="Recuperar evidências do corpus RAG")
    usar_memoria: bool = Field(True, description="Incluir memórias e skills aprendidas")
    usar_skills: bool = Field(True, description="Executar skills (consultas ao Elasticsearch)")
    raciocinio: bool = Field(True, description="Traço de raciocínio e verificação dos números")
    adaptador: Optional[str] = Field(
        None,
        max_length=120,
        description="Adaptador LoRA a usar (`qwen05-contratos`, `soup-*`); vazio usa o da plataforma",
    )


class PassoResposta(BaseModel):
    fase: str
    titulo: str
    detalhe: str = ""
    dados: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    resposta: str
    modelo: str
    adaptador: Optional[str] = None
    adaptador_escolhido: Optional[str] = None
    prompt_tokens: int = 0
    tokens_gerados: int = 0
    tokens: List[Dict[str, Any]] = Field(default_factory=list)
    confianca_media: Optional[float] = None
    verificacao: Dict[str, Any] = Field(default_factory=dict)
    passos: List[PassoResposta] = Field(default_factory=list)
    evidencias: List[Dict[str, Any]] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    prompt_sistema: str = ""
    duracao_s: float = 0.0


class MemoriaRequest(BaseModel):
    tipo: Literal["memoria", "skill"] = "memoria"
    titulo: str = Field(..., min_length=2, max_length=200)
    instrucao: str = ""
    dados: str = ""
    resposta: str = ""
    gatilhos: List[str] = Field(default_factory=list)


class PromptRequest(BaseModel):
    prompt_id: str = Field("", max_length=60)
    nome: str = Field(..., min_length=2, max_length=120)
    texto: str = Field(..., min_length=10, max_length=6000)


class FeedbackRequest(BaseModel):
    instrucao: str = Field(..., min_length=3, max_length=600)
    dados: str = ""
    resposta: str = ""
    correcao: str = ""
    nota: int = Field(0, ge=-1, le=1, description="-1 mau, 0 neutro, 1 bom")
    skills: List[str] = Field(default_factory=list)
    usou_rag: bool = False
    raciocinio: bool = False


class AvaliarRequest(BaseModel):
    limite: int = Field(8, ge=1, le=40, description="Pares held-out a medir")
    gerar: int = Field(2, ge=0, le=6, description="Respostas geradas para medir fidelidade")
    holdout: int = Field(60, ge=0, le=2000)
    seed: int = 42
    adaptador: Optional[str] = Field(
        None, max_length=120, description="Adaptador a avaliar (por omissão, o da plataforma)"
    )


class RagRequest(BaseModel):
    max_por_fonte: int = Field(200, ge=1, le=2000)
    fontes: Optional[List[str]] = None


class RetreinarRequest(BaseModel):
    passos: int = Field(12, ge=1, le=40)
    lr: float = Field(5e-5, gt=0, le=1e-3)
    reutilizar_existentes: bool = Field(
        False,
        description="Contar também pares já usados numa adaptação anterior (repetir o treino).",
    )


class ReverterRequest(BaseModel):
    versao: str = Field(
        ...,
        min_length=10,
        max_length=120,
        description="Nome do ficheiro de backup, ex.: `adapter_model.safetensors.bak-20261027-233744`.",
    )


# ---------------------------------------------------------------------------
# Ficha, diagramas e avaliação
# ---------------------------------------------------------------------------


@router.get("", summary="Ficha do modelo de contratos")
def estado_do_modelo() -> Dict[str, Any]:
    """Adaptador, metadados do treino e curva de perda (últimos passos)."""
    return service.model_state()


@router.get("/metricas", summary="Curva de perda do treino")
def metricas(limite: int = Query(200, ge=1, le=2000)) -> Dict[str, Any]:
    """Pontos de `metrics.jsonl` — a mesma curva que a página desenha."""
    pontos: List[Dict[str, Any]] = service.read_metrics(limit=limite)
    return {"pontos": pontos, "total": len(pontos)}


@router.get("/matriz", summary="Matriz de pesos do adaptador (24 camadas × 7 projecções)")
def matriz() -> Dict[str, Any]:
    """Magnitude real de cada actualização LoRA, lida do `adapter_model.safetensors`."""
    return service.matriz_adaptador()


@router.get("/matriz/{camada}/{modulo}", summary="Recorte das matrizes A e B de uma camada")
def matriz_detalhe(camada: int, modulo: str) -> Dict[str, Any]:
    """Pesos reais (A e B) de uma projecção — o que a matriz da página amplia."""
    dados = service.amostra_de_pesos(camada, modulo)
    if dados.get("erro"):
        raise HTTPException(status_code=404, detail=dados["erro"])
    return dados


@router.get("/ligacoes", summary="Proveniência: índices → dataset → treino → adaptador")
def ligacoes() -> Dict[str, Any]:
    """Contagem de pares por fonte e ligação ao treino e ao adaptador."""
    return service.ligacoes()


# ---------------------------------------------------------------------------
# Chat com memória, skills, RAG e raciocínio
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse, summary="Resposta do modelo (com traço)")
async def chat(req: ChatRequest, session: Session) -> ChatResponse:  # noqa: ARG001
    """Gera a resposta em CPU (segundos) — corre fora do event loop."""
    try:
        resultado = await run_in_threadpool(
            service.responder,
            instrucao=req.instrucao,
            dados=req.dados,
            prompt_id=req.prompt_id,
            sistema=req.sistema,
            usar_rag=req.usar_rag,
            usar_memoria=req.usar_memoria,
            usar_skills=req.usar_skills,
            raciocinio=req.raciocinio,
            max_new_tokens=req.max_tokens,
            temperatura=req.temperatura,
            adaptador=req.adaptador,
        )
    except Exception as error:  # pragma: no cover - depende do modelo em disco
        logger.exception("Falha ao gerar resposta com o modelo de contratos")
        raise HTTPException(status_code=503, detail=f"Modelo indisponível: {error}") from error
    return ChatResponse(**resultado)


@router.get("/adaptadores", summary="Adaptadores LoRA treinados disponíveis")
def listar_adaptadores() -> Dict[str, Any]:
    """Modelos treinados que o chat pode usar (plataforma e Soup).

    Leitura pública, como a ficha: a lista mostra o que existe em `model/` sem
    expor caminhos arbitrários — o `id` é o que o `/chat` aceita em `adaptador`.
    """
    from inference import contratos_lora

    itens = contratos_lora.listar_adaptadores()
    return {"adaptadores": itens, "total": len(itens)}


@router.post("/avaliar", summary="Correr a avaliação base vs adaptador")
async def avaliar(req: AvaliarRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Mede o held-out e guarda o resultado em `finance_llm_model_evals`."""
    try:
        return await run_in_threadpool(service.avaliar, req.limite, req.gerar, req.holdout, req.seed, req.adaptador)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # pragma: no cover - depende do modelo em disco
        logger.exception("Falha na avaliação do modelo de contratos")
        raise HTTPException(status_code=503, detail=f"Avaliação indisponível: {error}") from error


@router.get("/avaliacoes", summary="Histórico de avaliações")
def avaliacoes(size: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Últimas avaliações guardadas no Elasticsearch (vazio se o cluster faltar)."""
    docs = service.list_evals(size=size)
    return {"avaliacoes": docs, "total": len(docs)}


# ---------------------------------------------------------------------------
# Memória, skills e prompts
# ---------------------------------------------------------------------------


@router.get("/memoria", summary="Listar memórias e skills")
def listar_memoria(
    tipo: Optional[Literal["memoria", "skill"]] = Query(None),
    size: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    docs = agente.listar_memorias(tipo=tipo, size=size)
    return {"itens": docs, "total": len(docs)}


@router.post("/memoria", summary="Guardar memória ou skill")
def criar_memoria(req: MemoriaRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Guarda um facto (`memoria`) ou uma skill aprendida (`skill`).

    A skill entra imediatamente no prompt das respostas seguintes e, com
    `dados`+`resposta`, também nos pares de treino da adaptação incremental.
    """
    try:
        doc_id = agente.guardar_memoria(
            tipo=req.tipo,
            titulo=req.titulo,
            instrucao=req.instrucao,
            dados=req.dados,
            resposta=req.resposta,
            gatilhos=req.gatilhos,
            origem="utilizador",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not doc_id:
        raise HTTPException(status_code=503, detail="Elasticsearch indisponível: memória não guardada")
    return {"id": doc_id, "ok": True}


@router.delete("/memoria/{doc_id}", summary="Apagar memória ou skill")
def apagar_memoria(doc_id: str, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    if not agente.apagar_memoria(doc_id):
        raise HTTPException(status_code=404, detail="Memória não encontrada")
    return {"ok": True}


@router.get("/skills", summary="Skills executáveis disponíveis")
def skills() -> Dict[str, Any]:
    """Catálogo das skills que consultam o Elasticsearch (nome, descrição, gatilhos)."""
    itens = agente.skills_disponiveis()
    return {"skills": itens, "total": len(itens)}


@router.get("/prompts", summary="Prompts de sistema")
def prompts() -> Dict[str, Any]:
    itens = agente.listar_prompts()
    return {"prompts": itens, "total": len(itens)}


@router.post("/prompts", summary="Guardar prompt de sistema")
def guardar_prompt(req: PromptRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    try:
        doc_id = agente.guardar_prompt(prompt_id=req.prompt_id, nome=req.nome, texto=req.texto)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not doc_id:
        raise HTTPException(status_code=503, detail="Elasticsearch indisponível: prompt não guardado")
    return {"id": doc_id, "ok": True}


@router.delete("/prompts/{prompt_id}", summary="Apagar prompt de sistema")
def apagar_prompt(prompt_id: str, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    if not agente.apagar_prompt(prompt_id):
        raise HTTPException(status_code=404, detail="Prompt não encontrado")
    return {"ok": True}


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------


@router.get("/rag", summary="Estado do corpus RAG")
def estado_rag() -> Dict[str, Any]:
    return agente.estado_rag()


@router.post("/rag", summary="Indexar o corpus RAG a partir dos índices")
async def indexar_rag(req: RagRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Percorre contratos, entidades e subsídios e escreve pedaços pesquisáveis."""
    try:
        return await run_in_threadpool(agente.indexar_rag, req.max_por_fonte, req.fontes)
    except Exception as error:  # pragma: no cover - depende do cluster
        logger.exception("Falha ao indexar o RAG")
        raise HTTPException(status_code=503, detail=f"RAG indisponível: {error}") from error


@router.get("/rag/pesquisa", summary="Pesquisar no corpus RAG")
def pesquisar_rag(
    q: str = Query(..., min_length=2),
    k: int = Query(5, ge=1, le=20),
) -> Dict[str, Any]:
    itens = agente.recuperar_rag(q, k=k)
    return {"itens": itens, "total": len(itens)}


# ---------------------------------------------------------------------------
# Feedback e adaptação incremental (auto-aprendizagem)
# ---------------------------------------------------------------------------


@router.get("/feedback", summary="Estatísticas do feedback")
def feedback_stats() -> Dict[str, Any]:
    return agente.estatisticas_feedback()


@router.post("/feedback", summary="Avaliar uma resposta (e corrigi-la)")
def enviar_feedback(req: FeedbackRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Guarda a avaliação. Com `correcao`, cria matéria-prima para o retreino."""
    doc_id = agente.guardar_feedback(
        instrucao=req.instrucao,
        dados=req.dados,
        resposta=req.resposta,
        correcao=req.correcao,
        nota=req.nota,
        skill=req.skills,
        usou_rag=req.usou_rag,
        raciocinio=req.raciocinio,
    )
    if not doc_id:
        raise HTTPException(status_code=503, detail="Elasticsearch indisponível: feedback não guardado")
    return {"id": doc_id, "ok": True, "pares_de_treino": agente.estatisticas_feedback()["por_utilizar"]}


@router.get("/retreinar", summary="Estado da adaptação incremental")
def estado_retreino() -> Dict[str, Any]:
    estado = treino.estado_adaptacao()
    estado["feedback"] = agente.estatisticas_feedback()
    return estado


@router.post("/retreinar", summary="Adaptar o modelo com o feedback acumulado")
def retreinar(req: RetreinarRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Arranca a adaptação LoRA em segundo plano (a rota responde já).

    Só corre com pelo menos 3 pares (correções ou skills com exemplo); é esse o
    mínimo que evita mover o modelo por causa de uma frase. Com
    `reutilizar_existentes=true` também conta pares já usados numa adaptação
    anterior — útil para repetir o treino sem esperar por feedback novo.
    """
    apenas_novos = not req.reutilizar_existentes
    pares = agente.pares_de_feedback(limite=200, apenas_novos=apenas_novos)
    if len(pares) < treino.MIN_PARES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"só há {len(pares)} pares {'novos ' if apenas_novos else ''}com correção "
                f"(mínimo {treino.MIN_PARES}); dê feedback com correção antes de retreinar"
            ),
        )
    return treino.adaptar_em_segundo_plano(
        passos=req.passos, lr=req.lr, apenas_novos=apenas_novos
    )


@router.post("/retreinar/parar", summary="Parar a adaptação em curso")
def parar_retreino(session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Pede a paragem cooperativa: o ciclo termina no passo seguinte e, se já
    houve passos, guarda o que aprendeu (com backup do estado anterior)."""
    return treino.pedir_paragem()


@router.get("/retreinar/historico", summary="Histórico de adaptações")
def historico_retreino(
    limite: int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    registos = treino.historico_adaptacoes(limite=limite)
    return {"total": len(registos), "registos": registos}


@router.get("/versoes", summary="Versões guardadas do adaptador")
def versoes_adaptador() -> Dict[str, Any]:
    versoes = treino.listar_versoes()
    return {
        "total": len(versoes),
        "versoes": versoes,
        "atual": treino.estado_adaptacao().get("versoes", 0),
    }


# ---------------------------------------------------------------------------
# Motor Soup (`soup-cli`): alternativa de uma só tacada ao loop incremental.
# ---------------------------------------------------------------------------


class SoupTreinarRequest(BaseModel):
    config: str = Field(..., min_length=1, max_length=200, description="Nome do YAML em training/soup/")
    validar_primeiro: bool = Field(True, description="Correr `soup train --dry-run` antes de treinar")


@router.get("/soup", summary="Motor Soup: configs disponíveis e estado da corrida")
def estado_soup() -> Dict[str, Any]:
    """Leitura pública: o mesmo padrão da ficha do modelo.

    Devolve o retrato da corrida (fase, passo, perda, últimas linhas) **e** os
    configs de `training/soup/`, com o modelo base, o dataset e o número de
    pares — é o que a página de retreino mostra antes de lançar seja o que for.
    """
    return {"estado": soup.instantaneo(), "configs": soup.configs()}


@router.post("/soup/validar", summary="Validar um config do Soup sem treinar")
def validar_soup(req: SoupTreinarRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    return soup.validar(req.config)


@router.post("/soup/treinar", summary="Treinar com o Soup (subprocesso)")
def treinar_soup(req: SoupTreinarRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    """Lança `soup train -y --config <yaml>` e responde já.

    O subprocesso corre fora do processo da API: pode ser parado sem derrubar o
    servidor, e o progresso é lido linha a linha para o painel.
    """
    if req.validar_primeiro:
        veredicto = soup.validar(req.config)
        if not veredicto.get("ok"):
            raise HTTPException(status_code=409, detail=veredicto.get("mensagem") or "config inválido")
    resultado = soup.iniciar(req.config)
    if not resultado.get("ok"):
        raise HTTPException(status_code=409, detail=resultado.get("erro") or "não foi possível arrancar o Soup")
    return resultado


@router.post("/soup/parar", summary="Parar o treino do Soup")
def parar_soup(session: Session) -> Dict[str, Any]:  # noqa: ARG001
    return soup.parar()


@router.websocket("/retreinar/ws")
async def ws_retreino(websocket: WebSocket, token: Optional[str] = Query(None)) -> None:
    """Fluxo do retreino em direto: fases, passo, perda e tokens.

    O browser não deixa pôr `Authorization` no handshake, por isso o token vem na
    query (`?token=…`) e é validado como em qualquer pedido protegido. O canal
    envia o retrato completo a cada mudança (não deltas) e um `ping` a cada 15 s
    para o proxy não fechar uma ligação parada; a interface reconstrói tudo a
    partir do último retrato, incluindo a curva de perda desde o passo 1.
    """
    try:
        session_from_token(token)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return

    await websocket.accept()
    ultimo: Optional[str] = None
    ultimo_envio = time.monotonic()
    try:
        while True:
            estado = await run_in_threadpool(treino.instantaneo)
            estado["soup"] = await run_in_threadpool(soup.resumo)
            externo = estado.get("externo") or {}
            motor_soup = estado.get("soup") or {}
            assinatura = repr(
                (
                    estado.get("a_correr"),
                    estado.get("passo"),
                    estado.get("fase"),
                    estado.get("perda"),
                    estado.get("tokens"),
                    estado.get("erro"),
                    estado.get("paragem_pedida"),
                    len(estado.get("historico") or ()),
                    # O treino completo corre fora deste processo: o passo dele
                    # também tem de acordar o canal, senão a curva só aparecia
                    # no fim.
                    externo.get("passo"),
                    externo.get("a_correr"),
                    # O motor Soup também é um subprocesso: idem.
                    motor_soup.get("passo"),
                    motor_soup.get("a_correr"),
                    motor_soup.get("fase"),
                )
            )
            if assinatura != ultimo:
                await websocket.send_json({"tipo": "estado", **estado})
                ultimo = assinatura
                ultimo_envio = time.monotonic()
            elif time.monotonic() - ultimo_envio > 15:
                await websocket.send_json({"tipo": "ping", "agora_ts": time.time()})
                ultimo_envio = time.monotonic()
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        return
    except RuntimeError:  # pragma: no cover - ligação fechada a meio de um envio
        return


@router.post("/versoes/reverter", summary="Reverter o adaptador para uma versão guardada")
def reverter_adaptador(req: ReverterRequest, session: Session) -> Dict[str, Any]:  # noqa: ARG001
    try:
        return treino.reverter_para(req.versao)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
