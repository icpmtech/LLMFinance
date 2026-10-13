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
    ("capa-post-bemvindo.svg", "Capa · bem-vindo ao blog", "Bem-vindo ao blog do Sabemos Studio", ""),
    ("capa-post-contratos-2026.svg", "Capa · contratos públicos em 2026", "Contratos públicos em 2026: o que os dados mostram", ""),
)

#: Menu do site: rótulo e caminho da página, pela ordem em que aparece. O
#: «Benchmarks» só entra se a página existir na instalação.
MENU_PRINCIPAL: Sequence[Sequence[str]] = (
    ("Início", ""),
    ("Soluções", "solucoes"),
    ("Fontes", "fontes"),
    ("Benchmarks", "benchmarks"),
    ("Blog", "blog"),
    ("Contactos", "contactos"),
    ("Sobre", "sobre"),
)

#: Rodapé: o essencial, mais curto do que o cabeçalho.
MENU_RODAPE: Sequence[Sequence[str]] = (
    ("Soluções", "solucoes"),
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

    def tabela(self, title: str, head: Sequence[str], rows: Sequence[Sequence[str]]) -> Dict[str, Any]:
        return self.add("tabela", {"title": title, "head": list(head), "rows": [list(row) for row in rows]})

    def faq(self, title: str, items: Sequence[Sequence[str]]) -> Dict[str, Any]:
        return self.add("faq", {"title": title, "items": [{"question": pergunta, "answer": resposta} for pergunta, resposta in items]})

    def cta(self, title: str, text: str, label: str, href: str) -> Dict[str, Any]:
        return self.add("cta", {"title": title, "text": text, "button_label": label, "button_href": href})

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

    def formulario(self, title: str, intro: str, *, button_label: str = "Enviar mensagem") -> Dict[str, Any]:
        return self.add("formulario", {"title": title, "intro": intro, "button_label": button_label})

    def contactos(self, title: str, *, email: str = "", phone: str = "", address: str = "") -> Dict[str, Any]:
        return self.add("contactos", {"title": title, "email": email, "phone": phone, "address": address})

    def blog(self, title: str, limit: int = 3) -> Dict[str, Any]:
        return self.add("blog", {"title": title, "limit": limit})


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
        b.numeros("O que já está indexado", NUMEROS_DA_PLATAFORMA),
        b.texto(
            "O que é o Sabemos Studio",
            "O **Sabemos Studio** é um estúdio de produtos de dados: pegamos no que já é público — "
            "contratos, contas e registos — e devolvemos leitura que se pode verificar.\n\n"
            "O **IQ OS** é a plataforma onde isso acontece: recolha contínua de contratos públicos e de "
            "finanças locais, uma ontologia de entidades (empresas, municípios e pessoas) e assistentes de "
            "investigação que respondem com a evidência à vista.\n\n"
            "O que nos distingue:\n\n"
            "- **Fonte nomeada** — Portal BASE, INE, registos oficiais e boletins. Nenhum número aparece sem origem.\n"
            "- **Entidades ligadas** — a mesma empresa, o mesmo município e a mesma pessoa são o mesmo objeto "
            "em toda a plataforma, mesmo quando o nome aparece escrito de outra maneira.\n"
            "- **Fotografia datada** — cada análise guarda o dia em que foi lida: o número citado continua a "
            "ser o número que se viu.\n"
            "- **Conta refazível** — publicamos o critério e o registo, para quem lê poder repetir o cálculo.",
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
        b.galeria(
            [
                media.get("ilustracao-contratos.svg", ""),
                media.get("ilustracao-empresas.svg", ""),
                media.get("ilustracao-municipios.svg", ""),
                media.get("ilustracao-investigacao.svg", ""),
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


def conteudo_da_sobre() -> List[Dict[str, Any]]:
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
    """Páginas novas do site (soluções, fontes e contactos), por ordem de menu."""
    paginas: List[Dict[str, Any]] = []

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
                b.passos(
                    "O que é igual em todas",
                    [
                        ("Uma pergunta concreta", "Começamos pelo que se quer saber — não por um painel cheio de gráficos."),
                        ("Dados ligados", "Cruzamos contratação, contas e registos pela entidade certa, não pelo nome parecido."),
                        ("Resposta com rasto", "Cada valor sai com a fonte, o período e o critério."),
                        ("Fotografia datada", "O resultado fica guardado com a data da leitura."),
                    ],
                ),
                b.numeros("O que já está indexado", NUMEROS_DA_PLATAFORMA),
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
                b.passos(
                    "Como responde",
                    [
                        ("Interpretar", "A pergunta é decomposta em sub-perguntas sobre entidades concretas."),
                        ("Recolher", "Vão-se buscar os registos que respondem a cada uma, nas fontes certas."),
                        ("Ligar", "Os registos são cruzados pela entidade — empresa, município ou pessoa."),
                        ("Citar", "A resposta sai com as fontes numeradas, para abrir e conferir."),
                    ],
                ),
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
                b.cartoes(
                    "Como tratamos o que entra",
                    [
                        ("Ligação por identidade", "Cruza-se pelo NIF e pela chave da entidade, não pelo nome parecido."),
                        ("Sem estimativas escondidas", "Campos vazios ficam vazios, com nota — não são substituídos por médias."),
                        ("Fotografia datada", "Cada leitura guarda a data; o número citado não muda por baixo."),
                        ("Limites à vista", "Dizemos o que a fonte não cobre, antes que alguém tire a conclusão errada."),
                    ],
                ),
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
            seo_description="Fale com o Sabemos Studio: pedidos de análise à medida, correções, dados e pedidos de imprensa. Respondemos por email.",
            keywords=["contactos", "Sabemos Studio", "pedido de análise", "imprensa"],
            blocks=[
                b.hero(
                    "Fale connosco",
                    "Pedidos de análise, correções, dados ou imprensa — respondemos por email.",
                ),
                b.texto(
                    "O que tratar aqui",
                    "- **Análise à medida** — uma pergunta concreta sobre contratos, empresas ou municípios.\n"
                    "- **Correções** — um número que não bate certo. Damos prioridade e escrevemos a correção.\n"
                    "- **Dados** — saber o que temos, com que cobertura e em que formato.\n"
                    "- **Imprensa** — contexto, dados e a fonte primária por trás de cada número.",
                ),
                b.formulario(
                    "Pedido de contacto",
                    "Quanto mais concreta for a pergunta, mais rápida é a resposta. Se for sobre uma entidade, indique o NIF.",
                ),
                b.contactos("Outros canais", email="geral@iqos.pt"),
                b.faq(
                    "Perguntas frequentes",
                    [
                        ("Quanto tempo demoram a responder?", "Pedidos simples, em dias úteis; análises à medida, dizemos o prazo quando soubermos o âmbito."),
                        ("O que fazem com os meus dados?", "Usamos o nome e o email apenas para responder a este pedido. Pode pedir a eliminação a qualquer momento, pela mesma via."),
                    ],
                ),
            ],
        )
    )

    return paginas
