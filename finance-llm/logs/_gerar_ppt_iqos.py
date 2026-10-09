"""Gera o PowerPoint de análise de negócio do IQ OS.

Lê os dados medidos (`exports/business/analise_iqos.json`), os gráficos
(`exports/business/graficos/`) e os ecrãs da aplicação
(`exports/business/ecras/`) — todos produzidos pelos outros dois scripts — e
escreve `exports/business/IQOS_Analise_Negocio.pptx`.

Nada aqui é inventado: os números vêm do JSON. As únicas partes assumidas
(TAM/SAM/SOM e cenários de receita) estão **marcadas como pressupostos** nos
próprios diapositivos, tal como no relatório.

Uso::

    python logs/_gerar_ppt_iqos.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

RAIZ = Path(__file__).resolve().parents[1]
BASE = RAIZ / "exports" / "business"
GRAFICOS = BASE / "graficos"
ECRAS = BASE / "ecras"
SAIDA = BASE / "IQOS_Analise_Negocio.pptx"

FUNDO = RGBColor(0x0F, 0x17, 0x2A)
FUNDO_2 = RGBColor(0x16, 0x22, 0x3A)
TEXTO = RGBColor(0xE2, 0xE8, 0xF0)
SUAVE = RGBColor(0x94, 0xA3, 0xB8)
DESTAQUE = RGBColor(0x2D, 0xD4, 0xBF)
AZUL = RGBColor(0x38, 0xBD, 0xF8)
ROXO = RGBColor(0x81, 0x8C, 0xF8)
VERDE = RGBColor(0x34, 0xD3, 0x99)
AMBAR = RGBColor(0xFB, 0xBF, 0x24)
VERMELHO = RGBColor(0xF8, 0x71, 0x71)

LARGURA = Inches(13.333)
ALTURA = Inches(7.5)


# ---------------------------------------------------------------------------
# Utilidades de composição
# ---------------------------------------------------------------------------
def novo_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = LARGURA
    prs.slide_height = ALTURA
    return prs


def fundo(slide, cor: RGBColor = FUNDO) -> None:
    """Rectângulo de fundo — é o primeiro objecto do slide, logo fica atrás do resto."""
    forma = slide.shapes.add_shape(1, 0, 0, LARGURA, ALTURA)
    forma.fill.solid()
    forma.fill.fore_color.rgb = cor
    forma.line.fill.background()
    forma.shadow.inherit = False


def prs_largura():
    return LARGURA


def prs_altura():
    return ALTURA


def caixa(
    slide,
    texto: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    tamanho: int = 14,
    cor: RGBColor = TEXTO,
    negrito: bool = False,
    alinhamento: PP_ALIGN = PP_ALIGN.LEFT,
    espaco_linhas: float = 1.15,
    fundo_caixa: Optional[RGBColor] = None,
):
    """Caixa de texto simples (uma linha/parágrafo)."""
    esquerda, topo, larg, alt = Inches(left), Inches(top), Inches(width), Inches(height)
    if fundo_caixa is not None:
        painel = slide.shapes.add_shape(5, esquerda, topo, larg, alt)
        painel.fill.solid()
        painel.fill.fore_color.rgb = fundo_caixa
        painel.line.color.rgb = RGBColor(0x33, 0x41, 0x55)
        painel.line.width = Pt(0.75)
        painel.shadow.inherit = False
        caixa_texto = painel.text_frame
    else:
        caixa_texto = slide.shapes.add_textbox(esquerda, topo, larg, alt).text_frame
    caixa_texto.word_wrap = True
    caixa_texto.margin_left = caixa_texto.margin_right = Emu(91440)
    caixa_texto.margin_top = caixa_texto.margin_bottom = Emu(45720)
    paragrafo = caixa_texto.paragraphs[0]
    paragrafo.alignment = alinhamento
    paragrafo.line_spacing = espaco_linhas
    run = paragrafo.add_run()
    run.text = texto
    run.font.size = Pt(tamanho)
    run.font.color.rgb = cor
    run.font.bold = negrito
    run.font.name = "Segoe UI"
    return caixa_texto


def lista(
    slide,
    itens: Sequence[str],
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    tamanho: int = 13,
    cor: RGBColor = TEXTO,
    marcador: str = "▪",
    espaco: float = 0.22,
):
    """Lista com marcadores coloridos (`**negrito**` dentro do texto é suportado)."""
    caixa_texto = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height)).text_frame
    caixa_texto.word_wrap = True
    for indice, item in enumerate(itens):
        paragrafo = caixa_texto.paragraphs[0] if indice == 0 else caixa_texto.add_paragraph()
        paragrafo.space_after = Pt(espaco * 28)
        paragrafo.line_spacing = 1.1
        if marcador:
            marca = paragrafo.add_run()
            marca.text = f"{marcador}  "
            marca.font.color.rgb = DESTAQUE
            marca.font.size = Pt(tamanho)
        for parte, negrito in _fatiar_negrito(item):
            run = paragrafo.add_run()
            run.text = parte
            run.font.size = Pt(tamanho)
            run.font.bold = negrito
            run.font.color.rgb = cor if not negrito else RGBColor(0xFF, 0xFF, 0xFF)
            run.font.name = "Segoe UI"
    return caixa_texto


def _fatiar_negrito(texto: str) -> Iterable[Tuple[str, bool]]:
    """Divide `a **b** c` em [(a, False), (b, True), (c, False)]."""
    partes: List[Tuple[str, bool]] = []
    for indice, bloco in enumerate(texto.split("**")):
        if bloco:
            partes.append((bloco, indice % 2 == 1))
    return partes or [(texto, False)]


def cabecalho(slide, titulo: str, subtitulo: str = "", *, numero: int = 0) -> None:
    caixa(slide, titulo, 0.6, 0.35, 12.1, 0.7, tamanho=27, negrito=True)
    if subtitulo:
        caixa(slide, subtitulo, 0.6, 1.02, 12.1, 0.5, tamanho=12.5, cor=SUAVE)
    linha = slide.shapes.add_shape(1, Inches(0.6), Inches(1.5), Inches(12.1), Pt(1.5))
    linha.fill.solid()
    linha.fill.fore_color.rgb = RGBColor(0x2A, 0x3A, 0x52)
    linha.line.fill.background()
    if numero:
        caixa(slide, f"IQ OS · análise de negócio · {numero}", 0.6, 7.05, 12.1, 0.3, tamanho=9, cor=SUAVE)


def slide(
    prs: Presentation,
    titulo: str,
    subtitulo: str = "",
    *,
    numero: int = 0,
    cor_fundo: RGBColor = FUNDO,
):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fundo(s, cor_fundo)
    cabecalho(s, titulo, subtitulo, numero=numero)
    return s


def imagem(slide, caminho: Path, left: float, top: float, max_w: float, max_h: float, *, moldura: bool = True):
    """Coloca a imagem ajustada à caixa, preservando a proporção."""
    if not caminho.exists():
        caixa(slide, f"(falta {caminho.name})", left, top, max_w, 0.4, tamanho=10, cor=SUAVE)
        return
    from PIL import Image

    with Image.open(caminho) as img:
        largura_px, altura_px = img.size
    escala = min(max_w / largura_px, max_h / altura_px)
    largura, altura = largura_px * escala, altura_px * escala
    esquerda = Inches(left + (max_w - largura) / 2)
    topo = Inches(top + (max_h - altura) / 2)
    slide.shapes.add_picture(str(caminho), esquerda, topo, Inches(largura), Inches(altura))
    if moldura:
        canto = slide.shapes.add_shape(1, esquerda, topo, Inches(largura), Inches(altura))
        canto.fill.background()
        canto.line.color.rgb = RGBColor(0x33, 0x41, 0x55)
        canto.line.width = Pt(1)
        canto.shadow.inherit = False


def tabela(slide, dados: Sequence[Sequence[str]], left: float, top: float, width: float, height: float,
           *, tamanho: int = 11, larguras: Optional[Sequence[float]] = None):
    linhas, colunas = len(dados), len(dados[0])
    forma = slide.shapes.add_table(linhas, colunas, Inches(left), Inches(top), Inches(width), Inches(height))
    quadro = forma.table
    if larguras:
        total = sum(larguras)
        for indice, fatia in enumerate(larguras):
            quadro.columns[indice].width = Emu(int(Inches(width) * fatia / total))
    for i, linha in enumerate(dados):
        for j, valor in enumerate(linha):
            celula = quadro.cell(i, j)
            celula.text = str(valor)
            celula.margin_left = celula.margin_right = Emu(45720)
            celula.margin_top = celula.margin_bottom = Emu(18288)
            celula.fill.solid()
            celula.fill.fore_color.rgb = FUNDO_2 if i else RGBColor(0x1E, 0x2B, 0x45)
            paragrafo = celula.text_frame.paragraphs[0]
            paragrafo.line_spacing = 1.05
            for run in paragrafo.runs:
                run.font.size = Pt(tamanho)
                run.font.name = "Segoe UI"
                run.font.bold = i == 0
                run.font.color.rgb = DESTAQUE if i == 0 else TEXTO
    return quadro


# ---------------------------------------------------------------------------
# Diapositivos
# ---------------------------------------------------------------------------
def capa(prs: Presentation, m: Dict[str, Any]) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fundo(s, RGBColor(0x0B, 0x12, 0x20))
    caixa(s, "IQ OS", 0.9, 1.5, 11.5, 1.0, tamanho=54, negrito=True, cor=DESTAQUE)
    caixa(s, "Análise de negócio: produto, mercado e impacto", 0.9, 2.5, 11.5, 0.7, tamanho=26)
    caixa(
        s,
        "Números recolhidos da própria plataforma em execução — não de estimativas.",
        0.9, 3.2, 11.5, 0.5, tamanho=14, cor=SUAVE,
    )
    a = m["ativo_de_dados"]
    mk = m["mercado_enderecavel"]
    p = m["produto"]
    destaques = [
        (f"{a['documentos_totais']:,}".replace(",", " "), "documentos indexados"),
        (f"{mk['contratos_agregados']:,}".replace(",", " "), "contratos"),
        (f"{mk['valor_agregado_eur'] / 1e9:,.0f} mil M€".replace(",", " "), "valor agregado"),
        (f"{p['rotas_api']}", "rotas de API"),
    ]
    for indice, (valor, rotulo) in enumerate(destaques):
        x = 0.9 + indice * 3.05
        painel = s.shapes.add_shape(5, Inches(x), Inches(4.2), Inches(2.8), Inches(1.35))
        painel.fill.solid()
        painel.fill.fore_color.rgb = FUNDO_2
        painel.line.color.rgb = RGBColor(0x2D, 0xD4, 0xBF)
        painel.line.width = Pt(1)
        painel.shadow.inherit = False
        texto = painel.text_frame
        texto.word_wrap = True
        texto.vertical_anchor = MSO_ANCHOR.MIDDLE
        p1 = texto.paragraphs[0]
        p1.alignment = PP_ALIGN.CENTER
        r1 = p1.add_run()
        r1.text = valor
        r1.font.size = Pt(24)
        r1.font.bold = True
        r1.font.color.rgb = DESTAQUE
        p2 = texto.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = rotulo
        r2.font.size = Pt(11)
        r2.font.color.rgb = SUAVE
    caixa(
        s,
        f"Nota global do scorecard: {m['nota_global']}/5   ·   {date.today().strftime('%d/%m/%Y')}",
        0.9, 5.9, 11.5, 0.5, tamanho=13, cor=SUAVE,
    )


def sumario(prs, m, numero):
    s = slide(prs, "Sumário executivo", "O que o produto é, o que já vale e o que falta para vender", numero=numero)
    forcas = [
        f"**{m['ativo_de_dados']['documentos_totais']:,} documentos** em "
        f"{m['ativo_de_dados']['indices_com_dados']} índices — o ativo central e a maior barreira à entrada.".replace(",", " "),
        f"**{m['produto']['rotas_api']} rotas de API** em {m['produto']['dominios_rotas']} domínios: "
        "mercados, contratos, empresas, pessoas, IA, BI, CRM, CMS e recolha.",
        f"**IA com evidência citada** (Hermes, Researcher, ontologia anti-alucinação) — requisito em contratação pública.",
        f"**Receita já instrumentada**: {m['monetizacao']['pacotes_relatorio']} relatórios pagos "
        f"({m['monetizacao']['preco_min_eur']}–{m['monetizacao']['preco_max_eur']} €) com pagamento MB Way e loja.",
    ]
    riscos = [
        f"**Concentração**: {m['cobertura']['entidades_pt_pct']}% das entidades são portuguesas — "
        "o mercado doméstico é pequeno para o investimento feito.",
        f"**Elo mais fraco**: cobertura societária de {m['cobertura']['societario_cobertura_pct']}% e "
        f"{100 - m['cobertura']['entidades_com_nif_pct']}% de entidades sem NIF.",
        "**Sem telemetria nem planos**: não se mede uso, retenção ou receita recorrente.",
        f"**Dispersão**: {m['produto']['dominios_rotas']} domínios funcionais para uma equipa pequena.",
    ]
    caixa(s, "Pontos fortes", 0.6, 1.75, 6.0, 0.4, tamanho=15, negrito=True, cor=VERDE)
    lista(s, forcas, 0.6, 2.2, 6.0, 4.0, tamanho=12.5)
    caixa(s, "Riscos a decidir", 6.9, 1.75, 5.8, 0.4, tamanho=15, negrito=True, cor=AMBAR)
    lista(s, riscos, 6.9, 2.2, 5.8, 4.0, tamanho=12.5, marcador="▸")
    caixa(
        s,
        "Leitura: produto muito acima do que a operação comercial consegue hoje vender.",
        0.6, 6.35, 12.1, 0.45, tamanho=13.5, negrito=True, cor=DESTAQUE,
        fundo_caixa=FUNDO_2,
    )


def o_produto(prs, m, numero):
    s = slide(prs, "O produto em imagens", "Ecrãs reais da plataforma em execução", numero=numero)
    imagens = [
        ("02_dashboard_contratos", "Dashboard de contratos"),
        ("06_empresas_iq", "EmpresasIQ — ficha e relações"),
        ("09_hermes_ia", "Hermes — respostas com evidência"),
        ("11_visualizador_bi", "Visualizador BI"),
    ]
    for indice, (ficheiro, etiqueta) in enumerate(imagens):
        coluna, linha = indice % 2, indice // 2
        x = 0.6 + coluna * 6.25
        y = 1.75 + linha * 2.6
        imagem(s, ECRAS / f"{ficheiro}.png", x, y, 5.95, 2.15)
        caixa(s, etiqueta, x, y + 2.15, 5.95, 0.3, tamanho=10, cor=SUAVE, alinhamento=PP_ALIGN.CENTER)


def o_produto_2(prs, m, numero):
    s = slide(prs, "O produto em imagens (2)", "Dados geográficos, pessoas, investigação e monetização", numero=numero)
    imagens = [
        ("03_mapa_contratos", "Mapa da contratação por região"),
        ("08_pessoas_iq", "PessoasIQ — pessoas e cargos"),
        ("10_search360", "Search360 — dossiê por tema"),
        ("13_relatorios", "Relatórios pagos e pedidos"),
    ]
    for indice, (ficheiro, etiqueta) in enumerate(imagens):
        coluna, linha = indice % 2, indice // 2
        x = 0.6 + coluna * 6.25
        y = 1.75 + linha * 2.6
        imagem(s, ECRAS / f"{ficheiro}.png", x, y, 5.95, 2.15)
        caixa(s, etiqueta, x, y + 2.15, 5.95, 0.3, tamanho=10, cor=SUAVE, alinhamento=PP_ALIGN.CENTER)


def ativo_dados(prs, m, numero):
    a = m["ativo_de_dados"]
    s = slide(prs, "O ativo: dados que já existem", "Volume, diversidade e custo de replicação", numero=numero)
    imagem(s, GRAFICOS / "01_documentos_por_indice.png", 0.6, 1.75, 7.4, 4.6)
    lista(s, [
        f"**{a['documentos_totais']:,} documentos** em {a['indices_totais']} índices "
        f"({a['indices_com_dados']} com dados) e {a['tamanho_gb']} GB.".replace(",", " "),
        "Contratos de **PT, ES e FR** (BASE, PLACSP, DECP) mais cadastro de entidades.",
        "**Camadas de contexto**: 212 mil LEI, 137 mil pessoas, marcas INPI, firmas RNPC, "
        "publicações do MJ, insolvências e citações.",
        "**Sentimento e notícias** indexados, prontos para sinais de risco.",
        "Replicar isto exige anos de ingestão, licenças e engenharia — é a barreira à entrada.",
    ], 8.25, 1.85, 4.5, 4.5, tamanho=12.5)


def mercado(prs, m, numero):
    mk, c = m["mercado_enderecavel"], m["cobertura"]
    s = slide(prs, "Mercado endereçável", "Quem paga e porquê — medido a partir do próprio dataset", numero=numero)
    imagem(s, GRAFICOS / "02_entidades_por_pais.png", 0.6, 1.8, 6.4, 4.5)
    dados = [
        ["Segmento", "Tamanho no dataset", "Porque compra"],
        ["Fornecedores do Estado", f"{mk['adjudicatarios']:,}".replace(",", " "), "Achar oportunidades, preço de referência e concorrentes"],
        ["Entidades públicas", f"{mk['adjudicantes']:,}".replace(",", " "), "Benchmark de preços e historial de fornecedores"],
        ["Banca, seguros, auditoria", "n/d (subconjunto)", "Risco de contraparte e sinais societários"],
        ["Imprensa e investigação", "n/d (subconjunto)", "Prova documental citável em segundos"],
    ]
    tabela(s, dados, 7.2, 1.9, 5.55, 2.6, tamanho=10, larguras=[1.6, 1.2, 3.0])
    lista(s, [
        f"**{mk['valor_agregado_eur'] / 1e9:,.0f} mil M€** adjudicados no dataset, "
        f"**{mk['contratos_agregados']:,} contratos**.".replace(",", " "),
        f"Portugal concentra {c['entidades_pt_pct']}% das entidades; Espanha "
        f"{mk['entidades_es']:,} e França {mk['entidades_fr']:,} são amostras.".replace(",", " "),
        "O produto já cobre os dois lados do mercado (quem compra e quem vende).",
    ], 7.2, 4.65, 5.55, 1.7, tamanho=11.5)


def cobertura(prs, m, numero):
    c = m["cobertura"]
    s = slide(prs, "Onde a cobertura falha", "O que impede vender relatórios financeiros a escala hoje", numero=numero)
    imagem(s, GRAFICOS / "03_funil_cobertura.png", 0.6, 1.8, 7.0, 4.4)
    lista(s, [
        f"**{100 - c['entidades_com_nif_pct']}% das entidades não têm NIF** — sem a chave de junção ficam fora do grafo.".replace(".0%", "%"),
        f"**Cobertura societária de {c['societario_cobertura_pct']}%**: "
        f"{c['societario_entidades']} entidades recolhidas de {int(m['mercado_enderecavel']['entidades'] * c['entidades_com_nif_pct'] / 100):,}.".replace(",", " "),
        "O catálogo **promete** balanço, demonstrações e rácios — a matéria-prima ainda não está recolhida.",
        "A recolha por NIF é o gargalo; por **janelas de datas** o país inteiro cabe em ~721 consultas.",
    ], 7.85, 1.9, 4.9, 4.3, tamanho=12.5)


def modelo_negocio(prs, m, numero):
    mo = m["monetizacao"]
    s = slide(prs, "Modelo de negócio atual", "Como entra dinheiro hoje — e o que ainda não existe", numero=numero)
    colunas = [
        ("Proposta de valor", [
            "Um só sítio para decidir: contratos, empresas, pessoas, risco e IA.",
            "Respostas **citadas** em vez de pesquisa manual em 5 portais.",
            "Monitorização contínua (agenda, RSS, alertas).",
        ]),
        ("Receita hoje", [
            f"**Relatórios pagos**: {mo['pacotes_relatorio']} pacotes, "
            f"{mo['preco_min_eur']}–{mo['preco_max_eur']} € por pedido.",
            "**Loja** com produtos físicos e digitais e encomendas.",
            "**CRM** ligado ao cadastro de empresas (venda assistida).",
            "Pagamento MB Way/Ifthenpay com backoffice de pedidos.",
        ]),
        ("Custos e dependências", [
            "Armazenamento e compute do cluster de busca.",
            "**2captcha** por entidade na recolha societária.",
            "Tokens de LLM nos assistentes e agentes.",
            "Fontes públicas (BASE, PLACSP, DECP, MJ, INPI, GLEIF).",
        ]),
    ]
    for indice, (titulo, itens) in enumerate(colunas):
        x = 0.6 + indice * 4.2
        caixa(s, titulo, x, 1.8, 3.95, 0.4, tamanho=14, negrito=True, cor=DESTAQUE)
        lista(s, itens, x, 2.25, 3.95, 4.0, tamanho=11.5, marcador="•")
    caixa(
        s,
        "Falta a camada recorrente: não há planos, limites, contagem de uso nem telemetria — "
        "a receita depende de pedidos manuais.",
        0.6, 6.35, 12.1, 0.45, tamanho=13, negrito=True, cor=AMBAR, fundo_caixa=FUNDO_2,
    )


def precos(prs, m, numero):
    mo = m["monetizacao"]
    s = slide(prs, "Catálogo e preços já praticados", "Evidência de que a monetização foi pensada", numero=numero)
    linhas = [["Relatório", "Preço (€)", "Preço de lista (€)", "Prazo (dias)", "Alvos"]]
    for pacote in mo["pacotes"]:
        linhas.append([
            str(pacote.get("titulo") or "—"),
            f"{pacote.get('preco') or 0:.0f}",
            f"{pacote.get('preco_lista') or 0:.0f}",
            str(pacote.get("prazo_dias") or "—"),
            str(pacote.get("alvos") or "—"),
        ])
    tabela(s, linhas, 0.6, 1.85, 7.6, 2.4, tamanho=11)
    lista(s, [
        f"Intervalo **{mo['preco_min_eur']}–{mo['preco_max_eur']} €** (média {mo['preco_medio_eur']} €).",
        "Os pacotes espelham o que o mercado de informação empresarial já vende — "
        "vantagem: preço de referência aceite; risco: comparação directa com incumbentes.",
        "O **Relatório Concorrência** (130 €, até 6 empresas) é o produto de maior valor — "
        "é também o que exige dados financeiros que ainda faltam recolher.",
        "**Oportunidade imediata**: transformar pedidos manuais em subscrição com limites de uso.",
    ], 8.4, 1.9, 4.3, 4.3, tamanho=12)


def tam_sam_som(prs, m, numero):
    mk = m["mercado_enderecavel"]
    s = slide(prs, "Mercado: TAM, SAM e SOM", "Hipóteses explicitas — substituir por dados reais assim que houver vendas", numero=numero)
    imagem(s, GRAFICOS / "05_cenarios_receita.png", 0.6, 1.8, 6.5, 4.4)
    dados = [
        ["Camada", "Definição", "Estimativa"],
        ["TAM", f"Fornecedores do Estado no dataset ({mk['adjudicatarios']:,}) a 49 €/mês".replace(",", " "), "≈ 121 M€/ano"],
        ["SAM", "5% com perfil de subscrição, PT+ES", "≈ 6,0 M€/ano"],
        ["SOM · ano 1", "0,5% do SAM", "≈ 30 mil €"],
        ["SOM · ano 3", "5% do SAM", "≈ 302 mil €"],
    ]
    tabela(s, dados, 7.35, 1.9, 5.4, 2.3, tamanho=10, larguras=[0.9, 2.6, 1.2])
    lista(s, [
        "Pressupostos: 49 €/mês (plano Profissional), 5% dos adjudicatários com perfil de subscrição.",
        "**Não inclui** API, relatórios avulsos, loja, formação nem serviços — que podem valer mais que a subscrição.",
        "O SOM depende de **força de vendas**, não de produto: é o principal risco comercial.",
    ], 7.35, 4.4, 5.4, 1.9, tamanho=11.5)


def concorrencia(prs, m, numero):
    s = slide(prs, "Concorrência e diferenciação", "Onde o IQ OS ganha e onde perde", numero=numero)
    dados = [
        ["Alternativa", "O que faz bem", "Onde o IQ OS ganha"],
        ["Portais públicos (BASE, PLACSP, DECP)", "Fonte oficial, gratuita", "Junta países, empresas, pessoas, risco e IA num só sítio"],
        ["Informa D&B, Iberinform, eInforma", "Contas financeiras e notoriedade comercial", "Contratação pública a fundo (15,5 M contratos) e respostas citadas"],
        ["Agregadores de concursos", "Alertas de novas licitações", "Historial, concorrência e risco do adjudicatário, não só o anúncio"],
        ["Ferramentas de BI genéricas", "Flexíveis e conhecidas", "Dados já tratados, prontos a responder sem projeto de dados"],
        ["Chat IA genérico", "Barato e familiar", "Respostas com prova documental e audit trail"],
    ]
    tabela(s, dados, 0.6, 1.7, 12.1, 3.6, tamanho=10, larguras=[2.4, 2.7, 4.4])
    lista(s, [
        "**Diferencial defensável**: a junção por NIF entre contratos, societário, pessoas e risco — "
        "nenhum concorrente cobre as quatro camadas em Portugal.",
        "**Diferencial frágil**: a IA é replicável; o que não é replicável é o acervo e a cobertura.",
    ], 0.6, 5.5, 12.1, 1.4, tamanho=12)


def forcas(prs, m, numero):
    a, mk, p = m["ativo_de_dados"], m["mercado_enderecavel"], m["produto"]
    s = slide(prs, "Pontos fortes", "Cada afirmação tem um número medido por trás", numero=numero)
    itens = [
        f"**Ativo de dados próprio**: {a['documentos_totais']:,} documentos, {a['tamanho_gb']} GB, "
        f"{mk['contratos_agregados']:,} contratos e {mk['valor_agregado_eur'] / 1e9:,.0f} mil M€.".replace(",", " "),
        f"**Chave de junção única**: NIF liga contratos, empresas, pessoas, marcas, firmas, LEI e insolvências.",
        f"**Amplitude funcional**: {p['rotas_api']} rotas, {p['dominios_rotas']} domínios — "
        "mais alavancas de receita do que qualquer concorrente local.",
        "**IA com prova**: citações, validação anti-alucinação e audit trail — o que torna a resposta utilizável em compras públicas.",
        "**Multi-país por desenho**: PT, ES e FR já no mesmo modelo de dados.",
        "**Custo marginal baixo**: servir mais um utilizador não exige nova recolha.",
        "**Operação a jusante pronta**: loja, pedidos, pagamentos e CRM já existem.",
    ]
    lista(s, itens, 0.7, 1.8, 12.0, 5.0, tamanho=13.5)


def fraquezas(prs, m, numero):
    c, mk = m["cobertura"], m["mercado_enderecavel"]
    s = slide(prs, "Pontos fracos e riscos", "Ordenados por probabilidade × impacto", numero=numero)
    dados = [
        ["Risco", "Prova de hoje", "Impacto"],
        ["Concentração em Portugal", f"{c['entidades_pt_pct']}% das entidades", "TAM pequeno para o investimento"],
        ["Cobertura societária", f"{c['societario_cobertura_pct']}% das entidades com NIF", "Relatórios financeiros prometidos não são entregáveis a escala"],
        ["Cadastro incompleto", f"{100 - c['entidades_com_nif_pct']}% sem NIF", "Entidades fora do grafo e da pesquisa"],
        ["Dependência de terceiros", "2captcha, proxies, portais públicos", "Custo e interrupção fora de controlo"],
        ["Sem telemetria", "Sem contagem de uso/retensão/ARPU", "Decisões de produto e preço às cegas"],
        ["Dispersão de produto", f"{m['produto']['dominios_rotas']} domínios funcionais", "Manutenção e mensagem confusa"],
        ["RGPD", f"{c['pessoas_documentos']:,} documentos de pessoas".replace(",", " "), "Base legal, retenção e pedidos de titulares"],
        ["Bus factor", "Contexto técnico concentrado", "Risco operacional grave"],
    ]
    tabela(s, dados, 0.6, 1.7, 12.1, 4.5, tamanho=10.5, larguras=[2.5, 4.6, 5.0])


def scorecard(prs, m, numero):
    s = slide(prs, "Scorecard", f"Nota global {m['nota_global']}/5 — média de {len(m['scorecard'])} dimensões", numero=numero)
    imagem(s, GRAFICOS / "04_scorecard.png", 0.5, 1.7, 6.3, 5.0)
    dados = [["Dimensão", "Nota"]]
    for item in m["scorecard"]:
        dados.append([item["dimensao"], f"{item['nota']}"])
    tabela(s, dados, 7.1, 1.9, 3.4, 3.9, tamanho=11, larguras=[2.5, 0.9])
    caixa(
        s,
        "Leitura: os dados e o produto valem 5; o que trava é a cobertura, a medição e a operação comercial.",
        7.1, 6.05, 5.6, 0.7, tamanho=11.5, cor=DESTAQUE, fundo_caixa=FUNDO_2,
    )


def plano(prs, m, numero):
    s = slide(prs, "Plano de melhoria", "Sequenciado por retorno: o que fazer a 30, 90 e 365 dias", numero=numero)
    caixa(s, "30 dias — cobrar pelo que já existe", 0.6, 1.7, 4.0, 0.4, tamanho=13.5, negrito=True, cor=VERDE)
    lista(s, [
        "Três planos com limites (Explorador / Profissional / Empresa) e botão de subscrição.",
        "Telemetria mínima: utilizadores ativos, pesquisas, relatórios, conversão.",
        "Custo por pedido (LLM + captcha + storage) visível num painel.",
        "Duas páginas de venda por caso de uso.",
    ], 0.6, 2.15, 4.0, 4.4, tamanho=11, marcador="•")
    caixa(s, "90 dias — fechar a cobertura", 4.8, 1.7, 4.0, 0.4, tamanho=13.5, negrito=True, cor=AZUL)
    lista(s, [
        "Recolha societária por **janelas de datas** (≈721 consultas cobrem o país desde 2007).",
        "Deduplicação dos registos sem NIF (nome + morada + distrito).",
        "Profundar ES/FR com importações por ano e métricas de cobertura no produto.",
        "Base legal RGPD documentada para os dados de pessoas.",
    ], 4.8, 2.15, 4.0, 4.4, tamanho=11, marcador="•")
    caixa(s, "365 dias — escalar", 9.0, 1.7, 3.8, 0.4, tamanho=13.5, negrito=True, cor=ROXO)
    lista(s, [
        "API comercial com quotas e faturação de consumo.",
        "Prontidão enterprise: SSO, isolamento por cliente, SLA, auditoria exportável.",
        "Integrações (CRM dos clientes, Excel, Teams/Slack).",
        "Caso de estudo público com números medidos.",
    ], 9.0, 2.15, 3.8, 4.4, tamanho=11, marcador="•")


def impacto(prs, m, numero):
    mk = m["mercado_enderecavel"]
    s = slide(prs, "Impacto", "Económico, social e para o cliente — e como se mede", numero=numero)
    colunas = [
        ("Para o cliente", [
            "Pesquisa de dias → minutos, com prova documental.",
            "Menos propostas perdidas por informação incompleta.",
            "Deteção precoce de fornecedores em risco.",
        ]),
        ("Económico", [
            f"{mk['valor_agregado_eur'] / 1e9:,.0f} mil M€ de contratação analisável.".replace(",", " "),
            "Mais concorrência = melhor preço para o Estado.",
            "Empregos qualificados numa empresa de dados nacional.",
        ]),
        ("Social e institucional", [
            "Transparência: contratos, relações e titulares de cargos acessíveis.",
            "Igualdade de armas entre PMEs e grandes fornecedores.",
            "Auditoria e jornalismo com base factual citável.",
        ]),
    ]
    for indice, (titulo, itens) in enumerate(colunas):
        x = 0.6 + indice * 4.2
        caixa(s, titulo, x, 1.75, 3.95, 0.4, tamanho=14, negrito=True, cor=DESTAQUE)
        lista(s, itens, x, 2.2, 3.95, 3.0, tamanho=12, marcador="•")
    caixa(
        s,
        "Métricas de sucesso a instrumentar já: horas poupadas por processo, nº de fornecedores "
        "identificados por concurso, receita recorrente, custo por resposta de IA e retenção mensal.",
        0.6, 5.5, 12.1, 1.2, tamanho=12.5, fundo_caixa=FUNDO_2,
    )


def metodologia(prs, m, numero):
    s = slide(prs, "Como estes números foram obtidos", "Reprodutível: qualquer pessoa pode correr os scripts", numero=numero)
    lista(s, [
        "**Recolha automática** (`logs/_analise_negocio_iqos.py`) contra a API em execução, com sessão de serviço; "
        "cada valor guarda o endpoint de origem.",
        f"**Índices e volumetria** de `/elastic/indices`: {m['ativo_de_dados']['indices_totais']} índices, "
        f"{m['ativo_de_dados']['tamanho_gb']} GB.",
        "**Preços** do catálogo de relatórios (`/reports/catalogue`) — não de tabelas de marketing.",
        "**Ecrãs** capturados da aplicação real (`logs/_capturar_ecras_iqos.py`).",
        "**Não medido** (declarado como tal): "
        + (", ".join(m["nao_medido"]) if m["nao_medido"] else "nada") + ".",
        "**Assume-se** (e está marcado nos diapositivos): TAM/SAM/SOM, preço de 49 €/mês e taxas de conversão.",
    ], 0.7, 1.8, 12.0, 4.6, tamanho=13)
    caixa(
        s,
        "Sem telemetria de produto, qualquer número de clientes, retenção ou receita seria ficção — "
        "por isso não aparece nenhum.",
        0.7, 6.3, 12.0, 0.5, tamanho=12.5, negrito=True, cor=AMBAR,
    )


def proximos(prs, m, numero):
    s = slide(prs, "Decisões que faltam tomar", "O produto está pronto; a empresa ainda não está configurada", numero=numero)
    lista(s, [
        "**Foco**: escolher 2 casos de uso âncora (fornecedor do Estado e risco de contraparte) e dizer não ao resto.",
        "**Preço**: fixar planos e limites; matar a dependência de pedidos manuais.",
        "**Medição**: instrumentar o produto antes de vender, para saber o que funciona.",
        "**Cobertura**: decidir se se investe em societário/financeiro (custoso) ou se se vende só o que já existe.",
        "**Internacionalização**: Espanha antes de França; França só com parceiro local.",
        "**Risco jurídico**: contrato de utilização, RGPD e política de fontes escrita.",
    ], 0.7, 1.8, 12.0, 4.4, tamanho=13.5)
    caixa(
        s,
        "Próximo passo sugerido: 30 dias a empacotar preço e a medir uso — sem tocar no produto.",
        0.7, 6.3, 12.0, 0.5, tamanho=13, negrito=True, cor=DESTAQUE, fundo_caixa=FUNDO_2,
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    ficheiro = BASE / "analise_iqos.json"
    if not ficheiro.exists():
        print("Falta exports/business/analise_iqos.json — corre primeiro _analise_negocio_iqos.py", file=sys.stderr)
        return 1
    dados = json.loads(ficheiro.read_text(encoding="utf-8"))
    m = dados["metricas"]

    prs = novo_deck()
    capa(prs, m)
    sumario(prs, m, 2)
    o_produto(prs, m, 3)
    o_produto_2(prs, m, 4)
    ativo_dados(prs, m, 5)
    mercado(prs, m, 6)
    cobertura(prs, m, 7)
    modelo_negocio(prs, m, 8)
    precos(prs, m, 9)
    tam_sam_som(prs, m, 10)
    concorrencia(prs, m, 11)
    forcas(prs, m, 12)
    fraquezas(prs, m, 13)
    scorecard(prs, m, 14)
    plano(prs, m, 15)
    impacto(prs, m, 16)
    proximos(prs, m, 17)
    metodologia(prs, m, 18)

    prs.save(str(SAIDA))
    print(f"PowerPoint: {SAIDA} ({len(prs.slides._sldIdLst)} diapositivos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
