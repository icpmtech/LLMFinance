"""Motor alternativo de treino: o CLI do **Soup** (`soup-cli`).

O `training/train_lora_contratos.py` treina em CPU com pausa/retoma próprio; o
Soup é o caminho de **uma só tacada** (LoRA, quantização e `val_split` a partir
de um YAML). Este módulo não reimplementa nada do Soup: encontra o binário,
lista os configs de `training/soup/`, valida-os com `soup train --dry-run` e,
quando há `[train]` instalado, lança `soup train -y --config <yaml>` como
subprocesso, traduzindo o que ele imprime para o mesmo retrato que o WebSocket
do retreino já usa (fase, passo, perda).

Duas decisões que valem a pena conhecer:

- **Não se corre dentro do processo da API.** O Soup carrega modelos de vários
  GB; um subprocesso isolado pode ser morto (`parar`) sem arrastar a API.
- **O `soup` do venv é a instalação leve.** Sem o extra `[train]` ele valida
  configs e dados mas não treina — nesse caso a interface mostra o comando do
  contentor (`docker compose --profile train run --rm soup train …`), que é o
  caminho documentado em `docs/soup.md`.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "training" / "soup"

#: Comando do contentor que já traz `soup-cli[train]` (`docs/soup.md`).
COMANDO_CONTENTOR = "docker compose --profile train run --rm soup train -y --config {config}"

#: Módulos que o `soup train` precisa (o extra `[train]` do pacote).
MODULOS_TREINO = ("torch", "transformers", "peft", "trl", "datasets", "accelerate")

#: Quantas linhas de saída se guardam para a interface.
MAX_LOG = 60

_estado_lock = threading.Lock()
_processo: Optional[subprocess.Popen] = None
_cancelar = threading.Event()

_estado: Dict[str, Any] = {
    "a_correr": False,
    "config": None,
    "fase": "ocioso",
    "passo": 0,
    "passos": 0,
    "perda": None,
    "iniciado": None,
    "concluido": None,
    "erro": None,
    "codigo_saida": None,
    "saida": None,
    "log": [],
    "pontos": [],
}

_versao_cache: Dict[str, Any] = {"binario": None, "versao": None}


# ------------------------------------------------------------------ descoberta
def _comando_base() -> Optional[List[str]]:
    """Comando do Soup, já dividido: `SOUP_BIN` (aceita argumentos) ou `PATH`.

    `SOUP_BIN` aceita uma linha completa — `"C:/.../python.exe" stub.py` ou
    `uvx soup-cli` — o que permite testar a orquestração com um duplo e usar
    instalações que não põem um `soup` no `PATH`.
    """
    forcado = os.environ.get("SOUP_BIN")
    if forcado:
        partes = shlex.split(forcado)
        if not partes:
            return None
        primeiro = partes[0]
        if Path(primeiro).is_file():
            return [primeiro, *partes[1:]]
        achado = shutil.which(primeiro)
        return [achado or primeiro, *partes[1:]]
    achado = shutil.which("soup")
    return [achado] if achado else None


def binario() -> Optional[str]:
    """Primeiro elemento do comando do Soup (para mostrar na interface)."""
    partes = _comando_base()
    return partes[0] if partes else None


def versao() -> Optional[str]:
    """Versão do CLI (`soup --version`), guardada em cache por comando."""
    partes = _comando_base()
    if not partes:
        return None
    chave = " ".join(partes)
    if _versao_cache["binario"] == chave and _versao_cache["versao"]:
        return _versao_cache["versao"]
    try:
        saida = subprocess.run(
            [*partes, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    linhas = (saida.stdout or saida.stderr or "").strip().splitlines()
    valor = linhas[0].strip() if linhas else None
    _versao_cache.update({"binario": chave, "versao": valor})
    return valor


def _ler_yaml(caminho: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError:  # pragma: no cover - o Soup depende do pyyaml
        return {}
    try:
        with caminho.open("r", encoding="utf-8") as fh:
            dados = yaml.safe_load(fh) or {}
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def configs() -> List[Dict[str, Any]]:
    """Configs de `training/soup/*.yaml` com o essencial já lido."""
    if not CONFIG_DIR.is_dir():
        return []
    lista: List[Dict[str, Any]] = []
    for ficheiro in sorted(CONFIG_DIR.glob("*.yaml")):
        dados = _ler_yaml(ficheiro)
        dados_treino = dados.get("data") or {}
        treino = dados.get("training") or {}
        dataset = dados_treino.get("train")
        caminho_dataset = (ROOT / str(dataset).lstrip("./")).resolve() if dataset else None
        pares = None
        if caminho_dataset and caminho_dataset.is_file():
            try:
                with caminho_dataset.open("r", encoding="utf-8") as fh:
                    pares = sum(1 for linha in fh if linha.strip())
            except OSError:
                pares = None
        lista.append(
            {
                "nome": ficheiro.stem,
                "caminho": str(ficheiro.relative_to(ROOT)).replace("\\", "/"),
                "base": dados.get("base"),
                "dataset": dataset,
                "dataset_existe": bool(caminho_dataset and caminho_dataset.is_file()),
                "pares": pares,
                "saida": dados.get("output"),
                "tarefa": dados.get("task", "sft"),
                "epocas": treino.get("epochs"),
                "lr": treino.get("lr"),
                "lora_r": (treino.get("lora") or {}).get("r"),
                "quantizacao": treino.get("quantization"),
            }
        )
    return lista


def validar(nome: str, timeout: int = 180) -> Dict[str, Any]:
    """Corre `soup train --dry-run` e devolve o veredicto (não treina nada)."""
    partes = _comando_base()
    if not partes:
        return {"ok": False, "mensagem": "o CLI do Soup (`soup`) não está instalado"}
    config = _caminho_config(nome)
    if config is None:
        return {"ok": False, "mensagem": f"config desconhecido: {nome}"}
    try:
        saida = subprocess.run(
            [*partes, "train", "-c", str(config), "--dry-run"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "mensagem": "a validação demorou demasiado"}
    except OSError as exc:
        return {"ok": False, "mensagem": f"não foi possível correr o Soup: {exc}"}
    texto = f"{saida.stdout or ''}{saida.stderr or ''}".strip()
    return {"ok": saida.returncode == 0, "mensagem": _resumo(texto), "codigo_saida": saida.returncode}


# --------------------------------------------------------------------- execução
def _caminho_config(nome: str) -> Optional[Path]:
    if not nome:
        return None
    candidato = CONFIG_DIR / (nome if nome.endswith(".yaml") else f"{nome}.yaml")
    if candidato.is_file():
        return candidato
    alternativa = (ROOT / nome).resolve()
    if alternativa.is_file():
        return alternativa
    return None


def _resumo(texto: str, limite: int = 400) -> str:
    """Última linha útil: as mensagens do Soup vêm em painéis e barras."""
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    return linhas[-1][:limite] if linhas else ""


_RE_PASSO = re.compile(r"(\d+)\s*/\s*(\d+)")
_RE_PERDA = re.compile(r"loss[=:\s]+([0-9]*\.?[0-9]+)", re.IGNORECASE)
_RE_MOLDURA = re.compile(r"[│┃|]")


def _interpretar(linha: str) -> Optional[Dict[str, Any]]:
    """Extrai passo/passos/perda de uma linha do Soup (tqdm, época, loss)."""
    limpa = _RE_MOLDURA.sub(" ", linha)
    passo = passos = None
    achado = _RE_PASSO.search(limpa)
    if achado:
        candidato_passo, candidato_total = int(achado.group(1)), int(achado.group(2))
        # tqdm e «epoch 1/3» também dão `n/m`; só conta como passo o que couber.
        if 0 < candidato_passo <= candidato_total:
            passo, passos = candidato_passo, candidato_total
    perda = None
    achado_perda = _RE_PERDA.search(limpa)
    if achado_perda:
        try:
            perda = round(float(achado_perda.group(1)), 4)
        except ValueError:
            perda = None
    if passo is None and perda is None:
        return None
    return {"passo": passo, "passos": passos, "perda": perda}


def _registar(linha: str) -> None:
    interpretado = _interpretar(linha)
    with _estado_lock:
        registo = _estado["log"]
        registo.append(linha)
        if len(registo) > MAX_LOG:
            del registo[:-MAX_LOG]
        if not interpretado:
            return
        if interpretado["passo"] is not None:
            _estado["passo"] = interpretado["passo"]
        if interpretado["passos"]:
            _estado["passos"] = interpretado["passos"]
        if interpretado["perda"] is not None:
            _estado["perda"] = interpretado["perda"]
            _estado["pontos"].append(
                {"passo": _estado["passo"] or len(_estado["pontos"]) + 1, "perda": interpretado["perda"]}
            )
            if len(_estado["pontos"]) > 400:
                del _estado["pontos"][:-400]
        if _estado["fase"] in ("a_preparar", "ocioso") and interpretado["passo"]:
            _estado["fase"] = "a_treinar"


def _bombear(processo: "subprocess.Popen[str]") -> None:
    """Lê a saída do Soup linha a linha até o processo terminar."""
    global _processo
    try:
        if processo.stdout is not None:
            for linha in processo.stdout:
                if linha:
                    _registar(linha.rstrip())
    finally:
        codigo = processo.wait()
        with _estado_lock:
            _estado["codigo_saida"] = codigo
            _estado["a_correr"] = False
            _estado["concluido"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if codigo == 0:
                _estado["fase"] = "concluido"
            elif _cancelar.is_set():
                _estado["fase"] = "parado"
            else:
                _estado["fase"] = "erro"
                _estado["erro"] = _estado["erro"] or _resumo("\n".join(_estado["log"][-6:]))
        _cancelar.clear()
        _processo = None


def iniciar(nome: str) -> Dict[str, Any]:
    """Lança `soup train -y --config <yaml>` num subprocesso."""
    global _processo
    partes = _comando_base()
    if not partes:
        return {"ok": False, "erro": 'o CLI do Soup não está instalado (pip install "soup-cli[train]")'}
    config = _caminho_config(nome)
    if config is None:
        return {"ok": False, "erro": f"config desconhecido: {nome}"}

    with _estado_lock:
        if _estado["a_correr"]:
            return {"ok": False, "erro": "já há um treino do Soup a correr", "a_correr": True}

    # Dois treinos ao mesmo tempo disputam o mesmo CPU/RAM.
    try:
        from api import llm_contratos_treino as treino

        if treino.instantaneo().get("a_correr"):
            return {"ok": False, "erro": "a adaptação incremental está a correr; pare-a antes de lançar o Soup"}
    except Exception:  # pragma: no cover - a API pode não estar carregada (testes)
        pass

    _cancelar.clear()
    argumentos = [*partes, "train", "-y", "--config", str(config)]
    try:
        processo = subprocess.Popen(
            argumentos,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        return {"ok": False, "erro": f"não foi possível arrancar o Soup: {exc}"}

    with _estado_lock:
        _estado.update(
            {
                "a_correr": True,
                "config": config.name,
                "fase": "a_preparar",
                "passo": 0,
                "passos": 0,
                "perda": None,
                "iniciado": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "concluido": None,
                "erro": None,
                "codigo_saida": None,
                "saida": (_ler_yaml(config).get("output") or None),
                "log": [],
                "pontos": [],
            }
        )
    _processo = processo
    threading.Thread(target=_bombear, args=(processo,), name="soup-treino", daemon=True).start()
    return {"ok": True, "estado": "iniciado", "config": config.name, "comando": " ".join(argumentos)}


def parar() -> Dict[str, Any]:
    """Termina o subprocesso do Soup (se houver um a correr)."""
    processo = _processo
    if processo is None or processo.poll() is not None:
        return {"ok": False, "motivo": "não há treino do Soup a correr"}
    _cancelar.set()
    processo.terminate()
    try:
        processo.wait(timeout=20)
    except subprocess.TimeoutExpired:  # pragma: no cover - depende do sistema
        processo.kill()
    return {"ok": True, "estado": "parado"}


def treino_disponivel() -> bool:
    """`soup train` consegue mesmo treinar aqui? (extra `[train]` instalado).

    A instalação leve valida configs e dados mas aborta no treino por falta de
    `peft`/`trl`/`datasets`/`accelerate`. Sem esta verificação o botão parecia
    disponível e só falhava depois de arrancar.
    """
    import importlib.util

    return all(importlib.util.find_spec(nome) is not None for nome in MODULOS_TREINO)


def instantaneo() -> Dict[str, Any]:
    """Retrato do motor Soup para a interface (só memória, sem disco)."""
    with _estado_lock:
        estado = dict(_estado)
        estado["log"] = list(_estado["log"])
        estado["pontos"] = list(_estado["pontos"])
    estado["disponivel"] = binario() is not None
    estado["treino_disponivel"] = treino_disponivel()
    estado["versao"] = versao()
    estado["comando_contentor"] = COMANDO_CONTENTOR
    estado["agora_ts"] = time.time()
    return estado


def resumo() -> Dict[str, Any]:
    """Versão mínima para viajar no WebSocket do retreino (sem log nem pontos)."""
    estado = instantaneo()
    estado.pop("log", None)
    estado.pop("pontos", None)
    return estado
