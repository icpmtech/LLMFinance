"""Que fornecedor de IA a *solução* tem configurado? (diagnóstico)

Mostra, por utilizador: o fornecedor/modelo predefinidos, que fornecedores têm
chave (do utilizador ou do ambiente) e o que `pick_provider` escolhe com e sem
`user_id` — é esta última diferença que fazia a sonda cair no Ollama local
(lento) mesmo com um fornecedor cloud configurado.

Uso::

    python -u /app/logs/_diag_provider_configurado.py
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import auth_service  # noqa: E402
from api import providers_service as providers  # noqa: E402
from api import scraper_ai  # noqa: E402

users = auth_service.list_users(50) or []
print(f"utilizadores: {len(users)}")
for user in users[:6]:
    uid = str(user.get("id") or user.get("email") or "")
    config = providers.load_user_config(uid)
    defaults = config.get("defaults") or {}
    chaves = {
        pid: providers.resolve_key(uid, pid)[1]
        for pid in ("openai", "deepseek", "anthropic", "google", "groq", "mistral-ai", "openrouter", "xai", "ollama", "ollama-cloud")
    }
    com_chave = {pid: origem for pid, origem in chaves.items() if origem != "none"}
    print(f"\n  utilizador: {uid or '(sem id)'}")
    print(f"    predefinido: {defaults.get('provider') or '—'} / {defaults.get('model') or '—'}")
    print(f"    com chave  : {com_chave or '—'}")
    provider_id, spec, model_id, chave = scraper_ai.pick_provider(uid)
    print(f"    pick_provider(user): {provider_id} · {model_id} · chave={'sim' if chave else 'não'}")

provider_id, spec, model_id, chave = scraper_ai.pick_provider(None)
print(f"\npick_provider(sem user): {provider_id} · {model_id} · chave={'sim' if chave else 'não'}")
print("variáveis com chave definida:", [p for p in providers.PROVIDERS if providers.env_key(p["id"])])
