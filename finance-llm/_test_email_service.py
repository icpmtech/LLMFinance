"""Verificação rápida do serviço de Email (funções puras, sem rede)."""
import email as email_lib
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("email_service", "api/email_service.py")
service = importlib.util.module_from_spec(spec)
sys.modules["email_service"] = service
spec.loader.exec_module(service)

print("fornecedores:", len(service.PROVIDERS))
print("presets:", ", ".join(entry["id"] for entry in service.PROVIDERS))

for name in ("Caixa de Entrada", "Enviados", "Rascunhos/Rascunho", "A&B", "INBOX"):
    encoded = service._utf7_encode(name)
    decoded = service._utf7_decode(encoded)
    assert decoded == name, (name, encoded, decoded)
    print(f"utf7 OK: {name!r} -> {encoded!r} -> {decoded!r}")

listing = r'(\HasNoChildren) "/" "INBOX"'
print("pasta:", service._folder_from_listing(listing))
listing2 = r'(\HasNoChildren \Sent) "." "Enviados"'
print("pasta 2:", service._folder_from_listing(listing2))

# Pastas com acentos: o `id` devolvido é legível e o serviço volta a codificá-lo
# antes de falar com o servidor (evita a dupla codificação).
accented = "Enviados/Adiantamentos & Notas"
raw_name = service._utf7_encode(accented)
parsed = service._folder_from_listing(f'(\\HasNoChildren \\Sent) "/" "{raw_name}"')
assert parsed["id"] == accented, parsed
assert service._utf7_encode(parsed["id"]) == raw_name, parsed
print("pasta com acentos:", parsed["id"], "->", parsed["label"], "| reencoda OK")

print("endereços:", service._address_list('"Ana Silva" <ana@x.pt>, joao@y.pt'))

raw = b"Subject: =?utf-8?B?T2zDoQ==?=\r\nFrom: a@b.pt\r\nDate: Mon, 1 Sep 2025 10:00:00 +0000\r\n\r\ncorpo\r\n"
message = email_lib.message_from_bytes(raw)
print("assunto:", service._decode_header(message.get("Subject")))
print("data:", service._iso_date(message.get("Date")))

print("html->texto:", service._snippet(service._html_to_text("<p>Ol&#225; <b>mundo</b></p>")))
print("snippet:", service._snippet("linha1\nlinha2   espaços"))

catalog = service.provider_catalog()
print("catalogo:", catalog["total"], "itens")
print("stats vazio:", service.stats("ninguem@x.pt"))
print("conta invalida:", end=" ")
try:
    service.save_account("x@y.pt", {"email_address": "sem-arroba"})
except service.EmailError as exc:
    print(exc.message, "| status", exc.status)

draft = service.account_from_payload("x@y.pt", {"provider": "outlook", "email_address": "a@b.pt", "password": "segredo"})
print("preset outlook:", draft["imap_host"], draft["imap_port"], draft["smtp_host"], draft["smtp_port"], draft["smtp_security"])
public = service._public_account(draft)
assert "password" not in public and public["has_password"] is True
print("conta pública sem segredo: OK")

print("tudo verificado.")

# Erros de ligação devem ser legíveis e não rebentar a API.
bad = service.account_from_payload(
    "x@y.pt",
    {
        "provider": "custom",
        "email_address": "a@b.pt",
        "password": "x",
        "imap_host": "imap.invalido.invalid",
        "smtp_host": "smtp.invalido.invalid",
        "imap_port": 993,
        "smtp_port": 587,
    },
)
try:
    service.test_account(bad)
    print("erro de ligação: não detetado (inesperado)")
except service.EmailError as exc:
    print(f"erro de ligação tratado: status={exc.status} :: {exc.message[:90]}")
except Exception as exc:  # noqa: BLE001
    print(f"erro de ligação NÃO tratado: {type(exc).__name__}: {exc}")
