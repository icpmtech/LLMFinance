"""Validacao do pipeline de despesas municipais (sem indexar)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api import municipios_service as M  # noqa: E402

ine = M.recolher_ine()
print("meta:", json.dumps({k: v for k, v in ine["meta"].items() if k != "nuts"}, ensure_ascii=False, indent=1))
print("nuts disponiveis:", len(ine["meta"]["nuts"]))

contratos = M.agregar_contratos()
print("adjudicantes municipais agregados:", len(contratos["adjudicantes"]))
print("concelhos com distrito:", len(contratos["distritos"]))

registos, diag = M.construir_registos(ine, contratos)
print("\ndiagnostico:", json.dumps({k: v for k, v in diag.items() if not k.startswith("exemplos")}, ensure_ascii=False, indent=1))
print("exemplos nao atribuidos:", diag["exemplos_nao_atribuidos"])
print("exemplos ambiguos:", diag["exemplos_ambiguos"])

com_contratos = sorted(
    (r for r in registos if r.get("contratos_total")),
    key=lambda r: -(r.get("contratos_valor") or 0),
)[:8]
print("\ntop municipios por valor contratado:")
for r in com_contratos:
    print(
        f"   {r['nome']:<26} distrito={r.get('distrito') or '-' :<14} "
        f"despesas={r.get('despesas_total') or 0:>15,.0f} EUR  "
        f"contratos={r.get('contratos_total'):>6}  {(r.get('contratos_valor') or 0)/1e6:>9.1f} M EUR  "
        f"adj={len(r.get('adjudicantes') or [])}"
    )

sem_distrito = [r["nome"] for r in registos if not r.get("distrito")]
print("\nsem distrito:", len(sem_distrito), sem_distrito[:12])

amostra = next(r for r in registos if r["nome"] == "Abrantes")
print("\nexemplo Abrantes:")
print(json.dumps({
    k: v for k, v in amostra.items()
    if k not in ("despesas_por_ano", "classificadores", "contratos_por_ano")
}, ensure_ascii=False, indent=1))
print("despesas_por_ano:", json.dumps(amostra.get("despesas_por_ano"), ensure_ascii=False)[:300])
print("adjudicantes:", json.dumps(amostra.get("adjudicantes"), ensure_ascii=False))

Path(__file__).resolve().parent.joinpath("saida_registos.json").write_text(
    json.dumps({"fichas": registos, "diagnostico": diag}, ensure_ascii=False, indent=1), encoding="utf-8"
)
print("\nOK")
