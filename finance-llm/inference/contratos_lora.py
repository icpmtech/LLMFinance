"""Modelo de contratos+empresas: prompt partilhado e inferência com adaptador LoRA.

Este módulo é a **única** definição do molde de prompt do modelo afinado com os
dados do Elasticsearch (contratos, entidades e subvenções). Treino
(`training/train_lora_contratos.py`), avaliação
(`training/eval_lora_contratos.py`) e API (`api/llm_contratos_service.py`)
importam daqui, para que um prompt diferente não transforme um modelo bom em
respostas más.

Vive em `inference/` (e não em `training/`) porque `training/` fica fora do
contexto das imagens Docker (`ver .dockerignore`): o backend tem de conseguir
carregar o modelo, mas não precisa dos scripts de treino.
"""
from __future__ import annotations

import json
import os
import random
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]

# Modelo de partida escolhido para o fine-tune em CPU: já fala português,
# cabe na memória (0,5 B parâmetros) e é o mesmo que
# `training/soup/soup-qwen05-empresas-contratos.yaml` já previa.
DEFAULT_BASE_MODEL = os.environ.get("LLMFINANCE_BASE_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
DEFAULT_ADAPTER_DIR = ROOT / "model" / "qwen05-contratos"

SYSTEM_PROMPT = (
    "Assistente do IQ OS: descreves contratos públicos, empresas e subsídios "
    "portugueses em 2-3 frases, só com os dados recebidos. Se um campo faltar, "
    "dizes «não especificado»."
)

# Molde em texto simples (sem `chat_template`): o mesmo que
# `training/soup/eval_holdout.py` usa para medir o par instruction/input/output.
PROMPT_TEMPLATE = "### Instrução:\n{instruction}\n\n{input}\n\n### Resposta:\n"


def user_content(instruction: str, data: str) -> str:
    """Junta a instrução e os dados do documento no bloco do utilizador."""
    return f"### Instrução:\n{instruction.strip()}\n\n{data.strip()}"


def render_prompt(instruction: str, data: str, eos_token: str = "") -> str:
    """Prompt de texto simples — usado na avaliação e como rede de segurança."""
    del eos_token
    return PROMPT_TEMPLATE.format(instruction=instruction.strip(), input=data.strip())


def build_messages(instruction: str, data: str, *, sistema: Optional[str] = None, contexto: Optional[str] = None) -> List[Dict[str, str]]:
    """Mensagens no formato do `apply_chat_template` (Qwen2.5 traz o dele).

    `contexto` (memória + evidências do RAG + resultados de skills) entra **antes**
    dos dados do pedido: o modelo lê primeiro o que a plataforma sabe e só depois
    o documento, que é o que tem de descrever.
    """
    partes: List[str] = []
    if contexto and contexto.strip():
        partes.append(contexto.strip())
    partes.append(user_content(instruction, data))
    return [
        {"role": "system", "content": (sistema or SYSTEM_PROMPT).strip() or SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(partes)},
    ]


def render_chat_prompt(
    tokenizer,
    instruction: str,
    data: str,
    *,
    sistema: Optional[str] = None,
    contexto: Optional[str] = None,
) -> str:
    """Prompt com o `chat_template` do modelo e o turno do assistente aberto."""
    messages = build_messages(instruction, data, sistema=sistema, contexto=contexto)
    template = getattr(tokenizer, "chat_template", None)
    if not template:
        return render_prompt(instruction, data)
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


# ---------------------------------------------------------------------------
# Adaptadores no disco
# ---------------------------------------------------------------------------


def adapter_available(adapter_dir: Path | str = DEFAULT_ADAPTER_DIR) -> bool:
    """True quando há um adaptador LoRA treinado no diretório indicado."""
    path = Path(adapter_dir)
    return (path / "adapter_config.json").exists() and any(
        (path / name).exists() for name in ("adapter_model.safetensors", "adapter_model.bin")
    )


def read_run_metadata(adapter_dir: Path | str = DEFAULT_ADAPTER_DIR) -> Dict[str, Any]:
    """Metadados do treino guardados ao lado do adaptador (`run_metadata.json`).

    Devolve `{}` quando o ficheiro não existe — é o caso de um adaptador feito
    por outra ferramenta (a pasta `model/soup-*`), e a API mostra só o que sabe.
    """
    path = Path(adapter_dir) / "run_metadata.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def listar_adaptadores(raiz: Path | str | None = None) -> List[Dict[str, Any]]:
    """Adaptadores LoRA treinados que existem em `model/*/`.

    Inclui os `model/soup-*` (treinados pelo CLI do Soup) e o adaptador da
    plataforma (`qwen05-contratos`). O `base` vem do `adapter_config.json`
    quando lá está — é o que permite carregar um adaptador do Soup sem saber de
    antemão sobre que modelo foi treinado.
    """
    pasta = Path(raiz) if raiz else ROOT / "model"
    if not pasta.is_dir():
        return []
    lista: List[Dict[str, Any]] = []
    for candidato in sorted(pasta.iterdir()):
        if not candidato.is_dir() or not adapter_available(candidato):
            continue
        base = None
        try:
            config = json.loads((candidato / "adapter_config.json").read_text(encoding="utf-8"))
            base = config.get("base_model_name_or_path")
        except (OSError, ValueError):
            base = None
        try:
            bytes_adaptador = sum(f.stat().st_size for f in candidato.glob("adapter_model.*") if f.is_file())
        except OSError:  # pragma: no cover - depende do disco
            bytes_adaptador = 0
        metadados = read_run_metadata(candidato)
        base_modelo = base or metadados.get("modelo_base")
        lista.append(
            {
                "id": candidato.name,
                "nome": metadados.get("adaptador") or candidato.name,
                "caminho": str(candidato),
                "base": base_modelo,
                # Um LoRA só faz sentido sobre o modelo em que foi treinado: o
                # chat carrega `DEFAULT_BASE_MODEL`, por isso os adaptadores de
                # outro modelo (os `soup-*` do 22 M, por exemplo) ficam de fora
                # em vez de produzirem lixo.
                "compativel": not base_modelo or str(base_modelo) == DEFAULT_BASE_MODEL,
                "bytes": bytes_adaptador,
                "pares": metadados.get("dados", {}).get("pares_treino"),
                "perda_final": metadados.get("treino", {}).get("perda_final"),
                "criado_em": metadados.get("treino", {}).get("concluido_em"),
                "origem": "soup" if candidato.name.startswith("soup-") else "plataforma",
                "atual": candidato.resolve() == Path(DEFAULT_ADAPTER_DIR).resolve(),
            }
        )
    return lista


def resolver_adaptador(identificador: str | None, raiz: Path | str | None = None) -> Path:
    """Caminho do adaptador pedido (ou o predefinido quando não vem nenhum).

    Só aceita um `id` que conste da lista de adaptadores conhecidos: o valor vem
    de um pedido HTTP e não pode escolher um diretório arbitrário do disco.
    """
    if not identificador:
        return Path(DEFAULT_ADAPTER_DIR)
    for item in listar_adaptadores(raiz):
        if identificador in (item["id"], item["nome"]):
            if not item["compativel"]:
                raise ValueError(
                    f"adaptador {item['id']} foi treinado sobre {item['base']}, "
                    f"não sobre {DEFAULT_BASE_MODEL}"
                )
            return Path(item["caminho"])
    raise ValueError(f"adaptador desconhecido: {identificador}")


def split_indices(total: int, holdout: int, seed: int = 42) -> tuple[list[int], list[int]]:
    """Divide `total` linhas em treino e held-out de forma **estável**.

    Baralha com a semente antes de cortar: o exporter grava as linhas agrupadas
    por fonte (primeiro todos os contratos, depois as entidades, depois as
    subvenções), por isso cortar as últimas N linhas daria um held-out só de
    subvenções — e um `--max-pairs` pequeno treinaria só contratos. Com a
    baralha determinística, qualquer prefixo já é uma amostra das três fontes e
    a divisão é a mesma em todas as corridas.
    """
    indices = list(range(max(0, int(total))))
    random.Random(seed).shuffle(indices)
    holdout = max(0, min(int(holdout), len(indices)))
    return indices[holdout:], indices[:holdout]


# ---------------------------------------------------------------------------
# Inferência
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cache: Dict[str, Any] = {}


def _load(base_model: str, adapter_dir: Path | str, adapter: bool):
    """Carrega base + adaptador LoRA (uma vez por processo)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    threads = int(os.environ.get("LLMFINANCE_CPU_THREADS", "8"))
    torch.set_num_threads(threads)

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForCausalLM.from_pretrained(base_model, dtype=torch.float32)
    if adapter and adapter_available(adapter_dir):
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(adapter_dir))
        model = model.merge_and_unload()
    model.eval()
    return tokenizer, model


def get_model(base_model: str = DEFAULT_BASE_MODEL, adapter_dir: Path | str = DEFAULT_ADAPTER_DIR, adapter: bool = True):
    """Devolve `(tokenizer, model)` do cache do processo (carregamento pesado)."""
    key = f"{base_model}|{adapter_dir}|{int(adapter)}"
    with _lock:
        if key not in _cache:
            _cache[key] = _load(base_model, adapter_dir, adapter)
        return _cache[key]


def limpar_cache() -> None:
    """Esquece o modelo carregado (o adaptador foi reescrito por uma adaptação)."""
    with _lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Guarda numérica
# ---------------------------------------------------------------------------

#: Cache dos ids do vocabulário que são só dígitos/separadores, por tokenizer.
_ids_numericos: Dict[int, Dict[int, str]] = {}


def _digitos(texto: str) -> str:
    return "".join(c for c in texto if c in "0123456789")


def ids_numericos(tokenizer) -> Dict[int, str]:
    """Ids do vocabulário que escrevem números → os seus dígitos.

    Um modelo de 0,5 B inventa datas e valores («publicado a 19/07/2019» num
    contrato que não traz data). Bloquear, na geração, os tokens que formariam um
    número ausente do documento resolve isso na origem — e é determinístico, ao
    contrário de pedir ao modelo que se contenha.
    """
    chave = id(tokenizer)
    if chave in _ids_numericos:
        return _ids_numericos[chave]
    mapa: Dict[int, str] = {}
    try:
        vocabulario = tokenizer.get_vocab()
    except (AttributeError, NotImplementedError):  # pragma: no cover
        vocabulario = {}
    for token, token_id in vocabulario.items():
        texto = token.replace("Ġ", " ").replace("▁", " ").strip()
        # Só ASCII: dígitos de largura completa («０») e afins ficavam no mapa
        # sem nunca casar com um número permitido — bloqueados para sempre.
        if texto and all(c in "0123456789.,-/:" for c in texto) and _digitos(texto):
            mapa[token_id] = _digitos(texto)
    _ids_numericos[chave] = mapa
    return mapa


def _permitidos(contexto: str, extra: str = "") -> set:
    """Dígitos aceitáveis: os números que o contexto contém, sem zeros à direita."""
    from inference import contratos_eval

    numeros = set()
    for texto in (contexto or "", extra or ""):
        for valor in contratos_eval.numeric_tokens(texto):
            inteiro, _, decimal = str(valor).partition(".")
            digitos_inteiro = _digitos(inteiro)
            if not digitos_inteiro:
                continue
            numeros.add(digitos_inteiro)
            decimal = decimal.rstrip("0")
            if decimal:
                numeros.add(digitos_inteiro + _digitos(decimal))
    return numeros


class GuardaNumerica:
    """`LogitsProcessor` que proíbe números que não existem no documento.

    A cada passo olha para os dígitos já escritos (`buffer`): se estiverem a meio
    de um número, só deixa continuar tokens cujo resultado seja **prefixo** de um
    número permitido. Assim `20806.2` pode ser escrito (está no documento) e
    `208 062,20` — a duplicação que aparecia no chat — fica bloqueado assim que
    diverge.
    """

    def __init__(self, tokenizer, contexto: str, extra: str = ""):
        self.mapa = ids_numericos(tokenizer)
        self.permitidos = _permitidos(contexto, extra) or {"0"}
        self.ativos = set(self.mapa)
        self._ultimo: Optional[int] = None

    def __call__(self, input_ids, scores):
        import torch

        ultimo = int(input_ids[0, -1]) if input_ids.shape[-1] else None
        buffer = ""
        if ultimo in self.mapa:
            texto = input_ids[0, -8:].tolist()
            pedacos = []
            for token_id in reversed(texto):
                if token_id not in self.mapa:
                    break
                pedacos.append(self.mapa[token_id])
            buffer = "".join(reversed(pedacos))
        if not buffer:
            self._ultimo = ultimo
            return scores
        bloqueados = []
        for token_id in self.ativos:
            candidato = buffer + self.mapa[token_id]
            # O número **permitido** tem de começar pelo que já se escreveu:
            # «20» é prefixo de «20806» (ok), «201» não é (bloqueado).
            if not any(permitido.startswith(candidato) for permitido in self.permitidos):
                bloqueados.append(token_id)
        if bloqueados:
            scores = scores.clone()
            scores[:, bloqueados] = -float("inf")
        self._ultimo = ultimo
        return scores


def answer(
    instruction: str,
    data: str,
    *,
    base_model: str = DEFAULT_BASE_MODEL,
    adapter_dir: Path | str = DEFAULT_ADAPTER_DIR,
    adapter: bool = True,
    max_new_tokens: int = 160,
    temperature: float = 0.2,
    sistema: Optional[str] = None,
    contexto: Optional[str] = None,
    devolver_tokens: bool = False,
    guarda_numerica: Optional[bool] = None,
) -> Dict[str, Any]:
    """Gera a resposta do modelo afinado para um documento do Elasticsearch.

    Com `devolver_tokens`, devolve também a probabilidade que o modelo deu a cada
    token gerado — é a matéria-prima do diagrama «como é que ele chegou aqui»
    (uma resposta com tokens de 0,2 de probabilidade é um palpite).

    `guarda_numerica` (por omissão ligada quando há documento) impede a geração
    de escrever números que não estejam no documento/contexto — é o que garante
    que a verificação da resposta não encontra valores inventados.
    """
    import torch

    tokenizer, model = get_model(base_model, adapter_dir, adapter)
    prompt = render_chat_prompt(tokenizer, instruction, data, sistema=sistema, contexto=contexto)
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1536)
    prompt_len = inputs["input_ids"].shape[-1]

    if guarda_numerica is None:
        guarda_numerica = os.environ.get("LLMFINANCE_GUARDA_NUMERICA", "1") != "0"
    guardas = []
    if guarda_numerica and (data or contexto):
        guardas.append(GuardaNumerica(tokenizer, contexto or "", data or ""))

    with torch.no_grad():
        saida = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else 1.0,
            top_p=0.9,
            # 1,05 deixava o modelo em ciclo («o CPV principal principal é»).
            # 1,15 impunha pena a tokens legítimos e saía texto cosido
            # («Tecnopublicamente»); 1,08 corta a repetição sem estragar palavras.
            # `no_repeat_ngram_size` **não** se usa aqui: proíbe qualquer 3-grama
            # repetido (incluindo os do prompt) e um modelo de 0,5 B desfaz-se a
            # inventar alternativas — foi o que produziu «Instituto Superior
            # Tecnopublicamente contratou».
            repetition_penalty=1.08,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            output_scores=devolver_tokens,
            return_dict_in_generate=devolver_tokens,
            logits_processor=guardas or None,
        )
    sequencia = saida.sequences if devolver_tokens else saida
    gerados = sequencia[0][prompt_len:]
    text = tokenizer.decode(gerados, skip_special_tokens=True).strip()
    resultado: Dict[str, Any] = {
        "resposta": text,
        "modelo": base_model,
        "adaptador": str(adapter_dir) if adapter and adapter_available(adapter_dir) else None,
        "prompt_tokens": int(prompt_len),
        "tokens_gerados": int(sequencia.shape[-1] - prompt_len),
    }
    if devolver_tokens:
        tokens: List[Dict[str, Any]] = []
        for i, token_id in enumerate(gerados.tolist()):
            entrada: Dict[str, Any] = {"token": tokenizer.decode([token_id]), "id": token_id}
            if i < len(saida.scores):
                distribuicao = torch.softmax(saida.scores[i][0], dim=-1)
                probabilidade = float(distribuicao[token_id])
                entrada["probabilidade"] = round(probabilidade, 4)
                # Entropia normalizada: 0 = certeza absoluta, 1 = indecisão total.
                entrada["entropia"] = round(float(-(distribuicao * torch.log(distribuicao + 1e-12)).sum()) / 12.0, 3)
            tokens.append(entrada)
        resultado["tokens"] = tokens
        if tokens:
            probs = [t.get("probabilidade", 0.0) for t in tokens if "probabilidade" in t]
            resultado["confianca_media"] = round(sum(probs) / len(probs), 4) if probs else None
    return resultado
