# Testes end-to-end (Playwright + pytest)

Suite de testes de interface do IQ OS. Corre contra o frontend publicado
(não arranca servidores próprios) e compara o que o ecrã mostra com o que a
mesma API devolve, para que os valores esperados venham do Elasticsearch e não
de números escritos à mão.

## Cobertura

`test_entities_filters.py` — secção **EmpresasIQ › Entidades**:

- lista inicial (cards) e total do universo iguais à pesquisa sem filtros;
- pesquisa por nome (filtro enviado para `/companies/search` e entidades devolvidas);
- filtro por função (`adjudicante`/`adjudicatário`), incluindo a contagem distinta
  de NIF e a paginação sobre a lista completa;
- paginação (página seguinte/anterior) e limpeza de filtros;
- vistas de tabela e de mapa;
- menu de contexto de uma região do mapa e painel de contratos dessa região;
- exportação para Excel e para PDF (transferência de ficheiro com conteúdo).

## Preparação

```powershell
cd finance-llm\chat-ui
python -m venv e2e-venv
e2e-venv\Scripts\python.exe -m pip install pytest pytest-playwright playwright
e2e-venv\Scripts\python.exe -m playwright install chromium
```

O `e2e-venv/` não entra no repositório (ver `.gitignore`) — recria-se com os
comandos acima.

## Execução

Com o frontend a correr (por omissão em `http://127.0.0.1:4180`):

```powershell
e2e-venv\Scripts\python.exe -m pytest e2e/test_entities_filters.py -v
```

Só um teste, ou só o browser Chromium:

```powershell
e2e-venv\Scripts\python.exe -m pytest e2e/test_entities_filters.py -k pagination -v
e2e-venv\Scripts\python.exe -m pytest e2e/test_entities_filters.py --browser chromium
```

Para ver o browser durante a execução, acrescentar `--headed`.

## Configuração

| Variável | Efeito |
| --- | --- |
| `E2E_FRONTEND_URL` | URL do frontend em teste (por omissão `http://127.0.0.1:4180`). |
| `E2E_TOKEN` | Token de sessão já pronto; dispensa login. |
| `E2E_EMAIL` / `E2E_PASSWORD` | Credenciais usadas no login. Sem elas é usada a conta `e2e-empresas-iq@example.com`, criada automaticamente no primeiro ensaio. |

Se não for possível autenticar, a suite faz `skip` com a indicação do que falta.

## Notas de ambiente

- A aplicação exige sessão: o token é injetado em `localStorage`
  (`finance-llm-token`) antes de o bundle arrancar, e o service worker é
  desregistado para garantir que corre o bundle publicado.
- O banner de consentimento da iubenda flutua sobre as abas do módulo e engole
  os cliques (o Playwright dá o clique como bem-sucedido, mas o botão nunca o
  recebe). Os scripts de terceiros são bloqueados e qualquer nó do banner é
  removido depois de cada navegação.
