# ESG · Sustentabilidade

Módulo de **score ESG por empresa**, com leitura por pilar (Ambiente, Social e
Governação), série de três anos, benchmark de setor e dimensão, indicadores
declarados nos relatórios de sustentabilidade e análise da carteira de
fornecedores.

> O score **não é uma certificação nem uma auditoria**. Os indicadores de
> contratação pública são proxies; os indicadores dos relatórios são da
> responsabilidade de quem os publica. A cobertura e a confiança dizem quanta
> informação entrou — um score com cobertura baixa não deve ser lido como nota
> final.

## Onde está

| Peça | Caminho |
| --- | --- |
| Frontend | `/esg` (`chat-ui/src/pages/EsgPage.tsx`) |
| Rotas | `/esg/*` (`api/esg_routes.py`) |
| Motor | `api/esg_service.py` |
| Taxonomia e catálogo | `api/esg_sources.py` |
| Índices | `finance_esg_empresas`, `finance_esg_indicadores`, `finance_esg_recolhas` |
| Documentação do modelo | `GET /esg/meta` e o separador **Modelo e fontes** |

## Score

O score global (0–100) é a média dos pilares **com dados**, renormalizada pelos
pesos: Ambiente 40 %, Social 30 %, Governação 30 %. Cada pilar renormaliza pelos
componentes disponíveis. Nunca se inventa um componente em falta.

| Pilar | Componentes (peso) |
| --- | --- |
| **Ambiente** | compras com critérios ecológicos (30 %), exposição verde (20 %), exposição carbónica (20 %), serviços ambientais/circularidade (15 %), indicadores declarados (15 %) |
| **Social** | exposição a serviços sociais (25 %), concorrência nos procedimentos (20 %), diversidade de compradores (15 %), indicadores declarados (40 %) |
| **Governação** | transparência na publicação (25 %), ajuste direto (20 %), concentração de compradores (15 %), insolvências CIRE (15 %), dívidas públicas (10 %), indicadores declarados (15 %) |

Faixas: **Líder** ≥ 75, **Avançado** ≥ 60, **Intermédio** ≥ 45, **Inicial** ≥ 30,
**Frágil** < 30.

A **dimensão** é uma proxy calculada pelo valor contratado (micro < 0,5 M€,
pequena 0,5–2 M€, média 2–10 M€, grande ≥ 10 M€). O setor é a secção do CAE
principal; sem CAE, usa-se o CPV dominante e diz-se que é proxy.

## Fontes

- **Portal BASE / PLACSP** — contratos, CPV, procedimento, concorrentes, prazos
  e `ContratEcologico`.
- **Cadastro de contribuintes** — NIF, país, localização, dívida pública.
- **Registo de entidades / firmas** — CAE principal e secundários.
- **CIRE** — processos em que a empresa é a insolvente (não credora).
- **Relatórios de sustentabilidade** — indicadores declarados, catalogados e
  normalizados (GRI/ESRS), com ano, fonte, URL e verificação (declarada ou
  externa).
- **Referências abertas** — GRI, ISSB/IFRS S1-S2, EFRAG/ESRS, INE, IAPMEI, APA e
  DGEG (catálogo em `GET /esg/meta`).

## Taxonomia Europeia e percurso IAPMEI

O módulo segue o quadro descrito pelo IAPMEI em
[Alinhamento do negócio com fatores ESG](https://www.iapmei.pt/pt/saber-mais/industria-e-sustentabilidade/sustentabilidade-empresarial/esg-e-financas-sustentaveis/alinhamento-do-negocio-com-fatores-esg/)
e os dados oficiais do
[EU Taxonomy Compass](https://ec.europa.eu/sustainable-finance-taxonomy/taxonomy-compass).

- **Seis objetivos ambientais** do Regulamento (UE) 2020/852: mitigação,
  adaptação, água e mares, economia circular, poluição e biodiversidade.
- **151 atividades oficiais** com setor, códigos NACE e objetivos, carregadas
  em `api/esg_taxonomy.py` a partir da API do Compass.
- **Elegibilidade** é calculada pelo CAE/NACE da empresa. Sem CAE, usa-se o
  setor/CPV como proxy e diz-se que é proxy.
- **Alinhamento não é declarado.** A resposta máxima é
  `elegivel_nao_verificado`; o alinhamento exige critérios técnicos, DNSH e
  salvaguardas sociais mínimas documentados e verificados.
- **DNSH e salvaguardas** são acompanhados por indicadores declarados; a
  ausência de indicador fica «sem evidência», nunca «conforme».
- **ODS, temas materiais e normas de relato** (ESRS, VSME, GRI, ISSB, TCFD,
  TNFD, SDG Compass, B Corp, EcoVadis, Sedex) estão em `GET /esg/meta` e no
  separador **Taxonomia UE**.
- O percurso de cinco passos do IAPMEI/UN Global Compact está modelado em
  `passos` e ligado às funcionalidades do módulo.

## Endpoints

| Método | Caminho | Descrição |
| --- | --- | --- |
| GET | `/esg/meta` | Cartão do modelo, setores, taxonomia CPV, indicadores e fontes |
| GET | `/esg/status` | Índices, contagens, última fotografia e execuções |
| GET | `/esg/pesquisa?q=` | Pesquisa empresas; calcula ao vivo as que ainda não têm fotografia |
| GET | `/esg/sugestoes?q=` | Sugestões de nome/NIF |
| GET | `/esg/ranking` | Ranking por score, pilar, setor, dimensão e ano |
| GET | `/esg/ranking.csv` | Exportação do ranking |
| GET | `/esg/analitica` | Médias, distribuições e destaques |
| GET | `/esg/empresa/{pais}/{nif}` | Dossiê: score, pilares, componentes, histórico, benchmark, indicadores, contratos e fornecedores |
| GET | `/esg/empresa/{pais}/{nif}/historico` | Série de três anos + mediana dos pares |
| GET | `/esg/empresa/{pais}/{nif}/fornecedores` | Carteira de fornecedores do comprador |
| GET | `/esg/empresa/{pais}/{nif}/indicadores` | Indicadores declarados por ano/fonte |
| GET | `/esg/taxonomia` | Objetivos, atividades, DNSH, salvaguardas, ODS e normas de relato |
| GET | `/esg/taxonomia/atividades?q=&setor=&objetivo=&nace=` | Pesquisa local das atividades do Compass |
| GET | `/esg/empresa/{pais}/{nif}/taxonomia` | Elegibilidade da empresa e evidência DNSH/salvaguardas |
| POST | `/esg/carteira/analise` | Analisa uma carteira indicada por NIF/nome |
| POST | `/esg/indicadores` | Ingere indicadores de um relatório (sessão) |
| POST | `/esg/calcular` | Calcula e indexa um lote de empresas (sessão) |

A leitura é pública. A escrita no módulo `esg` segue a matriz de permissões
(administradores e gestores de plataforma).

## Indicadores declarados

`POST /esg/indicadores` aceita um objeto `{codigo: valor}` ou uma lista de
`{codigo, valor}`. Exemplo:

```json
{
  "nif": "503504564",
  "pais": "PT",
  "ano": 2026,
  "fonte": "relatorio_2025",
  "verificacao": "externa",
  "url": "https://exemplo.pt/relatorio",
  "indicadores": {
    "e_emissoes_scope1": 12000,
    "e_emissoes_scope2": 8000,
    "e_energia_renovavel_pct": 65,
    "e_iso14001": 1,
    "s_horas_formacao_colaborador": 22,
    "s_acidentes_trabalho": 2,
    "g_conselho_independentes_pct": 40,
    "g_codigo_etica": 1
  }
}
```

O código é validado contra o catálogo de `GET /esg/meta`; valores de contexto
(por exemplo `s_trabalhadores`) são guardados mas não pontuam. A verificação
externa tem precedência sobre a declaração simples. Poucos indicadores são
encolhidos para 50 % (`0,5 + (média − 0,5) × n/(n+3)`) para não sobrevalorizar
uma amostra pequena.

## Como popular o índice

1. Abrir uma empresa em **Empresas** — a primeira consulta calcula e guarda.
2. Ou `POST /esg/calcular` com sessão:

```json
{ "pais": "PT", "limite": 100, "min_contratos": 1, "anos": 3 }
```

O lote lê o cadastro (empresas com contratos), calcula em paralelo e indexa. O
benchmark de pares só aparece quando há pelo menos **5 empresas** no mesmo setor
e dimensão.

## Limitações

- Os contratos podem não identificar todos os fornecedores; o valor da carteira
  é repartido igualmente pelos fornecedores identificados.
- O CAE pode faltar no registo; nesse caso o setor é uma proxy pelo CPV.
- Os indicadores declarados só entram se forem ingeridos; sem eles, os
  componentes de emissões, formação, acidentes e governance ficam
  indisponíveis e a cobertura baixa.
- O score não substitui due diligence, certificação ou auditoria.
- A Taxonomia UE é usada para **elegibilidade indicativa**. O IQ OS não tem
  acesso automático aos critérios técnicos dos atos delegados, às provas de DNSH
  ou às salvaguardas mínimas de cada empresa; por isso nunca apresenta uma
  empresa como «alinhada».
- A correspondência CAE/NACE → atividade usa o prefixo NACE mais específico e,
  quando não há CAE, o setor do Compass como proxy. Atividades sem código NACE
  ficam disponíveis para pesquisa, mas não são atribuídas automaticamente.
