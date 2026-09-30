"""Testes das definições do MiroFish (`api/mirofish_settings.py`).

Cobrem o essencial: máscaras, escrita do `.env` (upsert sem estragar o resto do
ficheiro), resolução da chave do LLM a partir dos fornecedores da plataforma e o
que é escrito quando se aplica. Nada disto toca em rede nem em Docker.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import mirofish_settings as settings  # noqa: E402
from api import providers_service  # noqa: E402


@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    """`.env` isolado num diretório temporário."""
    path = tmp_path / ".env"
    path.write_text("# comentário inicial\nFINANCE_API_PORT=8003\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ENV_FILE", path)
    monkeypatch.setattr(settings, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(settings, "COMPOSE_FILE", tmp_path / "docker-compose.yml")
    return path


def test_mask_esconde_o_segredo():
    assert settings.mask("") == ""
    assert settings.mask("curta") == "•" * 5
    value = "sk-1234567890abcdef"
    assert settings.mask(value) == "sk-…cdef"
    assert value not in settings.mask(value)


def test_write_env_acrescenta_e_preserva_o_resto(env_file):
    written = settings.write_env({"MIROFISH_LLM_API_KEY": "sk-nova", "MIROFISH_ZEP_API_KEY": "zep-123"})
    assert sorted(written) == ["MIROFISH_LLM_API_KEY", "MIROFISH_ZEP_API_KEY"]
    text = env_file.read_text(encoding="utf-8")
    assert "FINANCE_API_PORT=8003" in text  # não mexe no que já existia
    assert "MIROFISH_LLM_API_KEY=sk-nova" in text
    assert "MIROFISH_ZEP_API_KEY=zep-123" in text
    assert settings.SECTION_HEADER in text
    assert settings.env_values()["MIROFISH_LLM_API_KEY"] == "sk-nova"


def test_write_env_atualiza_sem_duplicar(env_file):
    settings.write_env({"MIROFISH_LLM_API_KEY": "sk-1"})
    settings.write_env({"MIROFISH_LLM_API_KEY": "sk-2"})
    text = env_file.read_text(encoding="utf-8")
    assert text.count("MIROFISH_LLM_API_KEY=") == 1
    assert "MIROFISH_LLM_API_KEY=sk-2" in text


def test_write_env_ignora_linha_gerida_fora_da_seccao(env_file):
    env_file.write_text("MIROFISH_ZEP_API_KEY=antiga\n# outra linha\n", encoding="utf-8")
    settings.write_env({"MIROFISH_ZEP_API_KEY": "nova"})
    text = env_file.read_text(encoding="utf-8")
    assert text.count("MIROFISH_ZEP_API_KEY=") == 1
    assert "MIROFISH_ZEP_API_KEY=nova" in text
    assert "# outra linha" in text


def test_write_env_nao_escreve_valores_vazios(env_file):
    assert settings.write_env({"MIROFISH_LLM_API_KEY": "  ", "MIROFISH_ZEP_API_KEY": ""}) == []
    assert "MIROFISH" not in env_file.read_text(encoding="utf-8")


def test_write_env_falha_com_mensagem_util(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ENV_FILE", tmp_path / "sem-permissao" / ".env")
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("negado")))
    with pytest.raises(RuntimeError) as exc:
        settings.write_env({"MIROFISH_LLM_API_KEY": "sk-x"})
    assert "docker compose --profile mirofish up -d --force-recreate mirofish" in str(exc.value)


def test_resolve_llm_usa_a_chave_da_plataforma(monkeypatch):
    monkeypatch.setattr(providers_service, "resolve_key", lambda user_id, provider: ("sk-plataforma", "user"))
    monkeypatch.setattr(providers_service, "resolve_provider_url", lambda user_id, provider: None)
    monkeypatch.setattr(providers_service, "resolve_provider_model", lambda user_id, provider: None)

    llm = settings.resolve_llm({"llm_provider": "deepseek"}, "user-1")
    assert llm["key"] == "sk-plataforma"
    assert llm["source"] == "user"
    assert llm["base_url"] == "https://api.deepseek.com/v1"  # do catálogo do fornecedor
    assert llm["model"] == "deepseek-chat"


def test_resolve_llm_prefere_chave_personalizada(monkeypatch):
    monkeypatch.setattr(providers_service, "resolve_key", lambda user_id, provider: ("sk-plataforma", "user"))
    llm = settings.resolve_llm({"llm_provider": "deepseek", "llm_custom_key": "sk-minha", "llm_model": "deepseek-reasoner"}, None)
    assert llm["key"] == "sk-minha"
    assert llm["source"] == "custom"
    assert llm["model"] == "deepseek-reasoner"


def test_resolve_llm_sem_fornecedor():
    llm = settings.resolve_llm({"llm_provider": ""}, None)
    assert llm == {"key": "", "base_url": "", "model": "", "source": "none", "provider": ""}


def test_apply_settings_escreve_e_nao_recria(env_file, monkeypatch):
    monkeypatch.setattr(settings, "load_settings", lambda: {"llm_provider": "deepseek", "llm_custom_key": "sk-minha-chave-de-teste-9999", "zep_api_key": "zep-chave-de-teste-1234", "llm_model": "", "llm_base_url": ""})
    monkeypatch.setattr(settings, "save_settings", lambda patch, actor=None: {})
    chamadas: list = []
    monkeypatch.setattr(settings, "compose_recreate", lambda timeout=600.0: chamadas.append(True) or {"ok": True, "command": "docker compose ..."})

    result = settings.apply_settings(None, recreate=False)
    assert result["written"] == [
        "MIROFISH_LLM_API_KEY",
        "MIROFISH_LLM_BASE_URL",
        "MIROFISH_LLM_MODEL_NAME",
        "MIROFISH_ZEP_API_KEY",
    ]
    assert result["llm"]["key_hint"] == "sk-…9999"
    assert result["zep"]["key_hint"] == "zep…1234"
    assert result["recreate"] is None
    assert chamadas == []
    text = env_file.read_text(encoding="utf-8")
    assert "MIROFISH_ZEP_API_KEY=zep-chave-de-teste-1234" in text


def test_apply_settings_sem_chaves_avisa(env_file, monkeypatch):
    monkeypatch.setattr(settings, "load_settings", lambda: {"llm_provider": "", "llm_custom_key": "", "zep_api_key": ""})
    with pytest.raises(RuntimeError) as exc:
        settings.apply_settings(None, recreate=False)
    assert "Zep" in str(exc.value)


def test_settings_view_nao_expoe_chaves(env_file, monkeypatch):
    monkeypatch.setattr(settings, "load_settings", lambda: {"llm_provider": "deepseek", "llm_custom_key": "sk-segredo-muito-longo", "zep_api_key": "zep-segredo", "llm_model": "", "llm_base_url": "", "updated_at": None, "updated_by": None, "applied_at": None})
    monkeypatch.setattr(settings, "llm_candidates", lambda user_id=None: [])

    view = settings.settings_view(None)
    payload = str(view)
    assert "sk-segredo-muito-longo" not in payload
    assert "zep-segredo" not in payload
    assert view["settings"]["llm_key_hint"] == "sk-…ongo"
    assert view["settings"]["zep_key_set"] is True
    assert "docker compose --profile mirofish up -d --force-recreate mirofish" in view["commands"]["apply"]
