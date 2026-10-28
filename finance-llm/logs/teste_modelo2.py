"""Testa o modelo de contratos directamente (sem RAG/memoria/skills)."""
from __future__ import annotations
import json, re, sys, time
sys.path.insert(0, "/app")
from inference import contratos_lora

CONTRATO = (
    "Contrato 900001 - Aquisicao de reagentes de laboratorio\n"
    "Adjudicante: Instituto Superior Tecnico\n"
    "Adjudicatario: LABQUIMICA - EQUIPAMENTOS E REAGENTES, LDA\n"
    "Tipo: Aquisicao de bens moveis\n"
    "Procedimento: Concurso publico\n"
    "Preco contratual: 15430.75\n"
    "Descricao: Reagentes e consumiveis para o laboratorio de quimica analitica"
)
CASOS = [
    ("contrato_grounding", "Descreve este contrato publico portugues."),
    ("auditar", "Audita este contrato e aponta os riscos de contratacao publica."),
    ("pergunta_cidada", "Explica a um cidadao, sem jargao, o que foi comprado e por quanto."),
]
_NUM = re.compile(r"\d[\d\s.,]*\d|\d")
LIMITES = [15430.75, 900001.0, 0.0]

def fora(texto):
    achados = []
    for bruto in _NUM.findall(texto):
        limpo = bruto.replace(" ", "").strip(".")
        if not limpo:
            continue
        if "," in limpo:
            valor = float(limpo.replace(".", "").replace(",", "."))
        else:
            valor = float(limpo)
        if any(abs(valor - alvo) < 0.01 for alvo in LIMITES):
            continue
        achados.append(bruto.strip())
    return achados

saida = {}
for nome, instrucao in CASOS:
    inicio = time.time()
    r = contratos_lora.answer(instrucao, CONTRATO, adapter=True, max_new_tokens=160, temperature=0.2)
    seg = time.time() - inicio
    inv = fora(r["resposta"])
    print("\n=== %s (%.0fs) ===" % (nome, seg), flush=True)
    print(r["resposta"], flush=True)
    if inv:
        print("! NUMEROS INVENTADOS:", inv, flush=True)
    saida[nome] = {"texto": r["resposta"], "inventados": inv, "segundos": round(seg, 1)}
with open("/tmp/teste_modelo_antes.json", "w", encoding="utf-8") as fh:
    json.dump(saida, fh, ensure_ascii=False, indent=1)
