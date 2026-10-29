"""Adaptação incremental do adaptador LoRA com o que o utilizador ensinou.

O treino grande corre à mão (`training/train_lora_contratos.py`, com pausa e
retoma). Este módulo é a versão **curta e automática**: pega nas correções
humanas (`finance_llm_feedback`) e nas skills com exemplo
(`finance_llm_memoria`), escreve-as como pares Alpaca, dá alguns passos de
treino sobre o adaptador que já existe e guarda-o em sítio.

Regras que o tornam seguro:

- **Uma adaptação de cada vez** (`_lock` + estado), porque carrega outro modelo
  de 0,5 B para a memória;
- **Backup antes de escrever** (`adapter_model.safetensors.bak-<ts>`), para que
  uma adaptação má seja reversível;
- **Mínimo de pares** (`MIN_PARES`) — treinar com um exemplo só move o modelo na
  direção de uma frase e estraga o formato aprendido;
- **Avaliação antes/depois**: mede a perda nos próprios pares e guarda o número
  em `metricas_adaptacao.jsonl`, para a interface mostrar se melhorou.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_FICHEIRO = ROOT / "data" / "final" / "iqos_adaptacao.jsonl"

MIN_PARES = 3
MAX_PASSOS = 40

_estado: Dict[str, Any] = {
    "a_correr": False,
    "passo": 0,
    "passos": 0,
    "perda": None,
    "iniciado": None,
    "concluido": None,
    "pares": 0,
    "erro": None,
    "ultimo_resultado": None,
    "paragem_pedida": False,
    # Campos que a interface mostra em direto (WebSocket `/llm/modelo/retreinar/ws`).
    # `fase` diz em que etapa do processo está; `historico` é a curva de perda
    # passo a passo, para o gráfico poder ser desenhado desde o início mesmo que
    # a página abra a meio.
    "fase": "ocioso",
    "atividade": "",
    "tokens": 0,
    "historico": [],
    "perda_antes": None,
    "perda_depois": None,
    "iniciado_ts": None,
    "lr": None,
}
_estado_lock = threading.Lock()
_treino_lock = threading.Lock()
#: Sinaliza à thread de treino que deve parar no próximo passo.
_parar = threading.Event()

#: Ordem das fases, para a interface desenhar o fluxo e saber o que já passou.
FASES = ("a_preparar", "a_treinar", "a_avaliar", "a_guardar", "concluido")


def _atualizar(**campos: Any) -> None:
    with _estado_lock:
        _estado.update(campos)


#: Cache do `metrics.jsonl` externo (treino completo, corrido à mão). Guarda os
#: pontos e a data do ficheiro; só relê quando o ficheiro muda.
_metricas_cache: Dict[str, Any] = {"mtime": None, "pontos": [], "total": 0}


def progresso_externo(limite: int = 160) -> Dict[str, Any]:
    """Progresso do **treino completo** (`training/train_lora_contratos.py`).

    Esse treino corre à mão, fora deste processo, e não passa pelo `_estado` — a
    interface via-o só pela curva de perda, com 8 s de atraso e sem saber se
    ainda está vivo. O sinal de vida é o `mtime` do `metrics.jsonl`, que o script
    reescreve a cada `--log-every`; se ficou recente, está a correr.
    """
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    caminho = DEFAULT_ADAPTER_DIR / "metrics.jsonl"
    try:
        info = caminho.stat()
    except OSError:
        return {"disponivel": False, "a_correr": False, "pontos": [], "passo": 0}

    if _metricas_cache["mtime"] != info.st_mtime:
        pontos: List[Dict[str, Any]] = []
        try:
            with caminho.open("r", encoding="utf-8") as fh:
                for linha in fh:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        pontos.append(json.loads(linha))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return {"disponivel": False, "a_correr": False, "pontos": [], "passo": 0}
        _metricas_cache.update({"mtime": info.st_mtime, "pontos": pontos[-limite:], "total": len(pontos)})

    pontos = _metricas_cache["pontos"]
    return {
        "disponivel": True,
        "a_correr": (time.time() - info.st_mtime) < 180,
        "pontos": pontos,
        "passo": (pontos[-1].get("step") if pontos else 0) or 0,
        "total": _metricas_cache["total"],
        "atualizado_em": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(info.st_mtime)),
    }


#: Cache da última linha de `metricas_adaptacao.jsonl`. O WebSocket pede um
#: retrato a cada 400 ms: só se relê o ficheiro quando o `mtime` muda.
_ultimo_cache: Dict[str, Any] = {"mtime": None, "registo": None}


def _ultimo_registo() -> Optional[Dict[str, Any]]:
    """Última adaptação registada em `metricas_adaptacao.jsonl` (com cache)."""
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    ficheiro = DEFAULT_ADAPTER_DIR / "metricas_adaptacao.jsonl"
    try:
        info = ficheiro.stat()
    except OSError:
        _ultimo_cache.update({"mtime": None, "registo": None})
        return None
    if _ultimo_cache["mtime"] != info.st_mtime:
        ultimo: Optional[Dict[str, Any]] = None
        try:
            with ficheiro.open("r", encoding="utf-8") as fh:
                for linha in fh:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        ultimo = json.loads(linha)
                    except ValueError:
                        continue
        except OSError:  # pragma: no cover - depende do disco
            return _ultimo_cache["registo"]
        _ultimo_cache.update({"mtime": info.st_mtime, "registo": ultimo})
    return _ultimo_cache["registo"]


def instantaneo() -> Dict[str, Any]:
    """Retrato leve do estado, para o WebSocket (sem varrer o disco).

    `estado_adaptacao()` conta os ficheiros `.bak-*`, o que é aceitável num
    pedido HTTP mas não a cada 400 ms; o WebSocket usa esta versão. Os acessos a
    disco são dois `stat`: o `metrics.jsonl` (treino completo, que corre fora
    deste processo) e o `metricas_adaptacao.jsonl`.

    O estado em memória nasce vazio em cada arranque do processo. Sem este
    recuo, o painel «processo em direto» abria com travessões depois de um
    restart mesmo havendo adaptações concluídas — o histórico mostrava-as e o
    gráfico não. Parado, o retrato passa a trazer a última adaptação: perda
    antes/depois, curva passo a passo e contagem de passos.
    """
    with _estado_lock:
        estado = dict(_estado)
        estado["historico"] = list(_estado.get("historico") or [])

    if not estado.get("a_correr"):
        registo = _ultimo_registo()
        if registo:
            if not estado.get("ultimo_resultado"):
                estado["ultimo_resultado"] = registo
            if not estado["historico"] and registo.get("historico"):
                estado["historico"] = list(registo["historico"])
            for campo in ("perda_antes", "perda_depois"):
                if estado.get(campo) is None and registo.get(campo) is not None:
                    estado[campo] = registo[campo]
            if not estado.get("passo"):
                estado["passo"] = int(registo.get("passos") or 0)
            if not estado.get("passos"):
                estado["passos"] = int(registo.get("passos_pedidos") or registo.get("passos") or 0)
            if not estado.get("tokens") and estado["historico"]:
                estado["tokens"] = int(estado["historico"][-1].get("tokens") or 0)
            if estado.get("fase") == "ocioso":
                # Registos antigos não tinham `estado`: se há passos, concluiu.
                desfecho = registo.get("estado") or ("concluido" if registo.get("passos") else "ocioso")
                estado["fase"] = desfecho if desfecho in FASES + ("parado", "erro") else "concluido"
            if not estado.get("iniciado"):
                estado["iniciado"] = registo.get("concluido_em")

    estado["externo"] = progresso_externo()
    estado["agora_ts"] = time.time()
    return estado


def estado_adaptacao() -> Dict[str, Any]:
    """Estado da adaptação: o que está a correr **e** o que ficou da última.

    O estado em memória perde-se quando o contentor reinicia; o histórico está
    em `metricas_adaptacao.jsonl`, ao lado do adaptador, e é de lá que se lê o
    último resultado depois de um restart.
    """
    estado = instantaneo()
    if not estado.get("ultimo_resultado"):
        historico = _ler_historico()
        if historico:
            estado["ultimo_resultado"] = historico[-1]
    estado["versoes"] = _versoes_guardadas()
    return estado


def _ler_historico() -> List[Dict[str, Any]]:
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    ficheiro = DEFAULT_ADAPTER_DIR / "metricas_adaptacao.jsonl"
    if not ficheiro.exists():
        return []
    linhas: List[Dict[str, Any]] = []
    try:
        with ficheiro.open("r", encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.strip()
                if linha:
                    try:
                        linhas.append(json.loads(linha))
                    except ValueError:
                        continue
    except OSError:
        return []
    return linhas


def _versoes_guardadas() -> int:
    """Quantos backups do adaptador existem (cada adaptação cria um)."""
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    try:
        return len(list(DEFAULT_ADAPTER_DIR.glob("adapter_model.safetensors.bak-*")))
    except OSError:
        return 0


def listar_versoes() -> List[Dict[str, Any]]:
    """Backups do adaptador, do mais recente para o mais antigo.

    Cada adaptação copia o `adapter_model.safetensors` anterior para
    `.bak-<data>` antes de escrever. Esta lista é o que permite à interface
    oferecer «reverter» sem o utilizador ter de mexer em ficheiros.
    """
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    try:
        ficheiros = list(DEFAULT_ADAPTER_DIR.glob("adapter_model.safetensors.bak-*"))
    except OSError:
        return []
    versoes: List[Dict[str, Any]] = []
    for caminho in ficheiros:
        try:
            estado = caminho.stat()
        except OSError:
            continue
        # `copy2` preserva a data do ficheiro copiado, por isso a data do backup
        # tem de vir do nome (`.bak-AAAAMMDD-HHMMSS`), não do mtime.
        carimbo = caminho.name.rsplit(".bak-", 1)[-1].replace("-", " ")
        criado_em = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(estado.st_mtime))
        chave_ordem = estado.st_mtime
        try:
            momento = time.mktime(time.strptime(carimbo, "%Y%m%d %H%M%S"))
            criado_em = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(momento))
            chave_ordem = momento
        except ValueError:
            pass
        versoes.append(
            {
                "nome": caminho.name,
                "bytes": estado.st_size,
                "criado_em": criado_em,
                "_mtime": chave_ordem,
            }
        )
    versoes.sort(key=lambda v: v["_mtime"], reverse=True)
    for versao in versoes:
        versao.pop("_mtime", None)
    return versoes


def reverter_para(nome: str) -> Dict[str, Any]:
    """Repõe o adaptador a partir de um backup (`adapter_model.safetensors.bak-*`).

    Antes de repor, guarda o estado atual noutro backup — reverter também é
    reversível. O `nome` é validado contra a lista real de ficheiros para não
    aceitar caminhos arbitrários.
    """
    from inference.contratos_lora import DEFAULT_ADAPTER_DIR

    with _estado_lock:
        if _estado["a_correr"]:
            raise ValueError("há uma adaptação a correr; espere que termine antes de reverter")
    if not nome or "/" in nome or "\\" in nome or not nome.startswith("adapter_model.safetensors.bak-"):
        raise ValueError("nome de versão inválido")
    origem = DEFAULT_ADAPTER_DIR / nome
    if not origem.is_file():
        raise ValueError(f"versão não encontrada: {nome}")
    destino = DEFAULT_ADAPTER_DIR / "adapter_model.safetensors"

    carimbo = time.strftime("%Y%m%d-%H%M%S")
    seguranca = Path(str(destino) + f".bak-{carimbo}")
    try:
        if destino.exists():
            shutil.copy2(destino, seguranca)
    except OSError as exc:  # pragma: no cover - depende do disco
        logger.warning("Backup de segurança antes de reverter falhou: %s", exc)

    try:
        shutil.copy2(origem, destino)
    except OSError as exc:
        raise ValueError(f"não foi possível repor {nome}: {exc}") from exc

    from inference import contratos_lora

    contratos_lora.limpar_cache()

    resultado = {
        "estado": "revertido",
        "versao": nome,
        "backup_do_estado_anterior": seguranca.name,
        "concluido_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        with (DEFAULT_ADAPTER_DIR / "metricas_adaptacao.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "concluido_em": resultado["concluido_em"],
                        "estado": "revertido",
                        "versao": nome,
                        "pares": 0,
                        "passos": 0,
                        "perda_antes": None,
                        "perda_depois": None,
                        "delta": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass
    return resultado


def historico_adaptacoes(limite: int = 20) -> List[Dict[str, Any]]:
    """Histórico de adaptações (mais recente primeiro), lido do JSONL."""
    return list(reversed(_ler_historico()))[: max(1, limite)]


def pedir_paragem() -> Dict[str, Any]:
    """Pede à adaptação em curso que pare no próximo passo (cooperativo)."""
    with _estado_lock:
        if not _estado["a_correr"]:
            return {"ok": False, "motivo": "não há adaptação a correr", **_estado}
        _estado["paragem_pedida"] = True
    _parar.set()
    return {"ok": True, "estado": "a_parar"}


def _escrever_pares(pares: List[Dict[str, Any]]) -> Path:
    """Grava os pares de adaptação (um ficheiro só, reescrito de cada vez)."""
    DATA_FICHEIRO.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FICHEIRO.open("w", encoding="utf-8") as fh:
        for par in pares:
            fh.write(json.dumps(par, ensure_ascii=False) + "\n")
    return DATA_FICHEIRO


def _encode(tokenizer, par: Dict[str, Any], max_length: int = 512):
    """Mesmo molde do treino grande: perda só nos tokens da resposta."""
    import torch
    from inference.contratos_lora import render_chat_prompt

    prompt_ids = tokenizer(
        render_chat_prompt(tokenizer, par.get("instruction", ""), par.get("input", "")),
        add_special_tokens=False,
    )["input_ids"]
    resposta = str(par.get("output", "")).strip()
    alvo = tokenizer(resposta, add_special_tokens=False)["input_ids"]
    if tokenizer.eos_token_id is not None:
        alvo = alvo + [tokenizer.eos_token_id]
    if not alvo or len(prompt_ids) + len(alvo) >= max_length:
        return None
    ids = torch.tensor([prompt_ids + alvo])
    labels = torch.tensor([[-100] * len(prompt_ids) + alvo])
    return ids, labels


def adaptar(
    *,
    passos: int = 12,
    lr: float = 5e-5,
    max_length: int = 512,
    pares_minimos: int = MIN_PARES,
    marcar_utilizado: bool = True,
    apenas_novos: bool = True,
) -> Dict[str, Any]:
    """Dá `passos` actualizações sobre o adaptador, usando o feedback guardado."""
    from api import llm_contratos_agente as agente

    inicio = time.time()
    _atualizar(fase="a_preparar", atividade="A recolher os pares com correção", lr=lr)
    pares = agente.pares_de_feedback(limite=200, apenas_novos=apenas_novos)
    if len(pares) < pares_minimos:
        _atualizar(fase="ocioso", atividade="")
        return {
            "estado": "sem_dados",
            "mensagem": f"só há {len(pares)} pares com resposta corrigida (mínimo {pares_minimos})",
            "pares": len(pares),
        }

    ficheiro = _escrever_pares(pares)
    _atualizar(pares=len(pares), atividade=f"{len(pares)} pares escritos em {DATA_FICHEIRO.name}")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from inference.contratos_lora import DEFAULT_ADAPTER_DIR, DEFAULT_BASE_MODEL, adapter_available

    if not adapter_available(DEFAULT_ADAPTER_DIR):
        _atualizar(fase="ocioso", atividade="")
        return {"estado": "sem_adaptador", "mensagem": "não há adaptador treinado para adaptar"}

    torch.set_num_threads(int(__import__("os").environ.get("LLMFINANCE_CPU_THREADS", "8")))
    _atualizar(atividade="A carregar o tokenizer e o modelo base (Qwen 0.5B)")
    tokenizer = AutoTokenizer.from_pretrained(DEFAULT_BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    exemplos = [e for e in (_encode(tokenizer, p, max_length) for p in pares) if e]
    if not exemplos:
        _atualizar(fase="ocioso", atividade="")
        return {"estado": "sem_dados", "mensagem": "nenhum par cabe na janela do modelo", "pares": len(pares)}

    passos = max(1, min(int(passos), MAX_PASSOS))
    _atualizar(passos=passos, atividade="A carregar o modelo base e o adaptador LoRA")
    modelo_base = AutoModelForCausalLM.from_pretrained(DEFAULT_BASE_MODEL, dtype=torch.float32)
    modelo = PeftModel.from_pretrained(modelo_base, str(DEFAULT_ADAPTER_DIR), is_trainable=True)
    modelo.train()
    optimizer = torch.optim.AdamW([p for p in modelo.parameters() if p.requires_grad], lr=lr)

    def perda_media() -> float:
        modelo.eval()
        total, n = 0.0, 0
        with torch.no_grad():
            for ids, labels in exemplos:
                total += float(modelo(input_ids=ids, labels=labels).loss)
                n += 1
        modelo.train()
        return round(total / max(1, n), 4)

    _atualizar(fase="a_avaliar", atividade="A medir a perda de partida nos pares")
    perda_antes = perda_media()
    _atualizar(perda_antes=perda_antes, fase="a_treinar", atividade="A treinar")

    historico: List[Dict[str, Any]] = []
    tokens_acumulados = 0
    interrompido = False
    for passo in range(1, passos + 1):
        if _parar.is_set():
            interrompido = True
            logger.info("Adaptação interrompida a pedido do utilizador no passo %s", passo - 1)
            break
        ids, labels = exemplos[(passo - 1) % len(exemplos)]
        saida = modelo(input_ids=ids, labels=labels)
        saida.loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        perda = round(float(saida.loss.detach()), 4)
        tokens_acumulados += int(ids.shape[-1])
        historico.append(
            {
                "passo": passo,
                "perda": perda,
                "tokens": tokens_acumulados,
                "segundos": round(time.time() - inicio, 1),
            }
        )
        with _estado_lock:
            _estado.update(
                {"passo": passo, "perda": perda, "tokens": tokens_acumulados, "historico": list(historico)}
            )

    passos_feitos = len(historico)
    if passos_feitos == 0:
        return {
            "estado": "parado",
            "mensagem": "adaptação parada antes do primeiro passo; adaptador intacto",
            "pares": len(exemplos),
            "passos": 0,
        }

    _atualizar(fase="a_avaliar", atividade="A medir a perda final")
    perda_depois = perda_media()
    _atualizar(perda_depois=perda_depois, fase="a_guardar", atividade="A guardar o adaptador (com backup)")

    carimbo = time.strftime("%Y%m%d-%H%M%S")
    backup = Path(str(DEFAULT_ADAPTER_DIR / "adapter_model.safetensors") + f".bak-{carimbo}")
    try:
        atual = DEFAULT_ADAPTER_DIR / "adapter_model.safetensors"
        if atual.exists():
            shutil.copy2(atual, backup)
    except OSError as exc:  # pragma: no cover - depende do disco
        logger.warning("Backup do adaptador falhou: %s", exc)

    modelo.save_pretrained(str(DEFAULT_ADAPTER_DIR))

    resultado = {
        "estado": "parado" if interrompido else "concluido",
        "pares": len(exemplos),
        "passos": passos_feitos,
        "passos_pedidos": passos,
        "interrompido": interrompido,
        "lr": lr,
        "perda_antes": perda_antes,
        "perda_depois": perda_depois,
        "delta": round(perda_depois - perda_antes, 4),
        "backup": backup.name,
        "ficheiro": str(DATA_FICHEIRO.relative_to(ROOT)) if DATA_FICHEIRO.is_relative_to(ROOT) else str(DATA_FICHEIRO),
        "segundos": round(time.time() - inicio, 1),
        "concluido_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "historico": historico,
    }

    try:
        with (DEFAULT_ADAPTER_DIR / "metricas_adaptacao.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        k: resultado[k]
                        for k in (
                            "concluido_em",
                            "estado",
                            "pares",
                            "passos",
                            "passos_pedidos",
                            "perda_antes",
                            "perda_depois",
                            "delta",
                            "lr",
                            "segundos",
                            "backup",
                            # A curva passo a passo fica em disco: depois de um
                            # restart o painel ao vivo reconstrói-a daqui.
                            "historico",
                        )
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:  # pragma: no cover - depende do disco
        pass

    if marcar_utilizado:
        agente.marcar_feedback_utilizado([p["metadata"]["feedback_id"] for p in pares if p.get("metadata", {}).get("feedback_id")])

    try:
        from api import llm_contratos_service as service

        service.index_run(
            {
                "estado": "adaptacao_incremental",
                "modelo_base": DEFAULT_BASE_MODEL,
                "adaptador": DEFAULT_ADAPTER_DIR.name,
                "dados": {"ficheiro": resultado["ficheiro"], "pares_treino": len(exemplos), "fontes": ["feedback"]},
                "treino": {
                    "passos": passos,
                    "perda_final": perda_depois,
                    "segundos": resultado["segundos"],
                    "concluido_em": resultado["concluido_em"],
                },
            }
        )
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Não indexou a adaptação: %s", exc)

    # O adaptador mudou: a próxima inferência tem de recarregar.
    from inference import contratos_lora

    contratos_lora.limpar_cache()
    return resultado


def adaptar_em_segundo_plano(
    passos: int = 12, lr: float = 5e-5, apenas_novos: bool = True
) -> Dict[str, Any]:
    """Arranca a adaptação numa thread (a rota responde já, a página vai vendo)."""
    with _estado_lock:
        if _estado["a_correr"]:
            return {"estado": "a_correr", "ja_estava_a_correr": True, **_estado}
        _parar.clear()
        _estado.update(
            {
                "a_correr": True,
                "passo": 0,
                "passos": passos,
                "perda": None,
                "erro": None,
                "iniciado": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "concluido": None,
                "paragem_pedida": False,
                "fase": "a_preparar",
                "atividade": "A preparar a adaptação",
                "tokens": 0,
                "historico": [],
                "perda_antes": None,
                "perda_depois": None,
                "iniciado_ts": time.time(),
                "lr": lr,
            }
        )

    def _correr() -> None:
        with _treino_lock:
            try:
                resultado = adaptar(passos=passos, lr=lr, apenas_novos=apenas_novos)
                with _estado_lock:
                    _estado.update(
                        {
                            "ultimo_resultado": resultado,
                            "concluido": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "fase": "concluido" if resultado.get("estado") == "concluido" else str(resultado.get("estado")),
                            "atividade": resultado.get("mensagem") or "Adaptação terminada",
                        }
                    )
            except Exception as exc:  # pragma: no cover - protege a thread
                logger.exception("Adaptação incremental falhou")
                with _estado_lock:
                    _estado.update({"erro": str(exc), "fase": "erro", "atividade": f"Falhou: {exc}"})
            finally:
                with _estado_lock:
                    _estado["a_correr"] = False
                    _estado["paragem_pedida"] = False
                _parar.clear()

    threading.Thread(target=_correr, name="llm-adaptacao", daemon=True).start()
    return {"estado": "iniciado", "passos": passos}
