# Publicações de atos societários (Ministério da Justiça)

Módulo que recolhe e pesquisa os **atos de registo comercial** das entidades
portuguesas publicados em `https://publicacoes.mj.pt` (Instituto dos Registos e
do Notariado / Ministério da Justiça). É a fonte oficial desde 2007 — substituiu
a 3.ª série do Diário da República.

## Porque a recolha é assistida

A pesquisa do portal é protegida por **reCAPTCHA v2 validado no servidor**:

- o formulário é ASP.NET WebForms e o POST de pesquisa (`btSearch`) exige um
  `g-recaptcha-response` válido;
- sem ele o servidor devolve
  `ctl00_ContentPlaceHolderMain_lbNoResult` = «Por favor, efetue a Validação» e
  nenhuma grelha;
- não há serviço alternativo (`robots.txt`, `sitemap.xml`, `Resultado.aspx`,
  `Detalhe.aspx`, `*.asmx`, `api/*` → 404);
- não existe fonte aberta equivalente (`dados.gov.pt` → 0 resultados; o
  `diariodarepublica.pt` só cobre associações/fundações **antes de Julho de 2010**).

Não se contorna esta proteção (nem com serviços de resolução de captchas). Em vez
disso, o módulo trabalha com **uma pessoa no circuito**: essa pessoa resolve o
captcha e o coletor trata do resto.

## A chave da eficiência: janelas temporais

Verificou-se que **a paginação e o detalhe não voltam a pedir captcha**: uma
pesquisa validada autoriza o conjunto de resultados inteiro. Como o formulário
aceita pesquisar **só por datas** (intervalos até 10 dias), cada resolução de
captcha desbloqueia **milhares** de publicações de todo o país.

| Estratégia | Captchas | Cobertura |
|---|---|---|
| Uma pesquisa por entidade (113 469 NIF) | ~113 469 | só o que se enumerar |
| **Uma pesquisa por janela de 10 dias** | **721** (2007 → hoje) | todas as publicações do país |

Como cada linha traz o NIF da entidade, o resultado indexa-se **por entidade**:
obtém-se a ficha societária de cada empresa sem uma pesquisa por empresa.

## Ficheiros

| Ficheiro | Papel |
|---|---|
| `collectors/publicacoes_mj.py` | `PublicacoesMjClient` + `parse_detalhe`: pesquisa, paginação, detalhe e extração |
| `api/societario_service.py` | normalização, validação de datas, orquestração da recolha |
| `api/societario_routes.py` | rotas `/societario/*` |
| `api/elasticsearch_client.py` | índice `finance_publicacoes_mj` (mapping, indexação, pesquisa com facetas) |
| `_recolha_mj_assistida.py` | script assistido (Playwright) — o que abre o browser e pergunta pelo captcha |
| `_test_publicacoes_mj.py` | testes do parser com amostras fiéis ao HTML real |

## Como usar

### 1. Recolher (precisa de um clique no captcha)

```bash
# Uma janela de 3 dias (validação)
python _recolha_mj_assistida.py --data-ini 2026-09-14 --data-fim 2026-09-16 --max-paginas 5

# Uma entidade
python _recolha_mj_assistida.py --nif 500273170

# O plano completo (janelas de 10 dias desde 2007), com retoma
python _recolha_mj_assistida.py --plano

# Medir volume sem abrir detalhe nem indexar
python _recolha_mj_assistida.py --plano --limite-janelas 3 --sem-detalhe --sem-indexar
```

O script abre uma janela do Chromium no formulário, com os critérios já
preenchidos. Assim que o captcha é aceite, clica em «Pesquisar», percorre a
grelha, abre o detalhe de cada publicação, indexa e avança para a janela seguinte,
pedindo novo captcha.

O progresso fica em `data/societario/estado.json` (retoma automática; `--recomecar`
ignora-o). **Não feche a janela do Chromium** durante a recolha.

### 2. Consultar (API, sem captcha)

| Rota | Descrição |
|---|---|
| `GET /societario/meta` | tipos de publicação, distritos, sitekey, limites |
| `GET /societario/status` | volumetria (entidades, intervalo de datas, atos) |
| `GET /societario/search` | pesquisa com facetas (ato, tipo, distrito, ano, natureza jurídica) |
| `GET /societario/targets` | entidades com contratos no Portal BASE ainda sem publicações |
| `GET /societario/companies/{nif}` | publicações de uma entidade |
| `POST /societario/collect` | recolha assistida (sessão) — `recaptcha_token` ou `result_html` |
| `POST /societario/ingest` | indexar publicações já recolhidas (sessão) |

O grupo `societario` aparece em `/docs`.

## Dados extraídos por publicação

Da grelha: `data_publicacao`, `nif`, `entidade`, `concelho`, `acto`, `tipo`,
`has_documento`.

Do detalhe (`DetalhePublicacao.aspx`): `firma`, `natureza_juridica`, `sede`,
`distrito`, `freguesia`, `codigo_postal`, `conservatoria`, `matricula_nipc`,
`pedido`, `requerente`, `ano_contas`, `texto` (integral).

O `pub_id` é um SHA-1 de NIF + data + acto, pelo que **reingestões não duplicam**
e uma nova recolha da mesma entidade remove os registos que já não existem
(`replace_for_nif`).

O índice (`finance_publicacoes_mj`) é também um âmbito da **Pesquisa total**
(`/search/unified?scope=societario`) e da **Pesquisa profunda**
(`sources=["societario"]`), onde a pesquisa é feita por **relevância** (a
entidade primeiro) em vez da ordem por data usada na página do módulo.

## Fluxo do portal (para manutenção)

1. `GET Pesquisa.aspx` → formulário com `__VIEWSTATE`/`__EVENTVALIDATION`.
2. `POST Pesquisa.aspx` (`btSearch` + `g-recaptcha-response`) → grelha `gvSearchResult`.
3. `POST` com `__EVENTTARGET=gvSearchResult` + `Page$Next` → paginação (20 linhas/página).
4. `POST` com `__EVENTARGUMENT=Conteudo$N` → o servidor guarda a publicação **na
   sessão** e responde com `popitup('./DetalhePublicacao.aspx','detalhe')`.
5. `GET DetalhePublicacao.aspx` com os mesmos cookies → dados societários completos.

## Armadilhas

- **`txtDataInit`/`txtDataFim` têm máscara `99/99/9999`** — o valor é `DD/MM/AAAA`.
  Enviar ISO faz a pesquisa devolver **0 resultados**, sem qualquer erro de validação.
- Páginas em **Windows-1252** (não UTF-8): descodificar com `cp1252`.
- O intervalo de datas está limitado a **10 dias** pelo próprio portal.
- O detalhe abre numa janela nova (`popitup`), que o popup blocker trava — daí
  parecer que «Conteúdo» não faz nada. O conteúdo fica na sessão e é acessível por GET.
- O NoBot (`ChallengeScript`, ex.: `eval('52+93')`) exige que o postback aconteça
  alguns segundos depois de a página ser servida — irrelevante na recolha assistida.
