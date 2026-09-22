"""Testes do coletor das publicações do MJ (amostras fiéis ao HTML real)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors.publicacoes_mj import (  # noqa: E402
    PublicacaoMJ,
    PublicacoesMjClient,
    _captcha_rejected,
    _grid_html,
    form_state,
    parse_detalhe,
)

# --- amostras ---------------------------------------------------------

GRID_HTML = """
<table class="searchtable_pesquisa" cellspacing="0" rules="rows" border="1"
       id="ctl00_ContentPlaceHolderMain_gvSearchResult" style="border-collapse:collapse;">
  <tr class="headerRow">
    <th scope="col">Data</th><th scope="col">NIF/NIPC</th><th scope="col">Entidade</th>
    <th scope="col">Concelho</th><th scope="col">Acto/Facto</th>
    <th scope="col">&nbsp;</th><th scope="col">&nbsp;</th><th scope="col">&nbsp;</th>
  </tr>
  <tr class="normalRow">
    <td>2026-07-21</td><td>500273170</td><td>SONAE - SGPS, S.A.</td>
    <td>Maia                    </td><td>PRESTA&#199;&#195;O DE CONTAS CONSOLIDADAS</td>
    <td><a href="javascript:__doPostBack('ctl00$ContentPlaceHolderMain$gvSearchResult','Conteudo$0')">Conte&uacute;do</a></td>
    <td><a href="javascript:__doPostBack('ctl00$ContentPlaceHolderMain$gvSearchResult','Documento$0')"></a></td><td></td>
  </tr>
  <tr class="alternateRow">
    <td>2024-12-04</td><td>500273170</td><td>SONAE SGPS SA</td><td>Maia</td><td>An&uacute;ncio</td>
    <td></td><td><a href="javascript:__doPostBack('ctl00$ContentPlaceHolderMain$gvSearchResult','Documento$1')">Documento</a></td><td></td>
  </tr>
  <tr class="footerRow">
    <td colspan="8"><table border="0"><tr>
      <td><a href="javascript:__doPostBack('ctl00$ContentPlaceHolderMain$gvSearchResult','Page$Next')">Pr&oacute;ximos &gt;</a></td>
    </tr></table></td>
  </tr>
</table>
<div id="ctl00_ContentPlaceHolderMain_divSearchResult"><span>Resultado da pesquisa (1-20 de 200)</span></div>
"""

DETALHE_HTML = """
<table><tr><td>Publica&ccedil;&atilde;o</td></tr>
  <tr><td><table>
    <tr><td>NIF/NIPC</td><td>500273170</td></tr>
    <tr><td>Entidade</td><td>SONAE - SGPS, S.A.</td></tr>
    <tr><td>Data Publica&ccedil;&atilde;o</td><td>2026-07-21</td></tr>
  </table></td></tr>
  <tr><td><table><tr><td>Publica-se que em rela&ccedil;&atilde;o &agrave; entidade:</td></tr></table></td></tr>
  <tr><td><table><tr><td>
N&ordm; de Matr&iacute;cula/NIPC: 500273170
Firma: SONAE - SGPS, S.A.
Natureza Jur&iacute;dica: SOCIEDADE AN&oacute;NIMA
Sede: VIA NORTE-ESPIDO
Distrito: Porto Concelho: Maia Freguesia: Cidade da Maia
4470 MAIA
Matriculada na: 2&ordf; CRPC Maia
pelo pedido Dep 2763/2026-07-21, foi efectuado o seguinte acto de registo:
DEP 2763/2026-07-21 03:05:00 UTC - PRESTA&Ccedil;&Atilde;O DE CONTAS CONSOLIDADAS
Ano da Presta&ccedil;&atilde;o de Contas: 2025 (2025-01-01 a 2025-12-31)
Requerente e Respons&aacute;vel pelo Registo: SONAE SOC GESTORA PARTICIPACOES SOCIAIS SA
Men&ccedil;&atilde;o realizada nos termos do Decreto-Lei n&ordm;. 8/2007 de 17 Janeiro
  </td></tr></table></td></tr>
</table>
"""

FORM_HTML = """
<form name="aspnetForm" method="post" action="./Pesquisa.aspx" id="aspnetForm">
  <input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="/wEPDwUKMTEx&amp;abc" />
  <input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="xyz123" />
  <input name="ctl00$ContentPlaceHolderMain$txtDadosPubNif" type="text" value="500273170" />
  <input type="radio" name="ctl00$ContentPlaceHolderMain$rblTipoPub" value="0" checked="checked" />
  <select name="ctl00$ContentPlaceHolderMain$comboDadosPubDistrito">
    <option value="null">[Selecione]</option><option value="13" selected="selected">Porto</option>
  </select>
</form>
"""

CAPTCHA_HTML = """
<div id="ctl00_ContentPlaceHolderMain_divSearchNoResult" class="divSearchNoResult">
  <span id="ctl00_ContentPlaceHolderMain_lbNoResult">Por favor, efetue a Valida&ccedil;&atilde;o<br></span>
</div>
"""


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, extra: str = "") -> None:
        print(f"  [{'OK ' if ok else 'FALHA'}] {label}{(' -> ' + extra) if extra else ''}")
        if not ok:
            failures.append(label)

    client = PublicacoesMjClient()

    print("form_state:")
    state = form_state(FORM_HTML)
    check("__VIEWSTATE extraído e desescapado", state.get("__VIEWSTATE") == "/wEPDwUKMTEx&abc", state.get("__VIEWSTATE", ""))
    check("__EVENTVALIDATION extraído", state.get("__EVENTVALIDATION") == "xyz123")
    check("select com 'selected' lido", state.get("ctl00$ContentPlaceHolderMain$comboDadosPubDistrito") == "13")

    print("\nparse_results:")
    check("grelha encontrada", bool(_grid_html(GRID_HTML)))
    rows = client.parse_results(GRID_HTML, search_nif="500273170", tipo="0")
    check("2 linhas extraídas", len(rows) == 2, str(len(rows)))
    if len(rows) == 2:
        r0, r1 = rows
        check("data ISO 8601", r0.data_publicacao == "2026-07-21", str(r0.data_publicacao))
        check("nif", r0.nif == "500273170")
        check("entidade", r0.entidade == "SONAE - SGPS, S.A.", str(r0.entidade))
        check("concelho sem espaços extra", r0.concelho == "Maia", repr(r0.concelho))
        check("acto com acentos (entidades numéricas)", r0.acto == "PRESTAÇÃO DE CONTAS CONSOLIDADAS", str(r0.acto))
        check("índice da linha (Conteudo$N)", r0._index == 0 and r1._index == 1)
        check("has_documento detectado", r0.has_documento is True and r1.has_documento is True)
        check("search_nif propagado", r0.search_nif == "500273170")

    print("\nresult_range / has_next_page / captcha:")
    check("rodapé (1-20 de 200)", client.result_range(GRID_HTML) == {"start": 1, "end": 20, "total": 200}, str(client.result_range(GRID_HTML)))
    check("Page$Next detetado", client.has_next_page(GRID_HTML) is True)
    check("recusa por captcha detetada", _captcha_rejected(CAPTCHA_HTML) is True)
    check("sem captcha quando há grelha", _captcha_rejected(GRID_HTML) is False)

    print("\nparse_detalhe:")
    detail = parse_detalhe(DETALHE_HTML)
    check("entidade do cabeçalho", detail.get("entidade_detalhe") == "SONAE - SGPS, S.A.", str(detail.get("entidade_detalhe")))
    check("data do cabeçalho", detail.get("data_publicacao_detalhe") == "2026-07-21", str(detail.get("data_publicacao_detalhe")))
    check("firma", detail.get("firma") == "SONAE - SGPS, S.A.", str(detail.get("firma")))
    check("natureza jurídica", detail.get("natureza_juridica") == "SOCIEDADE ANóNIMA", str(detail.get("natureza_juridica")))
    check("sede", detail.get("sede") == "VIA NORTE-ESPIDO", str(detail.get("sede")))
    check("distrito", detail.get("distrito") == "Porto", str(detail.get("distrito")))
    check("concelho", detail.get("concelho") == "Maia", str(detail.get("concelho")))
    check("freguesia sem código postal", detail.get("freguesia") == "Cidade da Maia", str(detail.get("freguesia")))
    check("código postal separado", detail.get("codigo_postal") == "4470 MAIA", str(detail.get("codigo_postal")))
    check("conservatória", detail.get("conservatoria") == "2ª CRPC Maia", str(detail.get("conservatoria")))
    check("pedido", detail.get("pedido") == "Dep 2763/2026-07-21", str(detail.get("pedido")))
    check("acto de registo (sem o ano de contas)", detail.get("acto_detalhe", "").startswith("DEP 2763/2026-07-21 03:05:00 UTC - PRESTAÇÃO DE CONTAS CONSOLIDADAS"), str(detail.get("acto_detalhe"))[:80])
    check("ano de contas", detail.get("ano_contas") == "2025 (2025-01-01 a 2025-12-31)", str(detail.get("ano_contas")))
    check("requerente", detail.get("requerente") == "SONAE SOC GESTORA PARTICIPACOES SOCIAIS SA", str(detail.get("requerente")))
    check("texto integral guardado", "Menção realizada" in (detail.get("texto") or ""))

    print("\npub_id / to_dict:")
    pub = PublicacaoMJ(**{k: v for k, v in {
        "data_publicacao": "2026-07-21", "nif": "500273170", "acto": "PRESTAÇÃO DE CONTAS CONSOLIDADAS",
    }.items()})
    check("pub_id determinístico", pub.pub_id == PublicacaoMJ(nif="500273170", data_publicacao="2026-07-21", acto="PRESTAÇÃO DE CONTAS CONSOLIDADAS").pub_id)
    check("pub_id muda com o acto", pub.pub_id != PublicacaoMJ(nif="500273170", data_publicacao="2026-07-21", acto="Anúncio").pub_id)
    check("to_dict sem None", all(v is not None for v in pub.to_dict().values()))

    print(f"\n{'TODOS OS TESTES PASSARAM' if not failures else 'FALHAS: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
