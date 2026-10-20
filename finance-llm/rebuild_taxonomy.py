from pathlib import Path

p = Path(r"C:\LLMFinance\finance-llm\api\esg_taxonomy.py")
text = p.read_text(encoding="utf-8")
inicio = text.index("ATIVIDADES: List[Dict[str, Any]] = [")
fim = text.index("ATIVIDADE_BY_ID:")
atividades = text[inicio:fim].rstrip() + "\n"

header = '''"""Dados oficiais da **Taxonomia Europeia** usados pelo módulo ESG.

A lista de atividades, setores, códigos NACE e objetivos foi obtida do
*EU Taxonomy Compass* (Comissão Europeia, DG FISMA):

- https://ec.europa.eu/sustainable-finance-taxonomy/taxonomy-compass
- API: https://webgate.ec.europa.eu/sft/api/v1/en/activities/matches
- API: https://webgate.ec.europa.eu/sft/api/v1/en/objectives

Os textos legais e os critérios técnicos completos continuam na fonte oficial;
aqui ficam os identificadores necessários para ligar uma empresa (CAE/NACE) às
atividades elegíveis e para abrir a ficha oficial de cada atividade. O IQ OS
**não** declara alinhamento: sem os critérios técnicos, a análise DNSH e as
salvaguardas sociais mínimas documentadas, a classificação máxima é
«elegível, alinhamento por verificar».

Última sincronização: 2026-10-20.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

FONTE = {
    "id": "eu_taxonomy_compass",
    "label": "EU Taxonomy Compass — Comissão Europeia",
    "url": "https://ec.europa.eu/sustainable-finance-taxonomy/taxonomy-compass",
    "api": "https://webgate.ec.europa.eu/sft/api/v1/en",
    "sincronizado_em": "2026-10-20",
    "aviso": "A lista serve para elegibilidade indicativa. O alinhamento exige critérios técnicos, DNSH e salvaguardas mínimas documentados.",
}

OBJETIVOS: List[Dict[str, Any]] = [
    {
        "id": 41,
        "label": "Mitigação das alterações climáticas",
        "curto": "Clima (mitigação)",
        "cor": "#34d399",
        "descricao": "Contribuir para estabilizar as concentrações de gases com efeito de estufa, evitando ou reduzindo emissões.",
    },
    {
        "id": 42,
        "label": "Adaptação às alterações climáticas",
        "curto": "Clima (adaptação)",
        "cor": "#38bdf8",
        "descricao": "Reduzir a vulnerabilidade aos impactos climáticos e aumentar a resiliência de pessoas, natureza e ativos.",
    },
    {
        "id": 43,
        "label": "Utilização sustentável e proteção dos recursos hídricos e marinhos",
        "curto": "Água e mares",
        "cor": "#22d3ee",
        "descricao": "Proteger a qualidade da água e dos ecossistemas marinhos e usar os recursos hídricos de forma sustentável.",
    },
    {
        "id": 44,
        "label": "Transição para uma economia circular",
        "curto": "Economia circular",
        "cor": "#a78bfa",
        "descricao": "Prolongar a vida dos materiais, reduzir resíduos e manter o valor dos recursos na economia.",
    },
    {
        "id": 45,
        "label": "Prevenção e controlo da poluição",
        "curto": "Poluição",
        "cor": "#fbbf24",
        "descricao": "Prevenir ou reduzir a poluição do ar, da água e do solo e gerir substâncias perigosas.",
    },
    {
        "id": 46,
        "label": "Proteção e restauro da biodiversidade e dos ecossistemas",
        "curto": "Biodiversidade",
        "cor": "#fb7185",
        "descricao": "Proteger, conservar e restaurar a biodiversidade e os serviços dos ecossistemas.",
    },
]

OBJETIVO_BY_ID: Dict[int, Dict[str, Any]] = {item["id"]: item for item in OBJETIVOS}

#: Setor do Compass → secção CAE/NACE (usado quando a atividade não tem NACE).
SETOR_PARA_SECAO: Dict[str, str] = {
    "Accommodation activities": "I",
    "Arts, entertainment and recreation": "R",
    "Construction and real estate activities": "F",
    "Disaster risk management": "O",
    "Education": "P",
    "Energy": "D",
    "Environmental protection and restoration activities": "E",
    "Financial and insurance activities": "K",
    "Forestry": "A",
    "Human health and social work activities": "Q",
    "Information and communication": "J",
    "Manufacturing": "C",
    "Professional, scientific and technical activities": "M",
    "Services": "S",
    "Transport": "H",
    "Water supply, sewerage, waste management and remediation": "E",
}

#: Atividades do Compass (151). `objetivos` inclui o tipo de contributo
#: (Contribui significativamente | Enabling | Transitional).
'''

footer = '''
ATIVIDADE_BY_ID: Dict[int, Dict[str, Any]] = {item["id"]: item for item in ATIVIDADES}

#: Salvaguardas sociais mínimas (artigo 18.º do Regulamento (UE) 2020/852).
#: Cada requisito aponta para indicadores do catálogo ESG que podem servir de
#: evidência declarada. A ausência de indicador não prova incumprimento: fica
#: «sem evidência».
SALVAGUARDAS: List[Dict[str, Any]] = [
    {
        "id": "direitos_humanos",
        "label": "Direitos humanos",
        "descricao": "Compromisso, due diligence e mecanismos de reparação em matéria de direitos humanos.",
        "indicadores": ["g_direitos_humanos", "g_due_diligence", "g_codigo_etica"],
        "fonte": "Princípios Orientadores da ONU / OCDE",
    },
    {
        "id": "direitos_trabalho",
        "label": "Direitos e condições de trabalho",
        "descricao": "Liberdade sindical, negociação coletiva, segurança e saúde, igualdade e salário digno.",
        "indicadores": ["s_iso45001", "s_diferenca_salarial_genero_pct", "s_acidentes_trabalho", "s_salario_digno"],
        "fonte": "OIT — convenções fundamentais",
    },
    {
        "id": "anticorrupcao",
        "label": "Anticorrupção e suborno",
        "descricao": "Política, formação e canais de denúncia para prevenir corrupção e suborno.",
        "indicadores": ["g_iso37001", "g_formacao_anticorrupcao_pct", "g_canal_denuncias", "g_codigo_etica"],
        "fonte": "OCDE / UNGC Princípio 10",
    },
    {
        "id": "fiscalidade",
        "label": "Fiscalidade responsável",
        "descricao": "Transparência fiscal e ausência de práticas de elisão agressiva.",
        "indicadores": ["g_relatorio_sustentabilidade", "g_auditoria_externa", "g_politica_fiscal"],
        "fonte": "OCDE — tributação responsável",
    },
]

#: Critérios DNSH por objetivo ambiental: indicadores declarados que podem
#: sustentar uma primeira verificação. Nenhum indicador substitui a avaliação
#: técnica exigida pelo ato delegado.
DNSH: List[Dict[str, Any]] = [
    {"objetivo": 41, "indicadores": ["e_emissoes_scope1", "e_emissoes_scope2", "e_emissoes_scope3", "e_intensidade_carbono", "e_objetivos_climaticos"]},
    {"objetivo": 42, "indicadores": ["e_risco_climatico", "e_objetivos_climaticos", "e_emissoes_scope1"]},
    {"objetivo": 43, "indicadores": ["e_agua_m3", "e_gestao_agua", "e_politica_ambiental"]},
    {"objetivo": 44, "indicadores": ["e_residuos_valorizacao_pct", "e_residuos_perigosos_t", "e_economia_circular", "e_politica_ambiental"]},
    {"objetivo": 45, "indicadores": ["e_residuos_perigosos_t", "e_politica_ambiental", "e_emissoes_scope1"]},
    {"objetivo": 46, "indicadores": ["e_biodiversidade", "e_politica_ambiental", "e_risco_climatico"]},
]

#: Normas de relato referidas pelo IAPMEI e pelo quadro europeu.
NORMAS_RELATO: List[Dict[str, Any]] = [
    {"id": "esrs", "label": "ESRS — European Sustainability Reporting Standards", "url": "https://www.efrag.org/", "uso": "Normas europeias obrigatórias no âmbito da CSRD (Diretiva 2022/2464).", "ambito": "UE"},
    {"id": "vsme", "label": "VSME — Voluntary SME Standard", "url": "https://finance.ec.europa.eu/publications/commission-presents-voluntary-sustainability-reporting-standard-ease-burden-smes_en", "uso": "Modelo simplificado e voluntário para PME responderem a clientes e financiadores.", "ambito": "UE"},
    {"id": "gri", "label": "GRI Standards", "url": "https://www.globalreporting.org/standards/", "uso": "Normas mais usadas no relato voluntário; base dos códigos GRI do catálogo.", "ambito": "Internacional"},
    {"id": "issb", "label": "ISSB / IFRS S1-S2", "url": "https://www.ifrs.org/issued-standards/ifrs-sustainability-standards-navigator/", "uso": "Divulgação de sustentabilidade e clima orientada a investidores.", "ambito": "Internacional"},
    {"id": "tcfd", "label": "TCFD", "url": "https://www.fsb-tcfd.org/", "uso": "Governação, estratégia, gestão de risco e métricas climáticas.", "ambito": "Internacional"},
    {"id": "tnfd", "label": "TNFD", "url": "https://tnfd.global/", "uso": "Divulgação de dependências, impactos e riscos relacionados com a natureza.", "ambito": "Internacional"},
    {"id": "sdg_compass", "label": "SDG Compass", "url": "https://www.unglobalcompact.org/library/3101", "uso": "Guia GRI/UNGC/WBCSD para alinhar a estratégia com os ODS.", "ambito": "Internacional"},
    {"id": "bcorp", "label": "B Corp", "url": "https://www.bcorporation.net/", "uso": "Certificação de desempenho social e ambiental.", "ambito": "Certificação"},
    {"id": "ecovadis", "label": "EcoVadis", "url": "https://ecovadis.com/", "uso": "Avaliação de sustentabilidade na cadeia de valor.", "ambito": "Certificação"},
    {"id": "sedex", "label": "Sedex", "url": "https://www.sedex.com/", "uso": "Plataforma de dados éticos e de responsabilidade na cadeia de abastecimento.", "ambito": "Certificação"},
]

#: Os 17 ODS e os grupos de indicadores que lhes dão evidência no módulo.
ODS: List[Dict[str, Any]] = [
    {"id": 1, "label": "Erradicar a pobreza", "cor": "#e5243b", "grupos": ["Comunidade", "Emprego"]},
    {"id": 2, "label": "Erradicar a fome", "cor": "#dda63a", "grupos": ["Comunidade"]},
    {"id": 3, "label": "Saúde de qualidade", "cor": "#4c9f38", "grupos": ["Segurança", "Emprego"]},
    {"id": 4, "label": "Educação de qualidade", "cor": "#c5192d", "grupos": ["Formação"]},
    {"id": 5, "label": "Igualdade de género", "cor": "#ff3a21", "grupos": ["Diversidade", "Conselho"]},
    {"id": 6, "label": "Água potável e saneamento", "cor": "#26bde2", "grupos": ["Água"]},
    {"id": 7, "label": "Energias renováveis e acessíveis", "cor": "#fcc30b", "grupos": ["Energia", "Emissões"]},
    {"id": 8, "label": "Trabalho digno e crescimento económico", "cor": "#a21942", "grupos": ["Emprego", "Formação", "Segurança"]},
    {"id": 9, "label": "Indústria, inovação e infraestruturas", "cor": "#fd6925", "grupos": ["Certificações", "Emissões"]},
    {"id": 10, "label": "Reduzir as desigualdades", "cor": "#dd1367", "grupos": ["Diversidade", "Comunidade"]},
    {"id": 11, "label": "Cidades e comunidades sustentáveis", "cor": "#fd9d24", "grupos": ["Comunidade", "Resíduos"]},
    {"id": 12, "label": "Produção e consumo sustentáveis", "cor": "#bf8b2e", "grupos": ["Resíduos", "Compras", "Cadeia de valor"]},
    {"id": 13, "label": "Ação climática", "cor": "#3f7e44", "grupos": ["Emissões", "Energia", "Estratégia"]},
    {"id": 14, "label": "Proteger a vida marinha", "cor": "#0a97d9", "grupos": ["Água"]},
    {"id": 15, "label": "Proteger a vida terrestre", "cor": "#56c02b", "grupos": ["Biodiversidade", "Resíduos"]},
    {"id": 16, "label": "Paz, justiça e instituições eficazes", "cor": "#00689d", "grupos": ["Ética", "Transparência", "Conselho"]},
    {"id": 17, "label": "Parcerias para a implementação", "cor": "#19486a", "grupos": ["Cadeia de valor", "Comunidade"]},
]

#: Percurso de alinhamento do IAPMEI/UN Global Compact (5 passos).
PASSOS: List[Dict[str, Any]] = [
    {"id": 1, "label": "Conhecer o ponto de partida", "descricao": "Inventariar políticas, procedimentos, certificações e práticas já existentes e organizá-las por pilar ESG.", "no_iqos": "Componentes do score, indicadores declarados e certificações."},
    {"id": 2, "label": "Identificar temas materiais", "descricao": "Selecionar as áreas de maior impacto para o negócio e para os stakeholders, ao longo da cadeia de valor.", "no_iqos": "Cruzamento do CAE, CPV dominante e indicadores declarados."},
    {"id": 3, "label": "Alinhar com os ODS", "descricao": "Escolher dois ou três ODS prioritários e associar metas e indicadores.", "no_iqos": "Mapa ODS↔indicadores e ODS↔atividades."},
    {"id": 4, "label": "Medir", "descricao": "Medir o desempenho nas áreas materiais e nos ODS escolhidos.", "no_iqos": "Score por pilar, cobertura, confiança e série de três anos."},
    {"id": 5, "label": "Reportar", "descricao": "Reportar desempenho positivo e negativo, riscos e alinhamento com a Taxonomia e os ODS.", "no_iqos": "Dossiê, taxonomia UE, indicadores e exportação CSV."},
]

#: Temas materiais por secção CAE (ponto de partida do passo 2).
MATERIALIDADE: Dict[str, List[str]] = {
    "A": ["Água", "Biodiversidade", "Resíduos", "Trabalho sazonal"],
    "B": ["Emissões", "Água", "Biodiversidade", "Segurança"],
    "C": ["Emissões", "Energia", "Resíduos", "Cadeia de valor"],
    "D": ["Emissões", "Energia", "Biodiversidade", "Comunidade"],
    "E": ["Água", "Resíduos", "Emissões", "Economia circular"],
    "F": ["Emissões", "Resíduos", "Segurança", "Cadeia de valor"],
    "G": ["Cadeia de valor", "Resíduos", "Direitos humanos", "Consumo"],
    "H": ["Emissões", "Segurança", "Energia", "Comunidade"],
    "I": ["Emprego", "Comunidade", "Água", "Resíduos"],
    "J": ["Energia", "Privacidade", "Emprego", "Diversidade"],
    "K": ["Governação", "Ética", "Clima", "Cadeia de valor"],
    "L": ["Energia", "Emissões", "Resíduos", "Comunidade"],
    "M": ["Ética", "Emprego", "Cadeia de valor", "Clima"],
    "N": ["Emprego", "Segurança", "Direitos humanos", "Cadeia de valor"],
    "O": ["Ética", "Transparência", "Cadeia de valor", "Clima"],
    "P": ["Formação", "Diversidade", "Comunidade", "Emissões"],
    "Q": ["Segurança", "Emprego", "Resíduos", "Comunidade"],
    "R": ["Comunidade", "Emprego", "Resíduos", "Diversidade"],
    "S": ["Emprego", "Formação", "Resíduos", "Cadeia de valor"],
}

def objetivo_de(valor: Any) -> Optional[Dict[str, Any]]:
    """Objetivo oficial por id (aceita `41`, `\"41\"` ou dict)."""
    if isinstance(valor, dict):
        valor = valor.get("id")
    try:
        return dict(OBJETIVO_BY_ID[int(valor)])
    except (KeyError, TypeError, ValueError):
        return None

def secao_de_cae(cae: Optional[str]) -> str:
    """Secção CAE (`A`–`U`) a partir do código, sem depender de `esg_sources`."""
    texto = str(cae or "").strip().upper().replace(".", "").replace("-", "").replace(" ", "")
    letras = "".join(ch for ch in texto if ch.isalpha())
    digitos = "".join(ch for ch in texto if ch.isdigit())
    if letras:
        return letras[0]
    if len(digitos) >= 2:
        return _secao_por_divisao(int(digitos[:2]))
    return ""

def nace_de_cae(cae: Optional[str]) -> str:
    """Normaliza um CAE português para `SECÇÃO` + dígitos (ex.: `F42910`)."""
    texto = str(cae or "").strip().upper().replace(".", "").replace("-", "").replace(" ", "")
    letras = "".join(ch for ch in texto if ch.isalpha())
    digitos = "".join(ch for ch in texto if ch.isdigit())
    secao = letras[:1] or secao_de_cae(cae)
    if not secao or len(digitos) < 2:
        return ""
    return f"{secao}{digitos}"

def _secao_por_divisao(divisao: int) -> str:
    if divisao <= 3:
        return "A"
    if 5 <= divisao <= 9:
        return "B"
    if 10 <= divisao <= 33:
        return "C"
    if divisao == 35:
        return "D"
    if 36 <= divisao <= 39:
        return "E"
    if 41 <= divisao <= 43:
        return "F"
    if 45 <= divisao <= 47:
        return "G"
    if 49 <= divisao <= 53:
        return "H"
    if 55 <= divisao <= 56:
        return "I"
    if 58 <= divisao <= 63:
        return "J"
    if 64 <= divisao <= 66:
        return "K"
    if 68 <= divisao <= 68:
        return "L"
    if 69 <= divisao <= 75:
        return "M"
    if 77 <= divisao <= 82:
        return "N"
    if 84 <= divisao <= 84:
        return "O"
    if 85 <= divisao <= 85:
        return "P"
    if 86 <= divisao <= 88:
        return "Q"
    if 90 <= divisao <= 93:
        return "R"
    if 94 <= divisao <= 96:
        return "S"
    return ""

def normalizar_nace(codigo: Optional[str]) -> str:
    """Normaliza um código NACE do Compass (`F41.1` → `F411`)."""
    texto = str(codigo or "").strip().upper().replace(".", "").replace(" ", "")
    letras = "".join(ch for ch in texto if ch.isalpha())
    digitos = "".join(ch for ch in texto if ch.isdigit())
    if not letras:
        return ""
    if digitos and len(digitos) < 2:
        digitos = digitos.zfill(2)
    return f"{letras[0]}{digitos}"

def atividades_por_nace(cae: Optional[str]) -> List[Dict[str, Any]]:
    """Atividades cujo NACE é prefixo do CAE, das mais específicas para as gerais.

    Um CAE como `42910` (obras de engenharia civil) partilha a divisão `42` com
    muitas atividades. Devolver todas seria ruído; ficam as que têm o prefixo
    NACE mais longo (ex.: `F42.9`/`F42.91`) e as de especificidade imediatamente
    inferior. O `especificidade` permite à UI explicar a força do match.
    """
    alvo = nace_de_cae(cae)
    if not alvo:
        return []
    candidatos: List[Dict[str, Any]] = []
    for atividade in ATIVIDADES:
        melhor = None
        for codigo in atividade.get("nace") or []:
            prefixo = normalizar_nace(codigo)
            if prefixo and alvo.startswith(prefixo):
                if melhor is None or len(prefixo) > len(melhor[0]):
                    melhor = (prefixo, codigo)
        if melhor:
            candidatos.append(
                {
                    **atividade,
                    "match": "nace",
                    "nace_match": melhor[1],
                    "especificidade": len(melhor[0]),
                }
            )
    if not candidatos:
        return []
    maximo = max(item["especificidade"] for item in candidatos)
    minimo = max(2, maximo - 1)
    return sorted(
        (item for item in candidatos if item["especificidade"] >= minimo),
        key=lambda item: (-item["especificidade"], item["nome"]),
    )

def atividades_por_secao(secao: Optional[str]) -> List[Dict[str, Any]]:
    """Atividades do setor do Compass correspondente à secção CAE."""
    alvo = str(secao or "").strip().upper()
    if not alvo:
        return []
    saida = []
    for atividade in ATIVIDADES:
        if SETOR_PARA_SECAO.get(atividade["setor"]) == alvo:
            saida.append({**atividade, "match": "setor", "nace_match": None})
    return saida

def atividades_por_objetivo(objetivo: int) -> List[Dict[str, Any]]:
    return [item for item in ATIVIDADES if any(int(o["id"]) == int(objetivo) for o in item.get("objetivos") or [])]

def url_atividade(activity_id: int) -> str:
    return f"https://ec.europa.eu/sustainable-finance-taxonomy/activities/activity/{int(activity_id)}/view"
'''

p.write_text(header + atividades + footer, encoding="utf-8")
print("ok", len(atividades))
