"""Cliente HTTP do CLI.

Fala com a API FastAPI como qualquer outro cliente: envia
`Authorization: Bearer <token>` quando há sessão e traduz os erros da API
(`detail`) numa exceção legível.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

import requests

DEFAULT_TIMEOUT = 60


class ApiError(Exception):
    """Erro devolvido pela API (ou falha de ligação)."""

    def __init__(self, message: str, status: int | None = None, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class Client:
    """Cliente fino sobre `requests`, com token opcional."""

    def __init__(self, base_url: str, token: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------- transporte
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        payload: Optional[Mapping[str, Any]] = None,
        timeout: int | None = None,
        expect_json: bool = True,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body: Optional[str] = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps({k: v for k, v in payload.items() if v is not None})

        try:
            response = requests.request(
                method,
                url,
                params=params,
                data=body,
                headers=headers,
                timeout=timeout or self.timeout,
            )
        except requests.RequestException as error:
            reason = self._reason(error)
            raise ApiError(f"Não foi possível contactar a API em {self.base_url} ({reason})", code="connection") from error

        if not expect_json:
            if not response.ok:
                raise ApiError(self._error_message(response), status=response.status_code)
            return response.content

        try:
            data = response.json() if response.content else None
        except ValueError:
            data = None

        if not response.ok:
            raise ApiError(self._error_message(response, data), status=response.status_code)

        # Alguns endpoints assinalam falhas no corpo com `error` (ex.: ES em baixo).
        if isinstance(data, dict) and data.get("error"):
            raise ApiError(str(data["error"]), status=response.status_code, code="api_error")
        return data

    @staticmethod
    def _reason(error: requests.RequestException) -> str:
        """Explica a falha de ligação em português, sem despejar o stack trace."""
        if isinstance(error, requests.Timeout):
            return "tempo de espera excedido"
        text = str(error)
        if "10061" in text or "actively refused" in text or "Connection refused" in text:
            return "ligação recusada — o servidor está a correr nesse porto?"
        if "getaddrinfo" in text or "Name or service not known" in text:
            return "servidor não encontrado"
        return type(error).__name__

    @staticmethod
    def _error_message(response: requests.Response, data: Any = None) -> str:
        if isinstance(data, dict):
            detail = data.get("detail")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list) and detail:
                first = detail[0]
                if isinstance(first, dict) and first.get("msg"):
                    return str(first["msg"])
        return f"Erro {response.status_code} em {response.request.url if response.request else ''}".strip()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # ---------------------------------------------------------------- atalhos
    def health(self) -> Dict[str, Any]:
        return self.get("/health", timeout=20)

    def login(self, email: str, password: str, remember: bool = False) -> Dict[str, Any]:
        return self.post("/auth/login", payload={"email": email, "password": password, "remember": remember})

    def register(self, name: str, email: str, password: str, **extra: Any) -> Dict[str, Any]:
        return self.post(
            "/auth/register",
            payload={"name": name, "email": email, "password": password, **extra},
        )

    def me(self) -> Dict[str, Any]:
        return self.get("/auth/me")

    def logout(self) -> Dict[str, Any]:
        return self.post("/auth/logout")

    def sessions(self) -> Any:
        return self.get("/auth/sessions")

    def revoke_other_sessions(self) -> Dict[str, Any]:
        return self.delete("/auth/sessions")

    def change_password(self, current: str, new: str) -> Dict[str, Any]:
        return self.post("/auth/password", payload={"current_password": current, "new_password": new})

    def stats(self) -> Dict[str, Any]:
        return self.get("/auth/stats")
