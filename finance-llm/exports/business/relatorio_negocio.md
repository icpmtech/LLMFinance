# IQ OS — leitura de negócio a partir dos dados da própria plataforma

_Gerado a 2026-10-09T14:18:29Z a partir de `http://127.0.0.1:8000`. Todos os números vêm dos endpoints indicados em `fonte`._

## 1. O que existe hoje
- **37,967,981 documentos** em 43 índices com dados (31.38 GB).
- **5,077,363 contratos** e **198.8 mil M€** agregados.
- **214,123 entidades** (52.99% com NIF), 12,090 adjudicantes e 205,528 adjudicatários.
- **859 rotas de API** em 39 domínios funcionais.
- Dados de apoio: 212,134 registos LEI, 137,411 documentos de pessoas, 937 publicações societárias, 69 marcas.

## 2. Onde está o dinheiro já instrumentado
- 4 pacotes de relatório com preços de **0.0 € a 130.0 €** (média 43.0 €).
- Loja: “Loja IQ OS” com 3 tipos de produto.
- Pagamento por MB Way/Ifthenpay com backoffice de pedidos e notificações — ou seja, há operação a jusante.

## 3. Pontos fortes (com prova)
1. Ativo de dados proprietário e agregado por NIF — difícil de replicar por um concorrente novo.
2. Junção única: contratos ↔ entidades ↔ pessoas ↔ societário ↔ risco ↔ marcas/LEI.
3. IA com rasto de evidência (citação, validação anti-alucinação, audit trail) — requisito em contratação pública.
4. Várias portas de entrada comerciais: subscrição, API, relatórios pagos, loja, CRM, iframes.
5. Multi-país desde a arquitetura (PT/ES/FR) e custo marginal baixo por utilizador adicional.

## 4. Pontos fracos e riscos
1. **Concentração geográfica**: 91.99% das entidades são portuguesas; Espanha (4,389) e França (1,239) são amostras.
2. **Cobertura societária de 0.02%** das entidades com NIF — sem esta peça, os relatórios financeiros prometidos no catálogo não podem ser produzidos a escala.
3. **47.01% das entidades sem NIF** não entram no grafo (chave de junção).
4. Dependência de fontes públicas e de captcha pago (2captcha) no elo mais valioso (societário).
5. Sem telemetria de produto nem planos de subscrição — não se mede retenção, uso nem ARPU.
6. Amplitude (≈40 módulos) contra equipa pequena: risco de dispersão, manutenção e dificuldade de mensagem.
7. RGPD: 137 mil documentos de pessoas singulares exigem base legal, retenção e processo de titulares.

## 5. Pontos de melhoria, por ordem de retorno
1. **Empacotar preço**: 3 planos (Explorador/Profissional/Empresa) + API, e contagem de uso por conta.
2. **Telemetria mínima**: utilizadores ativos, pesquisas, relatórios, conversão e custo por pedido.
3. **Fechar a cobertura societária** por janelas de datas (≈721 janelas cobrem o país) em vez de por NIF.
4. **Resolver os 100.656 registos sem NIF** (deduplicação por nome/morada) para alargar o grafo.
5. **Profundar Espanha/França** com importações por ano e métricas de cobertura visíveis no produto.
6. **Custos de IA sob controlo**: roteamento por modelo, cache de respostas e orçamento por conta.
7. **Prontidão enterprise**: SSO, isolamento por cliente, SLA, registo de auditoria exportável.
8. **Prova social**: 3 casos de uso publicados (fornecedor do Estado, auditoria, risco de contraparte).

## 6. Scorecard

| Dimensão | Nota (0-5) | Justificação |
| --- | --- | --- |
| Ativo de dados | 5.0 | 37,967,981 documentos em 43 índices (31.38 GB) — inclui 15,5 M de contratos. |
| Amplitude do produto | 5.0 | 859 rotas de API em 39 domínios funcionais. |
| Profundidade de IA | 4.5 | Investigador com evidências citadas, ontologia com validação anti-alucinação, agentes LangGraph, world model com simulação e relatório de evidência. |
| Monetização pronta | 3.5 | 4 pacotes com preço (0.0–130.0 €), loja e CRM integrados; falta plano/assinatura e contagem de uso. |
| Mercado endereçável | 3.3 | Portugal concentra 91.99% das entidades (nota = 50% de cadastro com NIF, hoje 52.99%, + 50% de diversificação fora de PT, hoje 8.01%). Espanha 4,389 e França 1,239 são amostras. |
| Consistência dos dados | 2.0 | Apenas 52.99% das entidades têm NIF e a cobertura societária é 0.02% das entidades com NIF — é o elo mais fraco da cadeia de valor. |
| Compliance e licenciamento | 3.0 | Fontes são dados públicos, mas a recolha societária depende de captcha pago e a pesquisa social está desligada (0 canais ativos) — risco gerido por omissão, não por contrato. |
| Prontidão comercial | 2.5 | Sem telemetria de produto (não há contagem de utilizadores ativos, retenção ou ARPU em endpoint próprio) e sem planos de subscrição — a operação comercial é manual. |

**Nota global: 3.6 / 5.**

## 7. O que não foi possível medir
- Endpoints sem sessão/sem dados: relatorios_admin, relatorios_definicoes
- Não existe (ainda) telemetria de utilização: qualquer afirmção sobre clientes, retenção ou receita tem de ficar marcada como hipótese, não como medição.

## 8. Pressupostos de mercado (a confirmar, não são medições)
- TAM: universo de fornecedores do Estado no dataset (adjudicatários) × preço médio de subscrição anual.
- SAM: empresas com contratos acima de um valor mínimo, em PT e ES.
- SOM: 0,5% / 2% / 5% do SAM no ano 1/2/3 — depende de força de vendas, não do produto.
- Impacto: redução de horas de pesquisa por processo, deteção precoce de fornecedores em risco e mais concorrência nos concursos (menos assimetria de informação).