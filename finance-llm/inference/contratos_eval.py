"""Avaliação do modelo de contratos: o adaptador aprendeu, ou decorou?

Mede o **mesmo** conjunto held-out (as linhas que o treino nunca viu) antes e
depois do adaptador LoRA, com duas famílias de métricas:

1. **Perda e exatidão por token** — a medida barata e estável: `perplexidade`
   diz quanto o modelo hesita na resposta certa, `exactidao_token` diz quantas
   vezes o token mais provável é o do gabarito. Só contam os tokens da
   resposta (o prompt fica mascarado, como no treino).
2. **Fidelidade do que é gerado** — a medida que interessa ao utilizador:
   `f1` compara as palavras da resposta gerada com as do gabarito, e
   `numeros` verifica se os valores em euros, NIF e datas do gabarito
   aparecem na resposta. Um modelo que troca 20 806,20 € por 20,00 € falha
   aqui mesmo que a perplexidade baixe.

A lógica vive aqui (e não em `training/`) porque a pasta `training/` fica fora
do contexto das imagens Docker: o backend tem de conseguir correr uma avaliação
a pedido da rota `/llm/modelo/avaliar`. A CLI está em
`training/eval_lora_contratos.py`.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inference.contratos_lora import (  # noqa: E402
    DEFAULT_ADAPTER_DIR,
    DEFAULT_BASE_MODEL,
    adapter_available,
    render_chat_prompt,
    split_indices,
)

DATA_FILE = ROOT / "data" / "final" / "iqos_contratos_empresas_qwen.jsonl"

_NUMERO = re.compile(r"\d[\d\s.,]*\d|\d")
_PALAVRA = re.compile(r"[a-zà-ÿ0-9]+", re.IGNORECASE)


def _normalizar_numero(bruto: str) -> Optional[str]:
    """Normaliza um número escrito à portuguesa ou à inglesa.

    «20 806,20» (pt) e «20806.2» (en) têm de dar o mesmo valor: sem esta
    distinção, o ponto era sempre tratado como separador de milhares e
    «20806.2» virava 208 062 — a verificação acusava um valor inventado que
    estava à frente dos olhos.
    """
    limpo = bruto.replace(" ", "").replace("\u00a0", "")
    if "," in limpo:
        # vírgula decimal: os pontos são milhares
        limpo = limpo.replace(".", "").replace(",", ".")
    elif limpo.count(".") > 1:
        # vários pontos e sem vírgula: são milhares («1.234.567»)
        limpo = limpo.replace(".", "")
    try:
        return f"{float(limpo):.2f}"
    except ValueError:
        return None


def numeric_tokens(text: str) -> List[str]:
    """Extrai valores normalizados (20 806,20 € → 20806.20) para comparar."""
    valores: List[str] = []
    for bruto in _NUMERO.findall(text or ""):
        normalizado = _normalizar_numero(bruto)
        if normalizado is not None:
            valores.append(normalizado)
    return valores


def token_f1(predicao: str, gabarito: str) -> float:
    """F1 por multiconjunto de palavras — a métrica clássica de SQuAD."""
    p = _PALAVRA.findall((predicao or "").lower())
    g = _PALAVRA.findall((gabarito or "").lower())
    if not p or not g:
        return 0.0
    iguais = sum((Counter(p) & Counter(g)).values())
    if not iguais:
        return 0.0
    precisao = iguais / len(p)
    cobertura = iguais / len(g)
    return 2 * precisao * cobertura / (precisao + cobertura)


def numeric_fidelity(predicao: str, gabarito: str) -> Optional[float]:
    """Fracção dos números do gabarito que aparecem na resposta (None se não há)."""
    alvo = numeric_tokens(gabarito)
    if not alvo:
        return None
    obtidos = set(numeric_tokens(predicao))
    return sum(1 for v in alvo if v in obtidos) / len(alvo)


def numeric_grounding(predicao: str, dados: str) -> Optional[Dict[str, Any]]:
    """Números que a resposta cita e que **não estão no pedido** (invenção).

    `numeric_fidelity` mede se os números do gabarito aparecem; não diz nada
    sobre números a mais. E o defeito que este projeto teve foi exactamente um
    número a mais: com um contrato sem data, a resposta dizia «publicado a
    2021-08-26». Aqui conta-se ao contrário — de todos os números que o modelo
    escreveu, quantos existem no documento. É a métrica que falha quando ele
    inventa.
    """
    citados = numeric_tokens(predicao)
    if not citados:
        return None
    fonte = set(numeric_tokens(dados))
    inventados = [valor for valor in citados if valor not in fonte]
    return {
        "citados": len(citados),
        "inventados": inventados,
        "taxa": round(len(inventados) / len(citados), 4),
    }


def load_pairs(path: Path | str = DATA_FILE) -> List[Dict[str, Any]]:
    """Lê o JSONL Alpaca exportado do Elasticsearch."""
    rows: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def held_out_pairs(
    rows: List[Dict[str, Any]], holdout: int = 60, seed: int = 42, limite: int = 0
) -> List[Dict[str, Any]]:
    """Os pares que o treino reservou (`split_indices` com a mesma semente)."""
    _, idx = split_indices(len(rows), holdout, seed)
    pares = [rows[i] for i in idx]
    return pares[:limite] if limite else pares


def _perda_e_exatidao(model, tokenizer, pares: List[Dict[str, Any]]) -> Dict[str, float]:
    """Perda média por token da resposta e exatidão da previsão seguinte."""
    import torch

    total_perda, total_tokens, acertos = 0.0, 0, 0
    model.eval()
    with torch.no_grad():
        for row in pares:
            prompt_ids = tokenizer(
                render_chat_prompt(tokenizer, row.get("instruction", ""), row.get("input", "")),
                add_special_tokens=False,
            )["input_ids"]
            alvo_ids = tokenizer(str(row.get("output", "")).strip(), add_special_tokens=False)["input_ids"]
            if not alvo_ids:
                continue
            ids = torch.tensor([prompt_ids + alvo_ids])
            labels = torch.tensor([[-100] * len(prompt_ids) + alvo_ids])
            saida = model(input_ids=ids, labels=labels)
            total_perda += float(saida.loss) * len(alvo_ids)
            total_tokens += len(alvo_ids)
            logits = saida.logits[0, len(prompt_ids) - 1 : -1]
            acertos += int((logits.argmax(-1) == torch.tensor(alvo_ids)).sum())
    if not total_tokens:
        return {"perda_por_token": 0.0, "perplexidade": 0.0, "exactidao_token": 0.0, "tokens": 0}
    media = total_perda / total_tokens
    return {
        "perda_por_token": round(media, 4),
        "perplexidade": round(math.exp(min(media, 20)), 2),
        "exactidao_token": round(acertos / total_tokens, 4),
        "tokens": total_tokens,
    }


def _gerar(model, tokenizer, row: Dict[str, Any], max_new_tokens: int = 120) -> str:
    import torch

    prompt = render_chat_prompt(tokenizer, row.get("instruction", ""), row.get("input", ""))
    ids = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
    with torch.no_grad():
        saida = model.generate(
            **ids,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(saida[0][ids["input_ids"].shape[-1] :], skip_special_tokens=True).strip()


def score_model(
    model, tokenizer, pares: List[Dict[str, Any]], gerar: int = 0, etiqueta: str = ""
) -> Dict[str, Any]:
    """Perda/exatidão em todos os pares + fidelidade nos `gerar` primeiros."""
    resultado: Dict[str, Any] = _perda_e_exatidao(model, tokenizer, pares)
    if gerar:
        amostras = []
        for row in pares[:gerar]:
            texto = _gerar(model, tokenizer, row)
            ancoragem = numeric_grounding(texto, row.get("input", ""))
            amostras.append(
                {
                    "instrucao": row.get("instruction", ""),
                    "dados": row.get("input", ""),
                    "gabarito": row.get("output", ""),
                    "gerado": texto,
                    "f1": round(token_f1(texto, row.get("output", "")), 4),
                    "numeros": numeric_fidelity(texto, row.get("output", "")),
                    "ancoragem": ancoragem,
                }
            )
        f1s = [a["f1"] for a in amostras]
        nums = [a["numeros"] for a in amostras if a["numeros"] is not None]
        taxas = [a["ancoragem"]["taxa"] for a in amostras if a.get("ancoragem")]
        resultado["geracao"] = {
            "amostras": amostras,
            "f1_medio": round(statistics.mean(f1s), 4) if f1s else 0.0,
            "fidelidade_numerica": round(statistics.mean(nums), 4) if nums else None,
            # 1,0 = todos os números da resposta estão no documento; 0,0 = todos
            # foram inventados. É a métrica que apanha a data/regime inventados.
            "ancoragem_numerica": round(statistics.mean(taxas), 4) if taxas else None,
        }
    if etiqueta:
        resultado["modelo"] = etiqueta
    return resultado


def evaluate(
    *,
    pairs_path: Path | str = DATA_FILE,
    base_model: str = DEFAULT_BASE_MODEL,
    adapter_dir: Path | str = DEFAULT_ADAPTER_DIR,
    holdout: int = 60,
    seed: int = 42,
    limite: int = 12,
    gerar: int = 3,
) -> Dict[str, Any]:
    """Compara base e adaptador no held-out. Importável pela API (`/avaliar`)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    rows = load_pairs(pairs_path)
    pares = held_out_pairs(rows, holdout=holdout, seed=seed, limite=limite)
    if not pares:
        raise ValueError("o conjunto held-out está vazio — reduza o --holdout")

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    inicio = time.time()

    base = AutoModelForCausalLM.from_pretrained(base_model, dtype=torch.float32)
    base.eval()
    resultado: Dict[str, Any] = {
        "conjunto": {
            "ficheiro": Path(pairs_path).name,
            "pares": len(pares),
            "holdout_total": holdout,
            "origem": sorted({str(p.get("metadata", {}).get("fonte", "?")) for p in pares}),
        },
        "base": score_model(base, tokenizer, pares, gerar=gerar, etiqueta="base"),
    }

    if adapter_available(adapter_dir):
        from peft import PeftModel

        treinado = PeftModel.from_pretrained(base, str(adapter_dir))
        treinado.eval()
        resultado["treinado"] = score_model(treinado, tokenizer, pares, gerar=gerar, etiqueta="adaptador")
        b, t = resultado["base"], resultado["treinado"]
        resultado["delta"] = {
            "perplexidade": round(t["perplexidade"] - b["perplexidade"], 2),
            "exactidao_token": round(t["exactidao_token"] - b["exactidao_token"], 4),
        }
        if "geracao" in b and "geracao" in t:
            resultado["delta"]["f1_medio"] = round(t["geracao"]["f1_medio"] - b["geracao"]["f1_medio"], 4)
    else:
        resultado["treinado"] = None
        resultado["nota"] = f"sem adaptador em {adapter_dir}: medido só o modelo base"

    resultado["duracao_s"] = round(time.time() - inicio, 1)
    resultado["criado_em"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return resultado
