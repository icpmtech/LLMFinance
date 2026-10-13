#!/command/with-contenv sh
# shellcheck shell=sh
#
# Voz local do Hermes Agent: TTS Piper (pt-PT) + STT faster-whisper.
#
# Porquê este script:
#   * A Edge TTS (provider por omissão) devolve 403 a partir deste host, e o
#     `.env` não tem chaves de TTS — logo a voz tem de ser local (Piper).
#   * O `piper-tts` não vem na imagem: o venv é selado e os pacotes opcionais
#     vivem em `HERMES_LAZY_INSTALL_TARGET` (volume `hermes-data`), que um
#     `docker compose down -v` apagaria.
#   * O `python -m piper.download_voices` rebenta com nomes de voz não-ASCII
#     (UnicodeEncodeError no urllib, para o `ã` de `pt_PT-tugão-medium`), por
#     isso o download aqui usa o URL já percent-encoded.
#   * As chaves de configuração vivem no `$HERMES_HOME/config.yaml` (no volume)
#     e são escritas uma única vez, pelo caminho sancionado (`hermes config
#     set`) — nunca sobrepõem escolhas feitas depois, e nunca correm se já lá
#     estiverem. Assim o `docker-compose.yml` continua a ser a fonte de verdade.
#
# Corre em todos os arranques (cont-init do s6-overlay) e é idempotente. A voz
# é opcional: qualquer falha é um aviso e o contentor arranca na mesma.
set -e

DATA="${HERMES_HOME:-/opt/data}"
LAZY_TARGET="${HERMES_LAZY_INSTALL_TARGET:-$DATA/lazy-packages}"
VOICES_DIR="$DATA/cache/piper-voices"
VOICE="pt_PT-tugão-medium"
# Caminho remoto na HuggingFace com o `ã` de `tugão` em percent-encoding (%C3%A3).
VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_PT/tug%C3%A3o/medium/pt_PT-tug%C3%A3o-medium"
PY=/opt/hermes/.venv/bin/python3

as_hermes() { s6-setuidgid hermes "$@"; }

# Chave ausente no config.yaml *em bruto* (os defaults do Hermes não contam:
# `hermes config get` mostra sempre o valor resolvido, não o que está lá escrito).
# Devolve 0 (verdadeiro) apenas quando a chave não está escrita no ficheiro.
config_key_absent() {
    as_hermes env HOME="$DATA" "$PY" - "$1" <<'PY'
import os
import sys
from pathlib import Path

import yaml

key = sys.argv[1]
raw = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "config.yaml"
try:
    node = yaml.safe_load(raw.read_text(encoding="utf-8")) if raw.is_file() else None
except Exception:
    node = None
node = node or {}
for part in key.split("."):
    if not isinstance(node, dict) or part not in node:
        sys.exit(0)  # ausente
    node = node[part]
sys.exit(1)  # presente
PY
    return $?
}

ensure_config() {
    if config_key_absent "$1"; then
        as_hermes env HOME="$DATA" hermes config set "$1" "$2" >/dev/null \
            && echo "[hermes-voz] config: $1 = $2"
    else
        echo "[hermes-voz] config: $1 já definido — mantido."
    fi
}

main() {
    echo "[hermes-voz] a preparar TTS Piper + STT faster-whisper (voz $VOICE)."

    # 1) piper-tts no alvo durável (o venv da imagem é selado). O import é feito
    #    com o PYTHONPATH que o Hermes ativa no arranque (_durable lazy target).
    importa() { as_hermes env HOME="$DATA" PYTHONPATH="$LAZY_TARGET" "$PY" -c "import $1" >/dev/null 2>&1; }

    PIPER_OK=0
    if importa piper; then
        echo "[hermes-voz] piper-tts já instalado."
        PIPER_OK=1
    else
        echo "[hermes-voz] a instalar piper-tts em $LAZY_TARGET…"
        # --no-deps de propósito: o alvo já traz o stack científico que o Hermes
        # fixa (onnxruntime/numpy do faster-whisper) e um resolver livre subi-lo-ia.
        if as_hermes env HOME="$DATA" UV_CACHE_DIR="$DATA/home/.cache/uv" \
            uv pip install --target "$LAZY_TARGET" --no-deps --python "$PY" \
            piper-tts pathvalidate >/dev/null 2>&1; then
            if importa piper; then
                PIPER_OK=1
            else
                echo "[hermes-voz] aviso: piper-tts instalado mas ainda não importável —"
                echo "[hermes-voz]        faltam as dependências partilhadas (onnxruntime/numpy),"
                echo "[hermes-voz]        que chegam com a instalação lazy do faster-whisper."
            fi
        else
            echo "[hermes-voz] aviso: não foi possível instalar o piper-tts (sem rede?)."
        fi
    fi

    # 2) Voz pt-PT em cache — só descarrega se faltar algum dos dois ficheiros.
    mkdir -p "$VOICES_DIR"
    for ext in .onnx .onnx.json; do
        dest="$VOICES_DIR/$VOICE$ext"
        if [ -s "$dest" ]; then
            continue
        fi
        echo "[hermes-voz] a descarregar $VOICE$ext…"
        curl -fsSL --retry 2 --max-time 600 -o "$dest.part" "$VOICE_URL$ext?download=true"
        mv "$dest.part" "$dest"
    done
    chown -R hermes:hermes "$VOICES_DIR"

    # 3) Chaves de configuração: só as que faltam, e o motor só é escolhido
    #    quando o pacote correspondente está mesmo disponível (nunca deixar o
    #    provider apontado para algo que não existe). O idioma é só uma dica —
    #    vale para qualquer provider, por isso é escrito sempre.
    if [ "$PIPER_OK" = "1" ]; then
        ensure_config tts.provider piper
        ensure_config tts.piper.voice "$VOICE"
    fi
    if importa faster_whisper; then
        ensure_config stt.provider local
    fi
    ensure_config stt.language pt

    echo "[hermes-voz] pronto."
}

main || echo "[hermes-voz] aviso: preparação da voz falhou — o agente arranca sem voz."
exit 0
