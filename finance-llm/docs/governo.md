# Governo — nomeações e composição

Recolha das nomeações para os gabinetes dos membros do Governo e da composição
do Governo a uma data, a partir do Portal do Governo (`portugal.gov.pt`).

O coletor usa o **motor de recolha do IQ OS** (`api.scraper_service`) para
descarregar as páginas: `http` para as páginas das áreas (HTML do servidor) e
`dynamic` para a composição (a lista de membros é renderizada no browser).

## Fontes

| Fonte | URL | O que traz |
| --- | --- | --- |
| Nomeações (índice) | `/gc24/governo/nomeacoes` | As 18 áreas de governo e a página de cada uma |
| Nomeações (área) | `/pt/gc24/governo/nomeacoes/<área>` | Uma tabela por membro do Governo: função, nome, rendimento bruto/líquido, data de nomeação e publicação em DRE |
| Composição | `/gc24/governo/composicao?gc_timeline=AAAA-MM-DD` | Primeiro-Ministro, ministros e secretários de Estado em funções na data indicada |

## Utilização

```powershell
# recolha completa (todas as áreas, composição de 2025-06-05, JSON + Elasticsearch)
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo

# só ficheiros, sem Elasticsearch
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo --no-elastic

# uma ou mais áreas, sem composição
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo --areas financas,saude --no-composicao

# outra data da composição
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo --timeline 2025-06-05
```

| Opção | Efeito |
| --- | --- |
| `--timeline` | Data da composição (`aaaa-mm-dd`, omissão `2025-06-05`) |
| `--areas` | Áreas a recolher (lista separada por vírgulas; vazio = todas) |
| `--no-composicao` | Não recolher a composição |
| `--delay` | Pausa entre páginas de áreas (omissão `0.5` s) |
| `--out` | Ficheiro JSON de saída (omissão `data/governo/governo_nomeacoes.json`) |
| `--no-elastic` | Não indexar no Elasticsearch |
| `--no-scraped` | Indexar só nos índices dedicados, não em `finance_scraped` |

## Saídas

- `data/governo/governo_nomeacoes.json` — payload completo: `areas`, `membros`,
  `nomeacoes`, `fontes` e `stats`.
- `data/governo/governo_nomeacoes.jsonl` — uma nomeação por linha.
- `data/governo/governo_composicao.json` — os membros da composição.

## Índices Elasticsearch

| Índice | Documento | Chave |
| --- | --- | --- |
| `finance_governo_nomeacoes` | Uma nomeação | `item_id` (`governo-nomeacoes:<sha1>`) |
| `finance_governo_composicao` | Um membro do Governo | `item_id` (`governo-composicao:<sha1>`) |
| `finance_scraped` | Os mesmos registos, para a pesquisa do módulo de recolha | `item_id` |

Os `item_id` são determinísticos: repetir a recolha **atualiza** os documentos
conhecidos em vez de os duplicar.

### Campos principais

Nomeações: `area`, `area_slug`, `membro`, `funcao`, `nome`,
`rendimento_bruto_eur`, `rendimento_liquido_eur`, `data_nomeacao`, `dre_url` e
`encargos_servico_origem` (a nota «(1)» da página).

Composição: `grupo` (`Primeiro-Ministro`, `Ministros`, `Secretários de Estado`),
`nome`, `cargo`, `area_slug`, `periodo_inicio`, `periodo_fim` e
`secretarios_count`.

## Notas de manutenção

- A página do índice de nomeações e a da composição são renderizadas no browser.
  O coletor espera por `a.navigation-link[href*="/governo/nomeacoes/"]` e por
  `.search-composite-group .govinfo`, respetivamente; se o portal mudar as
  classes, é aí que se ajusta.
- As tabelas das áreas têm sempre seis colunas; a última coluna («Publicação em
  DRE») traz uma ligação para o Diário da República.
- Linhas exatamente repetidas na mesma página são ignoradas (o portal publica
  por vezes a mesma nomeação em dois blocos).
