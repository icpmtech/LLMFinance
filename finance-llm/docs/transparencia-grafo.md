# Grafo da Transparência

Módulo que transforma as **declarações únicas** da
[Entidade para a Transparência](./entidade-transparencia.md) numa rede de

- **pessoas** — titulares de cargos políticos e altos cargos públicos;
- **cargos** — o cargo/função exercido (Presidente, Vereador, Vogal…);
- **entidades públicas** — o organismo onde o cargo é exercido (Governo, câmaras,
  institutos, empresas municipais…);
- **empresas e outras entidades** — as entidades privadas (e organismos públicos
  sem id no catálogo) do **registo de interesses**;
- **sedes** — o «Local da sede» de cada empresa, geocodificado para o **mapa**.

A fonte é a pasta de declarações normalizadas do módulo
`/entidade-transparencia` (`data/entidade-transparencia/_normalized/declaracoes.jsonl`
e `catalogo/titularidades.jsonl`). O grafo **não** faz pedidos à EPT: reconstrói-se
a partir do que já está recolhido.

## Relações

| Relação | Origem → destino | Fonte |
| --- | --- | --- |
| `EXERCE` | pessoa → cargo | metadados da declaração e titularidades da EPT |
| `CARGO_EM` | cargo → entidade pública | idem |
| `ATIVIDADE` | pessoa → empresa/entidade | «Atividades profissionais, cargos e funções» |
| `PARTICIPACAO` | pessoa → empresa | «Filiação ou participação em entidades associativas» e «Sociedades» |
| `BENEFICIO` | pessoa → empresa/entidade | «Apoios ou benefícios» |
| `SERVICO` | pessoa → empresa/entidade | «Serviços prestados» |

O peso de cada aresta é o número de declarações/linhas que a sustentam; o grau de
cada nó é o número de vizinhos distintos.

### Chaves dos nós

| Tipo | `no_id` |
| --- | --- |
| pessoa | `pessoa:<id do titular na EPT>` |
| cargo | `cargo:<id do cargo>` ou `cargo:nome:<slug>` |
| entidade | `entidade:<id da entidade na EPT>` |
| empresa | `empresa:<NIF>`; sem NIF, `empresa:nome:<slug>` |

O **NIF é a chave** das empresas: a mesma organização não se divide em dois nós
só porque uma declaração a classifica como «setor público» e outra não. Só as
entidades que existem no catálogo da EPT ficam com o tipo `entidade`.

## Geocodificação da sede

`api/transparencia_geo.py` resolve o texto livre de «Local da sede» por ordem de
precisão:

1. **`postal`** — código postal português (`1100-394`) na tabela GeoNames;
2. **`alias`** — sedes institucionais conhecidas (Palácio de S. Bento, PCM…);
3. **`cidade`** — concelho/cidade, com tolerância a acentos, hífenes, caixa,
   palavras de rua à frente e gralhas (`LlSBOA` → Lisboa);
4. **`estrangeiro`** — cidades e países fora de Portugal (Bruxelas, Madrid,
   Angola…).

Sem resultado, a empresa fica **sem ponto**: o mapa não inventa coordenadas e a
lista «Sem coordenadas» permite abri-la na mesma. A tabela portuguesa é a mesma
do módulo GLEIF (`data/gleif/geo/pt.json`, GeoNames, construída por
`_gleif_geo_build.py`).

Cobertura atual: **~99 %** das linhas do registo de interesses com local.

## Índices

| Índice | Documento |
| --- | --- |
| `finance_ept_grafo_nos` | nó: tipo, nome, NIF, grau, anos, sede (`location` como `geo_point`) |
| `finance_ept_grafo_arestas` | aresta: origem, destino, relação, peso, anos |
| `finance_ept_grafo_recolhas` | manifesto da última construção |

A leitura do grafo usa os JSONL em disco (fonte de verdade) com cache curta; o
índice serve a integração com o resto da plataforma e a contagem de volumetria.

## API

Leitura aberta; construção e indexação exigem sessão de escrita.

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/transparencia-grafo/meta` | proveniência, ficheiros, índices, tipos e relações |
| GET | `/transparencia-grafo/stats` | nós, arestas, empresas e sedes resolvidas |
| GET | `/transparencia-grafo/dimensoes` | tipos, relações e precisões para a UI |
| GET | `/transparencia-grafo/grafo` | subgrafo filtrado (nós + arestas) |
| GET | `/transparencia-grafo/nos/{id}` | ficha do nó, vizinhos e contratação pública |
| GET | `/transparencia-grafo/empresas` | empresas/entidades com sede e coordenadas |
| GET | `/transparencia-grafo/concelhos/{concelho}` | empresas do concelho com relações e contratação |
| GET | `/transparencia-grafo/mapa` | pontos e agregado por concelho |
| GET | `/transparencia-grafo/export.csv` | exportação de empresas ou nós |
| POST | `/transparencia-grafo/construir` | constrói o grafo (segundo plano) |
| POST | `/transparencia-grafo/indexar` | indexa o grafo em disco |
| GET | `/transparencia-grafo/jobs[/{id}]` | progresso dos trabalhos |

### `/grafo`

Parâmetros: `tipo`, `relacao`, `q`, `ano`, `nif`, `foco`, `profundidade`,
`min_peso`, `limit` (nós) e `edge_limit` (arestas).

- Sem filtros devolve os nós mais ligados, **equilibrados por tipo**, para a rede
  ser legível;
- `foco=<no_id>` devolve a vizinhança a 1–3 saltos;
- `tipo`/`relacao` aceitam listas separadas por vírgula
  (`pessoa,empresa`, `ATIVIDADE,PARTICIPACAO`).

A resposta usa o formato dos grafos partilhados (`id`, `key`, `label`,
`dimension`, `type`, `count`, `total_value`), pelo que o `GraphCanvas` a desenha
sem conversão própria.

### `/concelhos/{concelho}`

Abre um concelho a partir do mapa: lista as empresas com sede ali, as **relações**
no grafo (por tipo, e os titulares/entidades ligados) e a **contratação pública**
do NIF no portal BASE (n.º de contratos, valor, anos e principais adjudicantes).

A contratação é obtida com uma única agregação por lote de NIFs
(`adjudicatarios.parsed.nif` → `reverse_nested` → soma de `precoContratual`), com
cache de 15 minutos. Quando o índice de contratos não responde, a resposta marca
`disponivel: false` — distinto de «sem contratos».

## Dados em disco

```
data/transparencia-grafo/
└── grafo/
    ├── nos.jsonl
    ├── arestas.jsonl
    └── _manifest.json
```

A pasta muda com `TRANSPARENCIA_GRAFO_DATA_DIR`. O manifesto guarda os totais por
tipo, as arestas por relação, os concelhos com mais empresas e a data da
construção.

## Frontend

Página `/transparencia-grafo` (`chat-ui/src/pages/TransparenciaGrafoPage.tsx`),
com quatro vistas:

- **Grafo** — rede interativa (`GraphCanvas`) com filtros e ficha lateral;
- **Mapa das empresas** — mapa OpenStreetMap sem biblioteca externa, por concelho
  ou por empresa. Clicar numa **empresa** abre a ficha numa janela (sem sair do
  mapa); clicar num **concelho** abre a lista de empresas com relações e
  contratação pública. As entidades cuja sede não foi resolvida ficam na lista
  «Sem coordenadas» — continuam acessíveis na ficha e no grafo;
- **Empresas** — lista pesquisável, com paginação e exportação CSV;
- **Construção e índice** — reconstruir o grafo e indexar, com progresso.

## Testes

`tests/test_transparencia_grafo.py` cobre a construção a partir de declarações
sintéticas (os quatro tipos de nó, as seis relações), a geocodificação (postal,
alias, cidade, estrangeiro, locais inválidos), a ficha do nó, a lista de um
concelho, o mapa e a exportação CSV — sem rede nem Elasticsearch.
