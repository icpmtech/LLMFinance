"""Sonda: exercita o trabalhador de importação da API (`_run_import`) sem passar pelo HTTP."""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import contratos_es_routes as routes  # noqa: E402

job_id = "probe0001"
routes._jobs[job_id] = {"id": job_id, "state": "queued", "created_at": "", "finished": False}
req = routes.ContratoEsImportRequest(fonte="menores", ano=2023, limit=1500, index=True)
routes._run_import(job_id, req)
time.sleep(0.5)
job = routes._jobs[job_id]
print("estado:", job.get("state"))
print("etapa:", job.get("stage"))
print("mensagem:", job.get("message"))
print("docs:", job.get("docs"), "indexados:", job.get("indexed"))
print("resultados:", job.get("results"))
