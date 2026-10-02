# Contratos Públicos de França (DECP) — Módulo Contratos FR

## Resumo

Módulo completo para ingestão, enriquecimento e pesquisa de contratos públicos franceses a partir do dataset **DECP** (Données Essentielles de la Commande Publique), disponível em [data.economie.gouv.fr](https://data.economie.gouv.fr).

- **Backend:** FastAPI + Elasticsearch (`contratos_fr`)
- **Frontend:** Chat UI (React + TypeScript + Tailwind) — páginas de pesquisa, dashboard e detalhe
- **Enriquecimento:** API Sirene (`recherche-entreprises.api.gouv.fr`) para nomes de compradores/adjudicatários
- **Índice atual:** ~61.106 contratos normalizados a partir de `decp-2026-09.json`

## Ficheiros principais

| Caminho | Função |
| --- | --- |
| `collectors/contratos_fr.py` | Coleta DECP, normaliza registos, enriquece com Sirene e indexa no ES |
| `collectors/sirene.py` | Cliente API Sirene com cache local (`data/cache/sirene/`) |
| `api/contratos_fr_routes.py` | Rotas FastAPI `/contracts-fr/*` |
| `api/elasticsearch_client.py` | Cliente ES e agregações do índice `contratos_fr` |
| `api/models.py` | Esquemas Pydantic (search, analytics, Sirene enrich, import) |
| `chat-ui/src/pages/ContractsFrSearchPage.tsx` | Pesquisa com filtros e facetas |
| `chat-ui/src/pages/ContractsFrDashboardPage.tsx` | Dashboard com gráficos por ano, procedimento, forma de preço, CPV, localização |
| `chat-ui/src/pages/ContractsFrDetailPage.tsx` | Detalhe de um contrato |
| `chat-ui/src/contratosFrApi.ts` | Cliente TypeScript da API |
| `mcp_server/catalog.py` | Ferramentas MCP expostas a agentes |

## Endpoints da API

```
GET    /contracts-fr/status             # volumetria e anos disponíveis
GET    /contracts-fr/meta               # ficheiros DECP processados
POST   /contracts-fr/search             # pesquisa textual e filtrada
GET    /contracts-fr/autocomplete       # sugestões de entidades/CPV
GET    /contracts-fr/entities           # lista de acheteurs e titulaires
GET    /contracts-fr/analytics          # dashboard: agregações e métricas
GET    /contracts-fr/{doc_id}           # detalhe de um contrato
POST   /contracts-fr/import             # arranca ingestão de um ficheiro DECP
GET    /contracts-fr/imports            # jobs de importação em curso
POST   /contracts-fr/sirene/enrich      # enriquece uma lista de SIRET/SIREN
```

## Facetas específicas de França

As agregações de `/contracts-fr/analytics` incluem:

- **CPV:** top códigos com descrição (`top_cpv`)
- **Forma de preço:** `Forfaitaire`, `Unitaire`, `Mixte`, etc. (`formes_prix`)
- **Localização:**
  - `localizacao.types` — tipo de código (`Code département`, `Code postal`, `Code commune`)
  - `localizacao.codes` — códigos de execução mais frequentes
- **Procedimentos:** `procedure`
- **Entidades:** top `acheteur` + `titulaires`

## Enriquecimento Sirene

### Rota dedicada

```bash
curl -X POST http://localhost:8002/contracts-fr/sirene/enrich \
  -H "Content-Type: application/json" \
  -d '{"identifiers": ["13000548100010"]}'
```

Resposta:

```json
{
  "results": [
    {"identifier": "13000548100010", "name": "FRANCE TRAVAIL", "found": true}
  ]
}
```

### Pipeline

Durante a normalização (`build_jsonl`), `collectors/contratos_fr.py` invoca `enrich_record_with_sirene()` para preencher `acheteur_nom` e `adjudicatario_nom` quando os identificadores existem mas o nome textual está em falta no DECP.

## Chat UI

### Navegação

A aplicação tem duas novas vistas registadas em `App.tsx`, `dock.ts` e `sidebarCatalog.ts`:

- `contratos-fr` — pesquisa e filtros
- `contratos-fr-dashboard` — dashboard analítico

### Métricas no dashboard

- Total de contratos e valor agregado
- Contratos por ano (barras)
- Procedimentos (donut)
- Forma de preço (donut)
- Top CPV (barras horizontais)
- Top entidades (barras)
- Tipos de localização (donut)
- Códigos de execução (barras horizontais)

## Como reingestar

```bash
python finance-llm/collectors/contratos_fr.py --data c:/LLMFinance/data/contratos-franca/decp-2026-09.json --index
```

Ou pela API:

```bash
curl -X POST http://localhost:8002/contracts-fr/import \
  -H "Content-Type: application/json" \
  -d '{"filename": "decp-2026-09.json", "index": true, "force": true}'
```

## Notas

- O DECP publica datas com anos de dois dígitos; o normalizador corrige para o século apropriado (`_fix_two_digit_year`).
- IDs determinísticos via SHA1 do registo original (`doc_id`).
- A enriquecimento Sirene usa cache em disco para evitar chamadas repetidas.
- 83 registos (de 64.352) falharam normalização na última ingestão.

## Contacto / dúvidas

Módulo mantido pela equipa Finance LLM. Para problemas de enriquecimento, verificar primeiro `data/cache/sirene/` e os logs do backend.
