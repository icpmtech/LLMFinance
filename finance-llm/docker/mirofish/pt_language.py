"""Garante que o LLM do MiroFish responde em **português**.

Porque é que isto é preciso
---------------------------
O upstream escreve os *prompts* em chinês (ontologia, personas, configuração do
mundo, relatório) e o modelo, sem indicação em contrário, responde no mesmo
idioma do prompt: as personas, as justificações e as publicações dos agentes
saíam em chinês — mesmo com a interface e o material-semente em português.

Todos os pedidos ao LLM passam por `LLMClient._create_completion`
(`chat` → `chat_json` → `_create_completion`), portanto é aí que se injeta uma
diretiva de idioma quando `MIROFISH_REPLY_LANGUAGE` está definida (por omissão
`pt-PT`, definida no `docker-compose.yml`).

A diretiva vai em **português e em chinês**: o prompt de origem é chinês e a
instrução no mesmo idioma é a que o modelo segue com mais fiabilidade. Pede
também que não se mexam em nomes de campos JSON, valores de enumeração nem
identificadores — para não partir o `chat_json` (que valida a estrutura).

Como é aplicada
---------------
Sobrepõe o método no **fim do módulo** (não mexe no corpo do método original):
sobrevive a atualizações do upstream e é idempotente — se o marcador já estiver
presente, não faz nada.
"""
from __future__ import annotations

import pathlib
import re
import sys

TARGET = pathlib.Path("/app/backend/app/utils/llm_client.py")
MARKER = "_IQ_OS_REPLY_LANGUAGE"

PATCH = '''

# ---------------------------------------------------------------------------
# IQ OS: idioma das respostas do LLM (ver `pt_language.py` na imagem)
# ---------------------------------------------------------------------------
_IQ_OS_REPLY_LANGUAGE = os.getenv("MIROFISH_REPLY_LANGUAGE", "").strip()

_IQ_OS_LANGUAGE_DIRECTIVE = (
    "IDIOMA: escreve todo o texto legível (análise, personas, publicações, "
    "comentários, justificações e relatórios) em {language}. "
    "Mantém inalterados os nomes de campos JSON, os valores de enumeração e os "
    "identificadores de código. 语言要求：所有可读文本必须使用{language_zh}书写；"
    "JSON 字段名、枚举值和代码标识符保持不变。"
)


def _iq_os_apply_reply_language(messages):
    """Acrescenta a diretiva de idioma à primeira mensagem de sistema."""
    if not _IQ_OS_REPLY_LANGUAGE or not isinstance(messages, list):
        return messages
    directive = _IQ_OS_LANGUAGE_DIRECTIVE.format(
        language=_IQ_OS_REPLY_LANGUAGE,
        language_zh=(
            "葡萄牙语（葡萄牙）"
            if _IQ_OS_REPLY_LANGUAGE.lower().startswith("pt")
            else _IQ_OS_REPLY_LANGUAGE
        ),
    )
    patched = []
    applied = False
    for message in messages:
        if (
            not applied
            and isinstance(message, dict)
            and str(message.get("role") or "") == "system"
        ):
            content = str(message.get("content") or "")
            patched.append({**message, "content": directive + "\\n\\n" + content})
            applied = True
        else:
            patched.append(message)
    if not applied:
        patched.insert(0, {"role": "system", "content": directive})
    return patched


if _IQ_OS_REPLY_LANGUAGE:
    _iq_os_original_create_completion = LLMClient._create_completion

    def _iq_os_create_completion(self, *, messages, temperature, max_tokens, response_format):
        return _iq_os_original_create_completion(
            self,
            messages=_iq_os_apply_reply_language(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    LLMClient._create_completion = _iq_os_create_completion
'''


def main() -> int:
    if not TARGET.exists():
        print(f"[pt_language] ficheiro não encontrado: {TARGET}", file=sys.stderr)
        return 1

    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"[pt_language] já aplicado em {TARGET}")
        return 0
    if "class LLMClient" not in text:
        print("[pt_language] LLMClient não encontrado: nada a fazer", file=sys.stderr)
        return 1

    if not re.search(r"^import os$", text, re.M):
        text = "import os\n" + text

    TARGET.write_text(text.rstrip() + PATCH, encoding="utf-8")
    print(f"[pt_language] diretiva de idioma instalada em {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
