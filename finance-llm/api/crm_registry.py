"""Registo declarativo da arquitetura de CRM do IQ OS.

Este módulo é **só dados**: descreve

- os **24 módulos** do CRM (contas, contactos, leads, oportunidades, casos,
  atividades, encomendas, contratos, produtos, propostas, previsões, campanhas,
  membros de campanha, atividades e jornadas de marketing, utilizadores, equipas,
  perfis, eventos, auditoria, documentos, conhecimento e IA);
- as **áreas** e os **departamentos** da organização;
- os **perfis de acesso** (roles) e o que cada um pode fazer.

Não importa nada do projeto (nem o Elasticsearch) para poder ser usado tanto
pelo motor do CRM (`api.crm_suite`) como pela definição de índices
(`api.elasticsearch_client`), que gera os mapeamentos a partir daqui.

Regra de ouro: um campo declarado aqui aparece automaticamente na API e na
interface (lista, ficha, filtros). Não há listas duplicadas.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------- tipos
TEXT = "text"
TEXTAREA = "textarea"
EMAIL = "email"
PHONE = "phone"
URL = "url"
SELECT = "select"
MULTI = "multiselect"
REF = "reference"
NUMBER = "number"
INT = "int"
PERCENT = "percent"
BOOL = "bool"
DATE = "date"
DATETIME = "datetime"
JSON = "json"

# Tipos que fazem sentido como filtro de igualdade na lista.
FILTERABLE = (SELECT, MULTI, REF, BOOL)

# Campos de sistema, escritos pelo motor (o cliente nunca os envia).
SCOPE_FIELDS: Tuple[str, ...] = (
    "owner_id",
    "owner_email",
    "org_area",
    "org_department",
    "org_team",
    "assigned_to",
    "created_by",
    "updated_by",
)

SYSTEM_FIELDS: Tuple[str, ...] = ("id", "kind", "created_at", "updated_at", "tags", *SCOPE_FIELDS)


def parse_options(raw: Optional[Any]) -> Tuple[Tuple[str, str], ...]:
    """Converte `"valor:Rótulo,outro"` numa lista de pares (valor, rótulo)."""
    if not raw:
        return ()
    if isinstance(raw, (list, tuple)):
        items: Iterable[Any] = raw
    else:
        items = str(raw).split(",")
    pairs: List[Tuple[str, str]] = []
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((str(item[0]).strip(), str(item[1]).strip()))
            continue
        text = str(item).strip()
        if not text:
            continue
        if ":" in text:
            value, label = text.split(":", 1)
            pairs.append((value.strip(), label.strip()))
        else:
            pairs.append((text, text))
    return tuple(pairs)


@dataclass(frozen=True)
class Field:
    """Um campo de um módulo do CRM."""

    key: str
    label: str
    type: str = TEXT
    options: Tuple[Tuple[str, str], ...] = ()
    required: bool = False
    reference: Optional[str] = None
    column: bool = False
    width: int = 1
    help: str = ""
    search: int = 0
    filter: bool = False
    system: bool = False
    computed: bool = False
    unique: bool = False

    # ------------------------------------------------------------- derivados
    @property
    def numeric(self) -> bool:
        return self.type in (NUMBER, INT, PERCENT)

    @property
    def sortable(self) -> bool:
        return self.type not in (TEXTAREA, JSON)

    @property
    def sort_field(self) -> str:
        # Só os campos de texto indexados com subcampo têm `.keyword`; os
        # restantes (`keyword`, numéricos, datas) ordenam-se pelo próprio nome.
        return f"{self.key}.keyword" if self.type == TEXT else self.key

    @property
    def searchable(self) -> bool:
        return self.search > 0 or self.type in (TEXT, TEXTAREA, EMAIL, PHONE)

    def to_public(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "options": [{"value": value, "label": label} for value, label in self.options],
            "required": self.required,
            "reference": self.reference,
            "column": self.column,
            "width": self.width,
            "help": self.help,
            "filter": self.filter,
            "system": self.system,
            "computed": self.computed,
        }


@dataclass(frozen=True)
class Module:
    """Um módulo (área funcional) do CRM."""

    slug: str
    kind: str
    label: str
    singular: str
    group: str
    icon: str
    description: str
    id_prefix: str
    fields: Tuple[Field, ...]
    label_fields: Tuple[str, ...] = ("name",)
    aliases: Tuple[str, ...] = ()
    defaults: Tuple[Tuple[str, Any], ...] = ()
    sort: Tuple[Tuple[str, str], ...] = ()
    default_sort: Tuple[Tuple[str, str], ...] = ()
    read_only: bool = False
    admin_only: bool = False
    ai: bool = False
    closed_field: Optional[str] = None
    closed_values: Tuple[str, ...] = ()

    # ------------------------------------------------------------- derivados
    @property
    def field_map(self) -> Dict[str, Field]:
        return {item.key: item for item in self.fields}

    @property
    def writable_fields(self) -> Tuple[Field, ...]:
        return tuple(item for item in self.fields if not item.computed and not item.system)

    @property
    def column_fields(self) -> Tuple[Field, ...]:
        return tuple(item for item in self.fields if item.column)

    @property
    def filter_fields(self) -> Tuple[Field, ...]:
        return tuple(item for item in self.fields if item.filter and not item.system)

    def defaults_map(self) -> Dict[str, Any]:
        return {key: value for key, value in self.defaults}

    def label_of(self, document: Dict[str, Any]) -> str:
        for key in self.label_fields:
            value = document.get(key)
            if value:
                return str(value)
        record_id = document.get("id") or ""
        return f"{self.singular} {str(record_id).split('_')[-1][:6]}"

    def to_public(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "kind": self.kind,
            "label": self.label,
            "singular": self.singular,
            "group": self.group,
            "icon": self.icon,
            "description": self.description,
            "fields": [item.to_public() for item in self.fields],
            "label_fields": list(self.label_fields),
            "aliases": list(self.aliases),
            "read_only": self.read_only,
            "admin_only": self.admin_only,
            "ai": self.ai,
        }


# ------------------------------------------------------------------- grupos
GROUPS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "relacao",
        "label": "Relação com o cliente",
        "icon": "Handshake",
        "description": "Contas, contactos, leads, oportunidades, casos, atividades, encomendas e contratos.",
    },
    {
        "id": "comercial",
        "label": "Comercial e catálogo",
        "icon": "Package",
        "description": "Produtos, propostas e previsões de venda.",
    },
    {
        "id": "marketing",
        "label": "Marketing",
        "icon": "Megaphone",
        "description": "Campanhas, públicos, atividades e jornadas de marketing.",
    },
    {
        "id": "administracao",
        "label": "Administração",
        "icon": "ShieldCheck",
        "description": "Utilizadores, equipas e perfis de acesso (área/departamento).",
    },
    {
        "id": "operacao",
        "label": "Operação e auditoria",
        "icon": "Activity",
        "description": "Eventos da agenda e registo de auditoria de todas as alterações.",
    },
    {
        "id": "conhecimento",
        "label": "Conhecimento",
        "icon": "BookOpen",
        "description": "Documentos e base de conhecimento.",
    },
    {
        "id": "inteligencia",
        "label": "Inteligência artificial",
        "icon": "Sparkles",
        "description": "Perceções geradas pelo motor de IA e histórico de interações.",
    },
)

# ------------------------------------------------------------------ módulos
# Abreviaturas de tipos de campo, para o registo ficar legível.
def F(
    key: str,
    label: str,
    type: str = TEXT,
    *,
    options: str = "",
    required: bool = False,
    ref: Optional[str] = None,
    column: bool = False,
    width: int = 1,
    help: str = "",
    search: int = 0,
    filter: Optional[bool] = None,
    computed: bool = False,
    unique: bool = False,
) -> Field:
    """Construtor compacto de campos do registo."""
    is_filter = type in FILTERABLE if filter is None else filter
    return Field(
        key=key,
        label=label,
        type=type,
        options=parse_options(options),
        required=required,
        reference=ref,
        column=column,
        width=width,
        help=help,
        search=search,
        filter=is_filter,
        computed=computed,
        unique=unique,
    )


ACCOUNT_MODULE = Module(
    slug="accounts",
    kind="account",
    label="Contas",
    singular="Conta",
    group="relacao",
    icon="Building2",
    description="Empresas cliente, prospectos e parceiros, ligáveis ao cadastro do EmpresasIQ pelo NIF.",
    id_prefix="acc",
    label_fields=("name",),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("nif", "NIF", column=True, search=2, unique=True),
        F("status", "Estado", SELECT, options="prospect:Prospecto,cliente:Cliente,inativo:Inativo", column=True),
        F("tier", "Segmento", SELECT, options="A:Conta-chave (A),B:Empresa (B),C:PME (C)"),
        F("industry", "Setor de atividade", TEXT, search=2),
        F("sector", "Sector (legado)", search=1),
        F("employees", "Colaboradores", INT),
        F("annual_revenue", "Volume de negócios", NUMBER),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP,BRL:BRL"),
        F("territory", "Território", SELECT, options="norte:Norte,centro:Centro,lisboa:Lisboa e Vale do Tejo,alentejo:Alentejo,algarve:Algarve,ilhas:Ilhas,internacional:Internacional"),
        F("region", "Região", column=True),
        F("city", "Cidade", column=True),
        F("country", "País"),
        F("postal_code", "Código postal"),
        F("address", "Endereço", TEXTAREA),
        F("website", "Site", URL),
        F("email", "Email", EMAIL, search=2),
        F("phone", "Telefone", PHONE),
        F("mobile", "Telemóvel", PHONE),
        F("linkedin", "LinkedIn", URL),
        F("lead_source", "Origem", SELECT, options="web:Web,referencia:Referência,evento:Evento,campanha:Campanha,outbound:Prospeção ativa,parceiro:Parceiro,empresas_iq:EmpresasIQ"),
        F("parent_account_id", "Conta-mãe", REF, ref="accounts"),
        F("rating", "Avaliação", SELECT, options="quente:Quente,morna:Morna,fria:Fria"),
        F("health_score", "Saúde da conta", INT, help="0–100, calculado pelo motor de IA a partir da atividade recente."),
        F("next_step", "Próximo passo"),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("updated_at", "desc"),),
)

CONTACT_MODULE = Module(
    slug="contacts",
    kind="contact",
    label="Contactos",
    singular="Contacto",
    group="relacao",
    icon="Users",
    description="Pessoas de contacto dentro das contas.",
    id_prefix="con",
    label_fields=("name",),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("account_id", "Conta", REF, ref="accounts", required=True, column=True),
        F("title", "Cargo", column=True, search=2),
        F("role", "Papel na decisão", SELECT, options="decisor:Decisor,influenciador:Influenciador,utilizador:Utilizador,tecnico:Técnico,financeiro:Financeiro,outro:Outro", column=True),
        F("department", "Departamento do contacto", TEXT, search=1),
        F("email", "Email", EMAIL, column=True, search=2),
        F("phone", "Telefone", PHONE),
        F("mobile", "Telemóvel", PHONE),
        F("linkedin", "LinkedIn", URL),
        F("is_primary", "Contacto principal", BOOL),
        F("language", "Idioma", SELECT, options="pt:Português,en:Inglês,es:Espanhol,fr:Francês"),
        F("consent_marketing", "Aceita marketing", BOOL),
        F("next_contact_at", "Próximo contacto", DATE),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("name.keyword", "asc"),),
)

LEAD_MODULE = Module(
    slug="leads",
    kind="lead",
    label="Leads",
    singular="Lead",
    group="relacao",
    icon="UserPlus",
    description="Contactos não qualificados, antes de existir conta ou oportunidade.",
    id_prefix="led",
    label_fields=("name", "contact_name"),
    fields=(
        F("name", "Empresa", required=True, column=True, width=2, search=4),
        F("contact_name", "Pessoa", column=True, search=3),
        F("email", "Email", EMAIL, column=True, search=2),
        F("phone", "Telefone", PHONE),
        F("mobile", "Telemóvel", PHONE),
        F("job_title", "Cargo"),
        F("industry", "Setor", search=1),
        F("company_size", "Dimensão", SELECT, options="1-10:1–10,11-50:11–50,51-250:51–250,251-1000:251–1000,1000+:+1000"),
        F("city", "Cidade"),
        F("country", "País"),
        F("source", "Origem", SELECT, options="web:Web,referencia:Referência,evento:Evento,campanha:Campanha,outbound:Prospeção ativa,parceiro:Parceiro,importacao:Importação", column=True),
        F("status", "Estado", SELECT, options="novo:Novo,contactado:Contactado,qualificado:Qualificado,nao-qualificado:Não qualificado,convertido:Convertido,nutrir:Em nutrição", column=True),
        F("rating", "Temperatura", SELECT, options="quente:Quente,morna:Morna,fria:Fria"),
        F("score", "Pontuação", INT, column=True, help="0–100, calculado a partir de engagement e perfil."),
        F("budget", "Orçamento", NUMBER),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("has_authority", "Tem poder de decisão", BOOL),
        F("need", "Necessidade identificada", TEXTAREA),
        F("timeline", "Prazo de compra", SELECT, options="imediato:Imediato,3-meses:Até 3 meses,6-meses:Até 6 meses,12-meses:Até 12 meses,sem-prazo:Sem prazo"),
        F("campaign_id", "Campanha", REF, ref="campaigns"),
        F("converted_account_id", "Conta criada", REF, ref="accounts"),
        F("converted_contact_id", "Contacto criado", REF, ref="contacts"),
        F("converted_opportunity_id", "Oportunidade criada", REF, ref="opportunities"),
        F("loss_reason", "Motivo de não qualificação", TEXT),
        F("next_action_at", "Próxima ação", DATE, column=True),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("score", "desc"), ("updated_at", "desc")),
)

OPPORTUNITY_MODULE = Module(
    slug="opportunities",
    kind="deal",
    label="Oportunidades",
    singular="Oportunidade",
    group="relacao",
    icon="Target",
    description="Pipeline comercial: valor, fase, probabilidade e previsão de fecho.",
    id_prefix="dea",
    aliases=("deals",),
    label_fields=("title",),
    closed_field="stage",
    closed_values=("ganho", "perdido"),
    fields=(
        F("title", "Título", required=True, column=True, width=2, search=4),
        F("account_id", "Conta", REF, ref="accounts", required=True, column=True),
        F("contact_id", "Contacto principal", REF, ref="contacts"),
        F("amount", "Valor", NUMBER, column=True),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP,BRL:BRL"),
        F("stage", "Fase", SELECT, options="prospeccao:Prospeção,qualificacao:Qualificação,proposta:Proposta,negociacao:Negociação,ganho:Ganho,perdido:Perdido", required=True, column=True),
        F("probability", "Probabilidade (%)", PERCENT),
        F("forecast_category", "Categoria de previsão", SELECT, options="pipeline:Pipeline,best-case:Melhor cenário,commit:Comprometido,closed:Fechado"),
        F("expected_close_date", "Fecho previsto", DATE, column=True),
        F("next_step", "Próximo passo"),
        F("next_step_at", "Data do próximo passo", DATE),
        F("deal_type", "Tipo", SELECT, options="novo-negocio:Novo negócio,renovacao:Renovação,upsell:Upsell,cross-sell:Cross-sell"),
        F("source", "Origem", SELECT, options="web:Web,referencia:Referência,evento:Evento,campanha:Campanha,outbound:Prospeção ativa,canal:Canal,empresas_iq:EmpresasIQ"),
        F("competitor", "Concorrente"),
        F("lead_id", "Lead de origem", REF, ref="leads"),
        F("campaign_id", "Campanha", REF, ref="campaigns"),
        F("quote_id", "Proposta", REF, ref="quotes"),
        F("contract_id", "Contrato", REF, ref="contracts"),
        F("loss_reason", "Motivo de perda", TEXT),
        F("closed_at", "Fechada em", DATETIME, computed=True),
        F("weighted_amount", "Valor ponderado", NUMBER, computed=True),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("updated_at", "desc"),),
)

CASE_MODULE = Module(
    slug="cases",
    kind="case",
    label="Casos",
    singular="Caso",
    group="relacao",
    icon="LifeBuoy",
    description="Pedidos de apoio ao cliente, com prioridade, SLA e escalonamento.",
    id_prefix="cas",
    label_fields=("subject",),
    closed_field="status",
    closed_values=("resolvido", "fechado", "cancelado"),
    fields=(
        F("subject", "Assunto", required=True, column=True, width=2, search=4),
        F("case_number", "Número", column=True, unique=True),
        F("account_id", "Conta", REF, ref="accounts", required=True, column=True),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("status", "Estado", SELECT, options="novo:Novo,em-analise:Em análise,aguarda-cliente:Aguarda cliente,aguarda-interno:Aguarda interno,resolvido:Resolvido,fechado:Fechado,cancelado:Cancelado", required=True, column=True),
        F("priority", "Prioridade", SELECT, options="baixa:Baixa,media:Média,alta:Alta,critica:Crítica", column=True),
        F("severity", "Severidade", SELECT, options="1:1 - Cosmético,2:2 - Menor,3:3 - Maior,4:4 - Bloqueante"),
        F("origin", "Canal", SELECT, options="email:Email,telefone:Telefone,web:Web,portal:Portal,chat:Chat,presencial:Presencial"),
        F("case_type", "Tipo", SELECT, options="incidente:Incidente,pergunta:Pedido de informação,problema:Problema,melhoria:Melhoria,reclamacao:Reclamação"),
        F("category", "Categoria", SELECT, options="faturacao:Faturação,tecnico:Técnico,comercial:Comercial,logistica:Logística,servico:Serviço,outro:Outro"),
        F("product_id", "Produto", REF, ref="products"),
        F("contract_id", "Contrato", REF, ref="contracts"),
        F("description", "Descrição", TEXTAREA),
        F("resolution", "Resolução", TEXTAREA),
        F("sla_hours", "SLA (horas)", INT),
        F("opened_at", "Aberto em", DATETIME, column=True),
        F("first_response_at", "Primeira resposta", DATETIME),
        F("closed_at", "Fechado em", DATETIME),
        F("escalated", "Escalado", BOOL),
        F("escalation_reason", "Motivo de escalonamento"),
        F("satisfaction", "Satisfação (1–5)", INT),
        F("notes", "Notas internas", TEXTAREA),
    ),
    default_sort=(("updated_at", "desc"),),
)

ACTIVITY_MODULE = Module(
    slug="activities",
    kind="activity",
    label="Atividades",
    singular="Atividade",
    group="relacao",
    icon="CalendarClock",
    description="Tarefas, chamadas, reuniões, emails e notas da equipa comercial e de apoio.",
    id_prefix="act",
    label_fields=("subject",),
    fields=(
        F("subject", "Assunto", required=True, column=True, width=2, search=4),
        F("type", "Tipo", SELECT, options="chamada:Chamada,reuniao:Reunião,email:Email,tarefa:Tarefa,nota:Nota", required=True, column=True),
        F("status", "Estado", SELECT, options="aberta:Aberta,em-curso:Em curso,concluida:Concluída,cancelada:Cancelada", column=True),
        F("priority", "Prioridade", SELECT, options="baixa:Baixa,media:Média,alta:Alta"),
        F("account_id", "Conta", REF, ref="accounts", column=True),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("opportunity_id", "Oportunidade", REF, ref="opportunities"),
        F("lead_id", "Lead", REF, ref="leads"),
        F("case_id", "Caso", REF, ref="cases"),
        F("order_id", "Encomenda", REF, ref="orders"),
        F("contract_id", "Contrato", REF, ref="contracts"),
        F("due_at", "Prazo", DATETIME, column=True),
        F("done", "Concluída", BOOL),
        F("done_at", "Concluída em", DATETIME, computed=True),
        F("outcome", "Resultado", SELECT, options="conectado:Contactado,sem-resposta:Sem resposta,reagendado:Reagendado,pedido-recebido:Pedido recebido,concluido:Concluído"),
        F("duration_minutes", "Duração (min)", INT),
        F("location", "Local"),
        F("meeting_url", "Ligação da reunião", URL),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("due_at", "asc"),),
)

ORDER_MODULE = Module(
    slug="orders",
    kind="order",
    label="Encomendas",
    singular="Encomenda",
    group="relacao",
    icon="ShoppingCart",
    description="Encomendas de clientes, do rascunho à faturação.",
    id_prefix="ord",
    label_fields=("order_number", "title"),
    closed_field="status",
    closed_values=("faturada", "cancelada"),
    fields=(
        F("order_number", "Número", column=True, unique=True),
        F("title", "Descrição", required=True, width=2, search=3),
        F("account_id", "Conta", REF, ref="accounts", required=True, column=True),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("opportunity_id", "Oportunidade", REF, ref="opportunities"),
        F("quote_id", "Proposta", REF, ref="quotes"),
        F("contract_id", "Contrato", REF, ref="contracts"),
        F("status", "Estado", SELECT, options="rascunho:Rascunho,aguarda-aprovacao:Aguarda aprovação,confirmada:Confirmada,em-producao:Em produção,enviada:Enviada,faturada:Faturada,cancelada:Cancelada", required=True, column=True),
        F("order_date", "Data da encomenda", DATE, column=True),
        F("delivery_date", "Entrega prevista", DATE),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("subtotal", "Subtotal", NUMBER),
        F("discount", "Desconto", PERCENT),
        F("tax_rate", "IVA (%)", PERCENT),
        F("total", "Total", NUMBER, column=True, computed=True),
        F("payment_terms", "Condições de pagamento", SELECT, options="pronto-pagamento:Pronto pagamento,30-dias:30 dias,60-dias:60 dias,90-dias:90 dias,outro:Outro"),
        F("shipping_address", "Morada de entrega", TEXTAREA),
        F("billing_address", "Morada de faturação", TEXTAREA),
        F("carrier", "Transportadora"),
        F("tracking_number", "Referência de envio"),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("order_date", "desc"),),
)

CONTRACT_MODULE = Module(
    slug="contracts",
    kind="contract",
    label="Contratos",
    singular="Contrato",
    group="relacao",
    icon="FileSignature",
    description="Contratos de serviço, licença e manutenção, com renovações e valores.",
    id_prefix="ctr",
    label_fields=("title", "contract_number"),
    closed_field="status",
    closed_values=("terminado", "renovado", "cancelado"),
    fields=(
        F("title", "Título", required=True, column=True, width=2, search=4),
        F("contract_number", "Número", column=True, unique=True),
        F("account_id", "Conta", REF, ref="accounts", required=True, column=True),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("opportunity_id", "Oportunidade", REF, ref="opportunities"),
        F("quote_id", "Proposta", REF, ref="quotes"),
        F("order_id", "Encomenda", REF, ref="orders"),
        F("contract_type", "Tipo", SELECT, options="servico:Serviço,manutencao:Manutenção,licenca:Licença,subscricao:Subscrição,projeto:Projeto", column=True),
        F("status", "Estado", SELECT, options="rascunho:Rascunho,em-negociacao:Em negociação,ativo:Ativo,suspenso:Suspenso,terminado:Terminado,renovado:Renovado,cancelado:Cancelado", required=True, column=True),
        F("start_date", "Início", DATE, column=True),
        F("end_date", "Fim", DATE, column=True),
        F("renewal_date", "Renovação", DATE),
        F("auto_renew", "Renovação automática", BOOL),
        F("notice_days", "Pré-aviso (dias)", INT),
        F("value", "Valor", NUMBER, column=True),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("billing_frequency", "Periodicidade", SELECT, options="mensal:Mensal,trimestral:Trimestral,semestral:Semestral,anual:Anual,unico:Pagamento único"),
        F("payment_terms", "Condições de pagamento", SELECT, options="pronto-pagamento:Pronto pagamento,30-dias:30 dias,60-dias:60 dias,90-dias:90 dias,outro:Outro"),
        F("signed_at", "Assinado em", DATE),
        F("signed_by", "Assinado por"),
        F("document_id", "Documento", REF, ref="documents"),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("end_date", "asc"),),
)

PRODUCT_MODULE = Module(
    slug="products",
    kind="product",
    label="Produtos",
    singular="Produto",
    group="comercial",
    icon="Package",
    description="Catálogo de produtos e serviços, com preços, custos e margens.",
    id_prefix="prd",
    label_fields=("name",),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("sku", "Referência", column=True, search=2, unique=True),
        F("category", "Categoria", SELECT, options="software:Software,servico:Serviço,hardware:Hardware,formacao:Formação,suporte:Suporte,consumivel:Consumível", column=True),
        F("status", "Estado", SELECT, options="ativo:Ativo,em-preparacao:Em preparação,descontinuado:Descontinuado", column=True),
        F("unit", "Unidade", SELECT, options="unidade:Unidade,hora:Hora,dia:Dia,mes:Mês,licenca:Licença,projeto:Projeto"),
        F("price", "Preço", NUMBER, column=True),
        F("cost", "Custo", NUMBER),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("tax_rate", "IVA (%)", PERCENT),
        F("margin", "Margem", NUMBER, computed=True),
        F("margin_pct", "Margem (%)", NUMBER, computed=True),
        F("stock", "Existências", INT),
        F("min_stock", "Existência mínima", INT),
        F("recurring", "Recorrente", BOOL),
        F("supplier", "Fornecedor"),
        F("description", "Descrição", TEXTAREA),
        F("datasheet_url", "Ficha técnica", URL),
    ),
    default_sort=(("name.keyword", "asc"),),
)

QUOTE_MODULE = Module(
    slug="quotes",
    kind="quote",
    label="Propostas",
    singular="Proposta",
    group="comercial",
    icon="FileText",
    description="Propostas comerciais com linhas, descontos e totais calculados.",
    id_prefix="qte",
    label_fields=("title", "quote_number"),
    closed_field="status",
    closed_values=("aceite", "rejeitada", "expirada"),
    fields=(
        F("quote_number", "Número", column=True, unique=True),
        F("title", "Título", required=True, column=True, width=2, search=4),
        F("account_id", "Conta", REF, ref="accounts", required=True, column=True),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("opportunity_id", "Oportunidade", REF, ref="opportunities"),
        F("status", "Estado", SELECT, options="rascunho:Rascunho,em-revisao:Em revisão,enviada:Enviada,aceite:Aceite,rejeitada:Rejeitada,expirada:Expirada", required=True, column=True),
        F("valid_until", "Válida até", DATE, column=True),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("lines", "Linhas", JSON, help="Lista de linhas: descrição, quantidade e preço unitário."),
        F("subtotal", "Subtotal", NUMBER, computed=True),
        F("discount", "Desconto", PERCENT),
        F("tax_rate", "IVA (%)", PERCENT),
        F("total", "Total", NUMBER, column=True, computed=True),
        F("payment_terms", "Condições de pagamento", SELECT, options="pronto-pagamento:Pronto pagamento,30-dias:30 dias,60-dias:60 dias,90-dias:90 dias,outro:Outro"),
        F("terms", "Condições gerais", TEXTAREA),
        F("sent_at", "Enviada em", DATETIME),
        F("accepted_at", "Aceite em", DATETIME),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("updated_at", "desc"),),
)

FORECAST_MODULE = Module(
    slug="forecasts",
    kind="forecast",
    label="Previsões",
    singular="Previsão",
    group="comercial",
    icon="TrendingUp",
    description="Objetivos e previsões de venda por período, equipa e área.",
    id_prefix="fcs",
    label_fields=("name",),
    fields=(
        F("name", "Designação", required=True, column=True, width=2, search=3),
        F("year", "Ano", INT, required=True, column=True),
        F("quarter", "Trimestre", SELECT, options="Q1:1.º trimestre,Q2:2.º trimestre,Q3:3.º trimestre,Q4:4.º trimestre", column=True),
        F("month", "Mês", SELECT, options="01:Janeiro,02:Fevereiro,03:Março,04:Abril,05:Maio,06:Junho,07:Julho,08:Agosto,09:Setembro,10:Outubro,11:Novembro,12:Dezembro"),
        F("scope", "Âmbito", SELECT, options="equipa:Equipa,area:Área,departamento:Departamento,produto:Produto,regiao:Região,conta:Conta", column=True),
        F("scope_ref", "Referência do âmbito"),
        F("target", "Objetivo", NUMBER, column=True),
        F("committed", "Comprometido", NUMBER, column=True),
        F("best_case", "Melhor cenário", NUMBER),
        F("pipeline", "Pipeline", NUMBER),
        F("won", "Ganho", NUMBER, column=True),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("attainment_pct", "Cumprimento (%)", NUMBER, computed=True),
        F("gap", "Desvio para o objetivo", NUMBER, computed=True),
        F("confidence", "Confiança (%)", PERCENT),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("year", "desc"), ("quarter", "asc")),
)

CAMPAIGN_MODULE = Module(
    slug="campaigns",
    kind="campaign",
    label="Campanhas",
    singular="Campanha",
    group="marketing",
    icon="Megaphone",
    description="Campanhas de marketing, orçamento e retorno.",
    id_prefix="cmp",
    label_fields=("name",),
    closed_field="status",
    closed_values=("concluida", "cancelada"),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("code", "Código", column=True, search=2, unique=True),
        F("campaign_type", "Tipo", SELECT, options="email:Email,evento:Evento,webinar:Webinar,social:Redes sociais,telemarketing:Telemarketing,anuncios:Publicidade,conteudo:Conteúdo,parceria:Parceria", column=True),
        F("status", "Estado", SELECT, options="planeada:Planeada,ativa:Ativa,pausada:Pausada,concluida:Concluída,cancelada:Cancelada", required=True, column=True),
        F("objective", "Objetivo", SELECT, options="gerar-leads:Gerar leads,reconhecimento:Reconhecimento,marca:Notoriedade de marca,retencao:Retenção,upsell:Upsell,reativacao:Reativação"),
        F("channel", "Canal", SELECT, options="email:Email,linkedin:LinkedIn,google:Google,meta:Meta,evento:Evento,telefone:Telefone,imprensa:Imprensa"),
        F("start_date", "Início", DATE, column=True),
        F("end_date", "Fim", DATE, column=True),
        F("budget", "Orçamento", NUMBER),
        F("actual_cost", "Custo real", NUMBER),
        F("expected_revenue", "Receita esperada", NUMBER),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("target_size", "Público-alvo", INT),
        F("members_count", "Membros", INT, computed=True),
        F("responses", "Respostas", INT),
        F("leads_generated", "Leads gerados", INT),
        F("won_revenue", "Receita ganha", NUMBER, computed=True),
        F("roi", "ROI (%)", NUMBER, computed=True),
        F("cost_per_lead", "Custo por lead", NUMBER, computed=True),
        F("response_rate", "Taxa de resposta (%)", NUMBER, computed=True),
        F("audience", "Público", TEXTAREA),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("start_date", "desc"),),
)

CAMPAIGN_MEMBER_MODULE = Module(
    slug="campaign-members",
    kind="campaign_member",
    label="Membros de campanha",
    singular="Membro de campanha",
    group="marketing",
    icon="Users2",
    description="Cada pessoa incluída numa campanha e o seu percurso até à conversão.",
    id_prefix="cmb",
    label_fields=("name", "email"),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("campaign_id", "Campanha", REF, ref="campaigns", required=True, column=True),
        F("email", "Email", EMAIL, column=True, search=2),
        F("phone", "Telefone", PHONE),
        F("lead_id", "Lead", REF, ref="leads"),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("account_id", "Conta", REF, ref="accounts"),
        F("status", "Estado", SELECT, options="inscrito:Inscrito,enviado:Enviado,aberto:Aberto,clicado:Clicado,respondido:Respondido,convertido:Convertido,desinscrito:Desinscrito,erro:Erro de envio", required=True, column=True),
        F("channel", "Canal", SELECT, options="email:Email,telefone:Telefone,evento:Evento,social:Redes sociais,anuncio:Publicidade"),
        F("response_type", "Tipo de resposta", SELECT, options="positiva:Positiva,negativa:Negativa,pedido-info:Pedido de informação,desinscricao:Desinscrição"),
        F("score", "Pontuação", INT),
        F("sent_at", "Enviado em", DATETIME),
        F("responded_at", "Respondido em", DATETIME),
        F("converted_at", "Convertido em", DATETIME),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("sent_at", "desc"),),
)

MARKETING_ACTIVITY_MODULE = Module(
    slug="marketing-activities",
    kind="marketing_activity",
    label="Atividades de marketing",
    singular="Atividade de marketing",
    group="marketing",
    icon="Send",
    description="Envios, publicações e ações táticas de uma campanha ou jornada.",
    id_prefix="mac",
    label_fields=("name",),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("campaign_id", "Campanha", REF, ref="campaigns", column=True),
        F("journey_id", "Jornada", REF, ref="marketing-journeys"),
        F("activity_type", "Tipo", SELECT, options="email:Email,sms:SMS,publicacao:Publicação,anuncio:Anúncio,webinar:Webinar,evento:Evento,chamada:Chamada", required=True, column=True),
        F("status", "Estado", SELECT, options="rascunho:Rascunho,agendada:Agendada,em-curso:Em curso,concluida:Concluída,cancelada:Cancelada", column=True),
        F("channel", "Canal", SELECT, options="email:Email,sms:SMS,linkedin:LinkedIn,google:Google,meta:Meta,telefone:Telefone,presencial:Presencial"),
        F("scheduled_at", "Agendada para", DATETIME, column=True),
        F("executed_at", "Executada em", DATETIME),
        F("audience_size", "Público", INT),
        F("sent", "Enviados", INT),
        F("opened", "Abertos", INT),
        F("clicked", "Cliques", INT),
        F("converted", "Conversões", INT),
        F("cost", "Custo", NUMBER),
        F("open_rate", "Taxa de abertura (%)", NUMBER, computed=True),
        F("ctr", "Taxa de cliques (%)", NUMBER, computed=True),
        F("conversion_rate", "Taxa de conversão (%)", NUMBER, computed=True),
        F("content_url", "Conteúdo", URL),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("scheduled_at", "desc"),),
)

MARKETING_JOURNEY_MODULE = Module(
    slug="marketing-journeys",
    kind="marketing_journey",
    label="Jornadas de marketing",
    singular="Jornada",
    group="marketing",
    icon="Route",
    description="Automatismos de nutrição com passos, público e conversões.",
    id_prefix="mjy",
    label_fields=("name",),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("status", "Estado", SELECT, options="rascunho:Rascunho,ativa:Ativa,pausada:Pausada,terminada:Terminada", required=True, column=True),
        F("goal", "Objetivo", TEXT),
        F("audience", "Público", SELECT, options="leads:Leads,clientes:Clientes,prospectos:Prospectos,churn:Risco de churn,parceiros:Parceiros"),
        F("entry_criteria", "Critério de entrada", TEXTAREA),
        F("steps", "Passos", JSON, help="Sequência de passos: tipo, espera e ação."),
        F("start_date", "Início", DATE, column=True),
        F("end_date", "Fim", DATE),
        F("enrolled", "Inscritos", INT, column=True),
        F("completed", "Concluíram", INT),
        F("converted", "Convertidos", INT),
        F("revenue", "Receita gerada", NUMBER),
        F("completion_rate", "Taxa de conclusão (%)", NUMBER, computed=True),
        F("conversion_rate", "Taxa de conversão (%)", NUMBER, computed=True),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("updated_at", "desc"),),
)

CRM_USER_MODULE = Module(
    slug="users",
    kind="crm_user",
    label="Utilizadores",
    singular="Utilizador",
    group="administracao",
    icon="UserCog",
    description="Utilizadores do CRM com o seu perfil de acesso, área, departamento e equipa.",
    id_prefix="usr",
    admin_only=True,
    label_fields=("name", "email"),
    fields=(
        F("name", "Nome", required=True, column=True, search=4),
        F("email", "Email", EMAIL, required=True, column=True, search=3, unique=True),
        F("role", "Perfil", SELECT, column=True, help="Determina módulos, ações e âmbito de visibilidade."),
        F("area", "Área", SELECT, column=True),
        F("department", "Departamento", SELECT, column=True),
        F("team_id", "Equipa", REF, ref="teams", column=True),
        F("job_title", "Função"),
        F("phone", "Telefone", PHONE),
        F("quota", "Objetivo de vendas", NUMBER),
        F("status", "Estado", SELECT, options="ativo:Ativo,suspenso:Suspenso,convidado:Convidado", column=True),
        F("last_login_at", "Último acesso", DATETIME, computed=True),
        F("updated_by", "Alterado por", system=True),
    ),
    default_sort=(("name.keyword", "asc"),),
)

TEAM_MODULE = Module(
    slug="teams",
    kind="crm_team",
    label="Equipas",
    singular="Equipa",
    group="administracao",
    icon="UsersRound",
    description="Equipas comerciais e de apoio, com responsável, área e objetivo.",
    id_prefix="tm",
    admin_only=True,
    label_fields=("name",),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("code", "Código", column=True, search=2, unique=True),
        F("area", "Área", SELECT, column=True),
        F("department", "Departamento", SELECT, column=True),
        F("manager_email", "Responsável", EMAIL, column=True, search=2),
        F("members", "Membros", MULTI, help="Emails dos membros da equipa."),
        F("region", "Região", SELECT),
        F("target", "Objetivo", NUMBER),
        F("currency", "Moeda", SELECT, options="EUR:EUR,USD:USD,GBP:GBP"),
        F("parent_team_id", "Equipa superior", REF, ref="teams"),
        F("status", "Estado", SELECT, options="ativa:Ativa,inativa:Inativa"),
        F("description", "Descrição", TEXTAREA),
    ),
    default_sort=(("name.keyword", "asc"),),
)

ROLE_MODULE = Module(
    slug="roles",
    kind="crm_role",
    label="Perfis de acesso",
    singular="Perfil",
    group="administracao",
    icon="ShieldCheck",
    description="Perfis (roles) com módulos, ações e âmbito de visibilidade por área e departamento.",
    id_prefix="rol",
    admin_only=True,
    label_fields=("label", "key"),
    fields=(
        F("key", "Chave", required=True, column=True, unique=True, help="Identificador usado nas atribuições (ex.: `gestor-comercial`)."),
        F("label", "Designação", required=True, column=True, width=2, search=4),
        F("area", "Área", SELECT, column=True),
        F("department", "Departamento", SELECT, column=True),
        F("scope", "Âmbito de visibilidade", SELECT, options="own:Só os seus registos,team:Equipa,department:Departamento,area:Área,all:Toda a organização", required=True, column=True),
        F("modules", "Módulos", MULTI, column=True, help="Módulos a que o perfil tem acesso."),
        F("actions", "Ações", MULTI, column=True, help="read, create, update, delete, export, manage."),
        F("rank", "Nível hierárquico", INT),
        F("builtin", "Perfil de sistema", BOOL, computed=True),
        F("description", "Descrição", TEXTAREA),
    ),
    default_sort=(("rank", "asc"),),
)

EVENT_MODULE = Module(
    slug="events",
    kind="crm_event",
    label="Eventos",
    singular="Evento",
    group="operacao",
    icon="CalendarDays",
    description="Agenda de eventos: reuniões, webinars, feiras e formações.",
    id_prefix="evt",
    label_fields=("title",),
    fields=(
        F("title", "Título", required=True, column=True, width=2, search=4),
        F("event_type", "Tipo", SELECT, options="reuniao:Reunião,chamada:Chamada,webinar:Webinar,feira:Feira,formacao:Formação,interno:Evento interno", required=True, column=True),
        F("status", "Estado", SELECT, options="planeado:Planeado,confirmado:Confirmado,em-curso:Em curso,realizado:Realizado,cancelado:Cancelado", column=True),
        F("start_at", "Início", DATETIME, required=True, column=True),
        F("end_at", "Fim", DATETIME),
        F("all_day", "Dia inteiro", BOOL),
        F("location", "Local"),
        F("address", "Endereço", TEXTAREA),
        F("meeting_url", "Ligação", URL),
        F("organizer_email", "Organizador", EMAIL, search=2),
        F("attendees", "Participantes", MULTI),
        F("account_id", "Conta", REF, ref="accounts"),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("lead_id", "Lead", REF, ref="leads"),
        F("opportunity_id", "Oportunidade", REF, ref="opportunities"),
        F("campaign_id", "Campanha", REF, ref="campaigns"),
        F("reminder_minutes", "Aviso (min antes)", INT),
        F("duration_minutes", "Duração (min)", INT, computed=True),
        F("description", "Descrição", TEXTAREA),
    ),
    default_sort=(("start_at", "asc"),),
)

AUDIT_MODULE = Module(
    slug="audit",
    kind="crm_audit",
    label="Auditoria",
    singular="Registo de auditoria",
    group="operacao",
    icon="ScrollText",
    description="Registo imutável de todas as alterações ao CRM (quem, quando, o quê e antes/depois).",
    id_prefix="aud",
    read_only=True,
    admin_only=True,
    label_fields=("summary", "record_label"),
    fields=(
        F("at", "Data", DATETIME, column=True),
        F("actor_email", "Utilizador", EMAIL, column=True, search=3),
        F("action", "Ação", SELECT, options="create:Criação,update:Alteração,delete:Eliminação,assign:Atribuição,export:Exportação,ai:Inteligência artificial,login:Sessão", column=True),
        F("module", "Módulo", SELECT, column=True),
        F("record_id", "Registo"),
        F("record_label", "Registo", column=True, search=2),
        F("summary", "Resumo", column=True, search=3),
        F("changes", "Campos alterados", MULTI),
        F("area", "Área", SELECT),
        F("department", "Departamento", SELECT),
        F("ip", "Endereço IP"),
        F("user_agent", "Cliente"),
        F("before", "Antes", JSON),
        F("after", "Depois", JSON),
    ),
    default_sort=(("at", "desc"),),
)

DOCUMENT_MODULE = Module(
    slug="documents",
    kind="crm_document",
    label="Documentos",
    singular="Documento",
    group="conhecimento",
    icon="FolderOpen",
    description="Documentos ligados a contas, oportunidades, propostas, contratos e encomendas.",
    id_prefix="doc",
    label_fields=("name",),
    fields=(
        F("name", "Nome", required=True, column=True, width=2, search=4),
        F("document_type", "Tipo", SELECT, options="proposta:Proposta,contrato:Contrato,fatura:Fatura,relatorio:Relatório,apresentacao:Apresentação,ata:Ata,outro:Outro", column=True),
        F("status", "Estado", SELECT, options="rascunho:Rascunho,em-revisao:Em revisão,aprovado:Aprovado,assinado:Assinado,arquivado:Arquivado", column=True),
        F("account_id", "Conta", REF, ref="accounts", column=True),
        F("contact_id", "Contacto", REF, ref="contacts"),
        F("opportunity_id", "Oportunidade", REF, ref="opportunities"),
        F("quote_id", "Proposta", REF, ref="quotes"),
        F("contract_id", "Contrato", REF, ref="contracts"),
        F("order_id", "Encomenda", REF, ref="orders"),
        F("case_id", "Caso", REF, ref="cases"),
        F("url", "Ligação", URL, column=True),
        F("mime", "Formato"),
        F("size_bytes", "Tamanho (bytes)", INT),
        F("version", "Versão"),
        F("valid_from", "Válido de", DATE),
        F("valid_until", "Válido até", DATE),
        F("signed", "Assinado", BOOL),
        F("notes", "Notas", TEXTAREA),
    ),
    default_sort=(("updated_at", "desc"),),
)

KNOWLEDGE_MODULE = Module(
    slug="knowledge",
    kind="crm_knowledge",
    label="Base de conhecimento",
    singular="Artigo",
    group="conhecimento",
    icon="BookOpen",
    description="Artigos que apoiam a equipa: procedimentos, FAQs, políticas e problemas conhecidos.",
    id_prefix="kno",
    label_fields=("title",),
    fields=(
        F("title", "Título", required=True, column=True, width=2, search=4),
        F("category", "Categoria", SELECT, options="procedimento:Procedimento,faq:FAQ,problema-conhecido:Problema conhecido,politica:Política,preco:Preço,tecnico:Técnico,comercial:Comercial", required=True, column=True),
        F("status", "Estado", SELECT, options="rascunho:Rascunho,publicado:Publicado,obsoleto:Obsoleto,arquivado:Arquivado", column=True),
        F("language", "Idioma", SELECT, options="pt:Português,en:Inglês,es:Espanhol"),
        F("summary", "Resumo", TEXT, column=True, search=3),
        F("body", "Conteúdo", TEXTAREA, search=2),
        F("product_id", "Produto", REF, ref="products"),
        F("case_id", "Caso de origem", REF, ref="cases"),
        F("author_email", "Autor", EMAIL, search=2),
        F("published_at", "Publicado em", DATE, column=True),
        F("views", "Consultas", INT),
        F("helpful_count", "Votos úteis", INT),
        F("url", "Ligação", URL),
        F("tags", "Etiquetas", MULTI),
    ),
    default_sort=(("published_at", "desc"),),
)

AI_INSIGHT_MODULE = Module(
    slug="ai-insights",
    kind="ai_insight",
    label="Perceções de IA",
    singular="Perceção",
    group="inteligencia",
    icon="Sparkles",
    description="Riscos, oportunidades e recomendações detetados pelo motor de IA sobre os dados do CRM.",
    id_prefix="ain",
    ai=True,
    closed_field="status",
    closed_values=("aplicado", "ignorado"),
    label_fields=("title",),
    fields=(
        F("title", "Título", required=True, column=True, width=2, search=4),
        F("insight_type", "Tipo", SELECT, options="risco:Risco,oportunidade:Oportunidade,previsao:Previsão,anomalia:Anomalia,recomendacao:Recomendação", required=True, column=True),
        F("severity", "Severidade", SELECT, options="info:Informação,baixa:Baixa,media:Média,alta:Alta,critica:Crítica", column=True),
        F("status", "Estado", SELECT, options="novo:Novo,em-analise:Em análise,aplicado:Aplicado,ignorado:Ignorado", required=True, column=True),
        F("module", "Módulo afetado", SELECT, column=True),
        F("record_id", "Registo"),
        F("record_label", "Referência", column=True, search=2),
        F("account_id", "Conta", REF, ref="accounts"),
        F("metric", "Indicador"),
        F("value", "Valor", NUMBER),
        F("baseline", "Referência", NUMBER),
        F("delta_pct", "Variação (%)", PERCENT),
        F("confidence", "Confiança (%)", PERCENT),
        F("summary", "Análise", TEXTAREA),
        F("recommendation", "Recomendação", TEXTAREA),
        F("evidence", "Evidência", JSON, help="Dados concretos que sustentam a perceção."),
        F("model", "Modelo"),
        F("generated_at", "Gerada em", DATETIME, column=True),
        F("applied_by", "Aplicada por"),
        F("applied_at", "Aplicada em", DATETIME),
        F("signature", "Assinatura", system=True),
    ),
    default_sort=(("generated_at", "desc"),),
)

AI_INTERACTION_MODULE = Module(
    slug="ai-interactions",
    kind="ai_interaction",
    label="Interações de IA",
    singular="Interação",
    group="inteligencia",
    icon="MessagesSquare",
    description="Histórico de perguntas e respostas do assistente de CRM, com contexto e modelo usado.",
    id_prefix="aix",
    ai=True,
    label_fields=("question",),
    fields=(
        F("question", "Pergunta", TEXTAREA, required=True, column=True, width=2, search=4),
        F("answer", "Resposta", TEXTAREA, search=2),
        F("intent", "Intenção", SELECT, options="consulta:Consulta,analise:Análise,recomendacao:Recomendação,accao:Ação,previsao:Previsão", column=True),
        F("status", "Estado", SELECT, options="ok:Concluída,sem-modelo:Sem modelo,erro:Erro", column=True),
        F("module", "Módulo", SELECT, column=True),
        F("record_id", "Registo"),
        F("account_id", "Conta", REF, ref="accounts"),
        F("provider", "Fornecedor"),
        F("model", "Modelo"),
        F("context", "Contexto", JSON),
        F("confidence", "Confiança (%)", PERCENT),
        F("latency_ms", "Latência (ms)", INT),
        F("tokens_prompt", "Tokens de entrada", INT),
        F("tokens_completion", "Tokens de saída", INT),
        F("feedback", "Avaliação", SELECT, options="util:Útil,nao-util:Não útil,nenhum:Sem avaliação", column=True),
        F("feedback_note", "Comentário"),
        F("asked_at", "Perguntado em", DATETIME, column=True),
    ),
    default_sort=(("asked_at", "desc"),),
)

MODULES: Tuple[Module, ...] = (
    ACCOUNT_MODULE,
    CONTACT_MODULE,
    LEAD_MODULE,
    OPPORTUNITY_MODULE,
    CASE_MODULE,
    ACTIVITY_MODULE,
    ORDER_MODULE,
    CONTRACT_MODULE,
    PRODUCT_MODULE,
    QUOTE_MODULE,
    FORECAST_MODULE,
    CAMPAIGN_MODULE,
    CAMPAIGN_MEMBER_MODULE,
    MARKETING_ACTIVITY_MODULE,
    MARKETING_JOURNEY_MODULE,
    CRM_USER_MODULE,
    TEAM_MODULE,
    ROLE_MODULE,
    EVENT_MODULE,
    AUDIT_MODULE,
    DOCUMENT_MODULE,
    KNOWLEDGE_MODULE,
    AI_INSIGHT_MODULE,
    AI_INTERACTION_MODULE,
)

MODULE_BY_SLUG: Dict[str, Module] = {module.slug: module for module in MODULES}


def _alias_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    for module in MODULES:
        index[module.slug] = module.slug
        for alias in module.aliases:
            index[alias] = module.slug
    return index


ALIAS_BY_SLUG: Dict[str, str] = _alias_index()
KIND_BY_SLUG: Dict[str, str] = {module.slug: module.kind for module in MODULES}
SLUG_BY_KIND: Dict[str, str] = {module.kind: module.slug for module in MODULES}

# Módulos cujos registos vivem no índice de RBAC (e não em `finance_crm`).
RBAC_SLUGS: Tuple[str, ...] = ("users", "teams", "roles", "audit")
# Módulos só de leitura (sem create/update/delete).
READ_ONLY_SLUGS: Tuple[str, ...] = ("audit",)


def resolve_module(slug: str) -> Optional[Module]:
    """Devolve o módulo a partir do slug ou de um dos seus alias."""
    if not slug:
        return None
    canonical = ALIAS_BY_SLUG.get(str(slug).strip().lower())
    return MODULE_BY_SLUG.get(canonical) if canonical else None


# ------------------------------------------------------- áreas e departamentos
AREAS: Tuple[Dict[str, str], ...] = (
    {"id": "comercial", "label": "Comercial", "description": "Vendas, pré-venda e gestão de contas."},
    {"id": "marketing", "label": "Marketing", "description": "Campanhas, conteúdo e geração de procura."},
    {"id": "servico", "label": "Serviço ao cliente", "description": "Apoio, casos e sucesso do cliente."},
    {"id": "operacoes", "label": "Operações", "description": "Encomendas, contratos e logística."},
    {"id": "financeiro", "label": "Financeiro", "description": "Faturação, cobrança e previsão."},
    {"id": "dados", "label": "Dados e inteligência", "description": "Análise, qualidade de dados e IA."},
    {"id": "administracao", "label": "Administração", "description": "Direção, TI e auditoria."},
)

DEPARTMENTS: Tuple[Dict[str, str], ...] = (
    {"id": "direcao", "label": "Direção", "area": "administracao"},
    {"id": "vendas", "label": "Vendas", "area": "comercial"},
    {"id": "pre-venda", "label": "Pré-venda", "area": "comercial"},
    {"id": "marketing", "label": "Marketing", "area": "marketing"},
    {"id": "apoio-cliente", "label": "Apoio ao cliente", "area": "servico"},
    {"id": "operacoes", "label": "Operações", "area": "operacoes"},
    {"id": "financeiro", "label": "Financeiro", "area": "financeiro"},
    {"id": "dados", "label": "Dados", "area": "dados"},
    {"id": "tecnologia", "label": "Tecnologia", "area": "administracao"},
)

AREA_IDS: Tuple[str, ...] = tuple(item["id"] for item in AREAS)
DEPARTMENT_IDS: Tuple[str, ...] = tuple(item["id"] for item in DEPARTMENTS)

# ------------------------------------------------------------------- ações
ACTIONS: Tuple[Dict[str, str], ...] = (
    {"id": "read", "label": "Consultar"},
    {"id": "create", "label": "Criar"},
    {"id": "update", "label": "Alterar"},
    {"id": "delete", "label": "Eliminar"},
    {"id": "export", "label": "Exportar"},
    {"id": "manage", "label": "Gerir administração"},
)

ACTION_IDS: Tuple[str, ...] = tuple(item["id"] for item in ACTIONS)

SCOPES: Tuple[Dict[str, str], ...] = (
    {"id": "own", "label": "Só os seus registos"},
    {"id": "team", "label": "Toda a equipa"},
    {"id": "department", "label": "Todo o departamento"},
    {"id": "area", "label": "Toda a área"},
    {"id": "all", "label": "Toda a organização"},
)

ALL_MODULES: Tuple[str, ...] = tuple(module.slug for module in MODULES)
ALL_MODULES_NO_ADMIN: Tuple[str, ...] = tuple(
    module.slug for module in MODULES if module.group not in ("administracao",)
)

# ------------------------------------------------------------------- perfis
RELACAO = (
    "accounts",
    "contacts",
    "leads",
    "opportunities",
    "cases",
    "activities",
    "orders",
    "contracts",
)
CATALOGO = ("products", "quotes", "forecasts", "documents", "knowledge")
MARKETING_SET = (
    "campaigns",
    "campaign-members",
    "marketing-activities",
    "marketing-journeys",
    "leads",
    "accounts",
    "contacts",
    "activities",
    "events",
    "documents",
    "knowledge",
    "ai-insights",
    "ai-interactions",
)
SERVICO_SET = (
    "cases",
    "activities",
    "events",
    "accounts",
    "contacts",
    "contracts",
    "products",
    "knowledge",
    "documents",
    "ai-insights",
    "ai-interactions",
)
OPERACOES_SET = (
    "orders",
    "contracts",
    "products",
    "events",
    "documents",
    "knowledge",
    "activities",
    "accounts",
)
FINANCEIRO_SET = (
    "contracts",
    "orders",
    "quotes",
    "forecasts",
    "documents",
    "accounts",
    "products",
    "ai-insights",
)


@dataclass(frozen=True)
class Role:
    """Um perfil de acesso: área, departamento, âmbito, módulos e ações."""

    key: str
    label: str
    area: str
    department: str
    scope: str
    modules: Tuple[str, ...]
    actions: Tuple[str, ...]
    rank: int
    description: str = ""

    @property
    def builtin(self) -> bool:
        return True

    def module_list(self) -> Tuple[str, ...]:
        return ALL_MODULES if "*" in self.modules else tuple(
            slug for slug in self.modules if slug in MODULE_BY_SLUG
        )

    def action_list(self) -> Tuple[str, ...]:
        return ACTION_IDS if "*" in self.actions else tuple(
            action for action in self.actions if action in ACTION_IDS
        )

    def to_public(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "area": self.area,
            "department": self.department,
            "scope": self.scope,
            "modules": list(self.module_list()),
            "actions": list(self.action_list()),
            "rank": self.rank,
            "builtin": True,
            "description": self.description,
        }


ROLES: Tuple[Role, ...] = (
    Role(
        key="admin",
        label="Administrador",
        area="administracao",
        department="tecnologia",
        scope="all",
        modules=("*",),
        actions=("*",),
        rank=0,
        description="Acesso total: todos os módulos, todas as ações, toda a organização e a administração do CRM.",
    ),
    Role(
        key="direcao",
        label="Direção",
        area="administracao",
        department="direcao",
        scope="all",
        modules=ALL_MODULES_NO_ADMIN,
        actions=("read", "export", "manage"),
        rank=1,
        description="Visão global de todos os módulos operacionais, com foco em indicadores e previsões.",
    ),
    Role(
        key="gestor-comercial",
        label="Gestor comercial",
        area="comercial",
        department="vendas",
        scope="department",
        modules=(
            *RELACAO,
            *CATALOGO,
            "campaigns",
            "ai-insights",
            "ai-interactions",
            "teams",
            "users",
        ),
        actions=("read", "create", "update", "delete", "export", "manage"),
        rank=2,
        description="Gere o pipeline e a equipa do departamento de vendas.",
    ),
    Role(
        key="comercial",
        label="Comercial",
        area="comercial",
        department="vendas",
        scope="own",
        modules=(
            "accounts",
            "contacts",
            "leads",
            "opportunities",
            "activities",
            "quotes",
            "orders",
            "contracts",
            "products",
            "events",
            "documents",
            "knowledge",
            "cases",
            "ai-insights",
            "ai-interactions",
        ),
        actions=("read", "create", "update", "export"),
        rank=3,
        description="Trabalha a sua própria carteira: contas, contactos, leads, oportunidades e propostas.",
    ),
    Role(
        key="pre-venda",
        label="Pré-venda",
        area="comercial",
        department="pre-venda",
        scope="own",
        modules=(
            "accounts",
            "contacts",
            "opportunities",
            "quotes",
            "products",
            "activities",
            "documents",
            "knowledge",
            "ai-insights",
            "ai-interactions",
        ),
        actions=("read", "create", "update", "export"),
        rank=3,
        description="Prepara propostas técnicas e comerciais para as oportunidades da equipa.",
    ),
    Role(
        key="gestor-marketing",
        label="Gestor de marketing",
        area="marketing",
        department="marketing",
        scope="department",
        modules=(*MARKETING_SET, "teams", "users"),
        actions=("read", "create", "update", "delete", "export", "manage"),
        rank=2,
        description="Planeia e mede campanhas e jornadas de marketing.",
    ),
    Role(
        key="marketing",
        label="Marketing",
        area="marketing",
        department="marketing",
        scope="own",
        modules=MARKETING_SET,
        actions=("read", "create", "update", "export"),
        rank=4,
        description="Executa campanhas, atividades e jornadas; gere públicos e membros.",
    ),
    Role(
        key="gestor-servico",
        label="Gestor de apoio ao cliente",
        area="servico",
        department="apoio-cliente",
        scope="department",
        modules=(*SERVICO_SET, "orders", "teams", "users"),
        actions=("read", "create", "update", "delete", "export", "manage"),
        rank=2,
        description="Gere a fila de casos, SLAs e a equipa de apoio.",
    ),
    Role(
        key="agente-servico",
        label="Agente de apoio",
        area="servico",
        department="apoio-cliente",
        scope="own",
        modules=(
            "cases",
            "activities",
            "events",
            "accounts",
            "contacts",
            "knowledge",
            "documents",
            "ai-insights",
            "ai-interactions",
        ),
        actions=("read", "create", "update"),
        rank=4,
        description="Resolve casos e mantém o conhecimento atualizado.",
    ),
    Role(
        key="financeiro",
        label="Financeiro",
        area="financeiro",
        department="financeiro",
        scope="all",
        modules=FINANCEIRO_SET,
        actions=("read", "update", "export"),
        rank=2,
        description="Acompanha contratos, encomendas, propostas e previsões em toda a organização.",
    ),
    Role(
        key="operacoes",
        label="Operações",
        area="operacoes",
        department="operacoes",
        scope="department",
        modules=OPERACOES_SET,
        actions=("read", "create", "update", "export"),
        rank=3,
        description="Garante a execução de encomendas e contratos do departamento.",
    ),
    Role(
        key="analista-dados",
        label="Analista de dados",
        area="dados",
        department="dados",
        scope="all",
        modules=(*ALL_MODULES_NO_ADMIN,),
        actions=("read", "export", "create"),
        rank=2,
        description="Lê tudo, exporta e alimenta o motor de IA com perceções e interações.",
    ),
    Role(
        key="auditor",
        label="Auditor",
        area="administracao",
        department="direcao",
        scope="all",
        modules=(
            "audit",
            "accounts",
            "opportunities",
            "contracts",
            "orders",
            "quotes",
            "documents",
            "ai-insights",
            "ai-interactions",
        ),
        actions=("read", "export"),
        rank=2,
        description="Acesso de leitura a registos e ao registo de auditoria, sem poder alterar dados.",
    ),
    Role(
        key="convidado",
        label="Convidado",
        area="comercial",
        department="vendas",
        scope="own",
        modules=("accounts", "contacts", "documents", "ai-insights"),
        actions=("read",),
        rank=5,
        description="Leitura limitada aos seus próprios registos, para demonstrações e estágios.",
    ),
)

ROLE_BY_KEY: Dict[str, Role] = {role.key: role for role in ROLES}
DEFAULT_ROLE_KEY = "comercial"


def role_module_options() -> Tuple[Tuple[str, str], ...]:
    """Pares (slug, etiqueta) de todos os módulos, para o campo `modules`."""
    return tuple((module.slug, module.label) for module in MODULES)


def role_action_options() -> Tuple[Tuple[str, str], ...]:
    return tuple((item["id"], item["label"]) for item in ACTIONS)


def role_area_options() -> Tuple[Tuple[str, str], ...]:
    return tuple((item["id"], item["label"]) for item in AREAS)


def role_department_options() -> Tuple[Tuple[str, str], ...]:
    return tuple((item["id"], item["label"]) for item in DEPARTMENTS)


def role_scope_options() -> Tuple[Tuple[str, str], ...]:
    return tuple((item["id"], item["label"]) for item in SCOPES)


def _fill_dynamic_options(module: Module) -> Module:
    """Preenche as opções dos campos que dependem do registo (perfis, áreas...)."""
    overrides: Dict[str, Tuple[Tuple[str, str], ...]] = {
        "role": tuple((role.key, role.label) for role in ROLES),
        "area": role_area_options(),
        "department": role_department_options(),
        "scope": role_scope_options(),
        "modules": role_module_options(),
        "actions": role_action_options(),
        "module": tuple((module.slug, module.label) for module in MODULES),
    }
    fields: List[Field] = []
    changed = False
    for item in module.fields:
        replacement = overrides.get(item.key)
        if replacement and not item.options and item.type in (SELECT, MULTI):
            fields.append(
                Field(
                    key=item.key,
                    label=item.label,
                    type=item.type,
                    options=replacement,
                    required=item.required,
                    reference=item.reference,
                    column=item.column,
                    width=item.width,
                    help=item.help,
                    search=item.search,
                    filter=item.filter,
                    system=item.system,
                    computed=item.computed,
                    unique=item.unique,
                )
            )
            changed = True
        else:
            fields.append(item)
    if not changed:
        return module
    return Module(
        slug=module.slug,
        kind=module.kind,
        label=module.label,
        singular=module.singular,
        group=module.group,
        icon=module.icon,
        description=module.description,
        id_prefix=module.id_prefix,
        fields=tuple(fields),
        label_fields=module.label_fields,
        aliases=module.aliases,
        defaults=module.defaults,
        sort=module.sort,
        default_sort=module.default_sort,
        read_only=module.read_only,
        admin_only=module.admin_only,
        ai=module.ai,
        closed_field=module.closed_field,
        closed_values=module.closed_values,
    )


MODULES = tuple(_fill_dynamic_options(module) for module in MODULES)
MODULE_BY_SLUG = {module.slug: module for module in MODULES}


# --------------------------------------------------- mapeamentos do Elasticsearch
_ES_TYPES: Dict[str, Dict[str, Any]] = {
    TEXT: {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
    TEXTAREA: {"type": "text"},
    EMAIL: {"type": "keyword"},
    PHONE: {"type": "keyword", "ignore_above": 64},
    URL: {"type": "keyword", "ignore_above": 1024},
    SELECT: {"type": "keyword"},
    MULTI: {"type": "keyword"},
    REF: {"type": "keyword"},
    NUMBER: {"type": "float"},
    INT: {"type": "integer"},
    PERCENT: {"type": "float"},
    BOOL: {"type": "boolean"},
    DATE: {"type": "date"},
    DATETIME: {"type": "date"},
    JSON: {"type": "object", "enabled": False},
}

CORE_FIELDS: Dict[str, Dict[str, Any]] = {
    "kind": {"type": "keyword"},
    "id": {"type": "keyword"},
    "owner_id": {"type": "keyword"},
    "owner_email": {"type": "keyword"},
    "org_area": {"type": "keyword"},
    "org_department": {"type": "keyword"},
    "org_team": {"type": "keyword"},
    "assigned_to": {"type": "keyword"},
    "created_by": {"type": "keyword"},
    "updated_by": {"type": "keyword"},
    "tags": {"type": "keyword"},
    "created_at": {"type": "date"},
    "updated_at": {"type": "date"},
}


def es_properties() -> Dict[str, Any]:
    """Propriedades do Elasticsearch para todos os módulos do CRM.

    Campos com o mesmo nome em módulos diferentes têm de ter o mesmo tipo (o
    índice é partilhado); em caso de divergência ganha o primeiro.
    """
    properties: Dict[str, Any] = dict(CORE_FIELDS)
    for module in MODULES:
        if module.slug in RBAC_SLUGS:
            continue
        for item in module.fields:
            if item.key in properties or item.system:
                continue
            mapping = _ES_TYPES.get(item.type)
            if mapping:
                properties[item.key] = dict(mapping)
    return properties


def es_extra_properties(existing: Dict[str, Any]) -> Dict[str, Any]:
    """Só as propriedades que ainda não existem no índice (evita conflitos)."""
    return {key: value for key, value in es_properties().items() if key not in (existing or {})}
