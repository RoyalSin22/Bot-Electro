"""WhatsApp Cloud API (Meta): parseo del webhook, verificación y envío."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

import httpx

MAX_TEXTO = 4096  # límite de WhatsApp para un mensaje de texto


class ErrorWhatsApp(RuntimeError):
    """Fallo al enviar. Nunca incluye el token."""


@dataclass(frozen=True)
class MensajeEntrante:
    telefono: str
    id: str
    tipo: str            # 'text', 'audio', 'image', ...
    texto: str | None    # solo si tipo == 'text'


def parsear_webhook(payload: dict) -> list[MensajeEntrante]:
    """Extrae los mensajes entrantes. Ignora los 'statuses' (entregado/leído) y
    cualquier estructura inesperada en vez de fallar."""
    salida: list[MensajeEntrante] = []
    if not isinstance(payload, dict):
        return salida
    for entrada in payload.get("entry") or []:
        for cambio in (entrada or {}).get("changes") or []:
            valor = (cambio or {}).get("value") or {}
            for m in valor.get("messages") or []:
                if not isinstance(m, dict) or not m.get("from") or not m.get("id"):
                    continue
                tipo = str(m.get("type", ""))
                texto = (m.get("text") or {}).get("body") if tipo == "text" else None
                salida.append(MensajeEntrante(str(m["from"]), str(m["id"]), tipo, texto))
    return salida


def verificar_firma(cuerpo: bytes, cabecera: str | None, app_secret: str) -> bool:
    """X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256(app_secret, cuerpo crudo)."""
    if not app_secret or not cabecera or not cabecera.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera[len("sha256="):])


def firmar(cuerpo: bytes, app_secret: str) -> str:
    """Útil para pruebas y para simular a Meta."""
    return "sha256=" + hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()


def verificar_suscripcion(modo: str | None, token: str | None, challenge: str | None, esperado: str) -> str | None:
    """GET /webhook: devuelve el challenge si el token coincide; si no, None."""
    if modo == "subscribe" and esperado and token and challenge is not None and hmac.compare_digest(token, esperado):
        return challenge
    return None


class ClienteWhatsApp:
    def __init__(self, token: str, phone_id: str, version: str = "v23.0", http_client: httpx.Client | None = None):
        if not token or not phone_id:
            raise ValueError("Faltan WHATSAPP_TOKEN o WHATSAPP_PHONE_ID")
        self._token = token
        self._url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        self._http = http_client or httpx.Client(timeout=15.0)

    def enviar_texto(self, telefono: str, texto: str) -> None:
        cuerpo = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "text",
            "text": {"body": texto[:MAX_TEXTO], "preview_url": False},
        }
        try:
            r = self._http.post(self._url, json=cuerpo, headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as e:
            raise ErrorWhatsApp(f"envío falló: {type(e).__name__}") from e
        if r.status_code >= 300:
            detalle = ""
            try:
                detalle = (r.json().get("error") or {}).get("message", "")
            except ValueError:
                pass
            raise ErrorWhatsApp(f"envío falló: HTTP {r.status_code} {detalle}".strip())
