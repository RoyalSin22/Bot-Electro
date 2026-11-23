"""Variables de entorno. Ninguna credencial vive en el código."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    whatsapp_token: str
    whatsapp_phone_id: str
    webhook_verify_token: str
    google_sheet_id: str
    google_credentials_json: str


def cargar_settings() -> Settings:
    """Lee el entorno bajo demanda (no al importar) para que las pruebas
    de la lógica pura no requieran credenciales."""
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        whatsapp_token=os.environ.get("WHATSAPP_TOKEN", ""),
        whatsapp_phone_id=os.environ.get("WHATSAPP_PHONE_ID", ""),
        webhook_verify_token=os.environ.get("WEBHOOK_VERIFY_TOKEN", ""),
        google_sheet_id=os.environ.get("GOOGLE_SHEET_ID", ""),
        google_credentials_json=os.environ.get("GOOGLE_CREDENTIALS_JSON", ""),
    )
