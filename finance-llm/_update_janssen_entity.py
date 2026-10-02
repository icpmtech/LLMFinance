import sys, json
from datetime import datetime, timezone
sys.path.insert(0, 'c:/LLMFinance/finance-llm')
from api.elasticsearch_client import get_es_client, ensure_indices, ENTITIES_INDEX

NIF = '500189412'
now = datetime.now(timezone.utc).isoformat()

enrichment = {
    "legal_name": "Janssen - Cilag Farmacêutica Lda - Sociedade por Quotas",
    "legal_form": "Sociedade por Quotas",
    "cae_code": "46460",
    "cae_description": "Comércio por grosso de produtos farmacêuticos e médicos",
    "activity_summary": "Comércio por grosso de produtos farmacêuticos e médicos; investigação, desenvolvimento e comercialização de medicamentos inovadores. Pertence ao grupo Johnson & Johnson Innovative Medicine.",
    "capital_social": "2.693.508,64 EUR",
    "capital_social_euros": 2693508.64,
    "crc": "Registada na Conservatória do Registo Comercial de Oeiras sob o n.º 10576",
    "crc_number": "10576",
    "crc_office": "Oeiras",
    "addresses": [
        {
            "kind": "sede_social",
            "label": "Sede Social",
            "street": "Lagoas Park - Edifício 9",
            "locality": "Porto Salvo",
            "postal_code": "2740-262",
            "country": "PT",
            "country_code": "PT",
            "geo": {"lat": 38.713605, "lon": -9.311199}
        },
        {
            "kind": "outro",
            "label": "Outro estabelecimento",
            "street": "Estrada Consiglieri Pedroso, 69 A - Queluz de Baixo",
            "locality": "Barcarena",
            "postal_code": "2734-503",
            "country": "PT",
            "country_code": "PT",
            "geo": {"lat": 38.74252, "lon": -9.26808}
        }
    ],
    "contacts": {
        "phone": "214 368 600",
        "phone2": "912 887 192",
        "fax": "214 357 506",
        "email": "doc.info@its.jnj.com",
        "email_pt": "jnj_im_pt@its.jnj.com",
        "website": "https://www.janssen.com/portugal/",
        "website_group": "https://www.jnj.com/innovativemedicine/portugal/",
        "linkedin": "https://pt.linkedin.com/company/janssen-cilag-farmacêutica-lda"
    },
    "parent_company": {
        "name": "Johnson & Johnson Innovative Medicine",
        "former_name": "Janssen Pharmaceutical Companies of Johnson & Johnson",
        "group": "Johnson & Johnson",
        "relationship": "subsidiária / unidade de negócio"
    },
    "brands": [
        "J & J GROUP",
        "JANSSEN",
        "JANSSEN-CILAG",
        "JANSSEN-CILAG FARMACÊUTICA, Lda"
    ],
    "aliases": [
        "Janssen-Cilag Farmacêutica, Lda.",
        "Johnson & Johnson Innovative Medicine Portugal",
        "Janssen Portugal"
    ],
    "news": [
        {
            "date": "2024",
            "headline": "Janssen passa a denominar-se Johnson & Johnson Innovative Medicine",
            "url": "https://justnews.pt/noticias/janssen-passa-a-denominarse-johnson-e-johnson-innovative-medicine",
            "source": "JustNews"
        }
    ],
    "enrichment": {
        "source": "web_search_searxng_scraper",
        "enriched_at": now,
        "tools_used": ["searxng", "scraper_service", "mcp_iq_os2_empresa_enriquecer"],
        "websites": [
            "https://www.indice.eu/pt/medicamentos/laboratorios/janssen-cilag-farmaceutica-lda/informacao-geral",
            "https://www.racius.com/janssen-cilag-farmaceutica-lda/",
            "https://www.einforma.pt/servlet/app/portal/ENTP/prod/ETIQUETA_EMPRESA_CONTRIBUINTE/nif/500189412/contribuinte/500189412",
            "https://www.jnj.com/innovativemedicine/portugal/sobre-nos/contatos",
            "https://www.jnj.com/innovativemedicine/portugal/aviso-legal",
            "https://justnews.pt/noticias/janssen-passa-a-denominarse-johnson-e-johnson-innovative-medicine"
        ]
    }
}

client = get_es_client()
ensure_indices(client)
doc_id = f"{ENTITIES_INDEX}:{NIF}"

try:
    resp = client.update(
        index=ENTITIES_INDEX,
        id=doc_id,
        body={"doc": enrichment, "doc_as_upsert": False},
        refresh=True,
    )
    print('update result:', resp.get('result'))
except Exception as e:
    print('update error:', type(e).__name__, e)
    sys.exit(1)

# verify
hit = client.get(index=ENTITIES_INDEX, id=doc_id)
source = hit['_source']
print('stored keys:', sorted(source.keys()))
print('name:', source.get('name'))
print('address:', source.get('addresses', [{}])[0])
print('contacts:', source.get('contacts'))
print('capital:', source.get('capital_social'))
print('cae:', source.get('cae_code'), source.get('cae_description'))
