"""Variables de entorno. Ninguna credencial vive en el código."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    whatsapp_token: str
    whatsapp_phone_id: str
    webhook_verify_token: str
    google_sheet_id: str
    google_credentials_json: str
    whatsapp_app_secret: str = ""      # firma X-Hub-Signature-256 del webhook (recomendado)
    whatsapp_api_version: str = "v23.0"
    numeros_permitidos: tuple = ()      # si no está vacío, el bot SOLO atiende estos números


def cargar_dotenv(ruta: Path | None = None) -> None:
    """Carga KEY=VALOR de un archivo `.env` (si existe) SIN pisar variables ya definidas
    en el entorno. `.env` está en .gitignore: ahí se pegan las claves, nunca en el código."""
    ruta = ruta or Path(__file__).resolve().parent / ".env"
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if clave and valor:
            os.environ.setdefault(clave, valor)


def cargar_settings() -> Settings:
    """Lee el entorno bajo demanda (no al importar) para que las pruebas
    de la lógica pura no requieran credenciales."""
    cargar_dotenv()
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        whatsapp_token=os.environ.get("WHATSAPP_TOKEN", ""),
        whatsapp_phone_id=os.environ.get("WHATSAPP_PHONE_ID", ""),
        webhook_verify_token=os.environ.get("WEBHOOK_VERIFY_TOKEN", ""),
        google_sheet_id=os.environ.get("GOOGLE_SHEET_ID", ""),
        google_credentials_json=os.environ.get("GOOGLE_CREDENTIALS_JSON", ""),
        whatsapp_app_secret=os.environ.get("WHATSAPP_APP_SECRET", ""),
        whatsapp_api_version=os.environ.get("WHATSAPP_API_VERSION", "v23.0"),
        numeros_permitidos=tuple(x.strip() for x in os.environ.get("NUMEROS_PERMITIDOS", "").split(",") if x.strip()),
    )
