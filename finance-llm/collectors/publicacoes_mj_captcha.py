"""Cliente programático das Publicações de Atos Societários com resolução 2captcha.

Estende ``PublicacoesMjClient`` para resolver automaticamente o reCAPTCHA v2
que protege o formulário de pesquisa em https://publicacoes.mj.pt/Pesquisa.aspx.

Uso típico::

    from collectors.publicacoes_mj_captcha import PublicacoesMjCaptchaClient

    client = PublicacoesMjCaptchaClient(api_key=os.environ["TWOCAPTCHA_API_KEY"])
    publicacoes = client.collect(nif="500273170", with_details=True)

O token do reCAPTCHA é resolvido remotamente pela 2captcha (pago). O tempo de
resposta varia entre dezenas de segundos e alguns minutos, conforme a fila.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from collectors.publicacoes_mj import (
    PAGE,
    RECAPTCHA_SITEKEY,
    CaptchaRequiredError,
    PublicacoesMjClient,
    PublicacaoMJ,
)

logger = logging.getLogger(__name__)

#: Ficheiros onde a solução guarda as chaves (o `.env` de `finance-llm/` e o da
#: raiz do projeto estão no `.gitignore`). Servem de fallback quando a variável
#: de ambiente não foi exportada pelo lançador — era o que fazia a recolha falhar
#: com «API key da 2captcha em falta» depois de a API ser reiniciada por outro
#: caminho.
_ENV_FILES = (
    Path(__file__).resolve().parents[1] / ".env",
    Path(__file__).resolve().parents[2] / ".env",
)


def _chave_no_env_file(nomes: tuple[str, ...]) -> Optional[str]:
    """Procura uma chave nos `.env` do projeto (primeiro que a defina)."""
    for caminho in _ENV_FILES:
        if not caminho.exists():
            continue
        try:
            for linha in caminho.read_text(encoding="utf-8", errors="ignore").splitlines():
                limpa = linha.strip()
                if not limpa or limpa.startswith("#") or "=" not in limpa:
                    continue
                chave, _, valor = limpa.partition("=")
                if chave.strip() in nomes:
                    valor = valor.strip().strip("'\"")
                    if valor:
                        return valor
        except OSError:  # pragma: no cover - ficheiro ilegível não pode travar
            continue
    return None


def api_key_2captcha(api_key: Optional[str] = None) -> Optional[str]:
    """Resolve a API key da 2captcha (parâmetro → índice → ambiente → `.env`).

    O índice é o `service-keys` de `finance_settings`, editável em
    **Administração → Chaves e integrações**: mudar lá a chave passa a valer de
    imediato, sem reiniciar o backend.
    """
    if api_key and str(api_key).strip():
        return str(api_key).strip()
    try:
        from api import service_keys

        guardada = service_keys.resolver("twocaptcha_api_key")
        if guardada:
            return guardada
    except Exception as exc:  # noqa: BLE001 - sem Elasticsearch seguem-se ambiente e `.env`
        logger.debug("Chave da 2captcha não veio do índice: %s", exc)
    nomes = ("TWOCAPTCHA_API_KEY", "TWOCAPTCHA_KEY")
    for nome in nomes:
        valor = (os.environ.get(nome) or "").strip()
        if valor:
            return valor
    return _chave_no_env_file(nomes)


def proxy_2captcha(proxy: Optional[str] = None) -> Optional[str]:
    """Proxy para o portal do MJ / 2captcha (parâmetro → índice → ambiente)."""
    if proxy and str(proxy).strip():
        return str(proxy).strip()
    try:
        from api import service_keys

        guardado = service_keys.resolver("twocaptcha_proxy")
        if guardado:
            return guardado
    except Exception:  # noqa: BLE001
        pass
    for nome in ("TWOCAPTCHA_PROXY", "SOCIAL_PROXY"):
        valor = (os.environ.get(nome) or "").strip()
        if valor:
            return valor
    return None


class PublicacoesMjCaptchaClient(PublicacoesMjClient):
    """Cliente do MJ com resolução automática de reCAPTCHA via 2captcha."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        min_interval: float = 4.0,
        timeout: int = 60,
        recaptcha_timeout: int = 180,
        proxy: Optional[str] = None,
        debug: bool = False,
    ):
        super().__init__(cookies=cookies, min_interval=min_interval, timeout=timeout, proxy=proxy_2captcha(proxy))
        self.api_key = api_key_2captcha(api_key)
        if not self.api_key:
            raise ValueError(
                "API key da 2captcha em falta: passe `api_key`, defina "
                "TWOCAPTCHA_API_KEY / TWOCAPTCHA_KEY ou escreva-a no `.env` de finance-llm."
            )
        self.recaptcha_timeout = recaptcha_timeout
        self._solver: Optional[Any] = None
        if debug:
            os.environ["MJ_DEBUG"] = "1"
            self._set_debug_enabled(True)

    def _get_solver(self) -> Any:
        """Importa a biblioteca twocaptcha só quando necessário (lazy)."""
        if self._solver is None:
            from twocaptcha import TwoCaptcha

            self._solver = TwoCaptcha(
                self.api_key,
                sleep_time=5,
            )
        return self._solver

    def solve_recaptcha(self, page_url: str = PAGE) -> str:
        """Resolve o reCAPTCHA v2 do portal e devolve o token."""
        solver = self._get_solver()
        logger.info("A resolver reCAPTCHA via 2captcha para %s (sitekey=%s)", page_url, RECAPTCHA_SITEKEY)
        try:
            token = solver.solve_captcha(
                site_key=RECAPTCHA_SITEKEY,
                page_url=page_url,
            )
        except Exception as exc:
            logger.exception("Falha ao resolver reCAPTCHA via 2captcha")
            raise CaptchaRequiredError(f"2captcha não conseguiu resolver o reCAPTCHA: {exc}") from exc

        if not token:
            raise CaptchaRequiredError("2captcha devolveu token vazio")
        logger.info("reCAPTCHA resolvido (token=%s...%s)", str(token)[:12], str(token)[-12:])
        return str(token)

    def collect(
        self,
        *,
        recaptcha_token: Optional[str] = None,
        form_html: Optional[str] = None,
        with_details: bool = True,
        max_pages: int = 50,
        **criteria: Any,
    ) -> List[PublicacaoMJ]:
        """Recolhe publicações resolvendo o captcha automaticamente quando necessário.

        Se ``recaptcha_token`` for fornecido, usa-o diretamente; caso contrário,
        resolve um novo token através da 2captcha.
        """
        if recaptcha_token:
            return super().collect(
                recaptcha_token=recaptcha_token,
                form_html=form_html or self.fetch_form(),
                with_details=with_details,
                max_pages=max_pages,
                **criteria,
            )

        token = self.solve_recaptcha()
        return super().collect(
            recaptcha_token=token,
            form_html=form_html or self.fetch_form(),
            with_details=with_details,
            max_pages=max_pages,
            **criteria,
        )


def collect_with_captcha(
    *,
    api_key: Optional[str] = None,
    nif: Optional[str] = None,
    entidade: Optional[str] = None,
    tipo: str = "0",
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    data_ini: Optional[str] = None,
    data_fim: Optional[str] = None,
    with_details: bool = True,
    max_pages: int = 50,
    min_interval: float = 1.0,
    recaptcha_timeout: int = 180,
    proxy: Optional[str] = None,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """Função de conveniência para recolha automática de uma entidade/janela."""
    client = PublicacoesMjCaptchaClient(
        api_key=api_key,
        min_interval=min_interval,
        recaptcha_timeout=recaptcha_timeout,
        proxy=proxy,
        debug=debug,
    )
    pubs = client.collect(
        nif=nif,
        entidade=entidade,
        tipo=tipo,
        distrito=distrito,
        concelho=concelho,
        data_ini=data_ini,
        data_fim=data_fim,
        with_details=with_details,
        max_pages=max_pages,
    )
    return [p.to_dict() for p in pubs]
