"""Google Sheets como base de datos (una pestaña por tabla).

`Repositorio` es lo único que el resto del bot conoce. Detrás hay una
`HojaGoogle` (gspread + cuenta de servicio) o una `HojaSimulada` en memoria
(pruebas y simulador local), con la misma interfaz mínima:

    leer(pestana) -> list[dict]       agregar(pestana, fila: list)

Decisiones:
- Lecturas con caché corta (TTL): la API de Sheets limita ~60 lecturas/min.
- Todo se lee como TEXTO (`numericise_ignore=all`); `negocio.py` parsea de forma
  determinista y no depende del idioma de la hoja.
- Toda escritura usa RAW: un mensaje de cliente que empiece con "=" se guarda
  como texto y NUNCA se evalúa como fórmula (inyección de fórmulas).
"""
from __future__ import annotations

import csv
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

import negocio as n

LIMA = timezone(timedelta(hours=-5))  # sin horario de verano
ENCABEZADOS = {
    "Productos": ["sku", "categoria", "marca", "modelo", "descripcion", "capacidad", "precio", "stock", "garantia_meses"],
    "Boletas": ["numero_boleta", "fecha_compra", "sku", "cliente", "telefono"],
    "Tickets": ["id", "fecha", "telefono", "numero_boleta", "sku", "problema", "estado"],
    "Conversaciones": ["fecha", "telefono", "mensaje", "intencion", "respuesta"],
    "Derivaciones": ["fecha", "telefono", "motivo", "mensaje_original", "atendido"],
    "Config": ["clave", "valor"],
}
MAX_CELDA = 2000  # Sheets admite 50 000; no guardamos novelas de un cliente


class Hoja(Protocol):
    def leer(self, pestana: str) -> list[dict]: ...
    def agregar(self, pestana: str, fila: list) -> None: ...


class ErrorHoja(RuntimeError):
    """Fallo al hablar con la hoja. No incluye credenciales."""


# --------------------------------------------------------------------------
# Implementaciones de Hoja
# --------------------------------------------------------------------------
class HojaSimulada:
    """Hoja en memoria con la misma interfaz que HojaGoogle."""

    def __init__(self, datos: dict[str, list[dict]] | None = None):
        self._tablas: dict[str, list[dict]] = {k: [] for k in ENCABEZADOS}
        for pestana, filas in (datos or {}).items():
            self._tablas[pestana] = [dict(f) for f in filas]
        self._lock = threading.Lock()

    def leer(self, pestana: str) -> list[dict]:
        with self._lock:
            return [dict(f) for f in self._tablas[pestana]]

    def agregar(self, pestana: str, fila: list) -> None:
        with self._lock:
            self._tablas[pestana].append(dict(zip(ENCABEZADOS[pestana], map(str, fila))))

    @classmethod
    def desde_csv_demo(cls, carpeta: Path | None = None, config: dict[str, str] | None = None) -> "HojaSimulada":
        """Carga datos/productos.csv y datos/boletas.csv (el simulador local usa esto)."""
        carpeta = carpeta or Path(__file__).resolve().parent / "datos"

        def leer_csv(nombre):
            with (carpeta / nombre).open(encoding="utf-8") as f:
                return list(csv.DictReader(f))

        cfg = config or CONFIG_DEMO
        return cls({
            "Productos": leer_csv("productos.csv"),
            "Boletas": leer_csv("boletas.csv"),
            "Config": [{"clave": k, "valor": v} for k, v in cfg.items()],
        })


CONFIG_DEMO = {
    "tasa_mensual_pct": "3.5",
    "plazos_cuotas": "3,6,12,18",
    "costo_evaluacion_tecnica": "50",
    "horario_atencion": "Lun-Sab 9:00-19:00, Dom 10:00-14:00",
    "direccion": "Av. Ficticia 123, Lima (tienda de demostración)",
    "telefono_guardia": "51999000000",
    "nombre_tienda": "Electro Demo",
}


class HojaGoogle:
    def __init__(self, sheet_id: str, credenciales_json: str, gc=None):
        if not sheet_id:
            raise ValueError("Falta GOOGLE_SHEET_ID")
        if gc is None:
            if not credenciales_json:
                raise ValueError("Falta GOOGLE_CREDENTIALS_JSON")
            import gspread  # import diferido: las pruebas puras no lo necesitan
            try:
                info = json.loads(credenciales_json)
            except json.JSONDecodeError as e:
                raise ValueError("GOOGLE_CREDENTIALS_JSON no es un JSON válido") from e
            gc = gspread.service_account_from_dict(info)
        try:
            self._libro = gc.open_by_key(sheet_id)
        except Exception as e:  # noqa: BLE001 - gspread lanza varios tipos
            raise ErrorHoja(f"No se pudo abrir la hoja: {type(e).__name__}") from e
        self._pestanas: dict[str, object] = {}

    def _ws(self, pestana: str):
        if pestana not in self._pestanas:
            self._pestanas[pestana] = self._libro.worksheet(pestana)
        return self._pestanas[pestana]

    def leer(self, pestana: str) -> list[dict]:
        try:
            return self._ws(pestana).get_all_records(numericise_ignore=["all"])
        except Exception as e:  # noqa: BLE001
            raise ErrorHoja(f"No se pudo leer '{pestana}': {type(e).__name__}") from e

    def agregar(self, pestana: str, fila: list) -> None:
        try:
            self._ws(pestana).append_row([str(c) for c in fila], value_input_option="RAW")
        except Exception as e:  # noqa: BLE001
            raise ErrorHoja(f"No se pudo escribir en '{pestana}': {type(e).__name__}") from e


# --------------------------------------------------------------------------
# Repositorio
# --------------------------------------------------------------------------
class Repositorio:
    def __init__(self, hoja: Hoja, ttl: float = 60.0, ahora: Callable[[], datetime] | None = None,
                 reloj: Callable[[], float] = time.monotonic):
        self._hoja = hoja
        self._ttl = ttl
        self._reloj = reloj
        self._ahora = ahora or (lambda: datetime.now(LIMA))
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    # ---- lectura (con caché) ----
    def _cacheado(self, clave: str, cargar):
        with self._lock:
            hit = self._cache.get(clave)
            if hit and self._reloj() - hit[0] < self._ttl:
                return hit[1]
        valor = cargar()
        with self._lock:
            self._cache[clave] = (self._reloj(), valor)
        return valor

    def invalidar(self) -> None:
        with self._lock:
            self._cache.clear()

    def catalogo(self) -> list[n.Producto]:
        return self._cacheado("Productos", lambda: n.productos_desde_filas(self._hoja.leer("Productos")))

    def boletas(self) -> list[n.Boleta]:
        return self._cacheado("Boletas", lambda: n.boletas_desde_filas(self._hoja.leer("Boletas")))

    def config(self) -> dict[str, str]:
        return self._cacheado("Config", lambda: n.config_desde_filas(self._hoja.leer("Config")))

    def hoy(self):
        return self._ahora().date()

    # ---- escritura ----
    def _fecha(self) -> str:
        return self._ahora().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _t(texto) -> str:
        return ("" if texto is None else str(texto))[:MAX_CELDA]

    def registrar_conversacion(self, telefono: str, mensaje: str, intencion: str, respuesta: str) -> None:
        self._hoja.agregar("Conversaciones", [self._fecha(), telefono, self._t(mensaje), intencion, self._t(respuesta)])

    def registrar_derivacion(self, telefono: str, motivo: str, mensaje_original: str) -> None:
        self._hoja.agregar("Derivaciones", [self._fecha(), telefono, self._t(motivo), self._t(mensaje_original), "NO"])

    def crear_ticket(self, telefono: str, numero_boleta: str, sku: str, problema: str) -> str:
        """Id correlativo T-0001... (suficiente para una tienda; con muchas instancias
        concurrentes habría que usar un id único en vez de un correlativo)."""
        ids = [f.get("id", "") for f in self._hoja.leer("Tickets")]
        numeros = [int(i[2:]) for i in ids if str(i).startswith("T-") and str(i)[2:].isdigit()]
        nuevo = f"T-{max(numeros, default=0) + 1:04d}"
        self._hoja.agregar("Tickets", [nuevo, self._fecha(), telefono, numero_boleta, sku, self._t(problema), "ABIERTO"])
        return nuevo
