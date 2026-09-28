"""Verificação do registo de regras (puro, ficheiro temporário)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

tmp = Path(tempfile.gettempdir()) / "padroes_regras_qa.json"
tmp.unlink(missing_ok=True)
os.environ["PADROES_REGRAS_PATH"] = str(tmp)

from api import padroes_regras as r  # noqa: E402

r.reset_state_cache()

estado = r.listar()
print("predefinidas:", len(estado["regras"]), "| templates:", len(estado["templates"]))
print("ficheiro criado:", tmp.is_file())
for regra in estado["regras"][:4]:
    resumo = r.resumo_regras([regra])[0]
    print(f"  - {resumo['id']:26s} {resumo['severidade']:6s} {resumo['condicao']}")

contexto = {
    "valor": 40000.0,
    "n_concorrentes": 1,
    "ratio_base": 1.35,
    "ratio_efetivo": 1.30,
    "ajuste_direto": 1,
    "taxa_ajuste_direto_cpv": 0.1,
    "taxa_ajuste_direto_global": 0.6,
    "z_cpv": 5.2,
    "dias_publicacao": 300,
}
hits = r.avaliar(contexto, r.regras_ativas())
print("\nhits no contrato de teste:", [h["padrao"] for h in hits])
print("detalhe 1:", json.dumps(hits[0]["detalhe"], ensure_ascii=False)[:160])

# criar uma regra personalizada
nova = r.guardar(
    {
        "label": "Grande contrato sem concurso",
        "descricao": "Mais de 5 M€ por ajuste direto",
        "severidade": "alerta",
        "modo": "todas",
        "condicoes": [
            {"campo": "valor", "operador": ">", "valor": 5_000_000},
            {"campo": "ajuste_direto", "operador": "==", "valor": 1},
        ],
    }
)
print("\ncriada:", nova["id"], nova["label"], "| origem:", nova["origem"])

# template
template = r.guardar_template({"nome": "Foco em ajuste direto", "descricao": "Regras de procedimento"})
print("template guardado:", template["nome"], "com", len(template["regras"]), "regras")
aplicado = r.aplicar_template(template["id"])
print("aplicado:", aplicado["nome"], "| ativas:", len(aplicado["ativas"]))
print("contagem de ativas depois:", len(r.regras_ativas()))

# duplicar / alternar / apagar
copia = r.duplicar("aditivo_valor")
print("\ncópia:", copia["id"], copia["label"])
r.alternar(copia["id"], False)
print("cópia ativa?", next(item for item in r.listar()["regras"] if item["id"] == copia["id"])["ativo"])
print("apagar cópia:", r.apagar(copia["id"]), "| apagar inexistente:", r.apagar("nao_existe"))

# validação
for invalido in (
    {"label": "x", "condicoes": [{"campo": "desconhecido", "operador": ">", "valor": 1}]},
    {"label": "x", "condicoes": [{"campo": "valor", "operador": "contem", "valor": "x"}]},
    {"label": "x", "condicoes": []},
    {"label": "x", "condicoes": [{"campo": "valor", "operador": ">", "valor": "abc"}]},
):
    try:
        r.validar(invalido)
        print("FALHOU a rejeitar:", invalido)
    except ValueError as exc:
        print("rejeitado bem:", str(exc)[:60])

print("\nrepor predefinições:", r.repor_default())
print("regras depois de repor:", len(r.listar()["regras"]), "| ativas:", len(r.regras_ativas()))
tmp.unlink(missing_ok=True)
print("limpo:", not tmp.exists())
