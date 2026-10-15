# Testes end-to-end (Playwright + pytest)

Suite de testes de interface do IQ OS. Corre contra o frontend publicado
(não arranca servidores próprios) e compara o que o ecrã mostra com o que a
mesma API devolve, para que os valores esperados venham do Elasticsearch e não
de números escritos à mão.

## Cobertura

`test_entities_filters.py` — secção **EmpresasIQ › Entidades**:

- lista inicial (cards) e total do universo iguais à pesquisa sem filtros;
- pesquisa por nome/NIF: devolve apenas entidades que casam pelo **próprio** nome
  (sem as contrapartes dos contratos), sem acentos e com os termos por qualquer
  ordem; um NIF devolve uma única entidade;
- botão «Pesquisar» do topo aplicado à lista de entidades;
- paginação: a API confirma o offset recebido em `from` e a UI avança/recua 15
  entidades por página;
- filtro por função (`adjudicante`/`adjudicatário`): devolve apenas entidades com
  esse papel, com o total do papel, o estado vazio quando não há
  correspondências e — sem pesquisa por nome — o aviso de lista limitada;
- limpar filtros devolve o universo inicial;
- vistas de tabela e de mapa;
- menu de contexto de uma região do mapa e painel de contratos dessa região;
- exportação para Excel e para PDF (transferência de ficheiro com conteúdo). A
  exportação para PDF é rasterizada no browser e pode demorar minutos numa
  máquina carregada — o limite do teste é folgado por isso.

`test_cms_menu_submenus.py` — **submenus do menu público** (CMS → Aparência →
menus):

- o editor acrescenta um subitem, guarda-o e o subitem chega à API;
- no computador o submenu só aparece com o rato ou com o foco (teclado), um item
  sem página nem URL é rótulo de grupo (não navega) e o submenu de segundo nível
  abre ao lado **dentro do ecrã**;
- no rodapé os submenus aparecem ao lado do item que os abre;
- no telemóvel (390×844) o botão «Menu» abre o painel, os submenus ficam à vista
  e indentados, a página não ganha scroll horizontal e tocar num subitem navega.

Além do que o editor guarda, o cabeçalho mostra **submenus derivados dos dados**
(calculados a cada renderização, nunca gravados no menu — ver
`cms_store._acrescentar_submenus_derivados`): as **subpáginas publicadas** com
«Mostrar no menu» entram sob o item que abre a página-mãe (é o caso dos estudos
de benchmark sob «Benchmarks») e o que está publicado no Estúdio entra agrupado
por área de trabalho sob o item que abre a biblioteca de relatórios. O rodapé não
os recebe. Como o painel pode ficar mais alto do que o ecrã (e o cabeçalho é
pegajoso), o painel do telemóvel rola dentro de si mesmo — sem isso, o fim da
lista ficava fora do alcance.

Estes testes **escrevem no CMS** (menu do cabeçalho e do rodapé, reposto no fim) e
por isso exigem uma sessão com papel `admin` ou `manager` — escrever no CMS está
reservado a esses papéis. Com a conta `member` que a suite provisiona por
omissão, os testes do ficheiro são saltados com essa indicação; para os correr,
promover a conta E2E na Administração ou passar `E2E_TOKEN` de uma conta gestora.

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
