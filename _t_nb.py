"""Testa se `{nb}` do fpdf2 e' substituido quando o rodape' e' ligado assim.

Isola o comportamento num documento minimo, para não andar às voltas no
gerador real.
"""

from fpdf import FPDF

ATTR = "__marca__"


def build() -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=24)
    pdf.set_margins(18, 18, 18)

    def footer():
        pdf.set_y(-20)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 4, f"rodape: pagina {pdf.page_no()} de {{nb}}", new_x="LMARGIN", new_y="NEXT")

    pdf.footer = footer
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    for i in range(3):
        pdf.cell(0, 6, f"conteudo da pagina 1, linha {i}", new_x="LMARGIN", new_y="NEXT")
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, "conteudo da pagina 2", new_x="LMARGIN", new_y="NEXT")

    # Duas passagens: com o total ja' conhecido, o rodape pode ser escrito
    # sem depender do `{nb}`.
    return bytes(pdf.output())


data = build()
open("/tmp/_nb.pdf", "wb").write(data)
print(f"bytes={len(data)} paginas={data.count(b'/Type /Page') - data.count(b'/Type /Pages')}")
print("alias literal presente no binario:", b"{nb}" in data)
