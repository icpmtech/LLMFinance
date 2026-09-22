"""Cliente HTTP do IQ OS usado pelo servidor MCP.

Fala com o backend FastAPI (`api.main`) por HTTP, reutilizando uma única
ligação `httpx.AsyncClient`.

Configuração por variáveis de ambiente:

======================  ====================================================
``IQOS_API_URL``        Base URL do backend (por omissão
                        ``http://127.0.0.1:8002``).
``IQOS_API_TOKEN``      Token de sessão (Bearer) já emitido por
                        ``POST /auth/login``.
``IQOS_API_EMAIL``      Se não houver token, faz login automático com este
``IQOS_API_PASSWORD``   email/palavra-passe na primeira chamada.
``IQOS_API_TIMEOUT``    Tempo limite por pedido, em segundos (60).
======================  ====================================================
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8002"


class IQOSError(RuntimeError):
    """Falha ao falar com o backend do IQ OS."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class IQOSClient:
    """Cliente assíncrono, com login automático e renovação em caso de 401."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("IQOS_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.token = token or os.getenv("IQOS_API_TOKEN") or None
        self.email = email or os.getenv("IQOS_API_EMAIL") or None
        self.password = password or os.getenv("IQOS_API_PASSWORD") or None
        self.timeout = timeout or _env_float("IQOS_API_TIMEOUT", 120.0)
        self._client: Optional[httpx.AsyncClient] = None

    # -- infraestrutura ---------------------------------------------------

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def login(self, email: Optional[str] = None, password: Optional[str] = None) -> str:
        """Autentica-se e guarda o token devolvido por ``/auth/login``."""
        email = email or self.email
        password = password or self.password
        if not email or not password:
            raise IQOSError(
                "Sem credenciais: defina IQOS_API_TOKEN ou IQOS_API_EMAIL/IQOS_API_PASSWORD."
            )
        client = await self._http()
        response = await client.post(
            "/auth/login", json={"email": email, "password": password}
        )
        if response.status_code >= 400:
            raise IQOSError(
                f"Login falhou ({response.status_code})", status_code=response.status_code
            )
        data = response.json()
        self.token = data.get("token") or self.token
        if not self.token:
            raise IQOSError("A resposta de /auth/login não trouxe token.")
        return self.token

    # -- pedidos ----------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, Any]] = None,
        body: Any = None,
        retry_auth: bool = True,
    ) -> Any:
        """Executa um pedido e devolve o corpo descodificado."""
        client = await self._http()
        params = {k: v for k, v in (query or {}).items() if v is not None}
        url = path if path.startswith("/") else f"/{path}"

        try:
            response = await client.request(
                method.upper(), url, params=params or None, json=body, headers=self._headers()
            )
        except httpx.HTTPError as exc:  # ligação recusada, timeout, DNS…
            raise IQOSError(f"Não foi possível contactar {self.base_url}: {exc}") from exc

        if response.status_code == 401 and retry_auth and self.email and self.password:
            await self.login()
            return await self.request(method, path, query=query, body=body, retry_auth=False)

        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            detail: Any = None
            if "json" in content_type:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text[:2000]
            else:
                detail = response.text[:2000]
            raise IQOSError(
                f"{method.upper()} {url} → HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
                payload=detail,
            )

        if "json" in content_type:
            return response.json()
        if content_type.startswith("text/") or not content_type:
            return {"status_code": response.status_code, "content_type": content_type, "text": response.text[:20000]}
        return {
            "status_code": response.status_code,
            "content_type": content_type,
            "bytes": len(response.content),
            "note": "Resposta binária (ficheiro) — descarregue pelo endpoint na interface.",
        }

    # -- introspeção ------------------------------------------------------

    async def openapi(self) -> Dict[str, Any]:
        """Especificação OpenAPI do backend (usa o cache do servidor)."""
        data = await self.request("GET", "/openapi.json")
        if not isinstance(data, dict):  # pragma: no cover - defensivo
            raise IQOSError("O backend não devolveu uma especificação OpenAPI válida.")
        return data
