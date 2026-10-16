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
- o submenu (cabeçalho, no computador e no telemóvel) **abre e fecha com um
  clique na seta do item, nunca com o rato por cima**: o rótulo continua a ser o
  link e a seta traz `aria-expanded` com o estado. Clicar fora do menu ou
  carregar em Esc fecha o que estivesse aberto. Um item sem página nem URL é
  rótulo de grupo (não navega) e o submenu de segundo nível abre ao lado
  **dentro do ecrã**;
- no rodapé os submenus aparecem ao lado do item que os abre;
- no telemóvel (390×844) o botão «Menu» abre o painel, a lista começa
  **fechada** e cada submenu abre e fecha pela sua própria seta (o rótulo do item
  continua a ser o link); os itens ficam indentados, a página não ganha scroll
  horizontal e tocar num subitem navega;
- o painel do telemóvel traz a **pesquisa** (envia para `/site/pesquisa?q=`),
  **entrar/criar conta** e um **ícone** em cada entrada de topo — com a geometria
  do **Lucide** (a mesma biblioteca que o `chat-ui` usa; ver `_ICONES` em
  `api/cms_render.py`), escondida no ecrã grande; as entradas de topo do CMS que
  levam a `/login` ou `/register` não se repetem no painel (marca
  `menu-igual-conta`, escondida só no telemóvel); nada disto passa pelo CMS, é o
  HTML do site que o publica;

Além do que o editor guarda, o cabeçalho mostra **submenus derivados dos dados**
(calculados a cada renderização, nunca gravados no menu — ver
`cms_store._acrescentar_submenus_derivados`): as **subpáginas publicadas** com
«Mostrar no menu» entram sob o item que abre a página-mãe (é o caso dos estudos
de benchmark sob «Benchmarks») e o que está publicado no Estúdio entra agrupado
por área de trabalho sob o item que abre a biblioteca de relatórios. O rodapé não
os recebe. Como o painel pode ficar mais alto do que o ecrã (e o cabeçalho é
pegajoso), o painel do telemóvel rola dentro de si mesmo — sem isso, o fim da
lista ficava fora do alcance. Numa linha apertada cedem o texto e os botões de
entrar/criar conta (que passam para a linha seguinte): o desenho dos ícones tem
`flex: none` para não encolher e ficar deformado.

Estes testes **escrevem no CMS** (menu do cabeçalho e do rodapé, reposto no fim) e
por isso exigem uma sessão com papel `admin` ou `manager` — escrever no CMS está
reservado a esses papéis. Com a conta `member` que a suite provisiona por
omissão, os testes que mexem no menu são saltados com essa indicação (os que só
olham para o site publicado — painel do telemóvel, pesquisa, ícones — correm com
qualquer conta); para os correr todos, promover a conta E2E na Administração ou
passar `E2E_TOKEN` de uma conta gestora.

`test_site_paginas_sistema.py` — **páginas de sistema do site público** (não
precisa de sessão nem de CMS): endereço que não existe (404), falta de rede
(`/site/offline`, servida pelo service worker) e a página do proxy (`/erro.html`,
do nginx, que substitui o 502 cru quando o backend não responde). Cada teste
navega a sério e valida o que se vê, não só o texto:

- o 404 responde **404** e mostra título, nota com humor, ilustração (com
  `role="img"`, texto alternativo, tamanho e proporção 800×480) e legenda;
- a plataforma e os cinco destinos úteis (Soluções, Relatórios, Fontes, Blog e
  Contactos) estão visíveis, e a trilha de navegação tem dois passos com o
  último marcado (`aria-current`);
- **alinhamento**: no computador o texto e a ilustração ficam lado a lado (sem
  sobreposição) e o título começa na mesma coordenada que a trilha; no telemóvel
  a ilustração passa para baixo do texto e nada estoura na horizontal;
- a pesquisa do 404 leva mesmo a `/site/pesquisa?q=…` com resultados, e as ações
  («Ir para o início», «Reportar o link») navegam para onde dizem;
- **sem rede** (com o service worker ativo e `context.set_offline(True)`): um
  endereço nunca visitado mostra a página de recurso com a ilustração, e uma
  página já visitada abre da cache em vez da página de recurso;
- o `/erro.html` devolve 200 com `Cache-Control: no-store`, explica o que se
  passa, dá a saída (tentar outra vez, voltar ao início) e não estoura em nenhum
  dos ecrãs.

De cada página fica uma captura em PNG no diretório temporário do teste
(`tmp_path`) — serve para confirmar a olho; os testes comparam geometria (caixas,
proporções, alinhamentos), não pixels, para não ficarem presos a tipos de letra
de cada máquina.

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
