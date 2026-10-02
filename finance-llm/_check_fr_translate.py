"""Verificação temporária da tradução FR→PT dos contratos."""
import json

from api.contratos_fr_translate import cache_status, translate_texts

TEXTOS = [
    "Travaux de construction d'une école maternelle",
    "Marché de partenariat",
    "Appel d'offres ouvert",
    "Fourniture de repas pour la restauration scolaire (lot 2)",
    "Code postal",
]

print("antes:", cache_status())
resultado = translate_texts(TEXTOS)
print("erro:", resultado.get("error"))
print("ia:", resultado.get("ai"))
print("pedidos:", resultado.get("requested"), "| cache:", resultado.get("cached"), "| traduzidos:", resultado.get("translated"), "| falhas:", resultado.get("failed"))
for original, traduzido in (resultado.get("translations") or {}).items():
    print(f"  {original!r}\n    -> {traduzido!r}")
print("depois:", cache_status())

# segunda passagem: tudo deve vir da cache (0 traduzidos)
repetido = translate_texts(TEXTOS)
print("2.a passagem -> traduzidos:", repetido.get("translated"), "| cache:", repetido.get("cached"))
