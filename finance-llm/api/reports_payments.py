"""Integração de pagamentos por MB Way (opcional) para os relatórios a pedido.

O caminho normal não precisa de gateway: o cliente transfere para o **número
MB Way** configurado na administração, escreve a referência do pedido nas
observações e carrega em «Já paguei»; o backoffice confirma.

Quando a administração configura uma **chave de API** (`settings.mbway_api_key`,
formato IFTThenPay «MbWayKey»), o fluxo passa a automático:

    1. o cliente indica o telemóvel a debitar;
    2. `create_payment_request` cria um *pedido de pagamento* no MB Way
       (`POST {mbway_api_url}` com `MbWayKey`, `canal`, `Referencia`, `Valor`,
       `NroTelefone`);
    3. o cliente aprova na app MB Way;
    4. `fetch_payment_status` consulta o estado (`acao=consultar`, `IdPedido`) e,
       quando o estado é de sucesso, o pedido de relatório passa a pago.

Nada aqui **derruba** o fluxo: qualquer erro de rede/API devolve
`{"ok": False, "message": ...}` e o pedido fica a aguardar confirmação manual —
é melhor um pagamento confirmado à mão do que um cliente sem forma de pagar.

Estados IFTThenPay relevantes (`Estado`): `000` pendente · `020` pago ·
`014` expirado · `016` cancelado · outros → erro.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://mbway.ifthenpay.com/ifthenpaymbw.ashx"
DEFAULT_CHANNEL = "03"
TIMEOUT_SECONDS = 20

STATUS_PENDENTE = "pendente"
STATUS_PAGO = "pago"
STATUS_EXPIRADO = "expirado"
STATUS_CANCELADO = "cancelado"
STATUS_ERRO = "erro"

_STATUS_MAP: Dict[str, str] = {
    "000": STATUS_PENDENTE,
    "020": STATUS_PAGO,
    "014": STATUS_EXPIRADO,
    "016": STATUS_CANCELADO,
}

_STATUS_LABELS: Dict[str, str] = {
    STATUS_PENDENTE: "Pedido de pagamento enviado para o telemóvel",
    STATUS_PAGO: "Pagamento efetuado",
    STATUS_EXPIRADO: "Pedido de pagamento expirado",
    STATUS_CANCELADO: "Pedido de pagamento cancelado",
    STATUS_ERRO: "Não foi possível confirmar o pagamento",
}


def normalise_phone_351(phone: str) -> str:
    """Formato que o MB Way espera: `351#912345678`."""
    digits = re.sub(r"\D+", "", phone or "")
    if digits.startswith("351") and len(digits) == 12:
        digits = digits[3:]
    return f"351#{digits}" if digits else ""


def api_configured(settings_data: Dict[str, Any]) -> bool:
    provider = str(settings_data.get("mbway_provider") or "ifthenpay").lower()
    return provider == "ifthenpay" and bool(str(settings_data.get("mbway_api_key") or "").strip())


def _parse_response(response: Any) -> Dict[str, Any]:
    """Aceita JSON ou texto delimitado («estado;idpedido»)."""
    text = (getattr(response, "text", "") or "").strip()
    data: Dict[str, Any] = {"raw": text[:600]}
    if not text:
        return data
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            data.update({str(key): value for key, value in parsed.items()})
            data["raw"] = text[:600]
            return data
    except Exception:  # noqa: BLE001 - resposta de terceiros
        pass
    parts = [part.strip() for part in re.split(r"[;|,]", text) if part.strip()]
    if parts:
        data.setdefault("Estado", parts[0])
        if len(parts) > 1:
            data.setdefault("IdPedido", parts[1])
        if len(parts) > 2:
            data.setdefault("MsgDescricao", parts[2])
    return data


def _first(data: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        for candidate, value in data.items():
            if candidate.lower() == key.lower() and value not in (None, ""):
                return str(value)
    return ""


def _status_from(data: Dict[str, Any]) -> tuple[str, str]:
    estado = _first(data, "Estado", "estado", "status")
    message = _first(data, "MsgDescricao", "Msg", "message", "descricao")
    if not estado:
        return STATUS_ERRO, message or "Resposta inesperada do serviço MB Way."
    status = _STATUS_MAP.get(estado.strip(), STATUS_ERRO)
    return status, message or _STATUS_LABELS.get(status, "")


def create_payment_request(
    settings_data: Dict[str, Any],
    *,
    phone: str,
    amount: Any,
    reference: str,
    description: str = "",
) -> Dict[str, Any]:
    """Cria o pedido de pagamento MB Way. Nunca levanta exceções."""
    key = str(settings_data.get("mbway_api_key") or "").strip()
    if not key:
        return {"ok": False, "configured": False, "message": "MB Way automático não está configurado."}
    target = normalise_phone_351(phone)
    if not target:
        return {"ok": False, "configured": True, "message": "Telemóvel inválido para o pedido MB Way."}
    url = str(settings_data.get("mbway_api_url") or DEFAULT_API_URL).strip() or DEFAULT_API_URL
    payload = {
        "MbWayKey": key,
        "canal": DEFAULT_CHANNEL,
        "Referencia": reference,
        "Valor": f"{float(amount):.2f}",
        "NroTelefone": target,
        "Descricao": description or f"Relatório {reference}",
    }
    try:
        import requests

        response = requests.post(url, data=payload, timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - rede/terceiros
        logger.warning("MB Way: falha a criar pedido de pagamento (%s)", exc)
        return {"ok": False, "configured": True, "message": f"Falha de comunicação com o MB Way: {exc}"}
    data = _parse_response(response)
    status_code = getattr(response, "status_code", 0)
    if status_code >= 400:
        return {
            "ok": False,
            "configured": True,
            "message": f"O serviço MB Way respondeu {status_code}.",
            "raw": data.get("raw", ""),
        }
    status, message = _status_from(data)
    request_id = _first(data, "IdPedido", "idpedido", "id")
    if status == STATUS_ERRO and not request_id:
        return {"ok": False, "configured": True, "message": message or "Pedido MB Way recusado.", "raw": data.get("raw", "")}
    return {
        "ok": True,
        "configured": True,
        "status": status,
        "status_label": _STATUS_LABELS.get(status, status),
        "request_id": request_id,
        "message": message,
        "raw": data.get("raw", ""),
    }


def fetch_payment_status(settings_data: Dict[str, Any], *, request_id: str) -> Dict[str, Any]:
    """Consulta o estado de um pedido de pagamento MB Way. Nunca levanta exceções."""
    key = str(settings_data.get("mbway_api_key") or "").strip()
    if not key or not str(request_id or "").strip():
        return {"ok": False, "message": "Sem chave de API ou id de pedido."}
    url = str(settings_data.get("mbway_api_url") or DEFAULT_API_URL).strip() or DEFAULT_API_URL
    payload = {
        "MbWayKey": key,
        "canal": DEFAULT_CHANNEL,
        "IdPedido": str(request_id),
        "acao": "consultar",
    }
    try:
        import requests

        response = requests.post(url, data=payload, timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - rede/terceiros
        logger.warning("MB Way: falha a consultar estado (%s)", exc)
        return {"ok": False, "message": f"Falha de comunicação com o MB Way: {exc}"}
    data = _parse_response(response)
    status, message = _status_from(data)
    return {
        "ok": True,
        "status": status,
        "status_label": _STATUS_LABELS.get(status, status),
        "paid": status == STATUS_PAGO,
        "message": message,
        "raw": data.get("raw", ""),
    }


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def statuses() -> Dict[str, str]:
    return dict(_STATUS_LABELS)


def _unused(_: Optional[Any] = None) -> None:  # pragma: no cover - reservado
    return None
