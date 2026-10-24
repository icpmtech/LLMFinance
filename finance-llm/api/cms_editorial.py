"""Conteúdo editorial do site público: páginas, blocos, SEO e imagens de marca.

Fica fora do `cms_store` de propósito — o `cms_store` é a máquina (documento,
revisões, publicação) e isto é o texto. Leem daqui:

* a semente (`cms_store._seed`), para uma instalação nova nascer com o site
  montado;
* a migração de instalações já em uso (`_atualizar_inicio_sabemos.py`), porque o
  deploy de código não envia a pasta `data/`.

Os *id* dos blocos são derivados do caminho da página e da posição, para que
correr a migração duas vezes dê exatamente o mesmo conteúdo.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# --------------------------------------------------------------------------
# Imagens de marca
# --------------------------------------------------------------------------
#: Ficheiros de `api/site_assets/` que a biblioteca de media deve ter, com o
#: título e o texto alternativo com que aparecem no CMS.
SEED_MEDIA: Sequence[Sequence[str]] = (
    ("logo-sabemos-studio.svg", "Logótipo Sabemos Studio", "Sabemos Studio", ""),
    ("icone-sabemos-studio.svg", "Ícone Sabemos Studio", "Sabemos Studio", "Usado como favicon do site."),
    (
        "capa-sabemos-studio.svg",
        "Capa do site",
        "Sabemos Studio — inteligência financeira e contratual",
        "Imagem de partilha (Open Graph) e de abertura da página inicial.",
    ),
    ("ilustracao-contratos.svg", "Ilustração · contratos públicos", "Contratos públicos: adjudicantes, adjudicatários e valores", ""),
    ("ilustracao-empresas.svg", "Ilustração · empresas", "Empresas: cadastro, relações societárias e sinais de risco", ""),
    ("ilustracao-municipios.svg", "Ilustração · municípios", "Municípios: despesa e contratação por concelho", ""),
    ("ilustracao-investigacao.svg", "Ilustração · investigação", "Investigação assistida com evidências citadas", ""),
    ("ilustracao-benchmarks.svg", "Ilustração · benchmarks", "Benchmarks de preços por loja", ""),
    (
        "ilustracao-pagina-nao-encontrada.svg",
        "Ilustração · página não encontrada",
        "Ficha de registo aberta com um lugar vazio e uma lupa a procurar o endereço em falta",
        "Usada na página de sistema do erro 404.",
    ),
    (
        "ilustracao-erro-interno.svg",
        "Ilustração · erro do serviço",
        "Painel de indicadores com uma peça solta e uma placa de aviso",
        "Usada na página de sistema do erro 500.",
    ),
    (
        "ilustracao-sem-ligacao.svg",
        "Ilustração · sem ligação",
        "Ligação interrompida entre o dispositivo e o servidor, com o que está guardado à vista",
        "Usada na página de sistema mostrada sem rede (service worker).",
    ),
    ("capa-post-bemvindo.svg", "Capa · bem-vindo ao blog", "Bem-vindo ao blog do Sabemos Studio", ""),
    ("capa-post-contratos-2026.svg", "Capa · contratos públicos em 2026", "Contratos públicos em 2026: o que os dados mostram", ""),
    # Diagramas: explicam o método e a leitura dos números, página a página.
    (
        "diagrama-percurso-do-dado.svg",
        "Diagrama · percurso do dado",
        "Percurso do dado: recolha, normalização, cálculo e evidência",
        "Como se chega ao número: do dado bruto à evidência citada.",
    ),
    (
        "diagrama-arquitetura-iqos.svg",
        "Diagrama · arquitetura do IQ OS",
        "Arquitetura do IQ OS: dados abertos, ontologia de entidades e produtos",
        "Os três andares da plataforma: o que entra, como se liga e o que sai.",
    ),
    (
        "diagrama-cadeia-do-contrato.svg",
        "Diagrama · cadeia do contrato",
        "Cadeia do contrato público: anúncio, concurso, adjudicação, contrato, aditivos e preço final",
        "O mesmo contrato visto em seis momentos, do anúncio ao valor que se paga.",
    ),
    (
        "diagrama-grafo-de-entidades.svg",
        "Diagrama · grafo de entidades",
        "Grafo de entidades: a empresa ligada a sócios, contratos, municípios e registos oficiais",
        "A empresa como nó central — cada ligação vem de uma fonte pública.",
    ),
    (
        "diagrama-municipio-vs-media.svg",
        "Diagrama · concelho e média nacional",
        "Indicadores de um concelho comparados com a média nacional",
        "A mesma grelha para os 308 concelhos, com a média nacional como referência.",
    ),
    (
        "diagrama-concentracao-de-mercado.svg",
        "Diagrama · concentração de mercado",
        "Concentração de fornecedores e posição de preço dentro do mesmo CPV",
        "O preço lido dentro do segmento e o peso dos maiores fornecedores.",
    ),
    (
        "diagrama-comparacao-lojas.svg",
        "Diagrama · índice de preço por loja",
        "Índice de preço por loja, com 100 a valer a média do estudo",
        "Como se lê um benchmark: dispersão entre lojas e melhor preço assinalado.",
    ),
    (
        "diagrama-cadeia-de-evidencia.svg",
        "Diagrama · cadeia de evidência",
        "Da pergunta à resposta citada: sub-perguntas, registos nas fontes e fontes numeradas",
        "O caminho de uma resposta: pergunta, registos e citação numerada.",
    ),
    (
        "diagrama-fontes-e-cobertura.svg",
        "Diagrama · fontes e cobertura",
        "Fontes usadas e cobertura por país e período",
        "Que fontes entram, para que países e desde quando.",
    ),
    (
        "diagrama-metodo.svg",
        "Diagrama · método em três passos",
        "Método em três passos: recolher, ligar e provar",
        "O método resumido: só fontes públicas, ligação por identidade e prova.",
    ),
    # As mesmas dez figuras, desenhadas em coluna para o telefone. O `imagem`
    # do site procura o par pelo nome (`<nome>-movel.svg`) e serve-o com
    # `<picture>` abaixo dos 900px — o CMS continua a apontar só para o largo.
    (
        "diagrama-percurso-do-dado-movel.svg",
        "Diagrama móvel · percurso do dado",
        "Percurso do dado: recolha, normalização, cálculo e evidência",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-arquitetura-iqos-movel.svg",
        "Diagrama móvel · arquitetura do IQ OS",
        "Arquitetura do IQ OS: dados abertos, ontologia de entidades e produtos",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-cadeia-do-contrato-movel.svg",
        "Diagrama móvel · cadeia do contrato",
        "Cadeia do contrato público: anúncio, concurso, adjudicação, contrato, aditivos e preço final",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-grafo-de-entidades-movel.svg",
        "Diagrama móvel · grafo de entidades",
        "Grafo de entidades: a empresa ligada a sócios, contratos, municípios e registos oficiais",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-municipio-vs-media-movel.svg",
        "Diagrama móvel · concelho e média nacional",
        "Indicadores de um concelho comparados com a média nacional",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-concentracao-de-mercado-movel.svg",
        "Diagrama móvel · concentração de mercado",
        "Concentração de fornecedores e posição de preço dentro do mesmo CPV",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-comparacao-lojas-movel.svg",
        "Diagrama móvel · índice de preço por loja",
        "Índice de preço por loja, com 100 a valer a média do estudo",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-cadeia-de-evidencia-movel.svg",
        "Diagrama móvel · cadeia de evidência",
        "Da pergunta à resposta citada: sub-perguntas, registos nas fontes e fontes numeradas",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-fontes-e-cobertura-movel.svg",
        "Diagrama móvel · fontes e cobertura",
        "Fontes usadas e cobertura por país e período",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    (
        "diagrama-metodo-movel.svg",
        "Diagrama móvel · método em três passos",
        "Método em três passos: recolher, ligar e provar",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    # Ilustrações que faltavam para completar o conjunto das seis áreas.
    (
        "ilustracao-mercado.svg",
        "Ilustração · mercado e preços",
        "Mercado e preços: posição dentro do segmento e concentração de fornecedores",
        "",
    ),
    (
        "ilustracao-fontes.svg",
        "Ilustração · fontes de dados",
        "Fontes de dados: registos verificados e cobertura por país e período",
        "",
    ),
    (
        "ilustracao-contactos.svg",
        "Ilustração · contactos",
        "Contactos: pedido escrito e resposta por email",
        "",
    ),
    (
        "ilustracao-plataforma.svg",
        "Ilustração · do estúdio à plataforma",
        "Do estúdio à plataforma: o Sabemos Studio publica leitura verificável com o IQ OS",
        "O que o estúdio faz e onde a plataforma entra.",
    ),
    (
        "ilustracao-iq-os-interior.svg",
        "Ilustração · interior do IQ OS",
        "Interior do IQ OS: módulos, indicadores, gráfico e assistente com fontes citadas",
        "O que se vê ao entrar: os módulos à esquerda, os indicadores em cima, o gráfico e o assistente com as fontes citadas.",
    ),
    (
        "ilustracao-iq-os-interior-movel.svg",
        "Ilustração móvel · interior do IQ OS",
        "Interior do IQ OS: módulos, indicadores, gráfico e assistente com fontes citadas",
        "Versão em coluna, para ecrãs estreitos.",
    ),
    # Ícones: usados no campo `icon_id` dos itens de um bloco de cartões.
    ("icone-fonte-nomeada.svg", "Ícone · fonte nomeada", "Fonte nomeada: cada número com origem", ""),
    ("icone-entidades-ligadas.svg", "Ícone · entidades ligadas", "Entidades ligadas pela identidade", ""),
    ("icone-fotografia-datada.svg", "Ícone · fotografia datada", "Fotografia datada: o número com o dia da leitura", ""),
    ("icone-conta-refazivel.svg", "Ícone · conta refazível", "Conta refazível: o critério publicado", ""),
    ("icone-mercados-previsoes.svg", "Ícone · mercados e previsões", "Mercados e previsões: séries, indicadores e previsão", ""),
    ("icone-contratos-empresas.svg", "Ícone · contratos e empresas", "Contratos e empresas: contratos ligados ao cadastro", ""),
    ("icone-pesquisa-assistentes.svg", "Ícone · pesquisa e assistentes", "Pesquisa e assistentes: perguntas com resposta citada", ""),
    ("icone-visualizacao-gestao.svg", "Ícone · visualização e gestão", "Visualização e gestão: painéis, grafos e CRM", ""),
    # Ícones das quatro razões para escrever (`/site/contactos`).
    ("icone-analise-medida.svg", "Ícone · análise à medida", "Análise à medida: gráfico lido à lupa, resposta a uma pergunta concreta", ""),
    ("icone-correcao.svg", "Ícone · correções", "Correções: número verificado na fonte e corrigido no registo", ""),
    ("icone-dados.svg", "Ícone · dados", "Dados: base indexada, cobertura e formato do que se entrega", ""),
    ("icone-imprensa.svg", "Ícone · imprensa", "Imprensa: contexto, dados e a fonte primária de cada número", ""),
)

#: Imagens dos produtos da loja (`/loja`). São a capa de cada produto do
#: catálogo de demonstração e ficam na mesma biblioteca de media do site; a
#: ligação ao produto é feita pelo `slug` (ver `shop_store.IMAGENS_PRODUTO`),
#: porque o `id` do media é aleatório em cada instalação.
SEED_MEDIA_LOJA: Sequence[Sequence[str]] = (
    (
        "produto-relatorio-contratacao-publica-portugal.svg",
        "Produto · Relatório de contratação pública",
        "Relatório de contratação pública em Portugal: adjudicantes, valores e concorrência",
        "",
    ),
    (
        "produto-relatorio-benchmark-portugal-espanha-franca.svg",
        "Produto · Relatório de benchmark",
        "Benchmark de preços do mesmo segmento em Portugal, Espanha e França",
        "",
    ),
    (
        "produto-dossie-de-empresa.svg",
        "Produto · Dossiê de empresa",
        "Dossiê de empresa: contratos, sócios, contas, insolvências e reputação",
        "",
    ),
    (
        "produto-assinatura-analista.svg",
        "Produto · Assinatura Analista",
        "Assinatura Analista: acesso mensal à plataforma, com pesquisa, dossiês e exportações",
        "",
    ),
    (
        "produto-creditos-investigacao-25.svg",
        "Produto · Créditos de investigação",
        "Pacote de 25 créditos de investigação assistida, sem prazo de validade",
        "",
    ),
    (
        "produto-formacao-contratacao-publica.svg",
        "Produto · Formação em contratação pública",
        "Formação de um dia em contratação pública, presencial ou online",
        "",
    ),
    (
        "produto-relatorio-mercados-iberia.svg",
        "Produto · Relatório de mercados",
        "Relatório mensal dos mercados ibéricos: setores, cotações e notícias",
        "",
    ),
    (
        "produto-manual-inteligencia-contratos.svg",
        "Produto · Manual impresso",
        "Manual impresso de inteligência de contratos, com fichas de trabalho",
        "",
    ),
    (
        "produto-dossie-de-mercado.svg",
        "Produto · Dossiê de mercado",
        "Dossiê de mercado de um setor: dimensão, operadores, contratos e tendências",
        "",
    ),
    (
        "produto-mala-de-arquivo.svg",
        "Produto · Mala de arquivo",
        "Mala de arquivo Sabemos, com lombada larga, para dossiês impressos",
        "",
    ),
)

#: Menu do site: rótulo e caminho da página, pela ordem em que aparece. O
#: «Benchmarks» só entra se a página existir na instalação. Os itens «Entrar»
#: e «Loja» são links directos para a plataforma, não páginas do site.
MENU_PRINCIPAL: Sequence[Sequence[str]] = (
    ("Início", ""),
    ("Pesquisar", "pesquisar"),
    ("Soluções", "solucoes"),
    ("Relatórios", "relatorios-gratuitos"),
    ("Fontes", "fontes"),
    ("Benchmarks", "benchmarks"),
    ("Blog", "blog"),
    ("Contactos", "contactos"),
    ("Sobre", "sobre"),
    ("Entrar", "/login"),
    ("Loja", "/loja"),
)

#: Rodapé: o essencial, mais curto do que o cabeçalho.
MENU_RODAPE: Sequence[Sequence[str]] = (
    ("Pesquisar", "pesquisar"),
    ("Soluções", "solucoes"),
    ("Relatórios", "relatorios-gratuitos"),
    ("Fontes", "fontes"),
    ("Blog", "blog"),
    ("Contactos", "contactos"),
    ("Sobre", "sobre"),
)


# --------------------------------------------------------------------------
# Construtores de blocos
# --------------------------------------------------------------------------
class _Blocos:
    """Lista de blocos de uma página, com *id* estável (`blk_<página>_<n>_<tipo>`)."""

    def __init__(self, prefixo: str) -> None:
        self._prefixo = prefixo or "pagina"
        self._n = 0

    def add(self, tipo: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._n += 1
        return {"id": f"blk_{self._prefixo}_{self._n:02d}_{tipo}", "type": tipo, "data": data or {}}

    def hero(self, title: str, subtitle: str, *, cta: Optional[Sequence[str]] = None, align: str = "esquerda", image: str = "") -> Dict[str, Any]:
        data: Dict[str, Any] = {"title": title, "subtitle": subtitle, "align": align}
        if cta:
            data["cta_label"], data["cta_href"] = cta
        if image:
            data["image_id"] = image
        return self.add("hero", data)

    def texto(self, title: str, markdown: str) -> Dict[str, Any]:
        return self.add("texto", {"title": title, "markdown": markdown})

    def numeros(self, title: str, items: Sequence[Sequence[str]]) -> Dict[str, Any]:
        return self.add("numeros", {"title": title, "items": [{"value": valor, "label": etiqueta, "note": nota} for valor, etiqueta, nota in items]})

    def cartoes(self, title: str, items: Sequence[Sequence[str]]) -> Dict[str, Any]:
        """Cartões: `(título, texto)` ou `(título, texto, ligação)`."""
        cartoes = []
        for item in items:
            cartao = {"title": item[0], "text": item[1]}
            if len(item) > 2 and item[2]:
                cartao["href"] = item[2]
            cartoes.append(cartao)
        return self.add("destaques", {"title": title, "items": cartoes})

    def passos(self, title: str, items: Sequence[Sequence[str]]) -> Dict[str, Any]:
        return self.add("passos", {"title": title, "items": [{"title": titulo, "text": texto} for titulo, texto in items]})

    def cartoes_com_icone(self, title: str, items: Sequence[Sequence[str]]) -> Dict[str, Any]:
        """Cartões com ícone: `(título, texto, id do ícone)` — o ícone é opcional."""
        cartoes = []
        for item in items:
            cartao = {"title": item[0], "text": item[1]}
            if len(item) > 2 and item[2]:
                cartao["icon_id"] = item[2]
            cartoes.append(cartao)
        return self.add("destaques", {"title": title, "items": cartoes})

    def tabela(self, title: str, head: Sequence[str], rows: Sequence[Sequence[str]]) -> Dict[str, Any]:
        return self.add("tabela", {"title": title, "head": list(head), "rows": [list(row) for row in rows]})

    def grafico(
        self,
        title: str,
        series: Sequence[Sequence[Any]],
        *,
        note: str = "",
        formato: str = "euros",
        legend: Sequence[str] = (),
        source: str = "",
    ) -> Dict[str, Any]:
        """Barras horizontais: `(nome, valor)`, `(nome, valor, 2.º valor)` ou `(nome, valor, 2.º valor, nota)`.

        Basta uma linha com segundo valor para todas as barras passarem a ter
        duas séries na **mesma escala** — é assim que se comparam pesos (número
        de contratos contra valor) sem obrigar o leitor a saltar entre gráficos.
        O `formato` é `euros`, `numero` ou `percentagem`.
        """
        itens = []
        for linha in series:
            item: Dict[str, Any] = {"label": linha[0], "value": linha[1]}
            # Um segundo valor vazio (`""`, `None` ou `0`) é ausência de série, não
            # uma barra a zero: sem isto, uma linha escrita com o lugar reservado
            # ganhava uma coluna de zeros no gráfico, na tabela e no PDF.
            if len(linha) > 2 and linha[2]:
                item["value2"] = linha[2]
            if len(linha) > 3 and linha[3]:
                item["note"] = linha[3]
            itens.append(item)
        data: Dict[str, Any] = {"title": title, "format": formato, "series": itens}
        if note:
            data["note"] = note
        rotulos = [nome for nome in legend if nome]
        if rotulos:
            data["legend"] = rotulos
        if source:
            data["source"] = source
        return self.add("grafico", data)

    def faq(self, title: str, items: Sequence[Sequence[str]]) -> Dict[str, Any]:
        return self.add("faq", {"title": title, "items": [{"question": pergunta, "answer": resposta} for pergunta, resposta in items]})

    def cta(self, title: str, text: str, label: str, href: str, botoes: Sequence[Sequence[str]] = ()) -> Dict[str, Any]:
        """Faixa de chamada à ação. `botoes` acrescenta botões secundários: `(texto, ligação)`."""
        data: Dict[str, Any] = {"title": title, "text": text, "button_label": label, "button_href": href}
        extras = [{"label": texto, "href": ligacao} for texto, ligacao in botoes if texto and ligacao]
        if extras:
            data["buttons"] = extras
        return self.add("cta", data)

    def citacao(self, quote: str, author: str = "") -> Dict[str, Any]:
        return self.add("citacao", {"quote": quote, "author": author})

    def aviso(self, text: str, *, tone: str = "") -> Dict[str, Any]:
        """Nota destacada; o `tone` é `amber`, `red` ou `green` (vazio = neutro)."""
        data: Dict[str, Any] = {"text": text}
        if tone in ("amber", "red", "green"):
            data["tone"] = tone
        return self.add("aviso", data)

    def galeria(self, media: Sequence[str]) -> Dict[str, Any]:
        return self.add("galeria", {"media_ids": [item for item in media if item]})

    def imagem(self, media: str, *, alt: str = "", caption: str = "") -> Dict[str, Any]:
        """Figura isolada, com legenda — é por aqui que entram os diagramas."""
        data: Dict[str, Any] = {"media_id": media}
        if alt:
            data["alt"] = alt
        if caption:
            data["caption"] = caption
        return self.add("imagem", data)

    def formulario(self, title: str, intro: str, *, button_label: str = "Enviar mensagem", anchor: str = "", note: str = "") -> Dict[str, Any]:
        """Formulário de contacto.

        `anchor` dá um endereço à secção (`#pedido`), para o botão da abertura
        trazer o leitor até ao formulário; `note` é a linha que fica ao lado do
        botão — o sítio para dizer o que acontece a seguir ao envio.
        """
        data: Dict[str, Any] = {"title": title, "intro": intro, "button_label": button_label}
        if anchor:
            data["anchor"] = anchor
        if note:
            data["note"] = note
        return self.add("formulario", data)

    def contactos(self, title: str, *, email: str = "", phone: str = "", address: str = "") -> Dict[str, Any]:
        return self.add("contactos", {"title": title, "email": email, "phone": phone, "address": address})

    def blog(self, title: str, limit: int = 3) -> Dict[str, Any]:
        return self.add("blog", {"title": title, "limit": limit})

    def pesquisa(
        self,
        title: str,
        intro: str = "",
        *,
        hint: str = "",
        exemplos: Sequence[str] = (),
        button: str = "",
    ) -> Dict[str, Any]:
        """Caixa de pesquisa do site (empresas, contratos, notícias e insolvências).

        O bloco desenha a caixa, as abas por tipo e os resultados lidos da
        plataforma em cada pedido: a página não guarda resultados, só a
        apresentação (título, texto de apoio, sugestões e rótulo do botão).
        """
        data: Dict[str, Any] = {"title": title}
        if intro:
            data["intro"] = intro
        if hint:
            data["hint"] = hint
        if exemplos:
            data["exemplos"] = list(exemplos)
        if button:
            data["button"] = button
        return self.add("pesquisa-sabemos", data)

    def relatorios(
        self,
        title: str,
        *,
        intro: str = "",
        limit: int = 24,
        free_only: bool = False,
        areas: Sequence[str] = (),
        cta_label: str = "Pedir este relatório",
        cta_href: str = "/reports",
    ) -> Dict[str, Any]:
        """Biblioteca de relatórios e documentos, agrupada por área de trabalho.

        O conteúdo é lido em tempo de renderização (`reports_library`): a página
        não guarda listas que ficam velhas — publica-se um relatório novo no
        Estúdio e ele aparece aqui.
        """
        data: Dict[str, Any] = {"title": title, "limit": limit, "free_only": free_only}
        if intro:
            data["intro"] = intro
        if areas:
            data["areas"] = list(areas)
        if cta_label:
            data["cta_label"] = cta_label
        if cta_href:
            data["cta_href"] = cta_href
        return self.add("relatorios", data)


def _pagina(
    *,
    page_id: str,
    title: str,
    path: str,
    prefixo: str,
    excerpt: str,
    seo_title: str,
    seo_description: str,
    keywords: Sequence[str],
    blocks: List[Dict[str, Any]],
    menu_label: str = "",
    menu_order: int = 0,
    template: str = "pagina-padrao",
    image_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": page_id,
        "title": title,
        # O caminho público é montado pelo CMS a partir do `slug` desta página e
        # dos ascendentes (`_page_path`), por isso o `slug` é só o último troço.
        "slug": path.rsplit("/", 1)[-1] or "inicio",
        "path": path,
        "parent_id": parent_id,
        "template": template,
        "status": "publicado",
        "scheduled_at": None,
        "show_in_menu": True,
        "menu_order": menu_order,
        "menu_label": menu_label,
        "excerpt": excerpt,
        "blocks": blocks,
        "seo": {
            "title": seo_title,
            "description": seo_description,
            "keywords": list(keywords),
            "image_id": image_id,
            "noindex": False,
        },
    }


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------
INICIO_ID = "pag_inicio"
SOBRE_ID = "pag_sobre"
BLOG_ID = "pag_blog"

INICIO_EXCERPT = "O Sabemos Studio junta contratos públicos, empresas, mercado e investigação assistida numa só plataforma."

INICIO_SEO: Dict[str, Any] = {
    "title": "Sabemos Studio — contratos públicos, empresas e dados abertos",
    "description": "O Sabemos Studio transforma dados abertos em inteligência financeira: contratos públicos, empresas, municípios e investigação com evidências citadas.",
    "keywords": [
        "Sabemos Studio",
        "sabemos.studio",
        "contratos públicos",
        "Portal BASE",
        "IQ OS",
        "empresas",
        "inteligência financeira",
        "dados abertos",
    ],
    "image_id": None,
    "noindex": False,
}

SOBRE_SEO: Dict[str, Any] = {
    "title": "Sobre o Sabemos Studio",
    "description": "Quem faz o IQ OS, com que fontes trabalhamos e que princípios seguimos.",
    "keywords": ["Sabemos Studio", "sobre", "dados abertos"],
    "image_id": None,
    "noindex": False,
}

#: Números reais da plataforma (contratos indexados, cadastro de entidades).
NUMEROS_DA_PLATAFORMA: Sequence[Sequence[str]] = (
    ("2 273 420", "Contratos públicos", "Portal BASE · Portugal, 2012 a 2026"),
    ("214 123", "Entidades no cadastro", "empresas, municípios e outras entidades"),
    ("12 090", "Adjudicantes", "compradores públicos identificados"),
    ("198,8 mil M€", "Valor contratado mapeado", "relações adjudicante–adjudicatário"),
)

#: As seis capacidades, na ordem em que aparecem na página inicial e no menu.
CAPACIDADES: Sequence[Sequence[str]] = (
    ("Contratos públicos", "Adjudicantes, adjudicatários, valores e procedimento, por região e por ano.", "solucoes/contratos-publicos"),
    ("Empresas e pessoas", "Cadastro, relações societárias, gerentes e sinais de risco a partir de fontes públicas.", "solucoes/empresas-e-pessoas"),
    ("Municípios", "Despesa, execução e contratação por concelho, com os indicadores oficiais do INE.", "solucoes/municipios"),
    ("Mercado e preços", "Concentração, concorrência e preços por CPV, com leitura estatística.", "solucoes/mercado-e-precos"),
    ("Benchmarks", "Comparação de preços e produtos entre lojas, a partir de recolhas próprias.", "solucoes/benchmarks-de-produtos"),
    ("Investigação assistida", "Perguntas em linguagem natural com resposta citada e grafo de evidências.", "solucoes/investigacao"),
)


def conteudo_da_inicio(media: Dict[str, str]) -> List[Dict[str, Any]]:
    """Blocos da página inicial (a mesma para a semente e para a migração)."""
    b = _Blocos("inicio")
    return [
        b.hero(
            "Inteligência financeira e contratual, num só sítio",
            "Contratos públicos de Portugal, Espanha e França, cadastro de empresas, mercado e investigação assistida — sempre com a fonte citada.",
            cta=("Explorar o blog", "/site/blog"),
            align="centro",
        ),
        b.numeros("O que já sabemos.", NUMEROS_DA_PLATAFORMA),
        b.texto(
            "O que é o Sabemos Studio",
            "O **Sabemos Studio** é um estúdio de produtos de dados: pegamos no que já é público — "
            "contratos, contas e registos — e devolvemos leitura que se pode verificar.\n\n"
            "O **IQ OS** é a plataforma onde isso acontece: recolha contínua de contratos públicos e de "
            "finanças locais, uma ontologia de entidades (empresas, municípios e pessoas) e assistentes de "
            "investigação que respondem com a evidência à vista.",
        ),
        b.imagem(
            media.get("ilustracao-plataforma.svg", ""),
            alt="Do estúdio à plataforma: o Sabemos Studio publica leitura verificável com o IQ OS",
            caption="O estúdio publica; a plataforma liga contratos, empresas, municípios e mercado.",
        ),
        b.cartoes_com_icone(
            "O que nos distingue",
            [
                (
                    "Fonte nomeada",
                    "Portal BASE, INE, registos oficiais e boletins. Nenhum número aparece sem origem.",
                    media.get("icone-fonte-nomeada.svg", ""),
                ),
                (
                    "Entidades ligadas",
                    "A mesma empresa, o mesmo município e a mesma pessoa são o mesmo objeto em toda a "
                    "plataforma, mesmo quando o nome aparece escrito de outra maneira.",
                    media.get("icone-entidades-ligadas.svg", ""),
                ),
                (
                    "Fotografia datada",
                    "Cada análise guarda o dia em que foi lida: o número citado continua a ser o número que se viu.",
                    media.get("icone-fotografia-datada.svg", ""),
                ),
                (
                    "Conta refazível",
                    "Publicamos o critério e o registo, para quem lê poder repetir o cálculo.",
                    media.get("icone-conta-refazivel.svg", ""),
                ),
            ],
        ),
        # A plataforma, apresentada a quem lê o site: o que se vê lá dentro e as
        # duas portas de entrada (a conta e a loja).
        b.texto(
            "A plataforma por dentro: o IQ OS",
            "Se quiser trabalhar os dados em vez de os ler, é aqui que entra o **IQ OS** — a plataforma "
            "do Sabemos Studio, no browser e sem instalação.\n\n"
            "Lá dentro estão os mesmos dados que alimentam este site, ainda em bruto: cotações e mercados, "
            "contratos públicos, cadastro de entidades e assistentes de investigação, lado a lado — para não "
            "se perder o contexto entre o número e a sua origem.",
        ),
        b.imagem(
            media.get("ilustracao-iq-os-interior.svg", ""),
            alt="Interior do IQ OS: módulos, indicadores, gráfico e assistente com fontes citadas",
            caption="Por dentro: os módulos, os indicadores, o gráfico e o assistente com as fontes citadas.",
        ),
        b.cartoes_com_icone(
            "O que encontra na plataforma",
            [
                (
                    "Mercados e previsões",
                    "Cotações e histórico, indicadores técnicos, sentimento das notícias e previsão com ARIMA e Kronos.",
                    media.get("icone-mercados-previsoes.svg", ""),
                ),
                (
                    "Contratos e empresas",
                    "Os mesmos contratos de Portugal, Espanha e França, ligados às fichas de empresa, marcas, "
                    "firmas e relações adjudicante–adjudicatário.",
                    media.get("icone-contratos-empresas.svg", ""),
                ),
                (
                    "Pesquisa e assistentes",
                    "Pesquisa total e dossiês de tema, respostas do Hermes com citação à vista e agentes "
                    "configuráveis com os seus próprios documentos.",
                    media.get("icone-pesquisa-assistentes.svg", ""),
                ),
                (
                    "Visualização e gestão",
                    "Painéis, grafos de entidades, mapas e visualizador, com o CRM e a agenda comercial ligados "
                    "ao mesmo cadastro.",
                    media.get("icone-visualizacao-gestao.svg", ""),
                ),
            ],
        ),
        b.cta(
            "Entrar na plataforma ou visitar a loja",
            "A conta é gratuita e abre no browser: a palavra-passe é derivada com scrypt e as sessões ficam "
            "auditadas. Na loja encontra relatórios, dossiês, formação e a assinatura da plataforma.",
            "Entrar na plataforma",
            "/login",
            botoes=(("Visitar a loja", "/loja"),),
        ),
        b.cartoes("Por onde começar", [(titulo, texto, f"/site/{caminho}") for titulo, texto, caminho in CAPACIDADES]),
        b.passos(
            "Como se chega ao número",
            [
                ("Recolha", "Lemos dados abertos: Portal BASE para contratação, INE para finanças locais, registos oficiais de empresas e boletins."),
                ("Normalização", "Limpamos, ligamos entidades e consolidamos tudo numa ontologia única — a mesma empresa é a mesma em todo o lado."),
                ("Cálculo", "Calculamos indicadores e guardamos a fotografia com a data da leitura, para o número não mudar por baixo da análise."),
                ("Evidência", "Cada resposta cita o documento e o registo de onde saiu, e pode ser reproduzida por quem a lê."),
            ],
        ),
        b.imagem(
            media.get("diagrama-percurso-do-dado.svg", ""),
            alt="Percurso do dado: recolha, normalização, cálculo e evidência",
            caption="Da fonte ao número: recolha, normalização, cálculo e evidência.",
        ),
        b.galeria(
            [
                media.get("ilustracao-contratos.svg", ""),
                media.get("ilustracao-empresas.svg", ""),
                media.get("ilustracao-municipios.svg", ""),
                media.get("ilustracao-investigacao.svg", ""),
                media.get("ilustracao-mercado.svg", ""),
                media.get("ilustracao-fontes.svg", ""),
            ]
        ),
        b.cartoes(
            "Explorar o site",
            [
                ("Soluções", "As seis áreas onde trabalhamos, do contrato ao indicador.", "/site/solucoes"),
                ("Fontes de dados", "De onde vem cada número, com período e cobertura.", "/site/fontes"),
                ("Contactos", "Um pedido concreto, uma análise à medida ou uma correção a apontar.", "/site/contactos"),
            ],
        ),
        b.faq(
            "Perguntas frequentes",
            [
                (
                    "Que fontes usam?",
                    "Só fontes públicas: Portal BASE (contratação pública), INE (despesa e finanças locais), registos oficiais de empresas, boletins e diários da República, e recolhas próprias de preços. Cada resposta indica de onde veio.",
                ),
                (
                    "Com que frequência os dados são atualizados?",
                    "A recolha é contínua. As páginas de análise guardam a **fotografia** do dia em que foram geradas, com a data à vista, para que o número citado continue a ser o número que foi lido.",
                ),
                (
                    "Que países cobrem?",
                    "Portugal, Espanha e França na contratação pública, com o cadastro de entidades a incluir contrapartes de outros países.",
                ),
                (
                    "Posso citar os números que aqui estão?",
                    "Sim. Damos a fonte primária e o critério usado, para poder refazer a conta. Se precisar do detalhe, fale connosco.",
                ),
                (
                    "O Sabemos Studio e o IQ OS são a mesma coisa?",
                    "O **Sabemos Studio** é quem faz; o **IQ OS** é a plataforma. Este site é a parte editorial — análises, fichas e notas de método.",
                ),
            ],
        ),
        b.cta("Precisa de um número que aguente ser citado?", "Lemos os dados abertos, ligamos as entidades e mostramos a evidência por trás de cada valor.", "Ver as análises", "/site/blog"),
        b.blog("Últimos artigos", 3),
    ]


def conteudo_da_sobre(media: Dict[str, str]) -> List[Dict[str, Any]]:
    """Blocos da página «Sobre»."""
    b = _Blocos("sobre")
    return [
        b.hero(
            "Sobre o Sabemos Studio",
            "Um estúdio de produtos de dados: recolha, ontologia e assistentes de investigação.",
        ),
        b.texto(
            "Como trabalhamos",
            "## Princípios\n\n"
            "- **Fonte aberta** — todo o dado bruto vem de fontes públicas.\n"
            "- **Rasto** — cada resposta cita a evidência que a sustenta.\n"
            "- **Reutilização** — o mesmo conteúdo serve a plataforma, o site e o blog.\n\n"
            "## O que fazemos\n\n"
            "Recolhemos e ligamos dados de contratação pública, finanças locais, registos de empresas e "
            "boletins oficiais. Em cima disso construímos indicadores, fichas por entidade e assistentes que "
            "respondem com a fonte à vista — para quem tem de decidir e para quem tem de justificar.",
        ),
        b.imagem(
            media.get("diagrama-metodo.svg", ""),
            alt="Método em três passos: recolher, ligar e provar",
            caption="O método em três passos: recolher, ligar e provar.",
        ),
        b.cartoes(
            "O que não fazemos",
            [
                ("Nada de dados privados", "Não usamos registos privados nem informação obtida por meios opacos."),
                ("Nada de números sem origem", "Se não conseguimos apontar a fonte, o número não entra."),
                ("Nada de previsões disfarçadas", "Dizemos o que os dados mostram — e o que não mostram."),
            ],
        ),
        b.faq(
            "Perguntas frequentes",
            [
                ("Quem pode usar o que publicamos?", "Tudo o que está neste site pode ser citado, com ligação à página de origem. Os dados brutos são de fontes públicas e têm as regras da fonte."),
                ("Trabalham por encomenda?", "Sim: análises a partir dos dados abertos que já tratamos, ou a partir de um conjunto novo. Diga-nos a pergunta em Contactos."),
                ("Corrigem erros?", "Sim, e damos prioridade. Se apontar uma incorreção, escrevemos a correção na própria página."),
            ],
        ),
        b.cta("Tem uma pergunta?", "A plataforma investiga com evidências citadas — comece pelo blog para ver o método em prática.", "Ler o blog", "/site/blog"),
    ]


def paginas_do_site(media: Dict[str, str]) -> List[Dict[str, Any]]:
    """Páginas novas do site (pesquisar, soluções, fontes e contactos), por ordem de menu."""
    paginas: List[Dict[str, Any]] = []

    # --- Pesquisar (a caixa única do site) --------------------------------
    b = _Blocos("pesquisar")
    paginas.append(
        _pagina(
            page_id="pag_pesquisar",
            title="Sabemos",
            path="pesquisar",
            prefixo="pesquisar",
            menu_label="Sabemos",
            menu_order=1,
            excerpt="Uma caixa para procurar empresas, contratos públicos, notícias e insolvências a partir de dados abertos.",
            seo_title="Sabemos — pesquisar empresas, contratos, notícias e insolvências",
            seo_description=(
                "Pesquise por empresa, NIF, objeto de contrato ou processo de insolvência: fichas com "
                "contratos públicos, insolvências do CIRE e notícias, a partir de dados abertos."
            ),
            keywords=["pesquisar", "empresas", "NIF", "contratos públicos", "insolvências", "CIRE", "notícias"],
            blocks=[
                b.pesquisa(
                    "Sabemos",
                    "Empresas, contratos públicos, notícias e insolvências — a mesma caixa para tudo o que os dados abertos dizem.",
                    hint="Um nome, um NIF ou uma palavra do objeto de um contrato. Sem filtros para escolher antes de procurar.",
                    exemplos=("Galp", "Município de Lisboa", "501964843", "insolvência"),
                ),
                b.texto(
                    "O que cada resultado abre",
                    "Cada resultado abre uma **ficha no site**, com os números e a fonte à vista:\n\n"
                    "- **Empresa** — NIF, contratos públicos, valores por papel (adjudicante e adjudicatário), "
                    "insolvências publicadas no CIRE e notícias que a mencionam.\n"
                    "- **Contrato** — objeto, preço contratual, procedimento, partes (com ligação à ficha de cada uma), "
                    "CPV, local de execução e peças do procedimento.\n"
                    "- **Notícia** — abre na publicação original (SAPO, Lusa, ECO, Observador, Jornal Económico…).\n"
                    "- **Insolvência** — abre a ficha da entidade visada, com o processo e o tribunal.\n\n"
                    "A pesquisa é feita sobre os índices da plataforma (Portal BASE, CIRE/CITIUS, cadastro de "
                    "entidades e recolha de imprensa); não há resultados inventados nem estimativas.",
                ),
                b.cta(
                    "Precisa do dossiê completo?",
                    "A plataforma junta pessoas, marcas, atos societários e risco na mesma ficha — com exportação e relatório.",
                    "Falar connosco",
                    "/site/contactos",
                    botoes=(("Ver as fontes", "/site/fontes"),),
                ),
            ],
        )
    )

    # --- Soluções (página-mãe das capacidades) -----------------------------
    b = _Blocos("solucoes")
    paginas.append(
        _pagina(
            page_id="pag_solucoes",
            title="Soluções",
            path="solucoes",
            prefixo="solucoes",
            menu_label="Soluções",
            menu_order=2,
            excerpt="Seis áreas de trabalho: contratos públicos, empresas e pessoas, municípios, mercado, benchmarks e investigação assistida.",
            seo_title="Soluções",
            seo_description="As seis áreas do Sabemos Studio: contratos públicos, empresas e pessoas, municípios, mercado e preços, benchmarks e investigação assistida.",
            keywords=["Sabemos Studio", "soluções", "contratos públicos", "dados abertos", "inteligência financeira"],
            blocks=[
                b.hero(
                    "O que fazemos, por área",
                    "Seis áreas, a mesma regra: dado público, fonte nomeada e conta refazível.",
                    cta=("Ver as fontes", "/site/fontes"),
                ),
                b.cartoes("As áreas", [(titulo, texto, f"/site/{caminho}") for titulo, texto, caminho in CAPACIDADES]),
                b.galeria(
                    [
                        media.get("ilustracao-contratos.svg", ""),
                        media.get("ilustracao-empresas.svg", ""),
                        media.get("ilustracao-municipios.svg", ""),
                        media.get("ilustracao-mercado.svg", ""),
                        media.get("ilustracao-benchmarks.svg", ""),
                        media.get("ilustracao-investigacao.svg", ""),
                    ]
                ),
                b.passos(
                    "O que é igual em todas",
                    [
                        ("Uma pergunta concreta", "Começamos pelo que se quer saber — não por um painel cheio de gráficos."),
                        ("Dados ligados", "Cruzamos contratação, contas e registos pela entidade certa, não pelo nome parecido."),
                        ("Resposta com rasto", "Cada valor sai com a fonte, o período e o critério."),
                        ("Fotografia datada", "O resultado fica guardado com a data da leitura."),
                    ],
                ),
                b.imagem(
                    media.get("diagrama-arquitetura-iqos.svg", ""),
                    alt="Arquitetura do IQ OS: dados abertos, ontologia de entidades e produtos",
                    caption="Os três andares: o que entra, como se liga e o que sai.",
                ),
                b.numeros("O que já sabemos.", NUMEROS_DA_PLATAFORMA),
                b.cta("Não encontrou a sua área?", "Diga-nos a pergunta e verificamos se os dados abertos a respondem.", "Falar connosco", "/site/contactos"),
            ],
        )
    )

    # --- Contratos públicos -----------------------------------------------
    b = _Blocos("solucoes-contratos")
    paginas.append(
        _pagina(
            page_id="pag_sol_contratos",
            title="Contratos públicos",
            path="solucoes/contratos-publicos",
            prefixo="solucoes-contratos",
            parent_id="pag_solucoes",
            excerpt="Quem contrata, com quem, por quanto e por que procedimento — a partir do Portal BASE e das plataformas de Espanha e França.",
            seo_title="Contratos públicos: dados abertos",
            seo_description="Adjudicantes, adjudicatários, valores e procedimento nos contratos públicos de Portugal, Espanha e França, a partir de dados abertos.",
            keywords=["contratos públicos", "Portal BASE", "adjudicantes", "adjudicatários", "contratação pública", "Sabemos Studio"],
            blocks=[
                b.hero(
                    "Contratos públicos, do anúncio ao preço final",
                    "Quem contrata, com quem, por quanto e por que procedimento — em Portugal, Espanha e França.",
                    cta=("Ver o blog", "/site/blog"),
                ),
                b.texto(
                    "Que perguntas responde",
                    "A contratação pública é o rasto mais completo de como o dinheiro público se transforma em "
                    "fornecimento. Aqui junta-se o **anúncio**, o **contrato** e os **aditivos** para responder a:\n\n"
                    "- Quem são os maiores compradores, por município, distrito e setor.\n"
                    "- Que empresas ganham, com que concentração e com que dependência de um único cliente.\n"
                    "- Que procedimento foi usado e o que isso faz ao preço.\n"
                    "- Como o valor se reparte ao longo do ano e por tipo de bem ou serviço (CPV).",
                ),
                b.imagem(
                    media.get("diagrama-cadeia-do-contrato.svg", ""),
                    alt="Cadeia do contrato público: anúncio, concurso, adjudicação, contrato, aditivos e preço final",
                    caption="O mesmo contrato em seis momentos — do anúncio ao valor que se paga.",
                ),
                b.cartoes(
                    "O que pode ver",
                    [
                        ("Por entidade", "Ficha do comprador e do fornecedor: contratos, valores, CPV e evolução."),
                        ("Por território", "Distrito e município de execução, com leitura comparada entre concelhos."),
                        ("Por procedimento", "Ajuste direto, consulta e concurso — volume, valor e quem ganha."),
                        ("Por CPV", "Onde está o dinheiro dentro de cada família de bens e serviços."),
                        ("Concorrência", "Quantos concorrentes por procedimento e quanto pesa o maior fornecedor."),
                        ("Anomalias", "Preços fora do padrão do segmento e sinais de concentração."),
                    ],
                ),
                b.galeria([media.get("ilustracao-contratos.svg", "")]),
                b.tabela(
                    "Exemplo de leitura",
                    ["Indicador", "O que diz"],
                    [
                        ["Valor contratado no ano", "Soma dos contratos com data de celebração no período."],
                        ["Taxa de ajuste direto", "Peso do ajuste direto no número de contratos."],
                        ["Concentração (HHI)", "Quanto o mercado local depende de poucos fornecedores."],
                        ["Dias até à assinatura", "Do anúncio ao contrato: sinal de urgência ou de procedimento."],
                    ],
                ),
                b.faq(
                    "Perguntas frequentes",
                    [
                        ("De onde vêm os contratos?", "Do Portal BASE (Portugal), da Plataforma de Contratación del Sector Público (Espanha) e da plataforma francesa, mais os boletins e diários oficiais."),
                        ("Com que detalhe?", "Contrato a contrato: objeto, valor, procedimento, adjudicantes, adjudicatários, datas e CPV."),
                        ("E o que não se vê?", "O que a fonte não publica não é inventado: quando o campo vem vazio, di-lo-mos em vez de preencher."),
                    ],
                ),
                b.cta("Precisa do detalhe de um comprador ou fornecedor?", "Conseguimos montar a ficha completa, contrato a contrato, com a evidência anexada.", "Pedir uma análise", "/site/contactos"),
            ],
        )
    )

    # --- Empresas e pessoas ------------------------------------------------
    b = _Blocos("solucoes-empresas")
    paginas.append(
        _pagina(
            page_id="pag_sol_empresas",
            title="Empresas e pessoas",
            path="solucoes/empresas-e-pessoas",
            prefixo="solucoes-empresas",
            parent_id="pag_solucoes",
            excerpt="Cadastro de empresas, relações societárias, gerentes e sinais de risco, cruzados com a contratação pública.",
            seo_title="Empresas e pessoas: cadastro e risco",
            seo_description="Cadastro de empresas, relações societárias, gerentes, benefício efetivo e sinais de risco, cruzados com contratos públicos e registos oficiais.",
            keywords=["empresas", "cadastro", "relações societárias", "beneficiário efetivo", "risco", "NIPC", "Sabemos Studio"],
            blocks=[
                b.hero(
                    "Quem está por trás de cada entidade",
                    "Cadastro, relações societárias, gerentes e sinais de risco — ligados aos contratos que assina.",
                    cta=("Falar connosco", "/site/contactos"),
                ),
                b.texto(
                    "Da ficha ao sinal",
                    "Uma empresa não é um nome: é um **NIPC** com sócios, gerentes, moradas, capital e histórico. "
                    "Ligamos o cadastro público à contratação e aos registos oficiais para responder a:\n\n"
                    "- Quem são os gerentes e os sócios, e onde mais aparecem.\n"
                    "- Que entidades partilham morada, gerência ou grupo económico.\n"
                    "- Que sinais existem — insolvência, dívida a fornecedores, alterações recentes.\n"
                    "- Quanto do negócio de uma empresa depende de compradores públicos.",
                ),
                b.imagem(
                    media.get("diagrama-grafo-de-entidades.svg", ""),
                    alt="Grafo de entidades: a empresa ligada a sócios, contratos, municípios e registos oficiais",
                    caption="A empresa como nó central — cada ligação vem de uma fonte pública.",
                ),
                b.cartoes(
                    "O que pode ver",
                    [
                        ("Ficha da empresa", "Identificação, CAE, morada, capital e situação registal."),
                        ("Relações societárias", "Sócios, gerentes e grupos, com o que muda ao longo do tempo."),
                        ("Benefício efetivo", "Cadeia de propriedade até à pessoa singular, a partir de registos públicos."),
                        ("Dívida e insolvência", "Publicações de insolvência e dívidas a fornecedores registadas."),
                        ("Apoios e fundos", "Subvenções e apoios públicos recebidos, com a fonte."),
                        ("Rede de contratos", "Com quem contrata, quanto e com que regularidade."),
                    ],
                ),
                b.passos(
                    "Como se liga",
                    [
                        ("Normalizar", "Limpamos nomes, NIF e moradas — a mesma entidade escrita de várias formas torna-se uma só."),
                        ("Cruzar", "Juntamos cadastro, registos, contratos e publicações oficiais."),
                        ("Pontuar", "Sinais de risco entram com o critério à vista, não como caixa negra."),
                        ("Explicar", "Cada sinal mostra o documento que o sustenta."),
                    ],
                ),
                b.galeria([media.get("ilustracao-empresas.svg", "")]),
                b.cta("Quer a ficha completa de uma empresa?", "Montamos a ficha com sócios, contratos e sinais, e dizemos de onde vem cada campo.", "Pedir uma análise", "/site/contactos"),
            ],
        )
    )

    # --- Municípios --------------------------------------------------------
    b = _Blocos("solucoes-municipios")
    paginas.append(
        _pagina(
            page_id="pag_sol_municipios",
            title="Municípios",
            path="solucoes/municipios",
            prefixo="solucoes-municipios",
            parent_id="pag_solucoes",
            excerpt="Despesa, execução e contratação por concelho, com os indicadores oficiais do INE e o Portal BASE.",
            seo_title="Municípios: despesa e contratação",
            seo_description="Despesa, execução orçamental e contratação pública de cada município português, com os indicadores oficiais do INE e o Portal BASE.",
            keywords=["municípios", "despesa municipal", "execução orçamental", "INE", "Portal BASE", "concelhos", "Sabemos Studio"],
            blocks=[
                b.hero(
                    "O concelho, em números que se comparam",
                    "Despesa, execução e contratação de cada município — os 308, com os mesmos critérios.",
                    cta=("Ver as fontes", "/site/fontes"),
                ),
                b.texto(
                    "Porque é que isto interessa",
                    "Os municípios são a fatia do Estado mais próxima de quem vive no território e a que mais "
                    "difícil é de comparar: cada um publica como quer, em anos diferentes, com rubricas "
                    "resumidas de outra maneira.\n\n"
                    "Nós lemos os indicadores oficiais do **INE** e os contratos do **Portal BASE** e "
                    "apresentamos todos os concelhos na mesma grelha: despesa total, correntes e de capital, "
                    "pessoal e bens e serviços, contratação celebrada e adjudicatários.",
                ),
                b.numeros(
                    "O que cobre",
                    [("308", "Municípios", "todos os concelhos de Portugal"), ("2", "Fontes oficiais", "INE e Portal BASE"), ("2012→", "Histórico de contratos", "com fotografia datada")],
                ),
                b.imagem(
                    media.get("diagrama-municipio-vs-media.svg", ""),
                    alt="Indicadores de um concelho comparados com a média nacional",
                    caption="O concelho comparado com a média nacional — a mesma grelha para todos.",
                ),
                b.tabela(
                    "Indicadores da grelha",
                    ["Indicador", "Fonte"],
                    [
                        ["Despesa total e por classificação", "INE · execução orçamental das autarquias"],
                        ["Despesas correntes e de capital", "INE"],
                        ["Despesas com pessoal", "INE"],
                        ["Contratos celebrados e valor", "Portal BASE"],
                        ["Adjudicatários do concelho", "Portal BASE"],
                    ],
                ),
                b.galeria([media.get("ilustracao-municipios.svg", "")]),
                b.faq(
                    "Perguntas frequentes",
                    [
                        ("Porque é que uns concelhos aparecem com mais anos?", "Porque é assim que o INE publica: em séries temporais. Preenchemos o que existe e não estimamos o que falta."),
                        ("Posso pedir a ficha de um concelho?", "Sim. As fichas por concelho podem ser publicadas como páginas próprias, com o texto e os números lado a lado."),
                    ],
                ),
                b.cta("Precisa de comparar concelhos?", "Fazemos a leitura comparada — despesa, contratação e evolução — com a fonte citada em cada linha.", "Pedir uma análise", "/site/contactos"),
            ],
        )
    )

    # --- Mercado e preços --------------------------------------------------
    b = _Blocos("solucoes-mercado")
    paginas.append(
        _pagina(
            page_id="pag_sol_mercado",
            title="Mercado e preços",
            path="solucoes/mercado-e-precos",
            prefixo="solucoes-mercado",
            parent_id="pag_solucoes",
            excerpt="Concentração, concorrência e preços por CPV, com leitura estatística e sinais de anomalia.",
            seo_title="Mercado e preços por CPV",
            seo_description="Concentração, concorrência, preços e anomalias por CPV na contratação pública: quem domina cada segmento e quanto se paga acima do padrão.",
            keywords=["mercado", "preços", "CPV", "concentração", "concorrência", "anomalias", "Sabemos Studio"],
            blocks=[
                b.hero(
                    "O que se paga, dentro de cada segmento",
                    "Concentração, concorrência e preços por família de bens e serviços (CPV).",
                ),
                b.texto(
                    "Um preço só faz sentido no seu segmento",
                    "Comparar um contrato de obras de saneamento com um de material de escritório não diz nada. "
                    "Por isso o mercado é lido **dentro do mesmo CPV**, com os mesmos critérios:\n\n"
                    "- mediana e percentis do preço, em vez de médias que a cauda distorce;\n"
                    "- número de concorrentes por procedimento e taxa de ajuste direto;\n"
                    "- concentração do lado dos fornecedores e do lado dos compradores;\n"
                    "- sinais de anomalia: preços muito acima do padrão do segmento e aditivos sucessivos.",
                ),
                b.imagem(
                    media.get("diagrama-concentracao-de-mercado.svg", ""),
                    alt="Concentração de fornecedores e posição de preço dentro do mesmo CPV",
                    caption="O preço lido dentro do segmento e o peso dos maiores fornecedores.",
                ),
                b.cartoes(
                    "O que pode ver",
                    [
                        ("Posição de preço", "Onde um contrato se situa face à mediana e ao p75 do mesmo CPV."),
                        ("Concentração", "Índices de concentração e peso do maior fornecedor do segmento."),
                        ("Aditivos", "Frequência e peso dos trabalhos a mais."),
                        ("Prazos", "Anúncio, decisão e assinatura, e o que a demora sugere."),
                        ("Concorrência", "Quem participa, quem desiste e quem ganha sempre."),
                        ("Onde vender", "Que compradores compram algo que uma empresa ainda não lhes vende."),
                    ],
                ),
                b.galeria([media.get("ilustracao-mercado.svg", "")]),
                b.aviso("**Leitura estatística.** Os sinais apontam para onde olhar; não são prova de irregularidade. Um preço alto pode ser um bem diferente, um prazo curto ou um mercado com um só fornecedor.", tone="amber"),
                b.cta("Quer saber onde está no seu mercado?", "Damos a posição relativa, os concorrentes e os segmentos onde há espaço.", "Pedir uma análise", "/site/contactos"),
            ],
        )
    )

    # --- Benchmarks --------------------------------------------------------
    b = _Blocos("solucoes-benchmarks")
    paginas.append(
        _pagina(
            page_id="pag_sol_benchmarks",
            title="Benchmarks de produtos",
            path="solucoes/benchmarks-de-produtos",
            prefixo="solucoes-benchmarks",
            parent_id="pag_solucoes",
            menu_label="Benchmarks",
            excerpt="O mesmo produto comparado entre lojas, com preço, dispersão e data de recolha à vista.",
            seo_title="Benchmarks de preços por loja",
            seo_description="O mesmo produto comparado entre lojas: melhor preço, dispersão entre lojas e quanto se poupa, com a data de recolha à vista.",
            keywords=["benchmarks", "comparação de preços", "preços por loja", "poupança", "Sabemos Studio"],
            blocks=[
                b.hero(
                    "O mesmo produto, lado a lado",
                    "Preço, dispersão entre lojas e quanto se poupa — com a data de recolha à vista.",
                ),
                b.texto(
                    "Como se faz um benchmark",
                    "Recolhemos os preços publicados por várias lojas, normalizamos para o **mesmo produto** "
                    "(marca, modelo, capacidade) e mostramos o melhor preço, a dispersão e a poupança de escolher "
                    "a oferta mais barata.\n\n"
                    "Cada estudo leva a data de recolha, porque num mercado de eletrónica uma semana muda o "
                    "resultado. E dizemos o que não conseguimos confirmar, em vez de assumir.",
                ),
                b.cartoes(
                    "O que entra em cada estudo",
                    [
                        ("Produto normalizado", "Marca, modelo e referência, para comparar o mesmo bem."),
                        ("Melhor preço", "Identificado e datado."),
                        ("Dispersão", "Quanto varia entre a loja mais barata e a mais cara."),
                        ("Poupança", "Diferença entre escolher o melhor preço e a média das lojas."),
                        ("Rasto", "Sempre a data da leitura, loja a loja."),
                        ("Aviso claro", "Preço publicado não é preço final: confirmar antes de decidir."),
                    ],
                ),
                b.imagem(
                    media.get("diagrama-comparacao-lojas.svg", ""),
                    alt="Índice de preço por loja, com 100 a valer a média do estudo",
                    caption="Como se lê um benchmark: dispersão entre lojas e melhor preço assinalado.",
                ),
                b.galeria([media.get("ilustracao-benchmarks.svg", "")]),
                b.cta("Quer um benchmark do seu mercado?", "Montamos a recolha, normalizamos os produtos e publicamos o estudo com a data à vista.", "Pedir um estudo", "/site/contactos"),
            ],
        )
    )

    # --- Investigação assistida --------------------------------------------
    b = _Blocos("solucoes-investigacao")
    paginas.append(
        _pagina(
            page_id="pag_sol_investigacao",
            title="Investigação assistida",
            path="solucoes/investigacao",
            prefixo="solucoes-investigacao",
            parent_id="pag_solucoes",
            excerpt="Perguntas em linguagem natural com resposta citada e grafo de evidências, sobre dados abertos ligados.",
            seo_title="Investigação com evidências citadas",
            seo_description="Investigação assistida sobre dados abertos: perguntas em linguagem natural, resposta com fontes citadas e grafo de evidências para seguir o rasto.",
            keywords=["investigação", "inteligência artificial", "evidências", "fontes citadas", "dados abertos", "Sabemos Studio"],
            blocks=[
                b.hero(
                    "Perguntar em português, receber a fonte",
                    "A resposta vem com o documento que a sustenta — e com o rasto para o verificar.",
                ),
                b.texto(
                    "O que muda face a uma pesquisa",
                    "Uma pesquisa devolve páginas. Aqui, a pergunta é feita em linguagem natural e a resposta é "
                    "montada a partir de **dados ligados** — contratos, contas, registos de empresas — com cada "
                    "afirmação ligada à evidência que a suporta.\n\n"
                    "O resultado é verificável: se a conta não fechar, vê-se logo onde. E fica guardado como "
                    "**dossiê**, com a data da leitura.",
                ),
                b.imagem(
                    media.get("diagrama-cadeia-de-evidencia.svg", ""),
                    alt="Da pergunta à resposta citada: sub-perguntas, registos nas fontes e fontes numeradas",
                    caption="O caminho de uma resposta: pergunta, registos e citação numerada.",
                ),
                b.passos(
                    "Como responde",
                    [
                        ("Interpretar", "A pergunta é decomposta em sub-perguntas sobre entidades concretas."),
                        ("Recolher", "Vão-se buscar os registos que respondem a cada uma, nas fontes certas."),
                        ("Ligar", "Os registos são cruzados pela entidade — empresa, município ou pessoa."),
                        ("Citar", "A resposta sai com as fontes numeradas, para abrir e conferir."),
                    ],
                ),
                b.galeria([media.get("ilustracao-investigacao.svg", "")]),
                b.citacao("Cada número tem procedência: o documento, o ano e o contrato de onde saiu.", "Método Sabemos Studio"),
                b.cta("Tem uma pergunta que ninguém responde?", "Diga-nos qual é. Construímos a resposta a partir dos dados abertos, com a evidência citada.", "Fazer uma pergunta", "/site/contactos"),
            ],
        )
    )

    # --- Fontes de dados ---------------------------------------------------
    b = _Blocos("fontes")
    paginas.append(
        _pagina(
            page_id="pag_fontes",
            title="Fontes de dados",
            path="fontes",
            prefixo="fontes",
            menu_order=3,
            excerpt="De onde vem cada número: fontes oficiais, cobertura, período e limites.",
            seo_title="Fontes de dados públicos",
            seo_description="As fontes por trás dos nossos números: Portal BASE, INE, registos oficiais de empresas e boletins — com cobertura, período e limites.",
            keywords=["fontes de dados", "dados abertos", "Portal BASE", "INE", "transparência", "Sabemos Studio"],
            blocks=[
                b.hero(
                    "De onde vem cada número",
                    "Fontes públicas, com cobertura e período à vista. O que a fonte não publica, não inventamos.",
                    cta=("Ver as soluções", "/site/solucoes"),
                ),
                b.tabela(
                    "Fontes que usamos",
                    ["Fonte", "O que dá", "Cobertura"],
                    [
                        ["Portal BASE", "Contratos públicos, adjudicantes, adjudicatários e valores", "Portugal · 2012 até hoje"],
                        ["INE", "Despesa e execução orçamental das autarquias, indicadores oficiais", "Portugal · por concelho e ano"],
                        ["Plataformas de contratação", "Contratos de Espanha e França", "Espanha · França"],
                        ["Registos oficiais de empresas", "Identificação, situação registal e relações societárias", "Portugal"],
                        ["Registos de benefício efetivo", "Cadeia de propriedade até à pessoa singular", "Portugal · onde publicado"],
                        ["Publicações de insolvência", "Insolvências e atos relacionados", "Portugal"],
                        ["Boletins e diários oficiais", "Atos publicados, apoios e fundos", "Portugal"],
                        ["Recolhas próprias", "Preços de loja para os benchmarks", "Datado, loja a loja"],
                    ],
                ),
                b.imagem(
                    media.get("diagrama-fontes-e-cobertura.svg", ""),
                    alt="Fontes usadas e cobertura por país e período",
                    caption="Que fontes entram, para que países e desde quando.",
                ),
                b.cartoes(
                    "Como tratamos o que entra",
                    [
                        ("Ligação por identidade", "Cruza-se pelo NIF e pela chave da entidade, não pelo nome parecido."),
                        ("Sem estimativas escondidas", "Campos vazios ficam vazios, com nota — não são substituídos por médias."),
                        ("Fotografia datada", "Cada leitura guarda a data; o número citado não muda por baixo."),
                        ("Limites à vista", "Dizemos o que a fonte não cobre, antes que alguém tire a conclusão errada."),
                    ],
                ),
                b.galeria([media.get("ilustracao-fontes.svg", "")]),
                b.faq(
                    "Perguntas frequentes",
                    [
                        ("Posso usar os dados para o meu trabalho?", "Os dados brutos são das fontes e seguem as regras de cada uma. A nossa leitura pode ser citada, com ligação à página."),
                        ("O que fazem quando as fontes discordam?", "Mostramos as duas e explicamos a diferença: quase sempre é definição, período ou âmbito."),
                        ("Publicam os ficheiros tratados?", "Consoante o caso. Diga-nos o que precisa em Contactos."),
                    ],
                ),
                b.cta("Falta uma fonte que devíamos ter?", "Diga-nos qual. Se for pública e relevante, avaliamos e integramos.", "Sugerir uma fonte", "/site/contactos"),
            ],
        )
    )

    # --- Contactos ---------------------------------------------------------
    # A página existe para levar a um pedido concreto: a abertura traz a
    # ilustração e um botão que salta para o formulário (`#pedido`), os quatro
    # temas vão em cartões com ícone (leem-se antes do texto corrido), e o que
    # acontece depois do envio está dito antes de o leitor clicar em «enviar».
    b = _Blocos("contactos")
    paginas.append(
        _pagina(
            page_id="pag_contactos",
            title="Contactos",
            path="contactos",
            prefixo="contactos",
            menu_order=5,
            excerpt="Escreva-nos: pedidos de análise, correções, dados e imprensa.",
            seo_title="Contactos",
            seo_description=(
                "Fale com o Sabemos Studio: pedidos de análise à medida, correções, dados e pedidos de imprensa. "
                "Respondemos por email, em dias úteis."
            ),
            keywords=["contactos", "Sabemos Studio", "pedido de análise", "imprensa"],
            blocks=[
                b.hero(
                    "Fale connosco",
                    "Pedidos de análise, correções, dados ou imprensa — respondemos por email.",
                    cta=("Escrever o pedido", "#pedido"),
                    image=media.get("ilustracao-contactos.svg", ""),
                ),
                b.cartoes_com_icone(
                    "O que tratar aqui",
                    [
                        (
                            "Análise à medida",
                            "Uma pergunta concreta sobre contratos, empresas ou municípios. Dizemos o que os dados "
                            "abertos respondem e o que fica de fora.",
                            media.get("icone-analise-medida.svg", ""),
                        ),
                        (
                            "Correções",
                            "Um número que não bate certo. Damos prioridade: verificamos na fonte e publicamos a "
                            "correção com a data da leitura.",
                            media.get("icone-correcao.svg", ""),
                        ),
                        (
                            "Dados",
                            "O que temos, com que cobertura e em que formato — para jornalistas, investigadores e "
                            "serviços públicos que precisam dos ficheiros.",
                            media.get("icone-dados.svg", ""),
                        ),
                        (
                            "Imprensa",
                            "Contexto, dados e a fonte primária por trás de cada número, dentro do prazo de fecho.",
                            media.get("icone-imprensa.svg", ""),
                        ),
                    ],
                ),
                b.formulario(
                    "Pedido de contacto",
                    "Quanto mais concreta for a pergunta, mais rápida é a resposta. Se for sobre uma entidade, indique o NIF.",
                    anchor="pedido",
                    note=(
                        "Se preferir escrever de fora do site, use [suporte@sabemos.studio](mailto:suporte@sabemos.studio) — "
                        "a caixa é a mesma e a resposta também."
                    ),
                ),
                b.passos(
                    "O que acontece a seguir",
                    [
                        (
                            "Recebemos o pedido",
                            "Fica registado com a data e a hora, e chega-nos por email — não se perde numa caixa qualquer.",
                        ),
                        (
                            "Verificamos na fonte",
                            "Confirmamos o dado no registo original e escrevemos de onde vem cada campo e cada número.",
                        ),
                        (
                            "Respondemos por email",
                            "Pedidos simples, em dias úteis; análises à medida, com o prazo indicado assim que o âmbito "
                            "estiver definido.",
                        ),
                    ],
                ),
                b.faq(
                    "Perguntas frequentes",
                    [
                        ("Quanto tempo demoram a responder?", "Pedidos simples, em dias úteis; análises à medida, dizemos o prazo quando soubermos o âmbito."),
                        ("O que fazem com os meus dados?", "Usamos o nome e o email apenas para responder a este pedido. Pode pedir a eliminação a qualquer momento, pela mesma via."),
                        ("Posso citar os vossos números?", "Pode, com ligação à página e a data da leitura. Cada número traz a fonte primária indicada, para se conferir."),
                        ("Fazem análises fora de Portugal?", "Temos contratos públicos de Portugal, Espanha e França. Para outros países, dizemos primeiro o que a cobertura deixa responder."),
                    ],
                ),
                b.cta(
                    "Talvez já esteja cá o que procura",
                    "O blog mostra o método em prática e os relatórios gratuitos saem com a fonte de cada linha — "
                    "é a forma mais rápida de ver o nível de detalhe que damos antes de pedir uma análise.",
                    "Ler o blog",
                    "/site/blog",
                    botoes=[("Relatórios gratuitos", "/site/relatorios-gratuitos")],
                ),
            ],
        )
    )

    # --- Relatórios gratuitos e documentos já gerados ----------------------
    b = _Blocos("relatorios")
    paginas.append(
        _pagina(
            page_id="pag_relatorios",
            title="Relatórios gratuitos",
            path="relatorios-gratuitos",
            prefixo="relatorios",
            menu_order=2,
            excerpt="Relatórios gratuitos e documentos já gerados pela plataforma, por área de trabalho — com download direto dos gratuitos.",
            seo_title="Relatórios gratuitos e documentos já gerados",
            seo_description=(
                "Relatórios gratuitos e documentos já gerados a partir de dados abertos: contratação pública, "
                "empresas e risco, mercados e setor público. Os gratuitos descarregam-se já; os restantes pedem-se no catálogo."
            ),
            keywords=[
                "relatórios gratuitos",
                "documentos",
                "contratação pública",
                "empresas",
                "dados abertos",
                "relatórios",
                "Sabemos Studio",
            ],
            blocks=[
                b.hero(
                    "Relatórios gratuitos e documentos já gerados",
                    "O que a plataforma já produziu, por área de trabalho — pronto a ler, com a fonte de cada número.",
                    cta=("Ver o catálogo completo", "/reports"),
                ),
                b.texto(
                    "O que está nesta página",
                    "Cada documento foi montado a partir de **dados abertos** — contratos públicos, registos de "
                    "empresas, imprensa e contas públicas — e fica aqui com a área a que pertence.\n\n"
                    "- **Relatórios gratuitos**: os pacotes do catálogo que não se pagam (o corporativo, por exemplo). "
                    "Pedem-se na plataforma e são produzidos a partir do NIF da empresa.\n"
                    "- **Documentos já gerados**: relatórios do Estúdio que já têm PDF. Os **gratuitos "
                    "descarregam-se nesta página**; os que têm preço pedem-se no catálogo.\n\n"
                    "Os números não são uma fotografia fixa: a página lê o catálogo e o Estúdio a cada visita, por "
                    "isso um documento publicado hoje aparece aqui sem ser preciso mexer nesta página.",
                ),
                b.relatorios(
                    "Por área de trabalho",
                    intro="Escolha a área e o documento. «Grátis» descarrega; o resto abre o catálogo.",
                    limit=24,
                ),
                b.passos(
                    "Como obter um relatório",
                    [
                        ("Escolher a área", "Contratação pública, empresas e risco, mercados ou setor público."),
                        ("Abrir o documento", "Os gratuitos descarregam já; os outros abrem no catálogo com o preço."),
                        ("Pedir com o NIF", "Indique a empresa ou as empresas (até 6) e recebe o PDF na plataforma."),
                    ],
                ),
                b.faq(
                    "Perguntas frequentes",
                    [
                        ("Os relatórios gratuitos são mesmo gratuitos?", "Sim. Os pacotes com preço 0 não passam pelo pagamento: pede-se e é produzido logo, quando a entrega é automática."),
                        ("O que significa «documento já gerado»?", "É um relatório do Estúdio que já foi produzido e tem PDF. Quando é gratuito, o ficheiro está nesta página; quando tem preço, segue pelo catálogo."),
                        ("Posso pedir um relatório sobre outra empresa?", "Pode. No catálogo escolhe-se a empresa (ou até seis, no caso da concorrência) e o relatório é montado a partir dos dados dessa entidade."),
                        ("Que áreas vão aparecer aqui?", "As mesmas do catálogo: contratação pública, empresas e risco, mercados e notícias, setor público e os documentos de referência."),
                    ],
                ),
                b.cta(
                    "Precisa de um relatório à medida?",
                    "Diga-nos a empresa, o setor ou a pergunta e montamos o relatório com a fonte de cada número.",
                    "Pedir um relatório",
                    "/reports",
                    botoes=[("Falar connosco", "/site/contactos")],
                ),
            ],
        )
    )

    return paginas


# --------------------------------------------------------------------------
# Artigos do blog
# --------------------------------------------------------------------------
#: Leitura dos contratos públicos publicados em 2026, com os números da base
#: indexada (leitura de 10/10/2026) e a data escrita em cada gráfico.
#:
#: Vive aqui — e não só na semente do CMS — porque uma instalação já em uso
#: precisa de receber o artigo pelo `_atualizar_site_sabemos.py`: o deploy de
#: código não leva a pasta `data/`, e sem isto o artigo ficava a prometer uma
#: análise por CPV que não tinha.
ARTIGO_CONTRATOS_2026_SLUG = "contratos-publicos-2026"
ARTIGO_CONTRATOS_2026_EXCERPT = (
    "Volume, valor e concentração nos contratos já publicados este ano — e as três leituras que interessam."
)

#: Fonte citada em todos os gráficos e tabelas do artigo.
_ARTIGO_FONTE = "Base de contratos públicos indexada no Sabemos Studio · leitura a 10/10/2026."


def artigo_contratos_2026() -> Dict[str, Any]:
    """Resumo, gráficos e tabelas do artigo «Contratos públicos em 2026».

    Os valores são os declarados pelos adjudicantes no momento da publicação e
    não incluem aditivos posteriores. O ano não está fechado: a contagem vai até
    10 de outubro e, por isso, a comparação com 2025 é feita com o período
    homólogo (188 725 contratos), nunca com o ano completo.
    """
    b = _Blocos("artigo-contratos-2026")
    fonte = _ARTIGO_FONTE

    markdown = (
        "Foram publicados **192 955 contratos** entre 1 de janeiro e 10 de outubro de 2026, no valor de "
        "**16,4 mil milhões de euros**. Em número, o ano segue o ritmo do anterior: no período homólogo de "
        "2025 saíram 188 725 contratos, ou seja, **+2,2%**. Em valor médio, está mais barato — **84 840 €** "
        "por contrato, contra **95 835 €** em 2025.\n\n"
        "**O essencial, em três leituras:**\n\n"
        "1. **O volume está na cauda; o valor, no topo.** 79,7% dos contratos valem menos de 50 000 €, e os "
        "quatro maiores adjudicatários levam 414,6 M€ — 73% de tudo o que foi para os dez primeiros.\n"
        "2. **O procedimento explica o preço.** O ajuste direto é 41,9% dos contratos e 16,6% do valor; o "
        "concurso público é 15,8% dos contratos e 47,9% do valor.\n"
        "3. **O medicamento manda.** Produtos farmacêuticos valem 2,60 mil M€, mais do que as onze classes de "
        "CPV que se seguem juntas. E falta preencher a região de execução em 39,1% dos contratos.\n\n"
        "Cada gráfico diz de onde vem e a que data pertence. Os números são os mesmos que a plataforma mostra."
    )

    blocos = [
        b.numeros(
            "2026 em cinco números",
            [
                ("192 955", "contratos publicados", "1 de janeiro a 10 de outubro de 2026"),
                ("16,4 mil M€", "valor total declarado", "+2,2% em número face a igual período de 2025"),
                ("84 840 €", "valor médio por contrato", "95 835 € no ano de 2025"),
                ("79,7%", "abaixo de 50 mil €", "só 3,65% passam os 350 mil €"),
                ("28 019", "adjudicatários distintos", "para 4 360 entidades adjudicantes"),
            ],
        ),
        b.texto(
            "1. O volume está na cauda; o valor, no topo",
            "Dos 192 955 contratos publicados, **153 710 (79,7%) ficam abaixo dos 50 000 €** e apenas "
            "**7 049 (3,65%) passam os 350 000 €**. O valor médio de 84 840 € diz mais sobre esses poucos "
            "contratos grandes do que sobre o contrato típico.\n\n"
            "Do lado de quem vende há **28 019 adjudicatários distintos** — 6,9 contratos por fornecedor, em "
            "média. Os dez maiores somam **565,6 M€: 3,45% do valor do ano**. À escala nacional, não há um "
            "punhado de empresas a ficar com o país.\n\n"
            "A concentração existe, mas **dentro de cada mercado**. Os quatro primeiros da lista levam "
            "**414,6 M€ — 73% de tudo o que foi para os dez maiores** — e são todos do medicamento: Medtronic "
            "(dispositivos médicos), Pfizer (farmacêutica), Cencora (distribuição) e Lusopalex (produtos de "
            "saúde). O quarto leva quase cinco vezes mais do que o décimo.",
        ),
        b.grafico(
            "Onde estão os contratos",
            [
                ("Menos de 50 mil €", 153710, 0, "79,7% do total"),
                ("50 a 100 mil €", 17713, 0, "9,2%"),
                ("100 a 150 mil €", 6066, 0, "3,1%"),
                ("150 a 200 mil €", 3395, 0, "1,8%"),
                ("200 a 250 mil €", 2323, 0, "1,2%"),
                ("250 a 300 mil €", 1569, 0, "0,8%"),
                ("300 a 350 mil €", 1130, 0, "0,6%"),
                ("350 mil € ou mais", 7049, 0, "3,65% do total, apesar de o escalão ser aberto"),
            ],
            note="Número de contratos por escalão de valor declarado. A cauda longa não é um detalhe: é quase todo o ano.",
            formato="numero",
            source=fonte,
        ),
        b.grafico(
            "Os dez maiores adjudicatários",
            [
                ("Medtronic Portugal", 124965474.67, 0, "1 203 contratos"),
                ("LAB. PFIZER", 100909059.32, 0, "858 contratos"),
                ("Cencora 3PL Portugal", 97250705.90, 0, "1 291 contratos"),
                ("Lusopalex — Produtos de Saúde", 91470541.56, 0, "1 143 contratos"),
                ("B. Braun Medical", 37672334.23, 0, "1 617 contratos"),
                ("Fresenius Kabi Pharma Portugal", 29523903.51, 0, "937 contratos"),
                ("Generis — Farmacêutica", 23613047.15, 0, "1 698 contratos"),
                ("Accord Healthcare", 21525530.63, 0, "904 contratos"),
                ("Labesfal — Laboratórios Almiro", 19865849.43, 0, "1 146 contratos"),
                ("Smile — Viagens e Turismo", 18758982.83, 0, "3 035 contratos"),
            ],
            note="Valor adjudicado em 2026. Juntos somam 565,6 M€ — 3,45% do valor total e 73% dele nos quatro primeiros.",
            source=fonte,
        ),
        b.tabela(
            "Quem compra mais: as maiores entidades adjudicantes",
            ["Entidade adjudicante", "Contratos", "Valor"],
            [
                ["Unidade Local de Saúde de Santa Maria", "4 319", "531,2 M€"],
                ["Unidade Local de Saúde de Coimbra", "4 087", "430,4 M€"],
                ["Unidade Local de Saúde de São José", "3 272", "366,0 M€"],
                ["Instituto Português de Oncologia do Porto", "8 940", "266,9 M€"],
                ["Unidade Local de Saúde do Algarve", "2 778", "179,5 M€"],
                ["Unidade Local de Saúde de Gaia/Espinho", "4 280", "158,1 M€"],
                ["Unidade Local de Saúde de Almada-Seixal", "4 441", "128,7 M€"],
                ["Águas do Norte", "2 342", "79,2 M€"],
            ],
        ),
        b.texto(
            "2. O procedimento explica o preço",
            "O ajuste direto é o procedimento mais usado e o menos pesado: **80 757 contratos (41,9%)** para "
            "**2,71 mil M€ (16,6%)** — uma média de **33 551 €** por contrato.\n\n"
            "O concurso público faz o inverso: **15,8% dos contratos e 47,9% do valor**, 7,84 mil M€, com um "
            "contrato médio de **257 107 €**. É **quase oito vezes** o do ajuste direto.\n\n"
            "Pelo meio ficam os acordos-quadro: os celebrados ao abrigo do artigo 259.º valem **2,45 mil M€ "
            "em 28 338 contratos** (média de 86 332 €). E a consulta prévia, o segundo procedimento mais usado "
            "em número, é o que menos valor move — **31 078 contratos para 988,6 M€**, uma média de 31 811 € "
            "que fica abaixo da do ajuste direto.",
        ),
        b.grafico(
            "Peso no número e peso no valor",
            [
                ("Ajuste direto (regime geral)", 41.9, 16.6, "80 757 contratos · 2,71 mil M€"),
                ("Consulta prévia", 16.1, 6.0, "31 078 contratos · 988,6 M€"),
                ("Concurso público", 15.8, 47.9, "30 501 contratos · 7,84 mil M€"),
                ("Acordo-quadro (art. 259.º)", 14.7, 14.9, "28 338 contratos · 2,45 mil M€"),
                ("Contratação excluída II", 7.6, 5.6, "14 704 contratos · 918,7 M€"),
                ("Acordo-quadro (art. 258.º)", 2.5, 3.9, "4 840 contratos · 639,2 M€"),
            ],
            note="Percentagem do total de contratos e do valor total, por tipo de procedimento. As barras partilham a mesma escala.",
            formato="percentagem",
            legend=["Contratos", "Valor"],
            source=fonte,
        ),
        b.tabela(
            "Os seis procedimentos que pesam",
            ["Procedimento", "Contratos", "% dos contratos", "Valor", "% do valor", "Valor médio"],
            [
                ["Concurso público", "30 501", "15,8%", "7,84 mil M€", "47,9%", "257 107 €"],
                ["Ajuste direto (regime geral)", "80 757", "41,9%", "2,71 mil M€", "16,6%", "33 551 €"],
                ["Acordo-quadro (art. 259.º)", "28 338", "14,7%", "2,45 mil M€", "14,9%", "86 332 €"],
                ["Consulta prévia", "31 078", "16,1%", "988,6 M€", "6,0%", "31 811 €"],
                ["Contratação excluída II", "14 704", "7,6%", "918,7 M€", "5,6%", "62 483 €"],
                ["Acordo-quadro (art. 258.º)", "4 840", "2,5%", "639,2 M€", "3,9%", "132 060 €"],
            ],
        ),
        b.texto(
            "3. O medicamento manda — e o mapa tem um buraco",
            "Cinco das doze classes de CPV que mais valor movem são da mesma família, a 33, que junta "
            "produtos farmacêuticos, equipamento médico e material de consumo. Somam **3,68 mil M€: 22,5% de "
            "tudo o que foi contratado no ano**.\n\n"
            "**Produtos farmacêuticos, sozinhos, valem 2,60 mil M€ em 25 842 contratos** — mais do que as "
            "onze classes que se seguem, todas juntas. O resto do topo é serviço: limpeza (199,5 M€), "
            "informática (96,0 M€ e 71,4 M€) e reparação e manutenção (71,7 M€).\n\n"
            "Há um detalhe que vale a pena guardar: o **contrato médio de limpeza (202 909 €) é o dobro do "
            "contrato médio de produtos farmacêuticos (100 541 €)**. O medicamento move mais dinheiro, mas em "
            "muitos contratos pequenos; a limpeza move menos, em poucos contratos grandes.\n\n"
            "No mapa, a **Área Metropolitana do Porto** lidera com **2,54 mil M€ em 31 286 contratos**, seguida "
            "de Grande Lisboa (1,19 mil M€). Mas **a região de execução não está preenchida em 75 525 "
            "contratos — 39,1% do número e 37,6% do valor**. É a maior fatia de todas, maior do que qualquer "
            "região real: enquanto este campo estiver assim, qualquer leitura por mapa é uma leitura parcial.",
        ),
        b.grafico(
            "Onde está o valor, por classe de CPV",
            [
                ("Produtos farmacêuticos", 2598184999.77, 0, "25 842 contratos · 100 541 € de média"),
                ("Equipamento médico", 473913219.86, 0, "5 442 contratos · 87 084 € de média"),
                ("Material médico de consumo", 271025534.94, 0, "8 725 contratos · 31 063 € de média"),
                ("Produtos farmacêuticos diversos", 232246535.24, 0, "2 983 contratos · 77 857 € de média"),
                ("Serviços de limpeza", 199459202.34, 0, "983 contratos · 202 909 € de média"),
                ("Equipamento e material informático", 115699245.90, 0, "959 contratos · 120 646 € de média"),
                ("Equipamento médico e medicamentos (código de divisão)", 100441855.64, 0, "11 038 contratos · 9 100 € de média"),
                ("Serviços de informática", 95967283.99, 0, "825 contratos · 116 324 € de média"),
                ("Serviços de saúde e ação social", 74436215.87, 0, "957 contratos · 77 781 € de média"),
                ("Serviços de reparação e manutenção", 71687923.68, 0, "2 630 contratos · 27 258 € de média"),
                ("Serviços de TI", 71397609.37, 0, "928 contratos · 76 937 € de média"),
            ],
            note="As doze maiores classes de CPV (quatro dígitos) por valor. Juntas valem 4,36 mil M€ — 26,6% do ano.",
            source=fonte,
        ),
        b.tabela(
            "As doze maiores classes de CPV",
            ["CPV", "Classe", "Contratos", "Valor", "Valor médio"],
            [
                ["3360", "Produtos farmacêuticos", "25 842", "2,60 mil M€", "100 541 €"],
                ["3310", "Equipamento médico", "5 442", "473,9 M€", "87 084 €"],
                ["3314", "Material médico de consumo", "8 725", "271,0 M€", "31 063 €"],
                ["3369", "Produtos farmacêuticos diversos", "2 983", "232,2 M€", "77 857 €"],
                ["9091", "Serviços de limpeza", "983", "199,5 M€", "202 909 €"],
                ["3020", "Equipamento e material informático", "959", "115,7 M€", "120 646 €"],
                ["3300", "Equipamento médico, medicamentos e produtos para cuidados pessoais", "11 038", "100,4 M€", "9 100 €"],
                ["7250", "Serviços de informática", "825", "96,0 M€", "116 324 €"],
                ["8500", "Serviços de saúde e ação social", "957", "74,4 M€", "77 781 €"],
                ["5000", "Serviços de reparação e manutenção", "2 630", "71,7 M€", "27 258 €"],
                ["7200", "Serviços de TI", "928", "71,4 M€", "76 937 €"],
                ["6351", "Serviços de agências de viagens", "2 599", "57,2 M€", "22 017 €"],
            ],
        ),
        b.grafico(
            "Valor por região de execução",
            [
                ("Área Metropolitana do Porto", 2543329630.19, 0, "31 286 contratos"),
                ("Grande Lisboa", 1187352143.75, 0, "10 917 contratos"),
                ("Extra-Regio NUTS 3", 983789597.88, 0, "5 229 contratos"),
                ("Região Autónoma da Madeira", 682914736.17, 0, "4 227 contratos"),
                ("Algarve", 653657583.16, 0, "8 394 contratos"),
                ("Cávado", 497765133.78, 0, "6 941 contratos"),
                ("Ave", 377300335.23, 0, "5 443 contratos"),
                ("Região de Coimbra", 342003571.36, 0, "4 586 contratos"),
                ("Douro", 331609868.30, 0, "6 508 contratos"),
                ("Tâmega e Sousa", 313728492.06, 0, "4 637 contratos"),
            ],
            note="Maiores regiões NUTS 3 por valor. Ficam de fora os 75 525 contratos (39,1%) sem região preenchida — 6,15 mil M€.",
            source=fonte,
        ),
        b.aviso(
            "**Como se lê isto.** Os números são os contratos publicados entre 1 de janeiro e 10 de outubro de "
            "2026: o ano não está fechado, por isso a comparação com 2025 é feita com o **período homólogo** "
            "(188 725 contratos), nunca com o ano completo. Os valores são os declarados no momento da "
            "publicação, sem aditivos posteriores. Duas reservas: a **região de execução** vem vazia em 39,1% "
            "dos contratos, e o **CPV** é lido ao nível das classes de quatro dígitos, que agrupam vários "
            "códigos de oito dígitos. Os mesmos números, em PDF, estão no botão no topo do artigo.",
            tone="amber",
        ),
        b.cta(
            "Quer o número de uma entidade concreta?",
            "Diga-nos a empresa, o município ou o setor e devolvemos a leitura com a fonte de cada valor.",
            "Falar connosco",
            "/site/contactos",
            [("Ver as soluções", "/site/solucoes")],
        ),
    ]

    return {
        "slug": ARTIGO_CONTRATOS_2026_SLUG,
        "excerpt": ARTIGO_CONTRATOS_2026_EXCERPT,
        "markdown": markdown,
        "blocks": blocos,
    }


#: Comparação de 2025 com 2026 no **mesmo período** de cada ano (1 de janeiro a
#: 10 de outubro), com as maiores empresas e as maiores classes de CPV em euros
#: absolutos. Os totais anuais usam o mesmo filtro de ano da plataforma, para
#: que qualquer número deste artigo seja reproduzível no painel.
ARTIGO_2025_2026_SLUG = "contratos-publicos-2025-vs-2026"
ARTIGO_2025_2026_EXCERPT = (
    "O mesmo período de cada ano, lado a lado: 11% mais contratos e 6% menos valor — e as empresas e as "
    "áreas de CPV que explicam a diferença."
)

#: SEO: título e descrição próprios do artigo. O título visível é outro, e a
#: descrição escrita é a que aparece nos resultados de pesquisa e na partilha.
ARTIGO_2025_2026_SEO: Dict[str, Any] = {
    "title": "Contratos públicos: 2025 contra 2026 em empresas e áreas de CPV",
    "description": (
        "Comparação de 2025 com 2026 no mesmo período: 192 941 contratos contra 173 830 (+11,0%) e 16,36 mil M€ "
        "contra 17,41 mil M€ (−6,0%). As maiores empresas adjudicatárias e as maiores classes de CPV, em euros."
    ),
    "keywords": [
        "contratos públicos 2025",
        "contratos públicos 2026",
        "comparação anual contratos",
        "áreas de CPV",
        "maiores adjudicatários",
        "compras públicas Portugal",
    ],
    "image_id": None,
    "noindex": False,
}

#: Fonte citada nos gráficos e nas tabelas deste artigo.
_ARTIGO_FONTE_2025_2026 = (
    "Base de contratos públicos indexada no Sabemos Studio · leitura a 10/10/2026 · valores declarados pelos "
    "adjudicantes no momento da publicação."
)

#: As doze classes de CPV que mais valor movem, em euros absolutos: `(classe,
#: nome, contratos em 2025, valor em 2025, contratos em 2026, valor em 2026)`.
#: Copiadas da leitura de 10/10/2026, classe a classe — sem amostragem.
_CPV_2025_2026: List[tuple] = [
    ("4523", "Obras em condutas, linhas de comunicação e de energia", 5208, 3193728479.26, 2723, 1347683159.04),
    ("4521", "Obras de construção de edifícios", 1764, 2805986697.77, 867, 728242832.13),
    ("3360", "Produtos farmacêuticos", 27684, 2625427553.97, 25842, 2598184999.77),
    ("4545", "Outras obras de acabamento de construção", 2238, 603705408.91, 1691, 363632630.99),
    ("9051", "Eliminação e tratamento de resíduos", 547, 534749286.18, 470, 283312077.78),
    ("4500", "Construção", 1653, 490511436.86, 729, 201317502.01),
    ("4520", "Obras de construção e de engenharia civil", 773, 420044666.01, 366, 147608832.58),
    ("0931", "Eletricidade", 747, 408246572.02, 488, 324169186.11),
    ("3314", "Material médico de consumo", 13788, 371548755.14, 9468, 296070068.33),
    ("0913", "Petróleo e destilados", 756, 347040646.06, 444, 255393676.89),
    ("3369", "Medicamentos vários", 5390, 346822443.60, 3861, 318645641.91),
    ("3310", "Equipamento médico", 4981, 250678293.53, 5442, 473913219.86),
]

#: Empresas adjudicatárias que marcaram um dos dois anos: `(nome, contratos em
#: 2025, valor em 2025, contratos em 2026, valor em 2026)`.
_EMPRESAS_2025_2026: List[tuple] = [
    ("AVAN Norte — Gestão da Ferrovia de Alta Velocidade", 1, 1661362811.55, 0, 0.0),
    ("Alstom Ferroviária Portugal", 1, 746042424.94, 8, 10147661.04),
    ("Petrogal", 990, 301297060.09, 569, 192026863.27),
    ("Janssen Cilag Farmacêutica", 806, 279583901.27, 595, 235631635.01),
    ("Veolia Portugal", 36, 270494057.18, 21, 4795716.45),
    ("Teixeira Duarte — Engenharia e Construções", 16, 228031976.91, 16, 205413064.21),
    ("Roche Farmacêutica Química", 722, 219694262.81, 439, 205454731.04),
    ("Novartis Farma", 730, 182730358.60, 556, 157375373.82),
    ("MEO — Serviços de Comunicações e Multimédia", 906, 177903913.64, 659, 72942268.12),
    ("Merck Sharp & Dohme", 504, 176461458.47, 308, 163164623.28),
    ("Iberdrola Clientes Portugal", 176, 164103914.20, 154, 167703057.98),
    ("Pfizer (LAB. PFIZER)", 1316, 146098947.33, 858, 100909059.32),
    ("Medtronic Portugal", 1732, 114863188.78, 1203, 124965474.67),
    ("Uniself — Restaurantes Públicos e Privados", 127, 114674100.74, 95, 174532786.21),
    ("Alnypt", 21, 107684770.04, 9, 190129918.14),
]

#: Maiores entidades adjudicantes em valor: `(nome, contratos em 2025, valor em
#: 2025, contratos em 2026, valor em 2026)`.
_COMPRADORES_2025_2026: List[tuple] = [
    ("Infraestruturas de Portugal", 726, 2183986726.72, 616, 1028368134.80),
    ("CP — Comboios de Portugal", 52, 837245570.39, 106, 117878289.27),
    ("Unidade Local de Saúde de Santa Maria", 5090, 517768004.50, 4319, 531205077.84),
    ("Estado Maior da Força Aérea", 1902, 441080074.57, 1439, 128477956.20),
    ("Unidade Local de Saúde de São José", 4206, 421872592.05, 3272, 365965227.16),
    ("Unidade Local de Saúde de Coimbra", 3775, 374844394.97, 4087, 430382271.56),
    ("Unidade Local de Saúde de Santo António", 1480, 358697519.20, 1279, 401999098.72),
    ("Unidade Local de Saúde de Lisboa Ocidental", 2040, 223911933.51, 1927, 236375038.70),
    ("Instituto Português de Oncologia do Porto", 15255, 211196856.00, 8940, 266938770.57),
    ("Unidade Local de Saúde do Algarve", 3778, 204100371.27, 2778, 179465574.33),
]


def _euros(valor: float) -> str:
    """Valor em euros com a grandeza escrita por extenso (`3,19 mil M€`)."""
    if valor >= 1_000_000_000:
        return f"{valor / 1_000_000_000:.2f}".replace(".", ",") + " mil M€"
    return f"{valor / 1_000_000:.1f}".replace(".", ",") + " M€"


def _variacao(anterior: float, atual: float) -> str:
    """Variação em percentagem, com sinal (`−57,8%`)."""
    if not anterior:
        return "—"
    if not atual:
        return "não voltou a contratar"
    return f"{(atual - anterior) / anterior * 100:+.1f}%".replace(".", ",").replace("-", "−")


def artigo_contratos_2025_2026() -> Dict[str, Any]:
    """Resumo, gráficos e tabelas do artigo que compara 2025 com 2026.

    A comparação é feita **no mesmo período de cada ano** — 1 de janeiro a 10 de
    outubro —, porque 2026 ainda não está fechado: 192 941 contratos em 2026
    contra 173 830 em igual período de 2025 (+11,0% em número) e 16,36 mil M€
    contra 17,41 mil M€ (−6,0% em valor). Os totais do ano fechado de 2025
    (246 992 contratos, 23,67 mil M€) aparecem ao lado, identificados como tal.

    Os valores são os declarados pelo adjudicante e incluem os contratos sem
    preço preenchido na contagem, mas não no valor. Todas as séries de CPV e de
    empresas são euros **absolutos**, lidos classe a classe na base indexada.
    """
    b = _Blocos("artigo-contratos-2025-2026")
    fonte = _ARTIGO_FONTE_2025_2026

    markdown = (
        "No mesmo período de cada ano — de 1 de janeiro a 10 de outubro —, 2026 registou **192 941 contratos**, "
        "contra **173 830** em 2025: **mais 11,0% em número**. O valor declarado, porém, desceu de **17,41** para "
        "**16,36 mil milhões de euros** (**−6,0%**), e o contrato médio caiu de **100 173 €** para **84 811 €**.\n\n"
        "**O essencial, em três leituras:**\n\n"
        "1. **Mais contratos, menos dinheiro.** O Estado celebra mais acordos por valores menores: o contrato "
        "médio perde **15,3%**.\n"
        "2. **A obra pública recua, a farmácia aguenta.** As duas maiores classes de construção perdem **57,8%** e "
        "**74,0%** do valor; produtos farmacêuticos ficam praticamente iguais (**−1,0%**) e lideram os dois anos.\n"
        "3. **As empresas trocam de mão.** O topo de 2025 é da alta velocidade e da construção; o de 2026 é da "
        "farmácia e do equipamento médico, que sobe **89,1%**.\n\n"
        "Todos os gráficos comparam os dois anos no mesmo eixo, em euros absolutos, e dizem de onde vêm os números."
    )

    blocos = [
        b.numeros(
            "2025 e 2026 no mesmo período (1 de janeiro a 10 de outubro)",
            [
                ("192 941", "contratos em 2026", "173 830 em igual período de 2025 (+11,0%)"),
                ("16,36 mil M€", "valor declarado em 2026", "17,41 mil M€ em 2025 no mesmo período (−6,0%)"),
                ("84 811 €", "contrato médio em 2026", "100 173 € em 2025 (−15,3%)"),
                ("246 992", "contratos no ano de 2025 fechado", "23,67 mil M€ em doze meses"),
                ("2 598 M€", "produtos farmacêuticos em 2026", "a maior classe de CPV nos dois anos (−1,0%)"),
            ],
        ),
        b.texto(
            "1. Mais contratos, menos dinheiro",
            "Entre 1 de janeiro e 10 de outubro de 2026 registaram-se **192 941 contratos**, mais **19 111** do que "
            "em igual período de 2025 (173 830) — **+11,0%**. É o número de acordos, não o dinheiro, que cresce.\n\n"
            "O valor declarado caiu **6,0%**, de **17,41** para **16,36 mil milhões de euros**, e o contrato médio "
            "passou de **100 173 €** para **84 811 €**: **menos 15,3%** por contrato.\n\n"
            "Para contexto, o ano de 2025 fechado soma **246 992 contratos** e **23,67 mil milhões de euros** — "
            "um ritmo de **2,0 mil milhões de euros por mês** que 2026 não repete.",
        ),
        b.grafico(
            "O valor declarado, em euros absolutos",
            [
                ("2025 — ano completo", 23670498334.05, 0, "246 992 contratos em 12 meses"),
                ("2026 — até 10 de outubro", 16370319232.74, 0, "192 955 contratos"),
                ("2025 — 1 de janeiro a 10 de outubro", 17413013409.40, 0, "173 830 contratos (período comparável)"),
                ("2026 — 1 de janeiro a 10 de outubro", 16363487365.18, 0, "192 941 contratos (período comparável)"),
            ],
            note="Só as duas últimas barras são comparáveis entre si: usam o mesmo intervalo de calendário nos dois anos.",
            source=fonte,
        ),
        b.texto(
            "2. As áreas de CPV: a obra recua, a farmácia não cede",
            "A maior mudança está na construção. A classe **4523** — obras em condutas, linhas de comunicação e de "
            "energia — cai de **3,19 mil M€** para **1,35 mil M€** (**−57,8%**), e a **4521**, obras de construção de "
            "edifícios, desce de **2,81 mil M€** para **728,2 M€** (**−74,0%**). Juntas perdem **3,53 mil milhões de "
            "euros** de um ano para o outro — mais do que a queda total do valor declarado.\n\n"
            "A farmácia é a exceção: **produtos farmacêuticos** (3360) valem **2 598,2 M€** em 2026 contra "
            "**2 625,4 M€** em 2025, uma variação de **−1,0%** em 25 842 contratos. É a maior classe de CPV nos dois "
            "anos e a única do topo que não se mexeu.\n\n"
            "Do lado de quem sobe há uma história clara: **equipamento médico** (3310) ganha **89,1%**, de **250,7** "
            "para **473,9 M€**, em 5 442 contratos. O resto do topo é energia e serviços: eletricidade recua "
            "**20,6%**, petróleo e destilados **26,4%**, mas ambas continuam acima dos **300 M€**.",
        ),
        b.grafico(
            "As áreas de CPV que mais valor movem — 2025 contra 2026",
            [
                (f"{nome} ({classe})", v25, v26, _variacao(v25, v26))
                for classe, nome, _n25, v25, _n26, v26 in _CPV_2025_2026
            ],
            note="As doze classes de CPV com mais valor em 2025 ou 2026, em euros absolutos. A segunda barra é 2026.",
            legend=["2025", "2026"],
            source=fonte,
        ),
        b.tabela(
            "As doze maiores classes de CPV, em valores absolutos",
            ["CPV", "Classe", "Contr. 2025", "Valor 2025", "Contr. 2026", "Valor 2026", "Variação"],
            [
                [
                    classe,
                    nome,
                    f"{n25}",
                    _euros(v25),
                    f"{n26}",
                    _euros(v26),
                    _variacao(v25, v26),
                ]
                for classe, nome, n25, v25, n26, v26 in _CPV_2025_2026
            ],
        ),
        b.texto(
            "3. As empresas: o comboio sai, a farmácia fica",
            "O maior vendedor ao Estado em 2025 não aparece em 2026: a **AVAN Norte**, que gere a ferrovia de alta "
            "velocidade, assinou um contrato de **1,66 mil milhões de euros** em 2025 e não voltou a contratar. A "
            "**Alstom Ferroviária** caiu de **746,0 M€** para **10,1 M€** (**−98,6%**) e a **Veolia Portugal**, de "
            "**270,5 M€** para **4,8 M€** (**−98,2%**).\n\n"
            "O topo de 2026 é outro. A **Janssen Cilag** passa a ser a maior adjudicatária (**235,6 M€**), seguida "
            "da **Roche** (**205,5 M€**) e da **Teixeira Duarte** (**205,4 M€**). Entre as que crescem, a "
            "**Alnypt** quase duplica (**+76,6%**) e a **Uniself**, da restauração coletiva, sobe **52,2%**.\n\n"
            "Nem tudo é queda no mundo dos combustíveis: a **Petrogal** mantém-se entre as cinco primeiras "
            "(**192,0 M€** em 569 contratos), ainda que **36,3%** abaixo de 2025. A **Iberdrola** é uma das poucas "
            "a crescer nos dois anos (**+2,2%**).",
        ),
        b.grafico(
            "As empresas adjudicatárias que marcaram os dois anos — em euros absolutos",
            [
                (nome, v25, v26, _variacao(v25, v26))
                for nome, _n25, v25, _n26, v26 in _EMPRESAS_2025_2026
            ],
            note="Valor adjudicado a cada empresa, em euros. A segunda barra é 2026; uma barra em falta significa que a empresa não teve contratos nesse ano.",
            legend=["2025", "2026"],
            source=fonte,
        ),
        b.tabela(
            "As maiores empresas adjudicatárias, em valores absolutos",
            ["Empresa adjudicatária", "Contr. 2025", "Valor 2025", "Contr. 2026", "Valor 2026", "Variação"],
            [
                [nome, f"{n25}", _euros(v25), f"{n26}" if n26 else "—", _euros(v26) if v26 else "—", _variacao(v25, v26)]
                for nome, n25, v25, n26, v26 in _EMPRESAS_2025_2026
            ],
        ),
        b.texto(
            "4. Quem compra: os mesmos, com menos dinheiro",
            "Do lado de quem compra, a liderança não muda de mãos — muda de escala. A **Infraestruturas de "
            "Portugal** continua a ser o maior comprador nos dois anos, mas cai de **2,18 mil M€** para "
            "**1,03 mil M€** (**−52,9%**); a **CP — Comboios de Portugal** desce de **837,2 M€** para "
            "**117,9 M€** e o **Estado Maior da Força Aérea**, de **441,1 M€** para **128,5 M€**.\n\n"
            "A saúde segura o lado de cima da tabela. As unidades locais de saúde e o **IPO do Porto** ocupam oito "
            "das dez primeiras posições, e três crescem: o **IPO do Porto** (**+26,4%**), a **ULS de Coimbra** "
            "(**+14,8%**) e a **ULS de Santo António** (**+12,1%**).\n\n"
            "É essa a explicação para o topo de CPV de 2026: o país compra menos obras e mais medicamento, mais "
            "equipamento médico e mais serviços de saúde — e são os hospitais que puxam a lista.",
        ),
        b.grafico(
            "Os maiores compradores públicos — 2025 contra 2026",
            [
                (nome, v25, v26, _variacao(v25, v26))
                for nome, _n25, v25, _n26, v26 in _COMPRADORES_2025_2026
            ],
            note="Maiores entidades adjudicantes por valor, em euros. A segunda barra é 2026.",
            legend=["2025", "2026"],
            source=fonte,
        ),
        b.tabela(
            "Os maiores compradores, em valores absolutos",
            ["Entidade adjudicante", "Contr. 2025", "Valor 2025", "Contr. 2026", "Valor 2026", "Variação"],
            [
                [nome, f"{n25}", _euros(v25), f"{n26}", _euros(v26), _variacao(v25, v26)]
                for nome, n25, v25, n26, v26 in _COMPRADORES_2025_2026
            ],
        ),
        b.aviso(
            "**Como se lê isto.** A comparação usa o **mesmo intervalo de calendário** nos dois anos — 1 de "
            "janeiro a 10 de outubro —, porque 2026 ainda não está fechado. Os totais de 2025 aparecem em duas "
            "versões: o ano completo (246 992 contratos, 23,67 mil M€) e o período comparável (173 830 contratos, "
            "17,41 mil M€). Os gráficos de CPV e de empresas mostram **euros absolutos**, somados classe a classe "
            "e empresa a empresa para todo o ano de cada ano: não são percentagens nem valores por contrato. "
            "Duas reservas de método: o valor é o **declarado pelo adjudicante** no momento da publicação, sem "
            "aditivos posteriores, e a classe de CPV agrupa vários códigos de oito dígitos. Os mesmos números "
            "estão no relatório em PDF, no botão no topo do artigo.",
            tone="amber",
        ),
        b.cta(
            "Quer a comparação de uma empresa ou de um setor?",
            "Diga-nos o NIF, o município ou a classe de CPV e devolvemos a leitura de 2025 contra 2026, com a "
            "fonte de cada valor.",
            "Falar connosco",
            "/site/contactos",
            [("Ver as soluções", "/site/solucoes"), ("Explorar contratos", "/contracts/search")],
        ),
    ]

    return {
        "slug": ARTIGO_2025_2026_SLUG,
        "excerpt": ARTIGO_2025_2026_EXCERPT,
        "seo": ARTIGO_2025_2026_SEO,
        "markdown": markdown,
        "blocks": blocos,
    }
