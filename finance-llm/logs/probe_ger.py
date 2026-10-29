"""Compara variantes de geracao e adaptadores (apagar depois)."""
import sys, time
sys.path.insert(0, "/app")
from inference import contratos_lora

CONTRATO = (
    "Contrato 900001 - Aquisicao de reagentes de laboratorio\n"
    "Adjudicante: Instituto Superior Tecnico\n"
    "Adjudicatario: LABQUIMICA - EQUIPAMENTOS E REAGENTES, LDA\n"
    "Procedimento: Concurso publico | Tipo: Aquisicao de bens moveis\n"
    "Preco contratual: 15430.75 | Data de publicacao: 2024-03-11\n"
    "Regime: Codigo dos Contratos Publicos | CPV principal: Reagentes de laboratorio"
)
inicio = time.time()
r = contratos_lora.answer("Descreve este contrato publico portugues.", CONTRATO, adapter=True, max_new_tokens=140, temperature=0.2)
print("=== atual (penalty 1.08, sem ngram) %.0fs ===" % (time.time()-inicio))
print(r["resposta"])
