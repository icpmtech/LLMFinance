"""Página pública do **custo de vida** (bloco do CMS `/site/solucoes/custo-de-vida`).

O mapa e a tabela do site são gerados a partir do índice `finance_custo_vida`,
não escritos à mão: assim o número que a página mostra é o mesmo que a API
serve, e atualizar os dados é recolher, construir e voltar a publicar.

Três blocos, como a página já tinha:

1. `cv_01_mapa` — HTML+JS autónomo (Leaflet + dados embutidos). Os dados vão
   embutidos, e não pedidos por `fetch`, para a página funcionar sem JS de
   terceiros e para os motores de busca lerem a tabela;
2. `cv_02_metodologia` — markdown com o que cada número mede e não mede;
3. `cv_03_fontes` — aviso com as fontes e as datas de leitura.

Uso:
    python -m api.custo_vida_pagina            # atualiza e publica a página
    python -m api.custo_vida_pagina --seco     # só mostra o que faria
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from api import custo_vida_service as servico


def _euros(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"{valor:,.0f}".replace(",", " ")


def _decimal(valor: Any, casas: int = 2) -> str:
    if valor is None:
        return "—"
    return f"{valor:.{casas}f}".replace(".", ",")


def dados_do_mapa(docs: List[Dict[str, Any]]) -> str:
    """O array `CV` que o mapa consome, compacto (uma chave curta por campo)."""
    linhas = []
    for doc in docs:
        linhas.append(
            {
                "n": doc["nome"],
                "d": doc["distrito"],
                "nu": doc["nuts"],
                "p": doc.get("populacao"),
                "r": doc.get("renda_m2"),
                "g": doc.get("gasoleo_l"),
                "i": doc.get("imi_pct"),
                "ia": doc.get("imi_anual"),
                "e": doc.get("eletricidade_mensal"),
                "z": doc.get("gas_mensal"),
                "x": doc.get("indice"),
                "k": doc.get("indice_posicao"),
                "dp": doc.get("despesa_hab"),
                "lat": doc.get("lat"),
                "lon": doc.get("lon"),
            }
        )
    return json.dumps(linhas, ensure_ascii=False, separators=(",", ":"))


def _distritos(docs: List[Dict[str, Any]]) -> str:
    nomes = sorted({doc["distrito"] for doc in docs if doc.get("distrito")})
    return "".join(f'<option value="{nome}">{nome}</option>' for nome in nomes)


_CSS = """
.cv{--teal:#0ea5a4;--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;--bg:#f8fafc;font-family:inherit;color:var(--ink)}
.cv *{box-sizing:border-box}
.cv-h h2{margin:0;font-size:1.35rem;letter-spacing:-.02em}
.cv-h p{margin:4px 0 0;color:var(--mut);font-size:.9rem;max-width:60ch}
.cv-f{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}
.cv-f label{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin-bottom:4px}
.cv-f input,.cv-f select{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:9px;font-size:.92rem;background:#fff;color:var(--ink)}
.cv-k{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:6px 0 16px}
.cv-k div{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.cv-k b{display:block;font-size:1.25rem;letter-spacing:-.02em}
.cv-k span{font-size:.74rem;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.cv-k i{display:block;font-style:normal;font-size:.78rem;color:var(--mut);margin-top:2px}
.cv #cv-mapa{height:520px;border:1px solid var(--line);border-radius:14px;overflow:hidden}
.cv-panel{border:1px solid var(--line);border-radius:14px;padding:14px;background:#fff;min-height:120px;margin-top:14px}
.cv-panel h3{margin:0 0 2px;font-size:1.05rem}
.cv-panel .sub{color:var(--mut);font-size:.82rem;margin-bottom:10px}
.cv-row{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px dashed var(--line);font-size:.9rem}
.cv-row:last-of-type{border:0}
.cv-row span{color:var(--mut)}
.cv-row b{font-variant-numeric:tabular-nums}
.cv-tot{margin-top:10px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:10px}
.cv-tot b{font-size:1.3rem}
.cv-tot small{display:block;color:#047857;font-size:.76rem;margin-top:2px}
.leaflet-container{font:inherit}
.leaflet-container img{max-width:none!important}
.cv-leg{background:#fff;padding:6px 8px;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.15);font-size:.72rem;line-height:1.5}
.cv-leg i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}
.cv-tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:16px}
.cv-tab{width:100%;border-collapse:collapse;margin-top:16px;font-size:.86rem}
.cv-tab th,.cv-tab td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.cv-tab th:first-child,.cv-tab td:first-child{text-align:left}
.cv-tab thead th{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);cursor:pointer}
.cv-tab tbody tr:hover{background:#f1f5f9}
.cv-tab .ix{font-weight:600}
.cv-n{margin-top:14px;font-size:.8rem;color:var(--mut);line-height:1.5}
@media(max-width:1000px){.cv-f{grid-template-columns:1fr 1fr}.cv-k{grid-template-columns:1fr 1fr}.cv #cv-mapa{height:520px}}
"""

_JS = r"""
const AREA = () => Number(document.getElementById('cv-t').value);
const LIT = () => Number(document.getElementById('cv-l').value);
const eur = v => v == null ? '\u2014' : String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
const dec = (v, c) => v == null ? '\u2014' : v.toFixed(c == null ? 2 : c).replace('.', ',');
function renda(x){ return x.r == null ? null : x.r * AREA(); }
function comb(x){ return x.g == null ? null : x.g * LIT(); }
function fixos(x){ return (x.e || 0) + (x.z || 0) + (x.ia ? x.ia / 12 : 0); }
function total(x){ const a = renda(x); if (a == null) return null; return a + (comb(x) || 0) + fixos(x); }
let MED = CV_MED;
function indice(x){ const t = total(x); if (t == null || !MED) return null; return 100 * t / MED; }
function medianaAtual(){
  const v = CV.map(total).filter(t => t != null).sort((a,b) => a - b);
  return v.length ? v[Math.floor(v.length / 2)] : null;
}
function corIndice(i){ return i == null ? '#94a3b8' : i < 85 ? '#0f766e' : i < 100 ? '#14b8a6' : i < 115 ? '#f59e0b' : i < 140 ? '#f97316' : '#dc2626'; }
function cor(x){ return corIndice(indice(x)); }
const mapa = L.map('cv-mapa', {scrollWheelZoom:false, zoomControl:true}).setView([39.6, -8.0], 7);
mapa.fitBounds([[36.85,-9.7],[42.2,-6.1]], {padding:[12,12]});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:18, attribution:'\u00a9 OpenStreetMap'}).addTo(mapa);
let camada = L.layerGroup().addTo(mapa);
const legenda = L.control({position:'bottomright'});
legenda.onAdd = function(){
  const d = L.DomUtil.create('div','cv-leg');
  d.innerHTML = '<b>\u00cdndice de custo de vida</b> (100 = mediana do pa\u00eds)<br>' +
    [[72,'at\u00e9 85'],[92,'85\u2013100'],[107,'100\u2013115'],[127,'115\u2013140'],[200,'mais de 140']]
    .map(([v,t]) => '<div><i style="background:' + corIndice(v) + '"></i>' + t + '</div>').join('');
  L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
  return d;
};
legenda.addTo(mapa);
function filtrados(){
  const q = document.getElementById('cv-q').value.trim().toLowerCase();
  const d = document.getElementById('cv-d').value;
  return CV.filter(x => (!d || x.d === d) && (!q || x.n.toLowerCase().includes(q)));
}
function desenhar(){
  MED = medianaAtual();
  camada.clearLayers();
  filtrados().forEach(x => {
    if (x.lat == null) return;
    const i = indice(x);
    const m = L.circleMarker([x.lat, x.lon], {radius: i == null ? 4 : 5 + Math.min(6, Math.abs(i - 100) / 12),
      color:'#fff', weight:1, fillColor: cor(x), fillOpacity:.9});
    m.bindPopup('<b>' + x.n + '</b><br>' + x.d + '<br>' +
      (i == null ? 'sem renda publicada' : 'índice ' + dec(i, 0) + ' · ' + eur(total(x)) + ' €/mês') +
      (x.g != null ? '<br>gasóleo ' + dec(x.g) + ' €/l' : '') +
      (x.i != null ? '<br>IMI ' + dec(x.i, 3) + ' %' : '') +
      '<br><a href="#" data-cv="' + x.n + '">ver orçamento</a>');
    m.on('popupopen', e => { const a = e.popup.getElement().querySelector('[data-cv]');
      a.onclick = ev => { ev.preventDefault(); painel(x.n); }; });
    m.addTo(camada);
  });
  tabela();
  kpis();
}

function kpis(){
  const f = filtrados().filter(x => indice(x) != null);
  document.getElementById('cv-k1').textContent = f.length;
  document.getElementById('cv-k1n').textContent = 'de ' + CV.length + ' concelhos com renda publicada';
  if (!f.length) { ['cv-k2','cv-k3','cv-k4'].forEach(i => document.getElementById(i).textContent = '\u2014'); return; }
  const valores = f.map(x => indice(x)).sort((a,b) => a - b);
  document.getElementById('cv-k2').textContent = dec(valores[Math.floor(valores.length / 2)], 0);
  const caro = f.reduce((a,b) => indice(a) >= indice(b) ? a : b);
  const barato = f.reduce((a,b) => indice(a) <= indice(b) ? a : b);
  document.getElementById('cv-k3').textContent = dec(indice(caro), 0);
  document.getElementById('cv-k3n').textContent = caro.n + ' · ' + eur(total(caro)) + ' €/mês';
  document.getElementById('cv-k4').textContent = dec(indice(barato), 0);
  document.getElementById('cv-k4n').textContent = barato.n + ' · ' + eur(total(barato)) + ' €/mês';
}
let ordem = {k:'x', asc:false};
function valor(x){
  switch (ordem.k) {
    case 'renda': return renda(x);
    case 'comb': return comb(x);
    case 'total': return total(x);
    case 'x': return indice(x);
    default: return x[ordem.k];
  }
}
function tabela(){
  const f = filtrados().slice().sort((a,b) => {
    const va = valor(a), vb = valor(b);
    if (va == null) return 1; if (vb == null) return -1;
    return ordem.asc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
  });
  const tb = document.querySelector('#cv-tab tbody');
  tb.innerHTML = f.map(x => '<tr data-n="' + x.n + '"><td>' + x.n + '</td><td>' + x.d + '</td>' +
    '<td>' + dec(x.r) + '</td><td>' + eur(renda(x)) + '</td><td>' + eur(comb(x)) + '</td>' +
    '<td>' + eur(x.e) + '</td><td>' + eur(x.z) + '</td><td>' + eur(x.ia) + '</td>' +
    '<td><b>' + eur(total(x)) + '</b></td><td class="ix">' + dec(indice(x), 0) + '</td>' +
    '<td>' + eur(x.dp) + '</td></tr>').join('');
  [...tb.querySelectorAll('tr')].forEach(tr => tr.onclick = () => painel(tr.dataset.n));
}
function painel(nome){
  const x = CV.find(y => y.n === nome); if (!x) return;
  const a = renda(x), b = comb(x), t = total(x), i = indice(x);
  document.getElementById('cv-panel').innerHTML = '<h3>' + x.n + '</h3><div class="sub">' + x.d +
    ' · ' + x.nu + ' · ' + (x.p ? eur(x.p) + ' hab.' : 'popula\u00e7\u00e3o n.d.') +
    (x.k ? ' · ' + x.k + '.\u00ba lugar no pa\u00eds' : '') + '</div>' +
    '<div class="cv-row"><span>Renda (' + dec(x.r) + ' \u20ac/m\u00b2 \u00d7 ' + AREA() + ' m\u00b2)</span><b>' + (a == null ? '\u2014' : eur(a) + ' \u20ac') + '</b></div>' +
    '<div class="cv-row"><span>Gas\u00f3leo (' + LIT() + ' l)</span><b>' + (b == null ? '\u2014' : eur(b) + ' \u20ac') + '</b></div>' +
    '<div class="cv-row"><span>Eletricidade</span><b>' + (x.e == null ? '\u2014' : eur(x.e) + ' \u20ac') + '</b></div>' +
    '<div class="cv-row"><span>G\u00e1s natural</span><b>' + (x.z == null ? '\u2014' : eur(x.z) + ' \u20ac') + '</b></div>' +
    '<div class="cv-row"><span>IMI (' + dec(x.i, 3) + ' % \u00d7 120 000 \u20ac \u00f7 12)</span><b>' + (x.ia == null ? '\u2014' : eur(x.ia / 12) + ' \u20ac') + '</b></div>' +
    '<div class="cv-tot">Or\u00e7amento mensal<br><b>' + (t == null ? '\u2014' : eur(t) + ' \u20ac/m\u00eas') + '</b>' +
    '<small>\u00cdndice ' + dec(i, 0) + ' (100 = mediana do pa\u00eds)</small></div>';
}
document.getElementById('cv-q').oninput = desenhar;
document.getElementById('cv-d').onchange = desenhar;
document.getElementById('cv-t').onchange = desenhar;
document.getElementById('cv-l').onchange = desenhar;
document.querySelectorAll('#cv-tab thead th').forEach(th => th.onclick = () => {
  if (ordem.k === th.dataset.k) ordem.asc = !ordem.asc; else { ordem.k = th.dataset.k; ordem.asc = true; }
  tabela();
});
desenhar();
"""


def bloco_mapa(docs: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    """Bloco `texto` com o mapa, os filtros, os indicadores e a tabela."""
    tipologias = servico.TIPOLOGIAS
    opcoes_tipologia = "".join(
        f'<option value="{area}"{" selected" if nome == servico.TIPOLOGIA_REFERENCIA else ""}>'
        f"{nome} — {area} m²</option>"
        for nome, area in tipologias.items()
    )
    opcoes_litros = "".join(
        f'<option value="{litros}"{" selected" if litros == servico.LITROS_MES else ""}>'
        f'{"Não incluir" if litros == 0 else str(litros) + " litros"}</option>'
        for litros in (0, 50, 100, 150)
    )
    mediana = meta.get("custo_mediano")
    return f"""<div class="cv" id="cv-app">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>{_CSS}</style>
<div class="cv-h">
<div><h2>Renda, energia, IMI e índice de custo de vida, concelho a concelho</h2>
<p>Renda mediana por m² (INE), gasóleo do concelho (DGEG), IMI deliberado por cada município (AT) e as tarifas nacionais de eletricidade e gás (ERSE), num orçamento mensal. O índice põe esse orçamento numa escala em que 100 é a mediana do país.</p></div>
</div>
<div class="cv-f">
<div><label for="cv-q">Procurar concelho</label><input id="cv-q" type="search" placeholder="ex.: Porto, Viseu, Loulé" autocomplete="off"></div>
<div><label for="cv-d">Distrito</label><select id="cv-d"><option value="">Todos</option>{_distritos(docs)}</select></div>
<div><label for="cv-t">Tipologia</label><select id="cv-t">{opcoes_tipologia}</select></div>
<div><label for="cv-l">Gasóleo / mês</label><select id="cv-l">{opcoes_litros}</select></div>
</div>
<div class="cv-k">
<div><span>Concelhos comparáveis</span><b id="cv-k1">—</b><i id="cv-k1n"></i></div>
<div><span>Índice mediano</span><b id="cv-k2">—</b><i>100 = mediana do país</i></div>
<div><span>Mais caro</span><b id="cv-k3">—</b><i id="cv-k3n"></i></div>
<div><span>Mais barato</span><b id="cv-k4">—</b><i id="cv-k4n"></i></div>
</div>
<div id="cv-mapa"></div>
<div class="cv-panel" id="cv-panel"><h3>Escolhe um concelho</h3><div class="sub">Clica num círculo do mapa ou numa linha da tabela.</div>
<div class="cv-n">O orçamento soma a renda estimada (€/m² × área), o gasóleo (preço mediano do concelho × litros), a eletricidade e o gás (tarifa nacional) e o IMI de um imóvel de referência de 120 000 €. Água, resíduos, transportes e alimentação ficam de fora — ver a nota no fim da página.</div></div>
<div class="cv-tw"><table class="cv-tab" id="cv-tab"><thead><tr><th data-k="n">Concelho</th><th data-k="d">Distrito</th><th data-k="r">€/m²</th><th data-k="renda">Renda</th><th data-k="comb">Gasóleo</th><th data-k="e">Eletricidade</th><th data-k="z">Gás</th><th data-k="ia">IMI/ano</th><th data-k="total">Total/mês</th><th data-k="x">Índice</th><th data-k="dp">Despesa/hab.</th></tr></thead><tbody></tbody></table></div>
<p class="cv-n" id="cv-cont"></p>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const CV = {dados_do_mapa(docs)};
const CV_MED = {json.dumps(mediana)};
{_JS}
</script>"""


def bloco_metodologia(meta: Dict[str, Any]) -> str:
    """Markdown com o que cada número mede — e o que não mede."""
    componentes = meta.get("componentes") or {}
    eletricidade = componentes.get("eletricidade") or {}
    gas = componentes.get("gas") or {}
    imi = componentes.get("imi") or {}
    gasoleo = componentes.get("gasoleo") or {}
    limites = meta.get("limites") or {}

    energia = (
        f"{_decimal(eletricidade.get('energia_kwh'), 4)} €/kWh e "
        f"{_decimal(eletricidade.get('termo_fixo_dia'), 4)} €/dia de potência (3,45 kVA)"
    )
    gas_txt = (
        f"{_decimal(gas.get('energia_kwh'), 4)} €/kWh e "
        f"{_decimal(gas.get('termo_fixo_dia'), 4)} €/dia"
    )
    partes = [
        "## O que este mapa mede",
        "",
        "**Renda.** Valor mediano das rendas por m² de novos contratos de arrendamento "
        f"(INE, 2.º trimestre de 2026). Multiplicado pela área da tipologia escolhida "
        f"(T0 {servico.TIPOLOGIAS['T0']} m², T1 {servico.TIPOLOGIAS['T1']} m², "
        f"T2 {servico.TIPOLOGIAS['T2']} m², T3 {servico.TIPOLOGIAS['T3']} m²) dá a renda mensal "
        "estimada. É uma mediana de contratos novos: não é o que paga quem tem contrato antigo.",
        "",
        "**Gasóleo.** Mediana do preço por litro nas bombas do concelho, calculada a partir dos "
        f"preços comunicados à DGEG (leitura de {gasoleo.get('leitura') or '—'}). Média simples entre "
        "postos, não ponderada pelo volume vendido: serve para comparar territórios, não para "
        "prever a fatura exata.",
        "",
        f"**IMI.** Taxa para prédios urbanos deliberada por cada município, publicada pela "
        f"Autoridade Tributária e Aduaneira (ano fiscal de {imi.get('ano') or '—'}). Aplicada a um "
        f"imóvel de referência de {_euros(servico.VPT_REFERENCIA)} € de valor patrimonial, dá o "
        "imposto anual — dividido por 12, entra no orçamento mensal. Oito municípios fixam a taxa "
        "por freguesia e não têm taxa única: ficam sem IMI em vez de se inventar um valor.",
        "",
        f"**Eletricidade.** Tarifa transitória de venda a clientes finais da ERSE — {energia} — "
        f"para 1 900 kWh por ano, que é o consumo do exemplo da própria ERSE. É **nacional**: não "
        "varia de concelho para concelho, e entra no orçamento como custo igual em todo o país.",
        "",
        f"**Gás natural.** Tarifa transitória da ERSE, escalão 1 (até 220 m³/ano): {gas_txt}, para "
        "138 m³ por ano. Também **nacional**. Onde não há rede de gás, a fatura real é outra — este "
        "valor é uma referência, não uma obrigação de consumo.",
        "",
        "**Orçamento tipo.** Soma a renda, o combustível do mês, a eletricidade, o gás e o IMI. "
        "É o custo que varia de concelho para concelho; os valores nacionais somam o mesmo a todos.",
        "",
        "**Índice de custo de vida.** 100 × (orçamento do concelho ÷ mediana nacional do "
        f"orçamento), na tipologia T2 e com {servico.LITROS_MES} litros de gasóleo por mês. "
        f"Mediana nacional: {_euros(meta.get('custo_mediano'))} €/mês. Um índice de 118 significa "
        "«18 % acima da mediana do país», não «118 euros». Só entram os concelhos com renda "
        "publicada, porque sem renda o orçamento não é comparável.",
        "",
        "**Despesa municipal.** Despesa total da câmara por habitante (INE/DGAL, execução de 2023) "
        "continua a ser mostrada como contexto do nível de serviços municipais — não é um custo "
        "para a família e não entra no índice.",
        "",
        "## O que fica de fora (e porquê)",
        "",
    ]
    for chave in ("agua", "transportes", "alimentacao"):
        item = limites.get(chave) or {}
        if not item:
            continue
        partes.append(f"- **{item.get('label', chave)}:** {item.get('motivo', '')}")
    partes.append("")
    return "\n".join(partes)


def bloco_fontes(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Aviso final: fontes, datas de leitura e o âmbito da análise."""
    componentes = meta.get("componentes") or {}
    gasoleo = componentes.get("gasoleo") or {}
    imi = componentes.get("imi") or {}
    eletricidade = componentes.get("eletricidade") or {}
    gas = componentes.get("gas") or {}
    texto = (
        f"Fontes: INE (rendas por m², 2.º trimestre de 2026), DGEG (preços de combustíveis, "
        f"{gasoleo.get('leitura') or '—'}), Autoridade Tributária e Aduaneira — taxas de IMI de "
        f"{imi.get('ano') or '—'}, reproduzidas por flatin.pt (dados.gov.pt, CC BY 4.0), ERSE "
        f"(tarifas transitórias de venda a clientes finais de eletricidade e gás, outubro de 2026), "
        f"INE/DGAL via IQ OS (despesa municipal 2023 e população 2021), OpenStreetMap (cartografia). "
        f"Consumo de referência: 1 900 kWh/ano de eletricidade e 138 m³/ano de gás. "
        f"Análise descritiva de dados públicos; não é recomendação de investimento nem avaliação "
        f"imobiliária."
    )
    if eletricidade.get("url") or gas.get("url"):
        texto += f" Ficheiros de tarifas: {eletricidade.get('url', '')} e {gas.get('url', '')}."
    return {"text": texto, "tone": "nota"}


def blocos(docs: List[Dict[str, Any]], meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Os três blocos do CMS, pela ordem em que a página os mostra."""
    return [
        {"id": "cv_01_mapa", "type": "texto", "hidden": False, "data": {"title": "", "markdown": bloco_mapa(docs, meta)}},
        {
            "id": "cv_02_metodologia",
            "type": "texto",
            "hidden": False,
            "data": {"title": "Metodologia e fontes", "markdown": bloco_metodologia(meta)},
        },
        {"id": "cv_03_fontes", "type": "aviso", "hidden": False, "data": bloco_fontes(meta)},
    ]


def atualizar_pagina(slug: str = "custo-de-vida", autor: str = "recolha automatica", publicar: bool = True) -> Dict[str, Any]:
    """Recolhe o índice, reconstrói os blocos e grava-os na página do CMS."""
    from api import cms_store as store

    construido = servico.construir()
    docs = construido.get("docs") or []
    meta = construido.get("meta") or {}
    if not docs:
        return {"erro": "sem concelhos para publicar"}

    pagina = None
    for item in store.list_items("pages", limit=500).get("items") or []:
        if item.get("slug") == slug:
            pagina = item
            break
    if pagina is None:
        return {"erro": f"página «{slug}» não encontrada no CMS"}

    novo = {**pagina, "blocks": blocos(docs, meta)}
    guardado = store.save_item("pages", novo, author=autor)
    if publicar:
        guardado = store.publish_item("pages", guardado["id"], author=autor)
    return {
        "pagina": guardado.get("slug"),
        "id": guardado.get("id"),
        "estado": guardado.get("status"),
        "concelhos": len(docs),
        "com_indice": meta.get("com_renda"),
        "custo_mediano": meta.get("custo_mediano"),
        "atualizado_em": guardado.get("updated_at"),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publica a página do custo de vida no CMS")
    parser.add_argument("--slug", default="custo-de-vida")
    parser.add_argument("--seco", action="store_true", help="não grava no CMS; mostra só o resumo")
    args = parser.parse_args(argv)

    if args.seco:
        construido = servico.construir()
        meta = construido.get("meta") or {}
        print(
            json.dumps(
                {
                    "concelhos": len(construido.get("docs") or []),
                    "com_renda": meta.get("com_renda"),
                    "custo_mediano": meta.get("custo_mediano"),
                    "mais_caro": meta.get("concelho_mais_caro"),
                    "mais_barato": meta.get("concelho_mais_barato"),
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    print(json.dumps(atualizar_pagina(slug=args.slug), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
