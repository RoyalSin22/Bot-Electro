"""FastAPI: webhook de WhatsApp Cloud API.

GET  /webhook  verificación del token (hub.challenge)
POST /webhook  mensajes entrantes (responde 200 enseguida y procesa en segundo plano:
               Meta reintenta si no recibe 200 rápido)
GET  /health   monitoreo del hosting
"""
from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

import whatsapp as wa
from config import Settings, cargar_settings

log = logging.getLogger("bot.main")


@dataclass
class Servicios:
    bot: object                 # flujo.Bot (o cualquier objeto con la misma interfaz)
    whatsapp: object            # whatsapp.ClienteWhatsApp
    settings: Settings


class _Vistos:
    """Meta puede entregar el mismo mensaje más de una vez: se procesa una sola."""

    def __init__(self, maximo: int = 2000):
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._max = maximo
        self._lock = threading.Lock()

    def nuevo(self, id_: str) -> bool:
        with self._lock:
            if id_ in self._ids:
                return False
            self._ids[id_] = None
            while len(self._ids) > self._max:
                self._ids.popitem(last=False)
            return True


def construir_servicios_desde_entorno() -> Servicios:
    from flujo import Bot
    from ia import GeminiClient
    from sheets import HojaGoogle, Repositorio

    s = cargar_settings()
    repo = Repositorio(HojaGoogle(s.google_sheet_id, s.google_credentials_json))
    return Servicios(
        bot=Bot(repo, GeminiClient(s.gemini_api_key)),
        whatsapp=wa.ClienteWhatsApp(s.whatsapp_token, s.whatsapp_phone_id, s.whatsapp_api_version),
        settings=s,
    )


def crear_app(servicios: Servicios | None = None) -> FastAPI:
    app = FastAPI(title="Bot electrodomésticos", docs_url=None, redoc_url=None)
    estado = {"servicios": servicios, "error": None}
    vistos = _Vistos()

    def obtener() -> Servicios:
        if estado["servicios"] is None:
            try:  # arranque perezoso: /health responde aunque falte configuración
                estado["servicios"] = construir_servicios_desde_entorno()
                if not estado["servicios"].settings.whatsapp_app_secret:
                    log.warning("WHATSAPP_APP_SECRET vacío: el webhook NO verifica la firma de Meta")
            except Exception as e:  # noqa: BLE001
                estado["error"] = f"{type(e).__name__}: {e}"
                log.error("configuración incompleta: %s", estado["error"])
                raise HTTPException(503, "servicio no configurado") from e
        return estado["servicios"]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/webhook")
    def verificar(request: Request):
        q = request.query_params
        esperado = (estado["servicios"].settings.webhook_verify_token if estado["servicios"]
                    else cargar_settings().webhook_verify_token)
        challenge = wa.verificar_suscripcion(q.get("hub.mode"), q.get("hub.verify_token"), q.get("hub.challenge"), esperado)
        if challenge is None:
            raise HTTPException(403, "token de verificación inválido")
        return PlainTextResponse(challenge)

    def atender(srv: Servicios, m: wa.MensajeEntrante) -> None:
        try:
            if m.tipo == "text" and m.texto is not None:
                respuesta = srv.bot.procesar(m.telefono, m.texto)
            else:
                respuesta = srv.bot.procesar_no_texto(m.telefono, m.tipo)
            srv.whatsapp.enviar_texto(m.telefono, respuesta)
        except Exception:  # noqa: BLE001 - nunca romper el worker; Meta no debe reintentar en bucle
            log.exception("fallo atendiendo mensaje %s", m.id)

    @app.post("/webhook")
    async def recibir(request: Request, tareas: BackgroundTasks):
        srv = obtener()
        cuerpo = await request.body()
        secreto = srv.settings.whatsapp_app_secret
        if secreto and not wa.verificar_firma(cuerpo, request.headers.get("X-Hub-Signature-256"), secreto):
            raise HTTPException(403, "firma inválida")
        try:
            payload = json.loads(cuerpo)
        except ValueError:
            raise HTTPException(400, "JSON inválido")
        for m in wa.parsear_webhook(payload):
            if vistos.nuevo(m.id):
                tareas.add_task(atender, srv, m)
        return {"status": "ok"}

    return app


app = crear_app()
