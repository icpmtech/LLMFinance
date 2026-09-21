---
name: finder-todos-dados
description: "Use when: the user asks to expand the macOS-style Finder of the IQ OS so that it can search/include all available data sources (entities, contracts, RAG documents, tickers/prices, news, INPI trademarks, RNPC firmas, scraped data, CRM records, Elasticsearch indices). Covers backend endpoints, Finder types, API wrappers, and FinderPage load logic."
---

# Finder — todos os dados pesquisáveis

## Goal
Make the IQ OS Finder a true universal explorer: every searchable platform dataset becomes a Finder location, each result is a `FinderItem` with the right kind, icon, deep-link and inspector data.

## Data sources already available

| Source | Backend endpoint(s) | Mapper in Finder |
|---|---|---|
| Entities | `POST /entities/search` | `kind: "entity"` |
| Contracts | `POST /contracts/search` | `kind: "contract"` |
| RAG documents | `GET /rag/documents` | `kind: "document"` |
| Tickers / prices | `GET /elastic/tickers` | `kind: "ticker"` |
| News | `GET /elastic/search/global` | `kind: "news"` |
| Trademarks (INPI) | `GET /trademarks/search` | `kind: "trademark"` |
| Firmas (RNPC) | `GET /firmas/search` | `kind: "firma"` |
| Scraped data | `GET /scraper/search` | `kind: "scraped"` |
| CRM records | `GET /crm/accounts`, `/crm/contacts`, `/crm/deals`, `/crm/activities` | `kind: "crm"` |
| ES indices | `GET /elastic/indices` (to add) | `kind: "index"` |

## Backend changes

1. **Model** — add `ElasticIndexItem` and `ElasticIndicesListResponse` in `api/models.py`.
2. **ES helper** — add `list_elastic_indices()` in `api/elasticsearch_client.py` using `client.cat.indices(format="json")` and filtering/indexing only platform indices (`finance_*`, `contratos`, `contratos_es`).
3. **Route** — add `GET /elastic/indices` in `api/main.py` returning doc counts, health and a human-readable label.

## Frontend changes

1. **`chat-ui/src/finder.ts`**
   - Expand `FinderLocationId` with: `trademarks`, `firmas`, `scraped`, `crm`, `news`, `prices`.
   - Add them to `FINDER_LOCATIONS` with distinct icons/gradients.
   - Expand `FinderKind` to: `entity | contract | document | ticker | index | trademark | firma | scraped | crm | news`.
   - Update `KIND_LABEL`, `KIND_ICON`, `KIND_GRADIENT`, `appHref`, `tagColor`.

2. **`chat-ui/src/api.ts`**
   - Add `searchTrademarks`, `searchFirmas`, `searchScrapedItems`, `searchGlobalNews`, `listElasticIndices`.
   - Reuse existing types or add minimal ones in `chat-ui/src/types.ts`.

3. **`chat-ui/src/pages/FinderPage.tsx`**
   - Import the new API helpers.
   - Add item mappers: `trademarkToItem`, `firmaToItem`, `scrapedToItem`, `crmToItem`, `newsToItem`, `priceToItem`.
   - Extend `load()` to handle each new `FinderLocationId`, calling the matching endpoint with an optional query.
   - CRM endpoint is read-only (listing). It already requires session; let the request fail silently for anonymous users and show a small message.

## Search/filter behavior
- Each location issues its dedicated endpoint.
- If `q` is empty, the endpoint returns a default listing (most recent / top by size).
- Filter locally only when the backend endpoint does not accept a query parameter (e.g. tickers list, RAG documents).
- When `q` is provided and the endpoint supports it, pass `q` and let the backend filter (contracts, entities, trademarks, firmas, scraped, news global, CRM).

## Quick Look / inspector
- Keep existing behavior: entity shows contracts, contract shows parties.
- For new kinds, inspector shows the raw JSON in the generic panel (acceptable first iteration).

## Validation steps
1. Backend `GET /elastic/indices` returns all platform indices + doc counts.
2. Finder sidebar shows the new locations.
3. Each location loads the correct data; counts appear in the status bar.
4. Search within each location filters correctly.
5. TypeScript compiles; build produces a new hashed bundle.
