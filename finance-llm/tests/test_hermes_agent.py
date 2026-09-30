"""Testes do motor do **Hermes Agent** (`api/hermes_agent_settings.py`).

Cobrem o que é determinístico e não depende de Docker nem de Elasticsearch:

- a resolução fornecedor → perfil do Hermes (incluindo os nomes que diferem);
- a construção do plano (o que vai para o `config.yaml` e para o `.env`);
- a escrita/limpeza do `.env` (funções puras);
- o ciclo `apply_settings` e o `diagnose`, com o Docker substituído por dublês.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import hermes_agent_settings as service  # noqa: E402

# Registo de perfis simplificado (o real é lido do container).
REGISTRY = {
    "deepseek": ["DEEPSEEK_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"],
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "xai": ["XAI_API_KEY"],
    "ollama-cloud": ["OLLAMA_API_KEY"],
    "custom": [],
}


# ---------------------------------------------------------------------------
# Perfil do Hermes por fornecedor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "provider, expected",
    [
        ("deepseek", ("deepseek", "DEEPSEEK_API_KEY")),
        ("anthropic", ("anthropic", "ANTHROPIC_API_KEY")),
        ("openrouter", ("openrouter", "OPENROUTER_API_KEY")),
        ("xai", ("xai", "XAI_API_KEY")),
        ("ollama-cloud", ("ollama-cloud", "OLLAMA_API_KEY")),
        ("openai", (None, None)),
        ("groq", (None, None)),
        ("mistral-ai", (None, None)),
        ("ollama", (None, None)),
    ],
)
def test_perfil_por_fornecedor(provider, expected):
    assert service.hermes_provider_for(provider, REGISTRY) == expected


def test_google_usa_o_perfil_gemini_e_a_variavel_da_plataforma():
    # O perfil aceita GOOGLE_API_KEY e GEMINI_API_KEY; a plataforma usa GEMINI_API_KEY.
    assert service.hermes_provider_for("google", REGISTRY) == ("gemini", "GOOGLE_API_KEY")
    assert service.hermes_provider_for("google", REGISTRY, preferred_env="GEMINI_API_KEY") == (
        "gemini",
        "GEMINI_API_KEY",
    )


def test_perfil_sem_variaveis_devolve_nome_sem_env():
    assert service.hermes_provider_for("custom", REGISTRY) == ("custom", None)


# ---------------------------------------------------------------------------
# Plano
# ---------------------------------------------------------------------------
def _settings(**overrides):
    return {**service.DEFAULTS, "llm_custom_key": "sk-personalizada-123456", "search_provider": "off", **overrides}


def test_plano_perfil_nativo_poe_a_chave_no_env():
    plan = service.build_plan(_settings(llm_provider="deepseek"), None, registry=REGISTRY)
    assert plan["config"]["model.provider"] == "deepseek"
    assert plan["config"]["model.default"] == "deepseek-chat"
    # O perfil sabe o endpoint: não se escreve base_url nenhum.
    assert plan["config"]["model.base_url"] is None
    assert plan["config"]["model.api_key"] is None
    assert plan["env"]["DEEPSEEK_API_KEY"] == "sk-personalizada-123456"
    assert "DEEPSEEK_API_KEY" not in plan["clear_env"]


def test_plano_sem_perfil_usa_custom_com_base_url_e_chave():
    plan = service.build_plan(_settings(llm_provider="groq"), None, registry=REGISTRY)
    assert plan["config"]["model.provider"] == "custom"
    assert plan["config"]["model.base_url"] == "https://api.groq.com/openai/v1"
    assert plan["config"]["model.api_key"] == "sk-personalizada-123456"
    # Nada para o `.env` do fornecedor (só a pesquisa, que aqui está desligada).
    assert plan["env"] == {}
    assert "GROQ_API_KEY" in plan["clear_env"]


def test_plano_troca_de_fornecedor_limpa_a_chave_antiga():
    plan = service.build_plan(_settings(llm_provider="anthropic"), None, registry=REGISTRY)
    assert plan["env"]["ANTHROPIC_API_KEY"]
    assert "DEEPSEEK_API_KEY" in plan["clear_env"]
    assert "OPENROUTER_API_KEY" in plan["clear_env"]


def test_plano_avisa_quando_nao_ha_chave(monkeypatch):
    monkeypatch.setattr(service.providers_service, "resolve_key", lambda user_id, provider: ("", "none"))
    plan = service.build_plan({**service.DEFAULTS, "llm_provider": "deepseek", "search_provider": "off"}, None, registry=REGISTRY)
    assert plan["env"] == {}
    assert any("ainda não tem chave" in note for note in plan["notes"])


def test_plano_fornecedor_desconhecido_nao_escreve_nada(monkeypatch):
    monkeypatch.setattr(service.providers_service, "resolve_key", lambda user_id, provider: ("sk-x", "user"))
    plan = service.build_plan(_settings(llm_provider="fornecedor-que-nao-existe"), None, registry=REGISTRY)
    assert plan["config"] == {}
    assert plan["env"] == {}
    assert plan["clear_env"] == list(service.MANAGED_ENV_KEYS)
    assert "desconhecido" in plan["notes"][0].lower()


def test_plano_reescreve_loopback_para_o_host():
    plan = service.build_plan(
        _settings(llm_provider="ollama", llm_base_url="http://127.0.0.1:11434/v1"),
        None,
        registry=REGISTRY,
    )
    assert plan["config"]["model.base_url"] == "http://host.docker.internal:11434/v1"


def test_plano_com_searxng_da_plataforma():
    plan = service.build_plan(
        _settings(llm_provider="deepseek", search_provider="searxng", searxng_url="http://searxng:8080"),
        None,
        registry=REGISTRY,
    )
    assert plan["env"]["SEARXNG_URL"] == "http://searxng:8080"
    assert any("SearXNG" in note for note in plan["notes"])


def test_plano_com_brave_usa_a_chave_da_plataforma(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "brave-da-plataforma")
    plan = service.build_plan(
        _settings(llm_provider="deepseek", search_provider="brave", brave_key=""), None, registry=REGISTRY
    )
    assert plan["env"]["BRAVE_SEARCH_API_KEY"] == "brave-da-plataforma"


def test_plano_com_brave_sem_chave_avisa():
    plan = service.build_plan(
        _settings(llm_provider="deepseek", search_provider="brave", brave_key=""), None, registry=REGISTRY
    )
    assert "BRAVE_SEARCH_API_KEY" not in plan["env"]
    assert any("Brave escolhida mas sem chave" in note for note in plan["notes"])


def test_plano_respeita_o_modelo_indicado_pelo_utilizador():
    plan = service.build_plan(
        _settings(llm_provider="deepseek", llm_model="deepseek-reasoner"), None, registry=REGISTRY
    )
    assert plan["config"]["model.default"] == "deepseek-reasoner"


# ---------------------------------------------------------------------------
# `.env` — funções puras
# ---------------------------------------------------------------------------
def test_env_names_ignora_vazias_e_comentarios():
    texto = "# comentário\nA=1\nB=\n\nC=3\n#D=4\n"
    assert service._env_names(texto) == ["A", "C"]


def test_upsert_env_escreve_e_preserva():
    original = "BROWSER_TIMEOUT=30\nCUSTOM=fica\n"
    novo, escritos, removidos = service.upsert_env(original, {"DEEPSEEK_API_KEY": "sk-nova"})
    assert escritos == ["DEEPSEEK_API_KEY"]
    assert removidos == []
    assert "BROWSER_TIMEOUT=30" in novo
    assert "CUSTOM=fica" in novo
    assert "DEEPSEEK_API_KEY=sk-nova" in novo
    assert service.ENV_HEADER in novo


def test_upsert_env_substitui_a_chave_gerida_que_existe():
    original = "DEEPSEEK_API_KEY=antiga\nOUTRA=1\n"
    novo, escritos, removidos = service.upsert_env(original, {"DEEPSEEK_API_KEY": "nova"})
    assert escritos == ["DEEPSEEK_API_KEY"]
    assert "DEEPSEEK_API_KEY=nova" in novo
    assert "DEEPSEEK_API_KEY=antiga" not in novo
    assert "OUTRA=1" in novo
    assert "nova" not in removidos


def test_upsert_env_remove_as_geridas_que_sobraram():
    original = "DEEPSEEK_API_KEY=antiga\nOPENROUTER_API_KEY=velha\nKEEP=1\n"
    novo, escritos, removidos = service.upsert_env(original, {"ANTHROPIC_API_KEY": "nova"})
    assert escritos == ["ANTHROPIC_API_KEY"]
    assert set(removidos) == {"DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"}
    assert "DEEPSEEK_API_KEY" not in novo
    assert "OPENROUTER_API_KEY" not in novo
    assert "KEEP=1" in novo


def test_upsert_env_nao_duplica_o_cabecalho():
    original = f"A=1\n\n{service.ENV_HEADER}\nB=2\n"
    novo, _, _ = service.upsert_env(original, {"C": "3"})
    assert novo.count(service.ENV_HEADER) == 1


def test_upsert_env_idempotente():
    primeiro, _, _ = service.upsert_env("", {"X": "1"})
    segundo, _, _ = service.upsert_env(primeiro, {"X": "1"})
    assert primeiro == segundo


# ---------------------------------------------------------------------------
# Máscaras e URLs
# ---------------------------------------------------------------------------
def test_mask_nao_mostra_a_chave():
    assert service._mask("") == ""
    assert service._mask("abc") == "•••"
    assert service._mask("sk-1234567890abcdef") == "sk-1…cdef"


def test_container_url():
    assert service._container_url("") == ""
    assert service._container_url("https://api.openai.com/v1") == "https://api.openai.com/v1"
    assert service._container_url("http://localhost:1234/v1") == "http://host.docker.internal:1234/v1"
    assert service._container_url("http://127.0.0.1") == "http://host.docker.internal"


# ---------------------------------------------------------------------------
# Aplicar e diagnosticar (com o Docker substituído)
# ---------------------------------------------------------------------------
@pytest.fixture()
def duble_container(monkeypatch):
    """Simula o container: guarda o `config.yaml` e o `.env` em memória."""
    estado = {
        "config": {
            "model.provider": "auto",
            "model.default": "anthropic/claude-opus-4.6",
            "model.base_url": "https://openrouter.ai/api/v1",
            "model.api_key": None,
        },
        "env": "# exemplo\nBROWSER_TIMEOUT=30\n",
        "chamadas": [],
        "recriado": 0,
    }

    monkeypatch.setattr(service, "docker_path", lambda: "docker")
    monkeypatch.setattr(service, "container_running", lambda: True)

    def fake_read_config(keys):
        estado["chamadas"].append(("get", tuple(keys)))
        return {key: estado["config"].get(key) for key in keys}

    def fake_apply_config(config):
        for key, value in config.items():
            estado["chamadas"].append(("config", key, value))
            estado["config"][key] = value if value not in (None, "") else None
        return [f"{key}={value}" if value not in (None, "") else f"-{key}" for key, value in config.items()]

    def fake_read_env():
        return estado["env"]

    def fake_write_env(text):
        estado["env"] = text
        estado["chamadas"].append(("env",))

    def fake_recreate(timeout=service.RECREATE_TIMEOUT):
        estado["recriado"] += 1
        return "Container finance-llm-hermes-agent  Recreated"

    monkeypatch.setattr(service, "read_config_values", fake_read_config)
    monkeypatch.setattr(service, "apply_config", fake_apply_config)
    monkeypatch.setattr(service, "read_container_env", fake_read_env)
    monkeypatch.setattr(service, "write_container_env", fake_write_env)
    monkeypatch.setattr(service, "compose_recreate", fake_recreate)
    monkeypatch.setattr(service, "provider_registry", lambda force=False: REGISTRY)
    monkeypatch.setattr(service, "read_settings", lambda: dict(estado.get("settings") or {}))
    monkeypatch.setattr(service, "save_settings", lambda patch, user="": {**estado.get("settings", {}), **patch})
    monkeypatch.setattr(service.providers_service, "resolve_key", lambda user_id, provider: ("sk-da-plataforma-1234", "user"))
    return estado


def test_apply_settings_escreve_no_container_e_recria(duble_container):
    duble_container["settings"] = {
        **service.DEFAULTS,
        "llm_provider": "deepseek",
        "search_provider": "searxng",
        "searxng_url": "http://searxng:8080",
    }
    out = service.apply_settings(None, "qa", recreate=True)

    assert out["recreated"] is True
    assert duble_container["recriado"] == 1
    assert duble_container["config"]["model.provider"] == "deepseek"
    assert duble_container["config"]["model.default"] == "deepseek-chat"
    assert duble_container["config"]["model.base_url"] is None
    assert "DEEPSEEK_API_KEY=sk-da-plataforma-1234" in duble_container["env"]
    assert "SEARXNG_URL=http://searxng:8080" in duble_container["env"]
    assert set(out["env_written"]) == {"DEEPSEEK_API_KEY", "SEARXNG_URL"}


def test_apply_settings_nao_devolve_a_chave_em_claro(duble_container):
    duble_container["settings"] = {**service.DEFAULTS, "llm_provider": "deepseek"}
    out = service.apply_settings(None, "qa", recreate=False)
    assert "sk-da-plataforma-1234" not in str(out["resolved"])
    assert out["resolved"]["key"].startswith("sk-d")


def test_apply_settings_sem_chave_falha_claro(duble_container, monkeypatch):
    monkeypatch.setattr(service.providers_service, "resolve_key", lambda user_id, provider: ("", "none"))
    duble_container["settings"] = {**service.DEFAULTS, "llm_provider": "deepseek", "search_provider": "off"}
    with pytest.raises(RuntimeError) as exc:
        service.apply_settings(None, "qa", recreate=False)
    assert "Nada para aplicar" in str(exc.value)


def test_apply_settings_sem_docker_explica_o_que_fazer(monkeypatch):
    monkeypatch.setattr(service, "docker_path", lambda: None)
    monkeypatch.setattr(service, "provider_registry", lambda force=False: REGISTRY)
    monkeypatch.setattr(service, "read_settings", lambda: {**service.DEFAULTS, "llm_provider": "deepseek"})
    monkeypatch.setattr(service.providers_service, "resolve_key", lambda user_id, provider: ("sk-x", "user"))
    with pytest.raises(RuntimeError) as exc:
        service.compose_recreate()
    assert "docker" in str(exc.value).lower()


def test_diagnose_marca_em_sincronia(duble_container):
    duble_container["settings"] = {
        **service.DEFAULTS,
        "llm_provider": "deepseek",
        "search_provider": "searxng",
        "searxng_url": "http://searxng:8080",
    }
    # Aplica e depois diagnostica: tem de ficar em sincronia.
    service.apply_settings(None, "qa", recreate=False)
    report = service.diagnose(None)
    assert report["in_sync"] is True
    assert report["problems"] == []
    assert report["config"]["model.provider"] == "deepseek"
    assert "DEEPSEEK_API_KEY" in report["env_keys"]
    # A chave do config.yaml (se existisse) sai mascarada.
    assert not report["config"].get("model.api_key")


def test_diagnose_detetou_o_estado_por_configurar(duble_container):
    duble_container["settings"] = {
        **service.DEFAULTS,
        "llm_provider": "deepseek",
        "search_provider": "searxng",
        "searxng_url": "http://searxng:8080",
    }
    report = service.diagnose(None)
    assert report["in_sync"] is False
    assert report["config"]["model.provider"] == "auto"
    assert any("não tem chave" in problem for problem in report["problems"])
    assert any("não está com o fornecedor" in problem for problem in report["problems"])


def test_diagnose_sem_docker_avisa(monkeypatch):
    monkeypatch.setattr(service, "docker_path", lambda: None)
    monkeypatch.setattr(service, "provider_registry", lambda force=False: REGISTRY)
    monkeypatch.setattr(service, "read_settings", lambda: dict(service.DEFAULTS))
    monkeypatch.setattr(service.providers_service, "resolve_key", lambda user_id, provider: ("sk-x", "user"))
    report = service.diagnose(None)
    assert report["docker_available"] is False
    assert report["in_sync"] is False
    assert any("docker" in problem for problem in report["problems"])


def test_diagnose_com_container_parado(monkeypatch):
    monkeypatch.setattr(service, "docker_path", lambda: "docker")
    monkeypatch.setattr(service, "container_running", lambda: False)
    monkeypatch.setattr(service, "provider_registry", lambda force=False: REGISTRY)
    monkeypatch.setattr(service, "read_settings", lambda: dict(service.DEFAULTS))
    monkeypatch.setattr(service.providers_service, "resolve_key", lambda user_id, provider: ("sk-x", "user"))
    report = service.diagnose(None)
    assert report["running"] is False
    assert any("não está a correr" in problem for problem in report["problems"])


# ---------------------------------------------------------------------------
# Candidatos e vista
# ---------------------------------------------------------------------------
def test_llm_candidates_mostra_modo_e_origem(duble_container):
    candidatos = service.llm_candidates(None)
    por_id = {item["id"]: item for item in candidatos}
    assert por_id["deepseek"]["hermes_provider"] == "deepseek"
    assert por_id["deepseek"]["mode"] == "perfil nativo"
    assert por_id["deepseek"]["key_hint"].startswith("sk-d")
    assert por_id["groq"]["mode"] == "custom (OpenAI-compatível)"
    assert por_id["groq"]["hermes_provider"] is None


def test_settings_view_nao_mostra_chaves(duble_container):
    duble_container["settings"] = {**service.DEFAULTS, "llm_provider": "deepseek"}
    view = service.settings_view(None, "qa@iqos.local")
    texto = str(view)
    assert "sk-da-plataforma-1234" not in texto
    assert view["settings"]["llm_provider"] == "deepseek"
    assert view["about"]["container"] == service.CONTAINER
    assert view["search_providers"]
    assert view["commands"]["apply"].startswith("docker compose")
    assert view["plan"]["config"]["model.provider"] == "deepseek"


def test_settings_view_marca_chave_personalizada_sem_a_mostrar(duble_container):
    duble_container["settings"] = {**service.DEFAULTS, "llm_provider": "deepseek", "llm_custom_key": "sk-segredo-9999"}
    view = service.settings_view(None)
    assert view["settings"]["llm_custom_key_set"] is True
    assert "sk-segredo-9999" not in str(view)
    assert view["resolved"]["source"] == "custom"


def test_settings_view_mostra_remocao_em_vez_de_chave_mascarada(duble_container):
    # No perfil nativo, `model.api_key` e `model.base_url` são removidos: o plano
    # tem de dizer «remover» (None), não uma chave mascarada sem sentido.
    duble_container["settings"] = {**service.DEFAULTS, "llm_provider": "deepseek"}
    view = service.settings_view(None)
    assert view["plan"]["config"]["model.api_key"] is None
    assert view["plan"]["config"]["model.base_url"] is None
    assert "••" not in str(view["plan"]["config"])


def test_mask_value_nao_mascara_vazio():
    assert service._mask_value("model.api_key", None) is None
    assert service._mask_value("model.api_key", "") == ""
    assert service._mask_value("model.api_key", "sk-1234567890") == "sk-1…7890"
    # Chaves que não são segredos ficam intactas.
    assert service._mask_value("model.default", "deepseek-chat") == "deepseek-chat"
