"""Hermes Agent sem `docker`: o backend escreve no **volume** do agente.

O backend corre em container e não tem o CLI do `docker` nem o socket; mas o
volume `hermes-data` que o agente vê em `/opt/data` está montado nele. Antes,
qualquer operação rebentava com

    RuntimeError: O comando `docker` não está disponível neste processo…

Estes testes fixam o novo modo «volume»:

- deteção do modo (`docker` / `volume` / `none`) e leitura do estado;
- `config.yaml` editado **cirurgicamente** (só a linha da chave, comentários
  intactos), com cópia de segurança e validação antes de gravar;
- `.env` lido e escrito preservando dono e permissões;
- perfil de modelo nativo mesmo sem ler o container (instantâneo);
- `apply_settings` escreve e **avisa** que é preciso reiniciar o container, em
  vez de falhar.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import hermes_agent_settings as hermes  # noqa: E402

CONFIG_EXEMPLO = '''# Hermes Agent CLI Configuration
# `hermes config set <section.key> <value>` atualiza esta secção.
_config_version: 46

model:
  # Default model to use (can be overridden with --model flag)
  default: "deepseek-chat"

  # Inference provider selection:
  #   "auto"         - Auto-detect from credentials (default)
  #   "openrouter"   - OpenRouter
  provider: "auto"

  # API configuration
  # api_key: "your-key-here"
  # base_url: "https://..."

kanban:
  review_dispatch: true
'''

ENV_EXEMPLO = "DEEPSEEK_API_KEY=chave-antiga\n# comentário\nOUTRA=1\n"


@pytest.fixture()
def volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Volume do Hermes montado em `tmp_path`, sem `docker` neste processo."""
    (tmp_path / "config.yaml").write_text(CONFIG_EXEMPLO, encoding="utf-8")
    (tmp_path / ".env").write_text(ENV_EXEMPLO, encoding="utf-8")
    (tmp_path / "gateway.pid").write_text("1234\n", encoding="utf-8")
    monkeypatch.setattr(hermes, "docker_path", lambda: None)
    monkeypatch.setattr(hermes, "HERMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(hermes, "data_dir", lambda: tmp_path)
    return tmp_path


def test_deteccao_do_modo(volume: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert hermes.container_mode() == "volume"
    assert hermes.container_running() is True  # `gateway.pid` presente

    monkeypatch.setattr(hermes, "HERMES_DATA_DIR", str(volume / "nao-existe"))
    monkeypatch.setattr(hermes, "data_dir", lambda: None)
    assert hermes.container_mode() == "none"


def test_le_as_chaves_do_config_yaml(volume: Path) -> None:
    valores = hermes.read_config_values(hermes.CONFIG_KEYS)
    assert valores["model.default"] == "deepseek-chat"
    assert valores["model.provider"] == "auto"
    assert valores["model.base_url"] is None
    assert valores["model.api_key"] is None


def test_define_e_remove_chaves_preservando_os_comentarios(volume: Path) -> None:
    antes = (volume / "config.yaml").read_text(encoding="utf-8")

    hermes.apply_config(
        {
            "model.provider": "deepseek",
            "model.default": "deepseek-chat",
            "model.base_url": "http://host.docker.internal:11434/v1",
            "model.api_key": "sk-teste-123",
        }
    )

    depois = (volume / "config.yaml").read_text(encoding="utf-8")
    # Comentários e restantes secções intactos.
    for linha in antes.splitlines():
        if not linha.strip().startswith(("provider:", "default:", "base_url:", "api_key:")):
            assert linha in depois, f"linha perdida na edição: {linha!r}"
    # Valores aplicados e legíveis.
    valores = hermes.read_config_values(hermes.CONFIG_KEYS)
    assert valores["model.provider"] == "deepseek"
    assert valores["model.base_url"] == "http://host.docker.internal:11434/v1"
    assert valores["model.api_key"] == "sk-teste-123"
    assert "kanban:\n  review_dispatch: true" in depois

    # Remover (`None`) tira a chave e volta a «não definida».
    hermes.apply_config({"model.base_url": None, "model.api_key": None})
    valores = hermes.read_config_values(hermes.CONFIG_KEYS)
    assert valores["model.base_url"] is None
    assert valores["model.api_key"] is None
    assert valores["model.provider"] == "deepseek"


def test_gravacao_fica_com_copia_de_seguranca(volume: Path) -> None:
    original = (volume / "config.yaml").read_text(encoding="utf-8")

    hermes.apply_config({"model.provider": "deepseek"})

    copias = sorted((volume / "backups").glob("iqos-config-*.yaml"))
    assert copias, "esperava uma cópia de segurança do config.yaml"
    assert copias[-1].read_text(encoding="utf-8") == original


def test_nao_grava_se_o_resultado_for_invalido(volume: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = (volume / "config.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr(hermes, "_yaml_set_text", lambda texto, chave, valor: texto + "\n  :: inválido ::\n")

    with pytest.raises(RuntimeError, match="YAML inválido"):
        hermes.apply_config({"model.provider": "deepseek"})
    assert (volume / "config.yaml").read_text(encoding="utf-8") == original


def test_env_lido_e_escrito_com_permissao_restrita(volume: Path) -> None:
    assert "DEEPSEEK_API_KEY=chave-antiga" in hermes.read_container_env()

    novo, escritas, _ = hermes.upsert_env(hermes.read_container_env(), {"DEEPSEEK_API_KEY": "nova"})
    hermes.write_container_env(novo)

    texto = (volume / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=nova" in texto
    assert "OUTRA=1" in texto
    assert escritas == ["DEEPSEEK_API_KEY"]
    if os.name != "nt":  # o Windows não guarda permissões POSIX
        assert (volume / ".env").stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="permissões POSIX")
def test_escrita_preserva_o_dono_do_ficheiro(volume: Path) -> None:
    """O `config.yaml` mantém dono **e** modo; o `.env` mantém o dono e fica 0600."""
    config = volume / "config.yaml"
    os.chown(config, 10000, 10000)
    os.chmod(config, 0o640)
    antes = config.stat()

    hermes.apply_config({"model.provider": "deepseek"})

    depois = config.stat()
    assert (depois.st_uid, depois.st_gid) == (antes.st_uid, antes.st_gid)
    assert depois.st_mode & 0o777 == 0o640

    env = volume / ".env"
    os.chown(env, 10000, 10000)
    os.chmod(env, 0o644)

    hermes.write_container_env(ENV_EXEMPLO)

    estado = env.stat()
    assert (estado.st_uid, estado.st_gid) == (10000, 10000)
    assert estado.st_mode & 0o777 == 0o600  # a chave nunca fica legível a outros


def test_registo_de_perfis_cai_para_o_instantaneo(volume: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem `docker` nem pasta local, usa-se o instantâneo (não fica vazio)."""
    monkeypatch.setenv("HERMES_PROVIDERS_DIR", str(volume / "sem-perfis"))
    monkeypatch.setattr(hermes, "_REGISTRY_CACHE", {"at": 0.0, "data": {}})

    registry = hermes.provider_registry(force=True)

    assert registry == hermes.PROVIDER_ENV_SNAPSHOT
    assert hermes.hermes_provider_for("deepseek", registry) == ("deepseek", "DEEPSEEK_API_KEY")
    assert hermes.hermes_provider_for("google", registry)[0] == "gemini"


def test_le_os_perfis_de_uma_pasta_local(volume: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem container, uma pasta com os plugins do Hermes serve de fonte."""
    pasta = volume / "model-providers"
    (pasta / "meu-perfil").mkdir(parents=True)
    (pasta / "meu-perfil" / "__init__.py").write_text(
        'env_vars = ("MEU_API_KEY", "MEU_TOKEN")\n', encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_PROVIDERS_DIR", str(pasta))
    monkeypatch.setattr(hermes, "_REGISTRY_CACHE", {"at": 0.0, "data": {}})

    registry = hermes.provider_registry(force=True)

    assert registry == {"meu-perfil": ["MEU_API_KEY", "MEU_TOKEN"]}


def test_aplicar_avisa_que_e_preciso_reiniciar(volume: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`apply_settings` escreve no volume e devolve aviso — não rebenta."""
    monkeypatch.setattr(
        hermes,
        "read_settings",
        lambda: {**hermes.DEFAULTS, "llm_provider": "deepseek", "llm_custom_key": "sk-teste-abcdef"},
    )
    monkeypatch.setattr(hermes, "save_settings", lambda *_a, **_k: {"applied_at": "2026-01-01T00:00:00+00:00"})

    resultado = hermes.apply_settings(recreate=True)

    assert resultado["restart_required"] is True
    assert resultado["recreated"] is False
    assert "docker restart" in resultado["warning"]
    assert "model.provider=deepseek" in resultado["config"]
    assert hermes.read_config_values(("model.provider",))["model.provider"] == "deepseek"
    assert "DEEPSEEK_API_KEY=sk-teste-abcdef" in hermes.read_container_env()


def test_diagnostico_funciona_sem_docker(volume: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hermes, "read_settings", lambda: dict(hermes.DEFAULTS))
    hermes.apply_config({"model.provider": "deepseek", "model.default": "deepseek-chat"})

    relatorio = hermes.diagnose()

    assert relatorio["mode"] == "volume"
    assert relatorio["running"] is True
    assert relatorio["config"]["model.provider"] == "deepseek"
    assert relatorio["restart_required"] is True
    # O aviso de reinício é uma nota, não um «problema» de configuração.
    assert not any("docker" in problema for problema in relatorio["problems"])


def test_volume_so_de_leitura_falha_com_mensagem_util(
    volume: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Volume `:ro` (como estava no compose) → erro explicativo, não OSError."""
    monkeypatch.setattr(hermes, "data_dir_writable", lambda: False)

    def recusa(*_a, **_k):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(tempfile, "mkstemp", recusa)

    with pytest.raises(RuntimeError, match="só de leitura"):
        hermes.apply_config({"model.provider": "deepseek"})


def test_diagnostico_avisa_volume_so_de_leitura(
    volume: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hermes, "read_settings", lambda: dict(hermes.DEFAULTS))
    monkeypatch.setattr(hermes, "data_dir_writable", lambda: False)

    relatorio = hermes.diagnose()

    assert relatorio["writable"] is False
    assert any("só de leitura" in problema for problema in relatorio["problems"])


def test_reinicio_pendente_pelas_datas_dos_ficheiros(
    volume: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`restart_required` só é verdadeiro enquanto o agente não arrancou depois da escrita."""
    assert hermes.restart_pending() is False  # fixture: gateway.pid é o mais recente

    hermes.apply_config({"model.provider": "deepseek"})
    assert hermes.restart_pending() is True  # config.yaml ficou mais novo que o pid

    # Simular o arranque do agente (o pid é reescrito).
    pid = volume / "gateway.pid"
    pid.write_text("5678\n", encoding="utf-8")
    os.utime(pid, (os.path.getmtime(volume / "config.yaml") + 5,) * 2)

    assert hermes.restart_pending() is False


def test_vista_inclui_a_nota_do_modo_volume(volume: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hermes, "read_settings", lambda: dict(hermes.DEFAULTS))
    hermes.apply_config({"model.provider": "deepseek"})  # escrita posterior ao arranque

    vista = hermes.settings_view()

    assert vista["about"]["mode"] == "volume"
    assert any(f"docker restart {hermes.CONTAINER}" in nota for nota in vista["plan"]["notes"])

    # Depois de o agente reiniciar, a nota desaparece.
    pid = volume / "gateway.pid"
    os.utime(pid, (os.path.getmtime(volume / "config.yaml") + 5,) * 2)
    vista = hermes.settings_view()
    assert not any("docker restart" in nota for nota in vista["plan"]["notes"])
