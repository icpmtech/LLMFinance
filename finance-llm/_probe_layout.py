import pathlib, tempfile
from api import reports_studio as studio, reports_store as store
tmp = pathlib.Path(tempfile.mkdtemp())
store.REPORTS_DIR = tmp / "reports"; store.REPORTS_PATH = tmp / "reports" / "reports.json"; store.FILES_DIR = tmp / "reports" / "files"
studio.STUDIO_DIR = tmp / "reports" / "studio"
store.reset_for_tests(); studio.reset_for_tests()
rel = studio.create_report({"template": "dossie", "title": "Dossie validacao"}, actor="prova")["report"]
res = studio.attach_pdf(rel["id"], "prova", {"user_id": "u", "email": "prova@iq.os", "see_all": True})
print("pdf", res["file"]["name"], res["file"]["size"])
import pymupdf
path = studio.report_dir(rel["id"]) / f"{res['file']['id']}-{res['file']['name']}"
doc = pymupdf.open(str(path))
print("paginas", doc.page_count)
texto = "\n".join(p.get_text() for p in doc)
print("email apoio:", studio.support_email() in texto)
print("compacto:", "mM" in texto or "mil" in texto)
W = 595.3
problemas = 0
for pg in doc:
    spans = [(s["bbox"], s["text"]) for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    for bb, t in spans:
        if bb[0] < 17 or bb[2] > W - 17:
            problemas += 1
            print("  fora da margem:", t[:40])
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            a, b2 = spans[i][0], spans[j][0]
            if not (a[2] <= b2[0] or b2[2] <= a[0] or a[3] <= b2[1] or b2[3] <= a[1]):
                ov = (min(a[2], b2[2]) - max(a[0], b2[0])) * (min(a[3], b2[3]) - max(a[1], b2[1]))
                if ov > 12:
                    problemas += 1
                    print(f"  sobreposicao {ov:.0f}: {spans[i][1][:26]!r} <-> {spans[j][1][:26]!r}")
print("problemas:", problemas)
