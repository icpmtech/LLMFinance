"""Taxonomia e catálogo de fontes do módulo **ESG**.

O módulo responde a três perguntas, com um número que se pode explicar:

1. **Onde está esta empresa nas vertentes E, S e G?** — score de 0 a 100 por
   pilar e global, construído com indicadores calculados a partir de dados
   abertos e com os indicadores que a empresa publica nos seus relatórios de
   sustentabilidade.
2. **Como evoluiu, e como se compara?** — série de três anos e posição relativa
   face ao setor e às empresas de dimensão equiparável.
3. **Como está a carteira de fornecedores?** — distribuição dos fornecedores
   por score ESG e pelos sinais que os sustentam.

Nada aqui certifica uma empresa. Os indicadores de contratação pública são
**proxies** (por exemplo, a fatia de contratos com critérios ecológicos não é a
pegada de carbono da empresa); os indicadores dos relatórios são declarados
pela própria empresa e a fonte é sempre mostrada. O cartão do modelo
(`cartao_modelo`) e os avisos acompanham todos os números.

Este ficheiro é só **dados e taxonomia** (pesos, limiares, catálogo de
indicadores, fontes, CPV e CAE). O cálculo vive em `esg_service.py`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: Versão do cartão do modelo. Sobe quando pesos, limiares ou indicadores mudam:
#: dois números de datas diferentes não devem ser comparados como se usassem o
#: mesmo modelo.
MODELO_VERSAO = "esg-1.1.0"

#: Aviso obrigatório em todos os números.
AVISO_GERAL = (
    "O score ESG do IQ OS é uma **leitura de dados abertos e de indicadores declarados**, não uma "
    "certificação nem uma auditoria. Os indicadores de contratação pública são proxies (volume e "
    "valor de contratos, CPV, concorrência, prazos e critérios ecológicos) e os indicadores dos "
    "relatórios são da responsabilidade de quem os publica. A cobertura e a confiança dizem quanta "
    "informação entrou: um score com cobertura baixa não deve ser lido como uma nota final."
)

#: Pilares e pesos. O global renormaliza pelos pilares com dados (nunca inventa
#: um pilar em falta); os pesos seguem a prática de mercado (ambiente 40 %,
#: social 30 %, governance 30 %).
PILARES: List[Dict[str, Any]] = [
    {
        "id": "e",
        "label": "Ambiente",
        "peso": 0.40,
        "cor": "#34d399",
        "descricao": "Compras e serviços com critérios ecológicos, exposição a atividades de maior impacto e indicadores ambientais declarados.",
    },
    {
        "id": "s",
        "label": "Social",
        "peso": 0.30,
        "cor": "#38bdf8",
        "descricao": "Exposição a serviços sociais e de saúde, concorrência nos procedimentos, diversidade de compradores e indicadores sociais declarados.",
    },
    {
        "id": "g",
        "label": "Governação",
        "peso": 0.30,
        "cor": "#a78bfa",
        "descricao": "Transparência na publicação, ajuste direto, concentração de compradores, insolvências, dívidas públicas e indicadores de governance declarados.",
    },
]

PILAR_BY_ID: Dict[str, Dict[str, Any]] = {item["id"]: item for item in PILARES}

#: Faixas do score (maior é melhor). `min` é inclusivo.
NIVEIS: List[Dict[str, Any]] = [
    {"id": "lider", "label": "Líder", "min": 75.0, "cor": "#10b981"},
    {"id": "avancado", "label": "Avançado", "min": 60.0, "cor": "#2dd4bf"},
    {"id": "intermedio", "label": "Intermédio", "min": 45.0, "cor": "#fbbf24"},
    {"id": "inicial", "label": "Inicial", "min": 30.0, "cor": "#fb923c"},
    {"id": "fraco", "label": "Frágil", "min": 0.0, "cor": "#ef4444"},
]

#: Dimensão da carteira de contratos (proxy da dimensão da empresa). A UE
#: classifica PME por efetivos e volume de negócios; como esses dados não estão
#: no portal, usa-se o valor contratado e diz-se que é uma proxy.
DIMENSOES: List[Dict[str, Any]] = [
    {"id": "sem_dados", "label": "Sem carteira registada", "min": 0.0, "max": 0.0},
    {"id": "micro", "label": "Micro carteira (< 0,5 M€)", "min": 0.0, "max": 500_000.0},
    {"id": "pequena", "label": "Pequena carteira (0,5–2 M€)", "min": 500_000.0, "max": 2_000_000.0},
    {"id": "media", "label": "Média carteira (2–10 M€)", "min": 2_000_000.0, "max": 10_000_000.0},
    {"id": "grande", "label": "Grande carteira (≥ 10 M€)", "min": 10_000_000.0, "max": None},
]

#: Componentes do score. `pilar` liga ao cartão; `peso` é relativo dentro do
#: pilar (soma 1,0); `pior`/`melhor` são os pontos da reta (podem estar
#: invertidos quando menor é melhor).
COMPONENTES: List[Dict[str, Any]] = [
    # ---------------------------------------------------------------- Ambiente
    {
        "id": "compras_ecologicas",
        "pilar": "e",
        "label": "Compras com critérios ecológicos",
        "peso": 0.30,
        "pior": 0.0,
        "melhor": 0.50,
        "unidade": "taxa",
        "descricao": "Parte do valor contratado em procedimentos assinalados como contratação ecológica no portal.",
        "metodo": "campo `ContratEcologico = Sim` do Portal BASE",
    },
    {
        "id": "exposicao_verde",
        "pilar": "e",
        "label": "Exposição a atividades verdes",
        "peso": 0.20,
        "pior": -0.20,
        "melhor": 0.60,
        "unidade": "saldo",
        "descricao": "Saldo entre a fatia de valor em CPV de transição verde e a fatia em CPV de maior intensidade carbónica.",
        "metodo": "taxonomia CPV do módulo (serviços ambientais, agricultura, construção sustentável vs. energia fóssil, minas e químicos)",
    },
    {
        "id": "intensidade_carbono",
        "pilar": "e",
        "label": "Exposição carbónica da carteira",
        "peso": 0.20,
        "pior": 0.60,
        "melhor": 0.0,
        "unidade": "taxa",
        "descricao": "Parte do valor em CPV de maior intensidade carbónica (combustíveis fósseis, minas, químicos).",
        "metodo": "taxonomia CPV do módulo (proxy, não medição de emissões)",
    },
    {
        "id": "servicos_ambientais",
        "pilar": "e",
        "label": "Serviços ambientais e economia circular",
        "peso": 0.15,
        "pior": 0.0,
        "melhor": 0.40,
        "unidade": "taxa",
        "descricao": "Parte do valor em resíduos, águas, energia, agricultura e reparação/reutilização.",
        "metodo": "taxonomia CPV do módulo",
    },
    {
        "id": "indicadores_ambientais",
        "pilar": "e",
        "label": "Indicadores ambientais declarados",
        "peso": 0.15,
        "pior": 0.0,
        "melhor": 1.0,
        "unidade": "índice",
        "descricao": "Média normalizada dos indicadores ambientais publicados no relatório de sustentabilidade (emissões, energia, água, resíduos, certificações).",
        "metodo": "indicadores declarados (catalogados e validados no módulo)",
    },
    # ------------------------------------------------------------------ Social
    {
        "id": "exposicao_social",
        "pilar": "s",
        "label": "Exposição a serviços sociais",
        "peso": 0.25,
        "pior": 0.0,
        "melhor": 0.50,
        "unidade": "taxa",
        "descricao": "Parte do valor em saúde, educação, ação social, equipamentos médicos e atividades culturais/desportivas.",
        "metodo": "taxonomia CPV do módulo",
    },
    {
        "id": "concorrencia",
        "pilar": "s",
        "label": "Concorrência nos procedimentos",
        "peso": 0.20,
        "pior": 1.0,
        "melhor": 6.0,
        "unidade": "concorrentes",
        "descricao": "Número mediano de concorrentes por contrato: mercados concorrenciais tendem a repartir melhor o valor.",
        "metodo": "campo de concorrentes do portal (mediana)",
    },
    {
        "id": "diversidade_compradores",
        "pilar": "s",
        "label": "Diversidade de compradores",
        "peso": 0.15,
        "pior": 1.0,
        "melhor": 12.0,
        "unidade": "compradores",
        "descricao": "Número de compradores distintos: uma carteira repartida é menos dependente de uma só relação.",
        "metodo": "contagem de adjudicantes distintos",
    },
    {
        "id": "indicadores_sociais",
        "pilar": "s",
        "label": "Indicadores sociais declarados",
        "peso": 0.40,
        "pior": 0.0,
        "melhor": 1.0,
        "unidade": "índice",
        "descricao": "Média normalizada dos indicadores sociais publicados (formação, acidentes, diversidade, avaliação ESG de fornecedores).",
        "metodo": "indicadores declarados (catalogados e validados no módulo)",
    },
    # -------------------------------------------------------------- Governação
    {
        "id": "transparencia",
        "pilar": "g",
        "label": "Transparência na publicação",
        "peso": 0.25,
        "pior": 180.0,
        "melhor": 0.0,
        "unidade": "dias",
        "descricao": "Dias entre a assinatura e a publicação do contrato: quanto mais longo, mais difícil é o escrutínio a tempo.",
        "metodo": "medianas de `dias_assinatura` e `dias_publicacao`",
    },
    {
        "id": "ajuste_direto",
        "pilar": "g",
        "label": "Peso do ajuste direto",
        "peso": 0.20,
        "pior": 0.80,
        "melhor": 0.0,
        "unidade": "taxa",
        "descricao": "Parte dos contratos adjudicados sem concurso público.",
        "metodo": "prefixos de procedimento do portal",
    },
    {
        "id": "concentracao",
        "pilar": "g",
        "label": "Concentração num só comprador",
        "peso": 0.15,
        "pior": 0.90,
        "melhor": 0.50,
        "unidade": "taxa",
        "descricao": "Parte do valor que vem do maior comprador.",
        "metodo": "concentração de valor por adjudicante",
    },
    {
        "id": "insolvencia",
        "pilar": "g",
        "label": "Processos de insolvência (CIRE)",
        "peso": 0.15,
        "pior": 2.0,
        "melhor": 0.0,
        "unidade": "processos",
        "descricao": "Processos em que a empresa é a insolvente (não credora).",
        "metodo": "join por NIF com o índice do CIRE",
    },
    {
        "id": "divida_publica",
        "pilar": "g",
        "label": "Dívidas públicas publicadas",
        "peso": 0.10,
        "pior": 1.0,
        "melhor": 0.0,
        "unidade": "sinal",
        "descricao": "Presença nas listas públicas de devedores da Autoridade Tributária ou da Segurança Social.",
        "metodo": "campo `devedor` do cadastro de contribuintes",
    },
    {
        "id": "indicadores_governacao",
        "pilar": "g",
        "label": "Indicadores de governance declarados",
        "peso": 0.15,
        "pior": 0.0,
        "melhor": 1.0,
        "unidade": "índice",
        "descricao": "Média normalizada dos indicadores de governance publicados (conselho, ética, denúncias, anticorrupção, relatório e auditoria).",
        "metodo": "indicadores declarados (catalogados e validados no módulo)",
    },
]

COMPONENTE_BY_ID: Dict[str, Dict[str, Any]] = {item["id"]: item for item in COMPONENTES}


def _ind(
    codigo: str,
    label: str,
    pilar: str,
    unidade: str,
    pior: Optional[float],
    melhor: Optional[float],
    grupo: str,
    descricao: str,
    fonte: str = "",
) -> Dict[str, Any]:
    """Entrada do catálogo de indicadores declarados.

    `pior` e `melhor` são os pontos da reta de normalização; quando `melhor <
    pior`, o indicador é «menor é melhor» (emissões, acidentes, rotação). `None`
    marca um indicador de contexto (guardado e mostrado, não pontuado).
    """
    return {
        "codigo": codigo,
        "label": label,
        "pilar": pilar,
        "unidade": unidade,
        "pior": pior,
        "melhor": melhor,
        "grupo": grupo,
        "descricao": descricao,
        "fonte_sugerida": fonte,
        "pontuavel": pior is not None and melhor is not None and pior != melhor,
    }


#: Catálogo de indicadores que os relatórios de sustentabilidade podem declarar.
#: A ingestão valida o código; o score só usa os pontuáveis.
INDICADORES: List[Dict[str, Any]] = [
    # Ambiente
    _ind("e_emissoes_scope1", "Emissões diretas (âmbito 1)", "e", "tCO2e", 25_000, 0, "Emissões", "Emissões diretas de gases com efeito de estufa.", "GRI 305-1 / GHG Protocol"),
    _ind("e_emissoes_scope2", "Emissões indiretas de energia (âmbito 2)", "e", "tCO2e", 25_000, 0, "Emissões", "Emissões associadas à energia comprada.", "GRI 305-2 / GHG Protocol"),
    _ind("e_emissoes_scope3", "Emissões da cadeia de valor (âmbito 3)", "e", "tCO2e", 120_000, 0, "Emissões", "Emissões da cadeia de valor, quando publicadas.", "GRI 305-3 / GHG Protocol"),
    _ind("e_intensidade_carbono", "Intensidade carbónica", "e", "tCO2e/M€", 250, 0, "Emissões", "Emissões por milhão de euros de volume de negócios.", "GRI 305-4"),
    _ind("e_energia_renovavel_pct", "Energia renovável", "e", "%", 0, 100, "Energia", "Parte do consumo de energia proveniente de fontes renováveis.", "GRI 302-1"),
    _ind("e_consumo_energia_mwh", "Consumo de energia", "e", "MWh", 50_000, 0, "Energia", "Consumo total de energia no ano.", "GRI 302-1"),
    _ind("e_agua_m3", "Consumo de água", "e", "m3", 500_000, 0, "Água", "Captação/consumo total de água.", "GRI 303-3"),
    _ind("e_residuos_valorizacao_pct", "Resíduos valorizados", "e", "%", 0, 100, "Resíduos", "Parte dos resíduos encaminhados para valorização (reciclagem, recuperação).", "GRI 306-4"),
    _ind("e_residuos_perigosos_t", "Resíduos perigosos", "e", "t", 500, 0, "Resíduos", "Quantidade de resíduos perigosos produzidos.", "GRI 306-3"),
    _ind("e_iso14001", "Certificação ISO 14001", "e", "0/1", 0, 1, "Certificações", "Sistema de gestão ambiental certificado."),
    _ind("e_emas", "Registo EMAS", "e", "0/1", 0, 1, "Certificações", "Adesão ao sistema europeu de ecogestão e auditoria."),
    _ind("e_criterios_verdes_pct", "Critérios verdes nas compras", "e", "%", 0, 100, "Compras", "Parte das compras com critérios ambientais declarados.", "GRI 308-1"),
    _ind("e_objetivos_climaticos", "Objetivos climáticos baseados na ciência", "e", "0/1", 0, 1, "Estratégia", "Metas de descarbonização aprovadas (SBTi ou equivalentes)."),
    # Social
    _ind("s_trabalhadores", "Trabalhadores", "s", "nº", None, None, "Emprego", "Número de trabalhadores (contexto, não pontua).", "GRI 2-7"),
    _ind("s_taxa_rotatividade_pct", "Rotatividade de pessoal", "s", "%", 30, 0, "Emprego", "Saídas de trabalhadores face ao efetivo médio.", "GRI 401-1"),
    _ind("s_horas_formacao_colaborador", "Horas de formação por trabalhador", "s", "h", 0, 40, "Formação", "Formação média anual por trabalhador.", "GRI 404-1"),
    _ind("s_acidentes_trabalho", "Acidentes de trabalho", "s", "nº", 20, 0, "Segurança", "Acidentes de trabalho com baixa no ano.", "GRI 403-9"),
    _ind("s_diferenca_salarial_genero_pct", "Diferença salarial de género", "s", "%", 30, 0, "Diversidade", "Diferença entre a remuneração média de homens e mulheres.", "GRI 405-2"),
    _ind("s_mulheres_quadros_pct", "Mulheres em cargos de chefia", "s", "%", 0, 50, "Diversidade", "Parte de mulheres nos quadros superiores.", "GRI 405-1"),
    _ind("s_emprego_local_pct", "Emprego local", "s", "%", 0, 100, "Comunidade", "Parte dos trabalhadores residentes na região de operação."),
    _ind("s_iso45001", "Certificação ISO 45001", "s", "0/1", 0, 1, "Certificações", "Sistema de gestão de segurança e saúde no trabalho."),
    _ind("s_fornecedores_avaliados_esg_pct", "Fornecedores avaliados em ESG", "s", "%", 0, 100, "Cadeia de valor", "Parte dos fornecedores avaliados com critérios ESG.", "GRI 308-2 / 414-2"),
    _ind("s_contribuicao_comunidade_pct", "Contribuição para a comunidade", "s", "% do volume de negócios", 0, 2, "Comunidade", "Investimento social face ao volume de negócios.", "GRI 413-1"),
    _ind("s_sa8000", "Certificação SA 8000", "s", "0/1", 0, 1, "Certificações", "Responsabilidade social certificada."),
    # Governação
    _ind("g_conselho_independentes_pct", "Administradores independentes", "g", "%", 0, 60, "Conselho", "Parte de membros independentes no órgão de administração.", "GRI 2-9 / CGS"),
    _ind("g_mulheres_conselho_pct", "Mulheres no conselho", "g", "%", 0, 40, "Conselho", "Parte de mulheres no órgão de administração.", "GRI 405-1"),
    _ind("g_codigo_etica", "Código de ética", "g", "0/1", 0, 1, "Ética", "Código de conduta publicado e aplicado."),
    _ind("g_canal_denuncias", "Canal de denúncias", "g", "0/1", 0, 1, "Ética", "Canal independente de denúncias e proteção do denunciante."),
    _ind("g_formacao_anticorrupcao_pct", "Formação anticorrupção", "g", "%", 0, 100, "Ética", "Parte dos trabalhadores com formação em anticorrupção.", "GRI 205-2"),
    _ind("g_iso37001", "Certificação ISO 37001", "g", "0/1", 0, 1, "Certificações", "Sistema de gestão antissuborno."),
    _ind("g_politica_privacidade", "Política de privacidade", "g", "0/1", 0, 1, "Dados", "Política de proteção de dados publicada."),
    _ind("g_relatorio_sustentabilidade", "Relatório de sustentabilidade", "g", "0/1", 0, 1, "Transparência", "Relatório anual publicado com indicadores verificáveis."),
    _ind("g_auditoria_externa", "Auditoria externa do relatório", "g", "0/1", 0, 1, "Transparência", "Relatório de sustentabilidade com verificação externa."),
    _ind("g_remuneracao_ceo_ratio", "Rácio de remuneração CEO/mediana", "g", "×", 100, 10, "Remuneração", "Relação entre a remuneração do CEO e a mediana dos trabalhadores.", "GRI 2-21"),
    _ind("g_taxa_conformidade_fornecedores_pct", "Fornecedores com conformidade avaliada", "g", "%", 0, 100, "Cadeia de valor", "Parte dos fornecedores com avaliação de conformidade.", "GRI 414-2"),
    _ind("g_objetivos_climaticos_governacao", "Metas climáticas aprovadas pelo conselho", "g", "0/1", 0, 1, "Estratégia", "Metas climáticas formalmente aprovadas pelo órgão de administração."),
    # Novos indicadores alinhados com a Taxonomia UE e com o percurso IAPMEI.
    # Sem eles, a verificação de DNSH e das salvaguardas mínimas fica
    # explicitamente «sem evidência» — não se presume conformidade.
    _ind("e_politica_ambiental", "Política ambiental formal", "e", "0/1", 0, 1, "Gestão ambiental", "Política ambiental aprovada e publicada.", "ISO 14001 / ESRS E1"),
    _ind("e_gestao_ambiental", "Sistema de gestão ambiental", "e", "0/1", 0, 1, "Gestão ambiental", "Sistema de gestão ambiental implementado e auditado.", "ISO 14001 / EMAS"),
    _ind("e_risco_climatico", "Avaliação de risco climático", "e", "0/1", 0, 1, "Clima", "Riscos físicos e de transição avaliados e geridos.", "TCFD / ESRS E1"),
    _ind("e_biodiversidade", "Gestão da biodiversidade", "e", "0/1", 0, 1, "Biodiversidade", "Dependências e impactos na biodiversidade avaliados e mitigados.", "TNFD / ESRS E4"),
    _ind("e_economia_circular", "Estratégia de economia circular", "e", "0/1", 0, 1, "Economia circular", "Objetivos de circularidade de materiais e produtos.", "ESRS E5"),
    _ind("e_gestao_agua", "Gestão do risco hídrico", "e", "0/1", 0, 1, "Água", "Avaliação de stress hídrico e gestão do consumo de água.", "ESRS E3"),
    _ind("s_salario_digno", "Salário digno", "s", "0/1", 0, 1, "Emprego", "Compromisso com salário digno e respetiva monitorização.", "GRI 202-1 / ESRS S1"),
    _ind("s_direitos_humanos", "Política de direitos humanos", "s", "0/1", 0, 1, "Direitos humanos", "Compromisso com direitos humanos e mecanismos de reparação.", "UNGP / ESRS S1-S2"),
    _ind("s_condicoes_trabalho", "Condições de trabalho avaliadas", "s", "0/1", 0, 1, "Emprego", "Avaliação de condições de trabalho na empresa e na cadeia de valor.", "OIT / ESRS S1"),
    _ind("g_direitos_humanos", "Due diligence de direitos humanos", "g", "0/1", 0, 1, "Direitos humanos", "Processo de due diligence em direitos humanos documentado.", "UNGP / OCDE"),
    _ind("g_due_diligence", "Due diligence ESG da cadeia de valor", "g", "0/1", 0, 1, "Cadeia de valor", "Diligência devida sobre fornecedores e parceiros.", "OCDE / ESRS G1"),
    _ind("g_codigo_fornecedores", "Código de conduta para fornecedores", "g", "0/1", 0, 1, "Cadeia de valor", "Código para fornecedores com critérios ESG e mecanismos de controlo.", "GRI 308 / 414"),
    _ind("g_politica_fiscal", "Política fiscal responsável", "g", "0/1", 0, 1, "Fiscalidade", "Política de transparência fiscal e controlo de práticas de elisão.", "OCDE"),
    _ind("g_politica_remuneracao", "Política de remuneração transparente", "g", "0/1", 0, 1, "Remuneração", "Política de remuneração publicada e ligada ao desempenho sustentável.", "ESRS G1"),
]

INDICADOR_BY_CODIGO: Dict[str, Dict[str, Any]] = {item["codigo"]: item for item in INDICADORES}

#: Fontes do módulo. `tipo` distingue o que é lido internamente (índices da
#: plataforma) do que é fonte aberta de referência (documentação, taxonomias e
#: relatórios que a empresa publica).
FONTES: List[Dict[str, Any]] = [
    {
        "id": "portal_base",
        "label": "Portal BASE — contratos públicos",
        "tipo": "interna",
        "url": "https://www.base.gov.pt/",
        "uso": "Volume, valor, CPV, procedimento, concorrentes, prazos e contratação ecológica.",
    },
    {
        "id": "placcp",
        "label": "PLACSP — contratação pública de Espanha",
        "tipo": "interna",
        "url": "https://contrataciondelestado.es/",
        "uso": "O mesmo tipo de indicadores para empresas espanholas.",
    },
    {
        "id": "contribuintes",
        "label": "Cadastro de contribuintes do IQ OS",
        "tipo": "interna",
        "url": "",
        "uso": "NIF, designações, país, localização, papéis e sinais de dívida pública.",
    },
    {
        "id": "entidades_cae",
        "label": "Registo de entidades e CAE",
        "tipo": "interna",
        "url": "",
        "uso": "CAE principal e secundários para o setor e a comparação entre pares.",
    },
    {
        "id": "cire",
        "label": "CIRE — processos de insolvência",
        "tipo": "interna",
        "url": "",
        "uso": "Processos em que a empresa é a insolvente (não credora).",
    },
    {
        "id": "devedores",
        "label": "Listas públicas de devedores (AT e Segurança Social)",
        "tipo": "interna",
        "url": "",
        "uso": "Presença nas listas e escalão publicado.",
    },
    {
        "id": "relatorios_sustentabilidade",
        "label": "Relatórios de sustentabilidade das empresas",
        "tipo": "declarada",
        "url": "",
        "uso": "Indicadores ambientais, sociais e de governance declarados, com ano, fonte e ligação.",
    },
    {
        "id": "gri",
        "label": "GRI Standards",
        "tipo": "referencia",
        "url": "https://www.globalreporting.org/standards/",
        "uso": "Códigos e definições dos indicadores declarados (GRI 302, 305, 306, 401, 403, 405, 414…).",
    },
    {
        "id": "issb",
        "label": "ISSB / IFRS S1-S2",
        "tipo": "referencia",
        "url": "https://www.ifrs.org/issued-standards/ifrs-sustainability-standards-navigator/",
        "uso": "Referencial de divulgação climática e de sustentabilidade.",
    },
    {
        "id": "efrag",
        "label": "EFRAG — ESRS",
        "tipo": "referencia",
        "url": "https://www.efrag.org/",
        "uso": "Normas europeias de relato de sustentabilidade (CSRD).",
    },
    {
        "id": "ine",
        "label": "INE — estatísticas das empresas",
        "tipo": "referencia",
        "url": "https://www.ine.pt/",
        "uso": "Contexto de setor, dimensão e território.",
    },
    {
        "id": "iapmei_esg",
        "label": "IAPMEI — alinhamento do negócio com fatores ESG",
        "tipo": "referencia",
        "url": "https://www.iapmei.pt/pt/saber-mais/industria-e-sustentabilidade/sustentabilidade-empresarial/esg-e-financas-sustentaveis/alinhamento-do-negocio-com-fatores-esg/",
        "uso": "Percurso de cinco passos para PME, temas materiais por pilar, ODS, normas de relato (ESRS/VSME) e ligação à Taxonomia UE.",
    },
    {
        "id": "eu_taxonomy_compass",
        "label": "EU Taxonomy Compass — Comissão Europeia",
        "tipo": "referencia",
        "url": "https://ec.europa.eu/sustainable-finance-taxonomy/taxonomy-compass",
        "uso": "Seis objetivos ambientais, atividades elegíveis, códigos NACE, contributo significativo, DNSH e critérios técnicos oficiais.",
    },
    {
        "id": "sdg_compass",
        "label": "SDG Compass (GRI, UN Global Compact, WBCSD)",
        "tipo": "referencia",
        "url": "https://www.unglobalcompact.org/library/3101",
        "uso": "Ligação entre estratégia empresarial, temas materiais e os 17 ODS.",
    },
    {
        "id": "vsme",
        "label": "VSME — norma voluntária de relato para PME",
        "tipo": "referencia",
        "url": "https://finance.ec.europa.eu/publications/commission-presents-voluntary-sustainability-reporting-standard-ease-burden-smes_en",
        "uso": "Modelo simplificado para PME responderem a pedidos de clientes e financiadores.",
    },
    {
        "id": "tcfd",
        "label": "TCFD — Task Force on Climate-related Financial Disclosures",
        "tipo": "referencia",
        "url": "https://www.fsb-tcfd.org/",
        "uso": "Governação, estratégia, gestão de risco e métricas climáticas.",
    },
    {
        "id": "tnfd",
        "label": "TNFD — Taskforce on Nature-related Financial Disclosures",
        "tipo": "referencia",
        "url": "https://tnfd.global/",
        "uso": "Dependências, impactos, riscos e oportunidades relacionados com a natureza.",
    },
    {
        "id": "certificacoes_esg",
        "label": "B Corp, EcoVadis e Sedex",
        "tipo": "referencia",
        "url": "https://www.bcorporation.net/",
        "uso": "Certificações e avaliações privadas usadas por PME exportadoras e por grandes compradores.",
    },
    {
        "id": "apa",
        "label": "APA — Agência Portuguesa do Ambiente",
        "tipo": "referencia",
        "url": "https://apambiente.pt/",
        "uso": "Referenciais ambientais e de resíduos.",
    },
    {
        "id": "dgeg",
        "label": "DGEG — energia",
        "tipo": "referencia",
        "url": "https://www.dgeg.gov.pt/",
        "uso": "Contexto energético e renovável.",
    },
]

#: Secções CAE (CAE Rev.3) e uma nota de relevância ESG. O setor é a secção
#: (letra) do CAE principal; sem CAE, usa-se o CPV dominante como proxy.
CAE_SECOES: Dict[str, Dict[str, str]] = {
    "A": {"label": "Agricultura, produção animal, caça, floresta e pesca", "nota": "Capital natural e uso do solo."},
    "B": {"label": "Indústrias extrativas", "nota": "Impacto ambiental elevado; transição crítica."},
    "C": {"label": "Indústrias transformadoras", "nota": "Energia, materiais e cadeia de valor."},
    "D": {"label": "Eletricidade, gás, vapor e ar condicionado", "nota": "Descarbonização e renováveis."},
    "E": {"label": "Captação, tratamento e distribuição de água", "nota": "Água, resíduos e economia circular."},
    "F": {"label": "Construção", "nota": "Construção sustentável e eficiência energética."},
    "G": {"label": "Comércio por grosso e a retalho", "nota": "Cadeia de valor e produtos sustentáveis."},
    "H": {"label": "Transportes e armazenagem", "nota": "Mobilidade e emissões."},
    "I": {"label": "Alojamento, restauração e similares", "nota": "Turismo sustentável e emprego local."},
    "J": {"label": "Atividades de informação e comunicação", "nota": "Digital, energia e privacidade."},
    "K": {"label": "Atividades financeiras e de seguros", "nota": "Financiamento sustentável e governance."},
    "L": {"label": "Atividades imobiliárias", "nota": "Eficiência dos edifícios."},
    "M": {"label": "Consultoria, científicas, técnicas e similares", "nota": "Serviços de engenharia e ambiente."},
    "N": {"label": "Atividades administrativas e serviços de apoio", "nota": "Emprego e cadeia de valor."},
    "O": {"label": "Administração Pública e Defesa", "nota": "Compras públicas e transparência."},
    "P": {"label": "Educação", "nota": "Capital humano e impacto social."},
    "Q": {"label": "Saúde humana e apoio social", "nota": "Impacto social e acesso."},
    "R": {"label": "Atividades artísticas, de espetáculos e recreativas", "nota": "Cultura, comunidade e território."},
    "S": {"label": "Outras atividades de serviços", "nota": "Serviços e emprego local."},
    "T": {"label": "Atividades das famílias e organizações", "nota": "Contexto social."},
    "U": {"label": "Organismos internacionais e outras instituições", "nota": "Contexto institucional."},
}

#: Divisão CPV → secção CAE (proxy quando não há CAE). Cobre as divisões usadas
#: nos contratos; o que não estiver aqui fica «N/D».
CPV_CAE_SECAO: Dict[int, str] = {
    1: "A", 2: "A", 3: "A", 5: "B", 9: "B", 10: "C", 11: "C", 12: "C", 13: "C", 14: "B",
    15: "C", 16: "C", 17: "C", 18: "C", 19: "C", 20: "C", 21: "C", 22: "C", 23: "C",
    24: "C", 25: "C", 26: "C", 27: "C", 28: "C", 29: "C", 30: "C", 31: "C", 32: "C",
    33: "C", 34: "C", 35: "D", 36: "E", 37: "C", 38: "C", 39: "C", 41: "F", 42: "F",
    43: "F", 44: "F", 45: "F", 46: "G", 47: "G", 48: "G", 49: "H", 50: "H", 51: "H",
    52: "H", 53: "H", 55: "I", 56: "I", 58: "J", 59: "J", 60: "H", 61: "H", 62: "J",
    63: "J", 64: "K", 65: "K", 66: "K", 67: "K", 68: "L", 69: "M", 70: "M", 71: "M",
    72: "J", 73: "M", 74: "M", 75: "O", 76: "M", 77: "A", 78: "N", 79: "N", 80: "P",
    81: "N", 82: "N", 83: "N", 84: "O", 85: "Q", 86: "Q", 87: "Q", 88: "Q", 89: "E",
    90: "E", 91: "O", 92: "R", 93: "R", 94: "S", 95: "S", 96: "S", 98: "U", 99: "U",
}

#: Divisões CPV com relevância ESG. `verde` e `social` entram na exposição;
#: `marrom` entra na intensidade carbónica. Uma divisão pode ter mais do que um
#: sinal (a construção é verde e material-intensiva, por exemplo).
CPV_ESG: Dict[int, Dict[str, Any]] = {
    1: {"label": "Produtos da agricultura, horticultura e silvicultura", "verde": True},
    2: {"label": "Produtos da pesca, aquicultura e caça", "verde": True},
    3: {"label": "Produtos da silvicultura", "verde": True},
    5: {"label": "Carvão e combustíveis minerais", "marrom": True},
    9: {"label": "Petróleo, combustíveis e eletricidade", "marrom": True},
    10: {"label": "Produtos metálicos e minérios", "marrom": True},
    14: {"label": "Produtos da mineração", "marrom": True},
    18: {"label": "Vestuário e calçado", "social": True},
    24: {"label": "Produtos químicos", "marrom": True},
    30: {"label": "Máquinas de escritório e informática", "circular": True},
    31: {"label": "Máquinas e aparelhos elétricos", "verde": True, "circular": True},
    33: {"label": "Equipamento médico e farmacêutico", "social": True},
    34: {"label": "Equipamento de transporte", "verde": True},
    37: {"label": "Instrumentos musicais, desportivos e de lazer", "social": True},
    38: {"label": "Equipamento de laboratório e precisão", "social": True},
    39: {"label": "Mobiliário e equipamento doméstico", "circular": True},
    41: {"label": "Água canalizada", "verde": True},
    42: {"label": "Obras de engenharia civil", "verde": True},
    43: {"label": "Trabalhos de construção", "verde": True},
    44: {"label": "Materiais de construção", "circular": True},
    45: {"label": "Trabalhos de construção", "verde": True},
    48: {"label": "Software e equipamento informático", "circular": True},
    50: {"label": "Serviços de reparação e manutenção", "circular": True},
    51: {"label": "Serviços de instalação", "circular": True},
    60: {"label": "Serviços de transporte", "verde": True},
    63: {"label": "Serviços de apoio ao transporte", "verde": True},
    64: {"label": "Serviços de telecomunicações", "social": True},
    65: {"label": "Serviços de utilities", "verde": True},
    66: {"label": "Serviços financeiros e de seguros", "social": True},
    70: {"label": "Serviços imobiliários", "social": True},
    71: {"label": "Serviços de arquitetura e engenharia", "verde": True},
    72: {"label": "Serviços de TI", "circular": True},
    73: {"label": "Serviços de investigação e desenvolvimento", "verde": True},
    75: {"label": "Serviços da administração pública", "social": True},
    77: {"label": "Serviços agrícolas, silvícolas e de jardinagem", "verde": True},
    79: {"label": "Serviços empresariais", "social": True},
    80: {"label": "Serviços de educação e formação", "social": True},
    85: {"label": "Serviços de saúde e ação social", "social": True},
    90: {"label": "Serviços de esgotos, resíduos e limpeza", "verde": True, "circular": True},
    91: {"label": "Serviços de administração pública e utilities", "social": True},
    92: {"label": "Serviços recreativos, culturais e desportivos", "social": True},
    93: {"label": "Serviços de saúde e ação social", "social": True},
    98: {"label": "Outros serviços", "social": True},
}

#: Divisões CPV puramente «marrom» (para a intensidade carbónica) e as que
#: entram na exposição verde e social. Derivadas de `CPV_ESG` para não haver
#: duas listas que se podem desencontrar.
CPV_VERDE: frozenset = frozenset(code for code, item in CPV_ESG.items() if item.get("verde"))
CPV_SOCIAL: frozenset = frozenset(code for code, item in CPV_ESG.items() if item.get("social"))
CPV_CIRCULAR: frozenset = frozenset(code for code, item in CPV_ESG.items() if item.get("circular"))
CPV_MARROM: frozenset = frozenset(code for code, item in CPV_ESG.items() if item.get("marrom"))

#: Referência de pares: mínimo de empresas comparáveis para se calcular um
#: percentil. Abaixo disto, o benchmark diz «amostra insuficiente».
MIN_PARES = 5

#: Máximo de documentos de pares lidos para o benchmark (protege o Elasticsearch).
MAX_PARES = 2_000


def nivel_de(score: Optional[float]) -> Dict[str, Any]:
    """Faixa do score (maior é melhor). `None` devolve «sem dados»."""
    if score is None:
        return {"id": "sem_dados", "label": "Sem dados", "min": 0.0, "cor": "#94a3b8"}
    valor = max(0.0, min(100.0, float(score)))
    for nivel in NIVEIS:
        if valor >= nivel["min"]:
            return dict(nivel)
    return dict(NIVEIS[-1])


def dimensao_de(valor: Optional[float]) -> Dict[str, Any]:
    """Dimensão da carteira a partir do valor contratado (proxy declarada)."""
    if not valor or valor <= 0:
        return dict(DIMENSOES[0])
    for dimensao in DIMENSOES[1:]:
        maximo = dimensao.get("max")
        if maximo is None or valor < float(maximo):
            return dict(dimensao)
    return dict(DIMENSOES[-1])


def cartao_modelo() -> Dict[str, Any]:
    """Cartão do modelo: pilares, componentes, limiares, faixas e fontes."""
    return {
        "versao": MODELO_VERSAO,
        "rotulo": "IQ OS Score ESG",
        "aviso": AVISO_GERAL,
        "pilares": [
            {
                **pilar,
                "componentes": [
                    {
                        "id": item["id"],
                        "label": item["label"],
                        "peso": item["peso"],
                        "pior": item["pior"],
                        "melhor": item["melhor"],
                        "unidade": item["unidade"],
                        "descricao": item["descricao"],
                        "metodo": item["metodo"],
                    }
                    for item in COMPONENTES
                    if item["pilar"] == pilar["id"]
                ],
            }
            for pilar in PILARES
        ],
        "niveis": [dict(nivel) for nivel in NIVEIS],
        "dimensoes": [dict(dimensao) for dimensao in DIMENSOES],
        "min_par_benchmark": MIN_PARES,
        "indicadores": [dict(item) for item in INDICADORES],
        "fontes": [dict(item) for item in FONTES],
    }


def setor_de_cae(cae: Optional[str]) -> Tuple[str, str]:
    """Secção CAE (`A`–`U`) e rótulo a partir do código CAE («42910», «42.910»)."""
    digitos = "".join(ch for ch in str(cae or "") if ch.isdigit())
    if len(digitos) < 2:
        return "", ""
    try:
        divisao = int(digitos[:2])
    except ValueError:
        return "", ""
    if divisao <= 3:
        secao = "A"
    elif 5 <= divisao <= 9:
        secao = "B"
    elif 10 <= divisao <= 33:
        secao = "C"
    elif divisao == 35:
        secao = "D"
    elif 36 <= divisao <= 39:
        secao = "E"
    elif 41 <= divisao <= 43:
        secao = "F"
    elif 45 <= divisao <= 47:
        secao = "G"
    elif 49 <= divisao <= 53:
        secao = "H"
    elif 55 <= divisao <= 56:
        secao = "I"
    elif 58 <= divisao <= 63:
        secao = "J"
    elif 64 <= divisao <= 66:
        secao = "K"
    elif divisao == 68:
        secao = "L"
    elif 69 <= divisao <= 75:
        secao = "M"
    elif 77 <= divisao <= 82:
        secao = "N"
    elif divisao == 84:
        secao = "O"
    elif divisao == 85:
        secao = "P"
    elif 86 <= divisao <= 88:
        secao = "Q"
    elif 90 <= divisao <= 93:
        secao = "R"
    elif 94 <= divisao <= 96:
        secao = "S"
    elif 97 <= divisao <= 98:
        secao = "T"
    else:
        secao = "U"
    return secao, CAE_SECOES.get(secao, {}).get("label", secao)
