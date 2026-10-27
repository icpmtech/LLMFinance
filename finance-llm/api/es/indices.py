"""Nomes dos índices e `INDEX_SETTINGS` (analisadores e sinónimos).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)



logger = logging.getLogger(__name__)



# Índice único para contratos públicos normalizados
CONTRACTS_INDEX = "contratos"



# Contratos públicos de Espanha (PLACSP). Índice próprio (`contratos_es`) para não
# se misturar com os contratos portugueses: os identificadores e o vocabulário
# (expediente, CODICE/UBL) são diferentes, mas os dois partilham o mesmo tipo de
# pesquisa por facetas. Alimentado por `collectors/contratos_es.py`.
CONTRATOS_ES_INDEX = "contratos_es"



# Contratos públicos de França (DECP / data.gouv.fr). Índice próprio para
# manter identificadores, idioma e estrutura DECP separados de PT e ES.
CONTRATOS_FR_INDEX = "contratos_fr"



# Fontes do PLACSP indexadas na plataforma.
CONTRATOS_ES_FONTES = ("licitaciones", "menores")



# Índice para marcas do INPI indexadas por entidade
TRADEMARKS_INDEX = "finance_trademarks"



# Índice para firmas/nomes comerciais do RNPC (Pesquisa de Nomes Existentes)
FIRMAS_INDEX = "finance_firmas"



# Índice para o cadastro de entidades do portal base (data/entidades-gov-portal-base/entidades.json)
ENTITIES_INDEX = "finance_entities"



# Índice para preferências do utilizador (favoritos, pastas do dossier e histórico do EmpresasIQ).
# Evita depender do localStorage do browser, que se perde ao mudar de origem/porta ou ao limpar dados.
USER_STATE_INDEX = "finance_user_state"



# Índice para traduções de resumos de tickers (originais e traduzidos por IA).
TICKER_TRANSLATIONS_INDEX = "finance_ticker_translations"



# Índice de contas de utilizador (autenticação). O `_id` do documento é o email
# normalizado, o que garante unicidade sem necessitar de transações.
AUTH_USERS_INDEX = "finance_users"



# Índice de sessões (uma por início de sessão). Guarda a validade e a revogação,
# para que o "terminar sessão" seja imediato e auditável.
AUTH_SESSIONS_INDEX = "finance_sessions"



# Registo de eventos do sistema (autenticação, pedidos à API, tarefas, erros) —
# alimenta o visualizador de eventos da área de administração.
EVENTS_INDEX = "finance_events"



# Chaves de API dos fornecedores de IA (uma linha por utilizador; `_id` = user id).
PROVIDER_KEYS_INDEX = "finance_provider_keys"



# Definições da plataforma geridas pela administração (documento único com
# `kind` próprio): por agora, o acesso aos módulos da barra lateral por perfil.
SETTINGS_INDEX = "finance_settings"



# Apoio ao cliente: conversas entre visitantes (site, loja e SPA) e operadores
# (administração). As mensagens ficam num índice próprio para as conversas
# crescerem sem reescrever o documento da sessão a cada mensagem.
SUPPORT_VISITORS_INDEX = "finance_support_visitors"
SUPPORT_SESSIONS_INDEX = "finance_support_sessions"
SUPPORT_MESSAGES_INDEX = "finance_support_messages"
SUPPORT_TICKETS_INDEX = "finance_support_tickets"
SUPPORT_FORM_RESPONSES_INDEX = "finance_support_form_responses"
SUPPORT_EVENTS_INDEX = "finance_support_events"
SUPPORT_OPERATORS_INDEX = "finance_support_operators"



# Módulo de CRM: contas, contactos, oportunidades e atividades num único índice.
# O campo `kind` distingue o tipo de registo e `owner_id` o utilizador dono
# (os administradores veem todos os registos).
CRM_INDEX = "finance_crm"



# Arquitetura de CRM: índice próprio para os utilizadores do CRM (atribuições de
# perfil/área/departamento/equipa), equipas, perfis personalizados e o registo de
# auditoria imutável. Fica separado de `finance_crm` para que os registos de
# negócio nunca sejam contaminados por metadados de administração.
CRM_RBAC_INDEX = "finance_crm_rbac"



# Módulo de recolha (scraping): itens extraídos de sites pelas "fontes"
# (definições) do `scraper_service`. Os campos de cada fonte variam, por isso o
# conteúdo extraído vive em `data` (tipo `flattened`), pesquisável e agregável
# sem precisar de um mapping diferente por site.
SCRAPED_INDEX = "finance_scraped"



# Módulo EU Taxonomy Navigator: atividades, objetivos e setores oficiais do
# Compass da Comissão Europeia, com texto original (EN) e tradução (PT).
EU_TAXONOMY_INDEX = "finance_eu_taxonomy"



# Módulo de pesquisa social: publicações recolhidas de redes sociais (LinkedIn,
# TikTok, Reddit e Facebook) pelos "canais" (definições) do `social_service`.
# Cada documento é uma publicação normalizada, com as métricas de interação em
# campos próprios (pesquisáveis e agregáveis) e o resto em `data` (`flattened`).
SOCIAL_INDEX = "finance_social"



# Configurações de agentes dinâmicos do IQ OS (LangGraph + ferramentas).
# Guarda grafos de agentes, nós, ferramentas, prompts e chaves por utilizador.
AGENT_CONFIGS_INDEX = "iq_os_agent_configs"



# Publicações de atos societários do Ministério da Justiça (publicacoes.mj.pt).
# A pesquisa do portal exige reCAPTCHA (ver `collectors/publicacoes_mj.py`), pelo que
# a recolha é assistida e o resultado fica guardado aqui para consulta e pesquisa.
SOCIETARIO_INDEX = "finance_publicacoes_mj"



# Publicações do CIRE (CITIUS / Ministério da Justiça): publicidade do PER, do
# PEAP, do PEVE e dos processos de insolvência — tribunal, processo, espécie,
# datas e intervenientes (com NIF/NIPC). Recolhido de `consultascire.aspx`.
CIRE_INDEX = "finance_cire"



# Citações e notificações editais (CITIUS / Ministério da Justiça): os éditos
# publicados quando o citando/notificado não é encontrado — tribunal, ato,
# processo, espécie, data e intervenientes (exequente, executado, réu, …).
# Recolhido de `consultascitedital.aspx`.
CITACOES_INDEX = "finance_citacoes_edital"


# Publicidade da Composição da Massa Insolvente (CITIUS / Ministério da Justiça):
# anúncios publicados pelo Administrador Judicial nos termos do art.º 152.º do
# CIRE — processo, espécie, tribunal, insolvente(s), área de negócio, valor da
# avaliação, data de atualização, descrição da massa e lista de ativos.
# Recolhido de `PublicidadeMassaInsolvente.aspx`.
MASSA_INSOLVENTE_INDEX = "finance_massa_insolvente"


# Venda de bens penhorados em processos executivos (CITIUS) e leilões / vendas
# promovidos pelos agentes de execução no e-leiloes.pt. Um documento por bem,
# com tribunal/comarca, processo, tipo/modalidade/estado, datas, valores,
# descrição, localização e intervenientes (executados e agentes).
VENDAS_PENHORADOS_INDEX = "finance_vendas_penhorados"



# Pessoas e cargos extraídos das publicações societárias (MJ). Um documento por
# NIF de pessoa (individual ou coletiva), com roles aninhados por empresa/acto.
PEOPLE_INDEX = "finance_people"



# Contribuintes: um documento por **NIF/NIPC**, agregando todas as entidades e
# pessoas que aparecem nos restantes índices da plataforma (contratos PT/ES,
# cadastro de entidades, publicações societárias, CIRE, PessoasIQ, firmas,
# marcas e CRM). É um índice **derivado**: `api/contribuintes_service.py`
# reconstrói-o periodicamente (cron) a partir das fontes, para haver um ponto
# único de pesquisa de contribuintes em todo o sistema.
CONTRIBUINTES_INDEX = "finance_contribuintes"



# Resumos de nós dos grafos (pessoas, empresas, sites): texto redigido por IA a
# partir dos factos do IQ OS e de pesquisa na web, guardado para consulta
# posterior (um documento por nó, substituído a cada novo resumo).
NODE_SUMMARIES_INDEX = "finance_node_summaries"



#: Análises de padrões guardadas por empresa (módulo «Deteção de padrões»):
#: fotografia da análise, ficha redigida por IA e páginas lidas no browser.
ANALISES_EMPRESA_INDEX = "finance_analises_empresa"



#: Métricas do **universo** por ano (dashboard global): um documento por ano, um
#: de total e um de meta, calculados por agregação sobre o índice inteiro.
GLOBAL_PADROES_INDEX = "finance_padroes_global"



# Diretório de empresas recolhido do Rigorbiz (nome, NIF, CAE, morada).
RIGORBIZ_INDEX = "finance_rigorbiz"



# GLEIF — «Golden Copy» dos registos LEI (Legal Entity Identifier). Um documento
# por LEI, com o nível 1 (quem é quem: nome legal, endereço, jurisdição, forma
# jurídica, estado, datas) e os identificadores associados (BIC, MIC, OCID, QCC,
# S&P Global). O índice é alimentado por `collectors/gleif.py` — quer a partir da
# API oficial do GLEIF, quer a partir do ficheiro *Golden Copy* (LEI-CDF) — e é
# pesquisável no módulo «GLEIF / LEI» (`/gleif/*`).
GLEIF_LEI_INDEX = "finance_gleif_lei"



# Listas públicas de devedores (Autoridade Tributária e Segurança Social). Um
# documento por devedor **e por lista**: `nif`/`nome` iguais em escalões
# diferentes são registos distintos (o NIF pode até estar em ambas as entidades).
# Alimentado por `api/devedores_service.py`, que descarrega os PDF oficiais das
# Finanças (6 escalões de singulares + 6 de coletivos) e guarda, a par do JSON e
# do próprio PDF, a **data da recolha** de cada ficheiro.
DEVEDORES_INDEX = "finance_devedores"



# Histórico das recolhas: um documento por **ficheiro e data** (lista + PDF
# guardados + nº de registos), para a área de pesquisa poder mostrar de onde veio
# cada dado e quando foi recolhido.
DEVEDORES_RECOLHAS_INDEX = "finance_devedores_recolhas"


# Lista de sociedades com **mais de 200 ações** (Portaria n.º 200/2011, de 20 de
# maio; artigo 13.º do Regulamento das Custas Processuais). Um documento por
# **sociedade e por ano**: `doc_id = <ano>:<nipc>`, porque a mesma sociedade pode
# entrar na lista em vários anos e o que conta é a lista de cada ano civil.
# Alimentado por `api/grandes_litigantes_service.py`, que percorre a consulta do
# Portal CITIUS (`/portal/consultas/Custas/Portaria200-2011.aspx`), guarda o
# instantâneo em JSON em `data/grandes-litigantes/` e indexa os registos.
GRANDES_LITIGANTES_INDEX = "finance_grandes_litigantes"


# Histórico das recolhas: um documento por **recolha** (data, anos abrangidos,
# nº de sociedades, páginas lidas e caminho do JSON).
GRANDES_LITIGANTES_RECOLHAS_INDEX = "finance_grandes_litigantes_recolhas"



# Subvenções e outros benefícios públicos (Lei n.º 64/2013, de 27/08). Um
# documento por **linha do ficheiro de origem**: quem deu (`entidade`), quem
# recebeu (`beneficiario`), quanto (`montante`), quando foi decidido
# (`data_decisao`) e com que fundamento legal (`tipo_ato`/`numero_ato`/
# `data_ato`). Alimentado por `api/subvencoes_service.py`, que lê os `.ods`
# publicados pela IGF na pasta `data/subvencoes` (um ficheiro por ano, ou uma
# subpasta por ano) e normaliza-os para JSONL antes de indexar.
SUBVENCOES_INDEX = "finance_subvencoes"



# Um documento por **ficheiro lido**: ano, caminho, tamanho, `sha256`, folha,
# número de linhas/registos e o total transferido — para a página poder mostrar
# o que já foi lido e de onde veio cada registo.
SUBVENCOES_LOTES_INDEX = "finance_subvencoes_lotes"



# Financiamento partidário (Tribunal Constitucional). A Entidade das Contas e
# Financiamentos Políticos (ECFP) publica, por ano, as **contas anuais** de cada
# partido, a **lista de ações e meios** de propaganda política, os relatórios da
# ECFP, os acórdãos e as decisões. Um documento por **entrada da página anual**
# (partido × ano × secção), com o texto do PDF extraído para pesquisa integral.
# `_id` = `<ano>:<secção>:<partido>` — reindexar o mesmo ano sobrepõe-se em vez
# de duplicar. Alimentado por `api/partidos_service.py`.
PARTIDOS_INDEX = "finance_partidos"



# Vereadores e remunerações autárquicas. Documento por pessoa × concelho ×
# cargo, agregando candidaturas, mandatos e valores de remuneração declarados
# pelas câmaras municipais.
VEREADORES_INDEX = "finance_vereadores"



# Despesas das câmaras municipais. Um documento por **município** (308), com a
# despesa anual do indicador do INE/DGAL (classificador económico) e a
# contratação pública em que o município é adjudicante, agregada do índice
# `contratos`. Alimentado por `api/municipios_service.py`.
MUNICIPIOS_DESPESAS_INDEX = "finance_municipios_despesas"



# Executivos municipais: membros das câmaras municipais dos 308 concelhos
# (presidente, vice-presidentes, vereadores). Documento por pessoa × concelho ×
# cargo — os nomes e os partidos vêm do Mapa Oficial da CNE e os pelouros, a
# fotografia e a página de cada eleito dos sites das câmaras.
MUNICIPIO_PESSOAS_INDEX = "finance_municipio_pessoas"



# Contactos das 308 câmaras municipais (presidente, morada, e-mail, telefone,
# site). Alimentado por `api/municipios_contactos_service.py` a partir do Excel
# `data/municipios-contatos/contactos presidente CM 04092026.xlsx`.
MUNICIPIOS_CONTACTOS_INDEX = "finance_municipios_contactos"

# Contactos das juntas de freguesia. Alimentado por
# `api/freguesias_contactos_service.py` a partir do Excel
# `data/municipios-contatos/Contactos_freguesias.xlsx`.
FREGUESIAS_CONTACTOS_INDEX = "finance_freguesias_contactos"

# Empresas locais com participação de entidades municipais. Alimentado por
# `api/empresas_locais_service.py` a partir do Excel
# `data/municipios-contatos/empresas locais 12_02_2025.xlsx`.
EMPRESAS_LOCAIS_INDEX = "finance_empresas_locais"



# Abonos dos eleitos locais. Um documento por **linha da tabela oficial**
# (ano × nível × regime × verba × cargo × modalidade), com os valores por escalão
# de eleitores — é o direito aplicável, não a pessoa. Alimentado por
# `api/remuneracoes_service.py` a partir de `data/remuneracoes/`.
REMUNERACOES_INDEX = "finance_remuneracoes"



# O mesmo direito aplicado ao **território**: um documento por concelho e por
# freguesia, com o número de eleitores inscritos (recenseamento), o escalão em
# que caem e as remunerações que lhes correspondem, mais o polígono do mapa.
REMUNERACOES_TERRITORIOS_INDEX = "finance_remuneracoes_territorios"



# As **pessoas** eleitas: um documento por eleito (presidente de câmara e
# vereadores), com o município, o partido, o cargo e a remuneração mensal que a
# tabela fixa para esse cargo. Os nomes vêm do Mapa Oficial da CNE (é a única
# publicação com os nomes de todos os eleitos); quem ganhou e quantos mandatos
# tem cada lista vem do MAI. `_id` = `<concelho_id>-<slug do nome>`.
REMUNERACOES_PESSOAS_INDEX = "finance_remuneracoes_pessoas"



# **Remunerações da Administração Pública**: um documento por linha do quadro da
# DGAEP — nível da Tabela Remuneratória Única, posição remuneratória de uma
# carreira/categoria ou cargo dirigente — com o valor mensal publicado para
# cada ano. Alimentado por `api/remuneracoes_ap_service.py` a partir dos PDF
# `SRAP_<ano>.pdf`. `_id` = `<tipo>-<ano>-<chave>`.
REMUNERACOES_AP_INDEX = "finance_remuneracoes_ap"



# Registo oficial dos partidos na **CNE**: denominação, sigla, data de inscrição,
# situação (`inscrito`/`extinto`), sítio na Internet, símbolo e descrição. É a
# chave que liga os documentos das contas ao partido. `_id` = `<chave>` (slug).
PARTIDOS_REGISTO_INDEX = "finance_partidos_registo"



# Histórico das recolhas: uma entrada por **página descarregada** (ano do TC ou
# listagem/partido da CNE), com o `sha256` do HTML, o que rendeu e eventuais
# erros — para a página poder mostrar o que está recolhido e de onde veio.
PARTIDOS_RECOLHAS_INDEX = "finance_partidos_recolhas"



# Portal da Transparência da **ERC** — entidades proprietárias de órgãos de
# comunicação social, as **pessoas** dos seus órgãos sociais e os OCS detidos.
# Três índices, alimentados por `api/erc_service.py`:
#
# - `finance_erc_entidades`: um documento por entidade (`_id` = `IdEntidade`),
#   com os dados gerais, o número de OCS e a lista de pessoas dos órgãos sociais
#   e das participações (detentores/detidas);
# - `finance_erc_pessoas`: um documento por pessoa regulada (`_id` = GUID da
#   pessoa), com os cargos (empresas onde é gerente/administrador) e as
#   participações diretas;
# - `finance_erc_ocs`: um documento por órgão de comunicação social
#   (`_id` = `<designação>:<tipo>:<entidade proprietária>`).
ERC_ENTIDADES_INDEX = "finance_erc_entidades"


ERC_PESSOAS_INDEX = "finance_erc_pessoas"


ERC_OCS_INDEX = "finance_erc_ocs"



# Histórico das recolhas do portal da ERC: uma entrada por **página descarregada**
# (listagem, ficha de entidade ou ficha de pessoa), com o `sha256` do HTML, o que
# rendeu e eventuais erros.
ERC_RECOLHAS_INDEX = "finance_erc_recolhas"



# **Entidade para a Transparência** — declarações únicas dos titulares de cargos
# políticos e altos cargos públicos. Quatro índices, alimentados por
# `api/entidade_transparencia_service.py`:
#
# - `finance_ept_titulares`: um documento por titular (`_id` = id da EPT), com o
#   resumo das declarações e a cascata entidade/cargo/órgão;
# - `finance_ept_titularidades`: uma linha por entidade × cargo × titular, com
#   as datas de exercício (é a tabela que a plataforma mostra na pesquisa);
# - `finance_ept_declaracoes`: uma declaração única, com as secções
#   normalizadas, as tabelas do registo de interesses e o texto pesquisável;
# - `finance_ept_recolhas`: o manifesto da última recolha.
EPT_TITULARES_INDEX = "finance_ept_titulares"


EPT_TITULARIDADES_INDEX = "finance_ept_titularidades"


EPT_DECLARACOES_INDEX = "finance_ept_declaracoes"


EPT_RECOLHAS_INDEX = "finance_ept_recolhas"



# **Grafo da Transparência** — rede de pessoas, cargos, entidades públicas e
# empresas extraída das declarações da EPT (`api/transparencia_grafo_service.py`):
#
# - `finance_ept_grafo_nos`: um nó por pessoa, cargo, entidade pública ou empresa,
#   com o grau, os anos em que aparece e, nas empresas, a sede geocodificada
#   (`location` como `geo_point`) para o mapa;
# - `finance_ept_grafo_arestas`: uma aresta por par de nós e relação (exerce o
#   cargo, cargo na entidade, atividade em, participação em, apoio, serviço);
# - `finance_ept_grafo_recolhas`: o manifesto da última construção do grafo.
TRANSPARENCIA_GRAFO_NOS_INDEX = "finance_ept_grafo_nos"


TRANSPARENCIA_GRAFO_ARESTAS_INDEX = "finance_ept_grafo_arestas"


TRANSPARENCIA_GRAFO_RECOLHAS_INDEX = "finance_ept_grafo_recolhas"



# **Arquivo.pt** — páginas da web preservadas pelo Arquivo.pt (FCT). Cada
# documento é uma captura de uma página, recolhida via API pública de pesquisa
# de texto completo (`textsearch`) ou CDX (`wayback/cdx`). Os campos principais
# (título, URL, domínio, data de captura, snippet, links) são pesquisáveis; o
# objeto `raw` guarda a resposta original da API.
ARQUIVO_PT_INDEX = "finance_arquivo_pt"



# ---------------------------------------------------------------------------
# «World Model» — o estado do mundo da contratação pública, materializado.
#
# A camada de *public data* (contratos PT/ES, cadastro de entidades, CIRE,
# pessoas, contribuintes) é lida por `api/world_sources.py`; `api/world_model.py`
# transforma-a em **estado** (entidades e contratos), **eventos** (registo
# temporal) e **relações** (grafo), gravando em três índices próprios. É este
# estado — e não os dados em bruto — que alimenta a rede neuronal dinâmica
# (`api/world_neural.py`), o motor de grafo/tempo (`api/world_graph.py`), o
# simulador de futuro (`api/world_simulator.py`) e o agente de investigação
# (`api/world_investigation.py`).
# ---------------------------------------------------------------------------

# Estado materializado: um documento por entidade (empresa, entidade pública,
# pessoa) ou por contrato-agregado. `_id` = `<entity_ref>`.
WORLD_STATE_INDEX = "finance_world_state"



# Registo de eventos (append-only, um documento por acontecimento): adjudicações,
# alterações de valor, cessação, insolvências, criação/desaparecimento de
# relações. Alimenta a linha temporal e a causalidade.
WORLD_EVENTS_INDEX = "finance_world_events"



# Relações do grafo (uma aresta por par entidade↔entidade e tipo).
WORLD_RELATIONS_INDEX = "finance_world_relations"



# **Estado temporal** do mundo: um documento por entidade **e por período**
# (mês/trimestre/ano), com os contadores acumulados e os do período, o risco
# recalculado no fim do período e o número de contrapartes/administradores.
# É esta série que alimenta o modelo de transição latente e a deteção de
# anomalias (a rede neuronal vê a evolução, não só o retrato atual).
WORLD_HISTORY_INDEX = "finance_world_history"



# Estado da rede neuronal dinâmica (uma versão por treino/growth): nós, arestas,
# memória, métricas e previsões. `_id` = `version:<n>`.
NETWORK_STATE_INDEX = "finance_network_state"



# Execuções do simulador de futuro (t0→t1→t2→t3) com os cenários e as
# distribuições produzidas.
SIMULATIONS_INDEX = "finance_world_simulations"



# Execuções do agente de investigação (Observe→Hypothesize→Search→Validate→
# Simulate→Evidence Report), com a auditoria completa e o relatório.
INVESTIGATIONS_INDEX = "finance_world_investigations"



# Execuções do modelo Lorenz (panorama + cenários de propagação), guardadas por
# `run_id` com a fotografia completa em `resultado` (não indexada).
LORENZ_RUNS_INDEX = "finance_lorenz_runs"



# Execuções do módulo de inteligência de mercado (benchmark CPV × CAE × contrato).
MERCADO_RUNS_INDEX = "finance_mercado_runs"



# Resultados de pesquisa OSINT (username/email) via user-scanner.
OSINT_INDEX = "finance_osint"



# Peças do procedimento descarregadas do Portal Vortal (uma entrada por ficheiro,
# com o texto extraído para pesquisa).
VORTAL_PECAS_INDEX = "finance_vortal_pecas"



# Caixas de correio do próprio IQ OS geridas em Administração → Correio: a
# configuração de cada caixa (servidores, contas, pastas a sincronizar) e o
# estado da sincronização.
PLATFORM_MAIL_ACCOUNTS_INDEX = "finance_mail_accounts"



# Arquivo pesquisável do correio da plataforma: uma entrada por mensagem
# sincronizada (assunto, participantes, corpo, anexos e fios de conversa). É este
# índice que serve a lista, a pesquisa e as contagens — o IMAP fica para o detalhe.
PLATFORM_MAIL_MESSAGES_INDEX = "finance_mail_messages"



# Módulo **ESG**: uma fotografia por empresa (score, pilares, componentes,
# historico de 3 anos, benchmark de pares e evidencias). O `_id` é
# `PAIS-NIF`, para que recalcular a mesma empresa atualize o mesmo documento.
ESG_EMPRESAS_INDEX = "finance_esg_empresas"



# Indicadores ESG declarados nos relatorios de sustentabilidade (uma entrada por
# empresa, ano e fonte). O score usa-os quando existem; sem eles, fica só com os
# indicadores calculados a partir dos dados abertos.
ESG_INDICADORES_INDEX = "finance_esg_indicadores"



# Registo das execucoes de calculo e de ingestao de indicadores (progresso,
# contagens e erros), como nos restantes modulos de recolha.
ESG_RECOLHAS_INDEX = "finance_esg_recolhas"



# Módulo DORA: Register of Information, incidentes, riscos, workflows,
# relatórios ITS/RTS, conteúdo recolhido da EIOPA e registo das recolhas.
DORA_REGISTO_INDEX = "finance_dora_registo"


DORA_INCIDENTES_INDEX = "finance_dora_incidentes"


DORA_RISCOS_INDEX = "finance_dora_riscos"


DORA_WORKFLOWS_INDEX = "finance_dora_workflows"


DORA_RELATORIOS_INDEX = "finance_dora_relatorios"


DORA_CONTEUDO_INDEX = "finance_dora_conteudo"


DORA_RECOLHAS_INDEX = "finance_dora_recolhas"


# Módulo SEC — filings EDGAR: metadados, texto integral e factos extraídos.
SEC_FILINGS_INDEX = "finance_sec_filings"


SEC_FACTS_INDEX = "finance_sec_facts"


SEC_RECOLHAS_INDEX = "finance_sec_recolhas"



# Definições (settings) específicas de determinados índices — nomeadamente
# analisadores usados em subcampos de pesquisa por prefixo.
INDEX_SETTINGS: Dict[str, Dict[str, Any]] = {
    RIGORBIZ_INDEX: {
        "analysis": {
            "analyzer": {
                "pt_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ANALISES_EMPRESA_INDEX: {
        # Os nomes de empresas e as notas do analista são escritos com acentos.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    LORENZ_RUNS_INDEX: {
        # O título de cada execução é escrito com acentos.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    MUNICIPIOS_CONTACTOS_INDEX: {
        # Nomes de municípios e de presidentes escritos com acentos.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    FREGUESIAS_CONTACTOS_INDEX: {
        # Nomes de freguesias e de presidentes escritos com acentos.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    EMPRESAS_LOCAIS_INDEX: {
        # Nomes de empresas e entidades locais escritos com acentos.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    MERCADO_RUNS_INDEX: {
        # Idem: títulos de mercado com acentos («Construção», «Saúde»).
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    EPT_TITULARES_INDEX: {
        # Nomes de titulares e de entidades escrevem-se com acentos.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    EPT_TITULARIDADES_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    EPT_DECLARACOES_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    TRANSPARENCIA_GRAFO_NOS_INDEX: {
        # Nomes de pessoas, entidades e empresas escrevem-se com acentos.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    VORTAL_PECAS_INDEX: {
        # Nomes de peças e texto de cadernos de encargos: acentos e maiúsculas
        # («CADERNO DE ENCARGOS», «Município») têm de ser pesquisáveis a dobrar.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    AGENT_CONFIGS_INDEX: {
        "analysis": {
            "analyzer": {
                "agent_name_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    # Arquivo.pt: títulos, snippets e texto extraído de páginas preservadas
    # podem conter acentos; o analisador `world_folding` normaliza a pesquisa.
    # O tokenizer parte em pontuação para que domínios e URLs
    # («www.portugal.gov.pt/noticias») sejam pesquisáveis por partes — com o
    # `standard` ficavam num único token e a pesquisa por «portugal» não os via.
    ARQUIVO_PT_INDEX: {
        "analysis": {
            "tokenizer": {
                "arquivo_urls": {
                    "type": "pattern",
                    "pattern": "[^\\p{L}\\p{N}]+",
                }
            },
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "arquivo_urls",
                    "filter": ["lowercase", "asciifolding"],
                }
            },
        }
    },
    # Portal da Transparência da ERC: nomes de entidades e pessoas escritos com
    # acentos («Comunicação», «Guimarães») — `asciifolding` deixa que uma pesquisa
    # sem acentos os encontre.
    ERC_ENTIDADES_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ERC_PESSOAS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ERC_OCS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ERC_RECOLHAS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    VEREADORES_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    MUNICIPIOS_DESPESAS_INDEX: {
        # Nomes de municípios escritos com acentos («Covilhã», «Alandroal»).
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    MUNICIPIO_PESSOAS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    REMUNERACOES_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    REMUNERACOES_TERRITORIOS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    REMUNERACOES_PESSOAS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    REMUNERACOES_AP_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    GRANDES_LITIGANTES_INDEX: {
        # Nomes de sociedades comerciais, especialmente bancos e seguradoras
        # estrangeiras (BANCO COMERCIAL PORTUGUES, ZURICH INSURANCE PLC...).
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    CONTRATOS_ES_INDEX: {
        # Os textos de origem vêm em espanhol (acentos e «ñ»). `asciifolding` deixa
        # que uma pesquisa sem acentos («adjudicacion») encontre «adjudicación».
        "analysis": {
            "analyzer": {
                "es_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    CONTRATOS_FR_INDEX: {
        # Textos em francês com acentos («marché», «forfaitaire»). `asciifolding`
        # permite pesquisar sem acentos.
        "analysis": {
            "analyzer": {
                "fr_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ENTITIES_INDEX: {
        "analysis": {
            "tokenizer": {
                # Permite pesquisa incremental: "SONAE" encontra "SONAECOM".
                "entity_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "entity_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "entity_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "entity_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    PEOPLE_INDEX: {
        "analysis": {
            "tokenizer": {
                "entity_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "entity_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "entity_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "entity_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    GLEIF_LEI_INDEX: {
        "analysis": {
            "tokenizer": {
                # Pesquisa incremental no nome da entidade («SIE» → «SIEMENS»).
                "gleif_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 18,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "gleif_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "gleif_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "gleif_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                # Os textos vêm em várias línguas; `asciifolding` deixa que uma
                # pesquisa sem acentos encontre «Câmara»/«Gesellschaft für …».
                "gleif_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    CONTRIBUINTES_INDEX: {
        "analysis": {
            "tokenizer": {
                "entity_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "entity_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "entity_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "entity_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                "contribuinte_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    WORLD_STATE_INDEX: {
        "analysis": {
            "tokenizer": {
                # Pesquisa incremental na designação da entidade («SON» → «SONAE»).
                "world_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "world_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "world_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "world_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                # Os nomes vêm em português e espanhol; sem acentos encontram-se
                # «Camara»/«Adjudicacion».
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    WORLD_HISTORY_INDEX: {
        "analysis": {
            "analyzer": {
                # Igual aos outros índices do mundo: sem acentos encontra «Camara».
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    WORLD_EVENTS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    WORLD_RELATIONS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    INVESTIGATIONS_INDEX: {
        # O relatório e a pergunta são indexados com `world_folding` (sem esta
        # definição, a criação do índice falha com «analyzer has not been configured»).
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    DEVEDORES_INDEX: {
        # Os nomes vêm em maiúsculas e com acentos («JOSÉ»); `world_folding` deixa
        # que uma pesquisa sem acentos («JOSE») os encontre.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    SUBVENCOES_INDEX: {
        # Entidades e beneficiários vêm em maiúsculas e com acentos («MUNICÍPIO
        # DE ALMADA»); `world_folding` deixa que «municipio de almada» os encontre.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    PARTIDOS_INDEX: {
        # Nomes de partidos e o texto extraído dos PDF das contas vêm com acentos
        # («Bloco de Esquerda», «Demonstração de Resultados»).
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    PARTIDOS_REGISTO_INDEX: {
        # Idem: «Alternativa Democrática Nacional», «Nós, Cidadãos!».
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    PARTIDOS_RECOLHAS_INDEX: {
        # As mensagens de erro das recolhas trazem acentos e maiúsculas.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    EU_TAXONOMY_INDEX: {
        # EU Taxonomy Navigator: nomes de atividades, setores e descrições em
        # inglês e português — `world_folding` normaliza acentos e maiúsculas.
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ESG_EMPRESAS_INDEX: {
        # Nomes de empresas e de setores vêm com acentos («Águas de Portugal»).
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ESG_INDICADORES_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ESG_RECOLHAS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    DORA_REGISTO_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    DORA_INCIDENTES_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    DORA_RISCOS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    DORA_CONTEUDO_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    DORA_WORKFLOWS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    DORA_RELATORIOS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    SEC_FILINGS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    SEC_FACTS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    SEC_RECOLHAS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
}

