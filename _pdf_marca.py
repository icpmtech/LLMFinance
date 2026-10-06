"""Gera os PDF (ficha + relatorio) dentro do container, para inspecao.

Corre com o venv do backend: `/app/backend/.venv/bin/python /tmp/_pdf_marca.py`.
"""

import pathlib
import sys

sys.path.insert(0, "/app/backend")

from app.api import iqos_export as x  # noqa: E402

simulations = sorted(pathlib.Path(x.SIM_DIR).glob("sim_*"))
if not simulations:
    raise SystemExit("sem simulacoes no volume")

sim_id = simulations[0].name
ficha = x._simulation_pdf(sim_id)
pathlib.Path("/tmp/ficha-marca.pdf").write_bytes(ficha)
print(f"ficha {sim_id}: {len(ficha)}B paginas={ficha.count(b'/Type /Page') - ficha.count(b'/Type /Pages')}")

reports = x._reports_for(sim_id)
if not reports:
    raise SystemExit(f"{sim_id} sem relatorio")
report_id = reports[-1]
relatorio = x._report_pdf(report_id)
pathlib.Path("/tmp/relatorio-marca.pdf").write_bytes(relatorio)
print(
    f"relatorio {report_id}: {len(relatorio)}B "
    f"paginas={relatorio.count(b'/Type /Page') - relatorio.count(b'/Type /Pages')}"
)
