# Entidade para a Transparência

Módulo de leitura das **declarações únicas** publicadas pela
[Entidade para a Transparência](https://entidadetransparencia.pt/) (EPT): os
titulares de cargos políticos e altos cargos públicos sujeitos à Lei n.º 52/2019,
de 31 de julho.

A fonte é a API pública da plataforma (`api.entidadetransparencia.pt`), não o
HTML: a SPA Vue não traz os dados na página. O módulo **recolhe** a cascata da
própria plataforma, **guarda** em JSONL, **indexa** no Elasticsearch e **serve**
pesquisa, ficha do titular e a ligação ao PessoasIQ.

## Cascata: entidade → cargo → nome

A plataforma organiza a consulta pública em três passos, e o módulo segue-os:

| Passo | Endpoint da EPT | O que devolve |
| --- | --- | --- |
| 1. Entidade | `POST /publicquery/getallentities` | entidades e órgãos com titularidades |
| 2. Cargo | `POST /publicquery/getallroles` (`EntityId`) | cargos da entidade escolhida |
| 3. Nome | `POST /publicquery/getallholders` (`EntityId`, `RoleId`) | titulares dessa combinação |
| Declarações | `POST /publicquery/search` (`HolderId`) | metadados das declarações do titular |
| Declaração | `POST /publicquery/getdeclaration` (`Id`) | árvore de secções da declaração |

As **titularidades** (entidade × cargo × titular, com datas de exercício) vêm de
`POST /publicquery`, paginado (17 084 linhas, 18 páginas de 1 000).

## O que é indexado

| Índice | Documento | `_id` |
| --- | --- | --- |
| `finance_ept_titulares` | resumo do titular: declarações, anos, entidades, cargos, órgãos | id do titular |
| `finance_ept_titularidades` | uma linha entidade × cargo × titular, com datas | id da titularidade |
| `finance_ept_declaracoes` | declaração normalizada: secções, campos, tabelas, registo de interesses e texto | `ept:<id>` |
| `finance_ept_recolhas` | manifesto da última recolha | `ept` |

A declaração é normalizada a partir da árvore `{key: uuid, value: [...]}` da API:

- **secções** — facto determinante, dados pessoais/morada/contactos, rendimentos,
  ativo patrimonial, passivo, promessa de vantagem patrimonial, outras
  declarações e **registo de interesses**;
- **campos** — com rótulos do modelo oficial (nome, sexo, naturalidade, data de
  nascimento, estado civil, regime de bens, morada, contactos, datas de funções);
- **tabelas** — atividades profissionais, filiação associativa, apoios,
  serviços, sociedades e as tabelas patrimoniais, com colunas rotuladas quando
  o modelo as identifica (ex.: cargo/função, entidade, natureza e área, local da
  sede, remuneração, datas, NIF/NIPC);
- **registo de interesses** — lista achatada `{tipo, valores}` pronta a mostrar;
- **texto** — todos os rótulos e valores, para pesquisa livre.

Campos com `isVisible: false` (NIF/NIC do titular) **não** entram na ficha nem no
texto indexado; o payload original pode ser pedido com `incluir_raw=true`.

## API do módulo

Leitura aberta; recolha e indexação exigem sessão de escrita.

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/entidade-transparencia/meta` | proveniência, pastas, índices e endpoints |
| GET | `/entidade-transparencia/stats` | titulares, titularidades e declarações em índice/disco |
| GET | `/entidade-transparencia/entidades` | passo 1 da cascata |
| GET | `/entidade-transparencia/cargos` | passo 2 (filtra por `entidade_id`) |
| GET | `/entidade-transparencia/orgaos` | filtro auxiliar |
| GET | `/entidade-transparencia/titulares` | passo 3; com `q` pesquisa pelo nome |
| GET | `/entidade-transparencia/titular/{id}` | ficha, posições, declarações e pessoa do PessoasIQ |
| GET | `/entidade-transparencia/declaracoes` | pesquisa por texto, entidade, cargo, ano e natureza |
| GET | `/entidade-transparencia/declaracoes/{id}` | declaração completa |
| GET | `/entidade-transparencia/pessoa/{nif}` | declarações ligadas a uma pessoa do PessoasIQ |
| GET | `/entidade-transparencia/export.csv` | exportação da pesquisa |
| POST | `/entidade-transparencia/recolher` | recolha em segundo plano (filtros da cascata) |
| POST | `/entidade-transparencia/exportar` | grava um JSON por entidade (segundo plano) |
| GET | `/entidade-transparencia/exportar/indice` | índice do último export por entidade |
| GET | `/entidade-transparencia/entidades/{id}/export.json` | ficheiro JSON de uma entidade |
| POST | `/entidade-transparencia/indexar` | indexa o que está em disco |
| POST | `/entidade-transparencia/titular/{id}/recolher` | recolhe um único titular |
| GET | `/entidade-transparencia/jobs[/{id}]` | progresso dos trabalhos |

### Recolha incremental

`POST /entidade-transparencia/recolher` aceita:

```json
{
  "entidade_id": "2",
  "cargo_id": "12",
  "titular_id": null,
  "limite_titulares": 50,
  "limite_declaracoes": null,
  "forcar": false,
  "indexar": true
}
```

Sem filtros, percorre o catálogo completo (12 372 titulares). Com `forcar=false`,
os titulares já recolhidos e as declarações já normalizadas são ignorados; o
manifesto (`_manifest.json`) guarda o que já foi lido. A pausa padrão entre
pedidos é de 0,4 s.

## Dados em disco

```
data/entidade-transparencia/
├── catalogo/
│   ├── entidades.json
│   ├── cargos.json
│   ├── orgaos.json
│   ├── titulares.json
│   └── titularidades.jsonl
├── _normalized/
│   ├── titulares.jsonl
│   └── declaracoes.jsonl
├── entidades/
│   ├── 4216.json
│   ├── _index.json
│   └── ...
└── _manifest.json
```

A pasta pode ser mudada com `ENTIDADE_TRANSPARENCIA_DATA_DIR`.

## Export por entidade

`exportar_entidades_json()` (e `POST /entidade-transparencia/exportar`) grava um
ficheiro por entidade com todos os titulares e declarações normalizadas:

```json
{
  "entidade_id": "4216",
  "entidade": "Conselho de Administração da Câmara Municipal de Lisboa",
  "gerado_em": "2025-01-31T12:00:00+00:00",
  "fonte": "entidade-transparencia",
  "fonte_url": "https://entidadetransparencia.pt",
  "cargos": ["Presidente"],
  "orgaos": ["Conselho de Administração"],
  "titulares": [
    {"titular_id": 4952, "nome": "…", "cargos": ["Presidente"], "declaracoes": []}
  ],
  "totais": {"titulares": 1, "declaracoes": 0}
}
```

`cargos` lista apenas posições (cargo); os órgãos declarados ficam em `orgaos`.
O `_index.json` resume cada entidade (`titulares`, `declaracoes`, `cargos`,
`orgaos`, `ficheiro`). A recolha exporta automaticamente no fim.

## Scraper fora da API

```bash
python scripts/recolher_entidade_transparencia.py --entidade 2 --limite 50
python scripts/recolher_entidade_transparencia.py --titular 4952
python scripts/recolher_entidade_transparencia.py --tudo --indexar
python scripts/recolher_entidade_transparencia.py --so-exportar
```

`--tudo --indexar` percorre o catálogo completo, indexa e, no fim, escreve um JSON
por entidade. `--so-exportar` regrava o export a partir do que está em disco.

## Ligação à ficha do político

A EPT **não publica o NIF do titular**, pelo que a ligação ao PessoasIQ é feita
por **nome**:

- normaliza-se o nome (sem acentos nem pontuação) e procuram-se variantes
  (nome completo, sem partículas, primeiro + último);
- aceita-se correspondência exata, semelhança ≥ 0,88, ou o nome curto do
  PessoasIQ contido no nome completo da EPT (ex.: «António Costa» ⊂ «António
  Luís Santos da Costa»);
- quando não há correspondência segura, devolvem-se os candidatos em vez de
  escolher um homónimo.

Na interface, a ficha do titular tem **«Abrir ficha do político»**; a ficha do
político em `/pessoas-iq/politicos` tem o separador **Transparência** com as
declarações da EPT e aceita a ligação direta `?nif=<NIF>`.

## Notas

- A plataforma publica a **publicidade dos registos de interesses**; as secções
  não disponibilizadas pela EPT vêm em `unavailableSections` e ficam registadas
  em `secoes_inacessiveis`.
- A API é pública e não documentada: há pausa entre pedidos e recuo exponencial
  em 429/5xx.
- A pesquisa funciona sem Elasticsearch, lendo o JSONL (`fonte: "disco"`), e a
  ficha de uma declaração pode ser lida ao vivo antes de qualquer recolha.
