import io, sys
sys.path.insert(0, r'C:\LLMFinance\finance-llm')
from collectors import racius

cases = [
    ("Benavente", "Santarém"),
    ("Sé", "Funchal"),
    ("Alcobaça", "Leiria"),
    ("Oeiras", "Lisboa"),
    ("Oeiras e São Julião Barra", "Oeiras"),
    ("Santa Cruz", "Coimbra"),
    ("Funchal", "Madeira"),
    ("Porto", "Porto"),
    ("Matosinhos", "Porto"),
    ("Forma Jurídica", "Sociedade por Quotas"),
    ("Horta", "Açores"),
]
for label, value in cases:
    print(f"{label!r:35} {value!r:25} -> {racius.resolve_geo(label, value)}")

print("\nlocalizacao:", [racius._geo_from_localizacao(x) for x in
                         ["Samora Correia, Benavente", "Fafe", "Portugal", "Sé, Funchal"]])

html = io.open(r'C:\LLMFinance\_tmp_racius_detail.html', encoding='utf-8').read()
doc = racius.parse_detail(html)
print("\nparse_detail:", {k: doc.get(k) for k in ("concelho", "distrito", "localidade", "morada")})
