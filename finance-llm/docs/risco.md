# Empresas & Risco (`/empresas-risco`, API `/risco/*`)

Responde a uma pergunta concreta: **que empresas adjudicatárias merecem ser olhadas primeiro, e porquê?**

Cada empresa recebe um **nível de risco de 0 a 100** (com os componentes que o compõem), os
contratos que o sustentam, comparação com outras empresas e um grafo analítico 360.

> **Não é um juízo sobre a empresa.** É uma prioridade de análise construída com dados públicos do
> portal de contratação (regras calibradas nos dados + ML sobre empresas comparáveis). O número é
> reprodutível; o texto de IA é interpretação e nunca altera o número.

## Método (dois níveis)

| Nível | O que lê | Tempo típico | Cobertura |
|---|---|---|---|
| **Triagem** | contratos da empresa (até 200) + cadastro + CIRE filtrado | ~0,2–3 s por empresa | ~80 % (sem réguas de CPV) |
| **Dossiê** | análise completa do módulo de padrões (réguas de CPV por setor) + população de referência | 2–20 s a frio, cache 20 min | 100 % |

O `score` é a média **ponderada pelos componentes que têm dados** (renormalização) e a `cobertura`
diz quanta informação entrou — uma triagem sem réguas de CPV não é penalizada, mas a `confiança`
baixa. Sem Elasticsearch devolve `{"error": ...}`; sem `scikit-learn` o componente de anomalia fica
indisponível e o peso é redistribuído (nunca se inventa um número).

## Componentes e limiares (`risco-1.0.0`)

| Componente | Peso | 0 pontos | 100 pontos | Método |
|---|---|---|---|---|
| Processos de insolvência (CIRE) | 0,20 | 0 | 2 processos | regra (join por NIF, **papel «Insolvente»**) |
| Aditivos financeiros | 0,16 | 0 % | 25 % | regra (`ratio_efetivo > 1,15`) |
| Peso do ajuste direto | 0,13 | 0 % | 80 % | regra (prefixos de procedimento) |
| Dependência de um só comprador | 0,12 | 50 % | 90 % | regra (concentração de valor) |
| Falta de concorrência registada | 0,11 | 0 % | 50 % | regra (`n_concorrentes`) |
| Transparência tardia | 0,08 | 0 d | 180 d | regra (medianas de assinatura/publicação) |
| Valores atípicos para o CPV | 0,12 | 0 σ | 3,5 σ | estatística robusta (mediana + MAD) por CPV |
| Fora do padrão das empresas pares | 0,08 | percentil 50 | percentil 99 | ML: `IsolationForest` (não supervisionado) |

Faixas: **Baixo** <20 · **Moderado** <40 · **Elevado** <60 · **Muito elevado** <80 · **Crítico** ≥80.

O cartão completo (com os limiares editáveis e as fontes) está em `GET /risco/meta` e no separador
**Modelo de risco** da página.

## Risco por contrato

Dentro da empresa, cada contrato recebe um índice 0–100 (`pontuar_contrato`): severidade das regras
cumpridas (alerta 55, aviso 30, info 15) + aditivo financeiro (25) + valor atípico para o CPV (20) +
ajuste direto sem concorrentes (15) + transparência tardia (10). Serve para ordenar *que contratos
olhar primeiro*, não para acusar.

## ML e IA

- **Não supervisionado** — `IsolationForest` ajustado à população de referência (empresas da amostra
  nacional de contratos, ~300–1000) sobre features de carteira (contratos, valor, comprador,
  ajuste direto, aditivos). O componente é o **percentil** da empresa nessa população.
- **Supervisionado** — o `Gradient Boosting` do módulo de padrões (rótulo derivado:
  `PrecoTotalEfetivo > 115 % do contratual`), apresentado como sinal de aditivo (AUC/lift).
- **IA** — `POST /risco/empresa/ia` escreve o parecer (nível, o que puxa, o que contém, o que
  verificar, limitações) a partir **só** dos factos calculados; sem fornecedor configurado devolve o
  parecer factual com os mesmos números. O score nunca é alterado pela IA.

## Rotas

| Rota | O que faz |
|---|---|
| `GET /risco/meta` | cartão do modelo, features, fontes, estado da IA e da cache |
| `GET /risco/pesquisa?q=&pais=&nivel=&ordenar=&size=&from=&detalhado=` | pesquisa tipo motor de busca, com risco por empresa (paralelo + cache) |
| `GET /risco/sugestoes?q=` | sugestões (nome/NIF) do cadastro |
| `GET /risco/empresa/{pais}/{nif}?detalhado=` | risco + análise (e, no dossiê, contratos com risco por contrato) |
| `GET /risco/empresa/{pais}/{nif}/grafo` | grafo analítico 360 (compradores, órgãos sociais, empresas ligadas, CIRE) |
| `POST /risco/empresa/ia` | parecer de risco por IA (sessão) |
| `POST /risco/comparar` | risco de até 12 empresas + cruzamentos + rede |
| `POST /risco/cache/clear` | limpa a cache de risco (sessão) |

Aceita `PT`/`ES` **e** o nome do país («Portugal», «Espanha») — o cadastro guarda o nome.

### Como a pesquisa resolve nomes de empresas

Escrever «CLARANET, S.A.» tem de encontrar a Claranet — e não os maiores contratantes do país.
A resolução (`consulta_cadastro` + `ordem_candidato`) faz:

1. **Tokens significativos**: sem acentos e sem formas societárias/ligações (`s.a` → nada, `lda`,
   `unipessoal`, `de`, `do`, …). «CLARANET, S.A.» procura só `claranet`; um NIF (8–10 caracteres
   com 6+ dígitos) entra por `term`.
2. **Passagem estrita** (`operator: and`, mais `match_phrase` no nome): encontra o que casa com
   **todas** as palavras. Só se esta não devolver nada é que há **recuo** (`ou`) — e aí a resposta
   vem marcada com `parcial: true` e a UI avisa que são correspondências aproximadas.
3. **Ordenação por relevância** (por omissão, `ordenar=relevancia`): nome que contém a frase pedida
   (comparada por **sequência de tokens**, para «mota engil» casar «MOTA-ENGIL») → empresas com
   contratos registados → menos palavras a mais no nome → mais contratos → `_score` do BM25.
   A ordenação pedida (`risco`, `valor`, `contratos`) aplica-se **à página** escolhida pela
   relevância — como em qualquer motor de busca.

Exemplos validados: «águas do norte» → Águas do Norte, SA (e não a do Alentejano); «nos comunicações»
→ NOS - Comunicações S.A.; «mota-engil» → as empresas Mota-Engil; «CLARANET, S.A.» → a entidade com
esse nome exato e, a seguir, as restantes Claranet.

## Página (`/empresas-risco`)

Cinco separadores: **Pesquisar empresas** (motor de busca com risco, filtros por país/nível e
ordenação por risco/valor/contratos, seleção múltipla), **Dossiê 360** (medidor, componentes,
evidência, contratos com risco, relações, parecer por IA), **Comparar empresas** (ranking, carteira
lado a lado, cruzamentos, rede), **Grafos analíticos** (rede 360 desenhada a pedido) e
**Modelo de risco** (o cartão). A vista vive na query string (`?tab=…&nif=…`), logo o link é
partilhável.

## Armadilhas (validadas)

- **Pesquisa por nome não pode ser ordenada por volume de contratos.** A pesquisa partilhada do
  cadastro (`contribuintes_service.search`, usada na página Contribuintes) ordena por
  `contracts_count` e a sua cláusula `ou` casa 20 000+ documentos: com ela, «CLARANET, S.A.»
  devolvia Águas do Norte, Generis e MEO. Resolver nomes exige `_score` primeiro (e, depois,
  reordenar por relevância explícita) — é o que `_procurar_cadastro` faz.
- **`match_phrase` mente em nomes com hífen**: «mota engil» não é substring de «mota-engil».
  Comparar por **sequência de tokens**, não por texto.
- **`CLARANET, S.A.` tem o NIF `A61129086` (país: Espanha)**: tem 18 contratos no PLACSP e nenhum no
  PORTAL BASE. O `contracts_count` do cadastro é só PT; para espanholas conta `contratos_es_count`.
- **CIRE conta credores**: o índice lista em `nifs` todos os intervenientes do processo — bancos, AT
  e Segurança Social incluídos. Sem filtrar `intervenientes.papel` por «Insolvente», a Caixa
  Económica Montepio Geral aparecia com 100 pontos de insolvência por cobrar dívidas (e o cadastro
  `cire_count` dá 12 560 «processos»). O número honesto só sai da consulta filtrada; o
  `cire_count` do cadastro **não** é mostrado na UI.
- **`finance_contribuintes.country`** é o **nome** do país («Portugal»), não o código — daí
  `pais_codigo()`.
- **`anos`** na triagem tem de ser `[primeiro, último]` (convenção do módulo de padrões); devolver a
  lista completa fazia a UI mostrar «2020–2021» para uma empresa com contratos até 2026.
- **O grafo do dossiê** usa todas as menções no CIRE (para mostrar relações); o payload separa
  `insolvencias` (a empresa é a insolvente) de `processos_cire` (aparece como credor/requerente) e
  rotula-os de forma diferente.
- **Duas chamadas a `analyze()` com `per_year` diferentes** têm caches distintas: o risco usa
  `per_year=250`, o mesmo valor por omissão de `analise_empresa`, para partilhar a entrada de cache
  (a fase cara).

## Operação

- Testes: `tests/test_risco.py` (26, puros — sem Elasticsearch).
- Sondas: `_probe_risco_cire.py`, `_probe_risco_cire2.py` (filtro por papel no CIRE),
  `_probe_risco_pesquisa.py` (como o cadastro resolve nomes), `_probe_risco_contratos.py`
  (cadastro vs contratos por NIF/país).
- Reiniciar a API pela porta (`Get-NetTCPConnection -LocalPort 8002 … | Stop-Process`) e confirmar
  `/health`; o uvicorn corre sem `--reload`.
