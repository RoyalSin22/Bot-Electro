"""Capa de IA: llamadas a Gemini y guardas deterministas sobre su salida.

El modelo interpreta (clasifica y extrae) y redacta. Todo lo que devuelve se
trata como NO CONFIABLE: se valida contra el mensaje original y contra los
datos que dio el sistema. Ante cualquier fallo se degrada a DERIVAR o a una
plantilla fija; nunca se deja pasar un dato sin respaldo.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

import negocio as n
from prompts import BP01, BP02, BP05, INTENCIONES, Prompt

MODELO = "gemini-flash-lite-latest"
URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
UMBRAL_CONFIANZA = 0.7
MAX_CHARS_MENSAJE = 1000
_REINTENTABLES = {429, 500, 502, 503, 504}


class ErrorIA(Exception):
    """Fallo de la llamada o respuesta inutilizable. Nunca incluye la clave."""


# --------------------------------------------------------------------------
# Cliente HTTP
# --------------------------------------------------------------------------
def construir_payload(prompt: Prompt, entrada: str) -> dict:
    contents = []
    for ej_in, ej_out in prompt.ejemplos:  # few-shot como turnos previos
        contents.append({"role": "user", "parts": [{"text": ej_in}]})
        contents.append({"role": "model", "parts": [{"text": ej_out}]})
    contents.append({"role": "user", "parts": [{"text": entrada}]})
    config: dict = {"temperature": prompt.temperatura, "maxOutputTokens": 1024}
    if prompt.es_json:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = prompt.esquema
    return {
        "systemInstruction": {"parts": [{"text": prompt.sistema}]},
        "contents": contents,
        "generationConfig": config,
    }


def _texto_de_respuesta(data: dict) -> str:
    candidatos = data.get("candidates") or []
    if not candidatos:
        bloqueo = (data.get("promptFeedback") or {}).get("blockReason", "sin_candidatos")
        raise ErrorIA(f"respuesta sin candidatos ({bloqueo})")
    partes = (candidatos[0].get("content") or {}).get("parts") or []
    texto = "".join(p.get("text", "") for p in partes).strip()
    if not texto:
        raise ErrorIA(f"respuesta vacía (finishReason={candidatos[0].get('finishReason')})")
    return texto


class GeminiClient:
    def __init__(self, api_key: str, modelo: str = MODELO, http_client: httpx.Client | None = None,
                 reintentos: int = 1, pausa=time.sleep):
        if not api_key:
            raise ValueError("Falta GEMINI_API_KEY")
        self._api_key = api_key
        self._url = URL_BASE.format(modelo=modelo)
        self._http = http_client or httpx.Client(timeout=20.0)
        self._reintentos = reintentos
        self._pausa = pausa

    def generar(self, prompt: Prompt, entrada: str) -> str:
        payload = construir_payload(prompt, entrada)
        headers = {"X-goog-api-key": self._api_key, "Content-Type": "application/json"}
        ultimo = "desconocido"
        for intento in range(self._reintentos + 1):
            try:
                resp = self._http.post(self._url, headers=headers, json=payload)
            except httpx.HTTPError as e:  # el texto de httpx no incluye cabeceras
                ultimo = type(e).__name__
            else:
                if resp.status_code == 200:
                    try:
                        return _texto_de_respuesta(resp.json())
                    except ValueError as e:
                        raise ErrorIA("respuesta no es JSON") from e
                ultimo = f"HTTP {resp.status_code}"
                if resp.status_code not in _REINTENTABLES:
                    break
            if intento < self._reintentos:
                self._pausa(1.0 * (intento + 1))
        raise ErrorIA(f"llamada a Gemini falló: {ultimo}")


def parsear_json(texto: str) -> dict:
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        obj = json.loads(limpio)
    except json.JSONDecodeError as e:
        raise ErrorIA("JSON inválido") from e
    if not isinstance(obj, dict):
        raise ErrorIA("se esperaba un objeto JSON")
    return obj


def _limpiar(mensaje: str) -> str:
    return (mensaje or "").strip()[:MAX_CHARS_MENSAJE]


# --------------------------------------------------------------------------
# BP-01 Clasificación
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Clasificacion:
    intencion: str            # la que se usa para enrutar
    confianza: float
    intencion_modelo: str | None = None
    motivo_derivacion: str | None = None  # por qué se forzó DERIVAR, si aplica


def clasificar_intencion(cliente: GeminiClient, mensaje: str) -> Clasificacion:
    mensaje = _limpiar(mensaje)
    if not mensaje:
        return Clasificacion("DERIVAR", 0.0, None, "mensaje_vacio")
    try:
        obj = parsear_json(cliente.generar(BP01, mensaje))
        intencion = str(obj["intencion"]).strip().upper()
        confianza = float(obj["confianza"])
    except ErrorIA as e:
        return Clasificacion("DERIVAR", 0.0, None, f"error_ia: {e}")
    except (KeyError, TypeError, ValueError):
        return Clasificacion("DERIVAR", 0.0, None, "respuesta_invalida")
    if intencion not in INTENCIONES or not 0.0 <= confianza <= 1.0:
        return Clasificacion("DERIVAR", 0.0, None, "respuesta_invalida")
    if confianza < UMBRAL_CONFIANZA:
        return Clasificacion("DERIVAR", confianza, intencion, "baja_confianza")
    return Clasificacion(intencion, confianza, intencion)


# --------------------------------------------------------------------------
# Guardas de respaldo: un dato extraído debe aparecer en el mensaje
# --------------------------------------------------------------------------
def _alnum(texto) -> str:
    return re.sub(r"[^a-z0-9]", "", n.normalizar(texto))


def _numeros_del_mensaje(mensaje: str) -> set[Decimal]:
    nums = set()
    for tok in re.findall(r"\d[\d.,]*", mensaje):
        try:
            nums.add(n.a_decimal(tok))
        except (ValueError, InvalidOperation):
            pass
        nums.add(Decimal(re.sub(r"\D", "", tok) or 0))  # '1,500' / '1.500' -> 1500
    return nums


def _precio_respaldado(precio: Decimal, mensaje: str) -> bool:
    if precio in _numeros_del_mensaje(mensaje):
        return True
    m = n.normalizar(mensaje)
    if re.search(r"\bmil\b|\bk\b", m):  # 'mil quinientos', '2 mil', '2k'
        return True
    return False


def _capacidad_respaldada(capacidad: str, mensaje: str) -> bool:
    m = re.match(r"\s*(\d+(?:\.\d+)?)", capacidad)
    if not m:
        return False
    return Decimal(m.group(1)) in _numeros_del_mensaje(mensaje)


# --------------------------------------------------------------------------
# BP-02 Criterios de búsqueda
# --------------------------------------------------------------------------
def extraer_criterios(cliente: GeminiClient, mensaje: str) -> n.Criterios:
    """Criterios vacíos si falla algo: el flujo pedirá aclaración (BP-06)."""
    mensaje = _limpiar(mensaje)
    if not mensaje:
        return n.Criterios()
    try:
        obj = parsear_json(cliente.generar(BP02, mensaje))
    except ErrorIA:
        return n.Criterios()

    def texto(clave):
        v = obj.get(clave)
        return v.strip() if isinstance(v, str) and v.strip() else None

    categoria, marca, capacidad = texto("categoria"), texto("marca"), texto("capacidad")
    if marca and _alnum(marca) not in _alnum(mensaje):
        marca = None  # marca inventada: no estaba en el mensaje
    if capacidad and not _capacidad_respaldada(capacidad, mensaje):
        capacidad = None
    precio = None
    try:
        if obj.get("precio_max") is not None:
            candidato = n.a_decimal(obj["precio_max"])
            if candidato > 0 and _precio_respaldado(candidato, mensaje):
                precio = candidato
    except (ValueError, InvalidOperation):
        precio = None
    return n.Criterios(categoria, marca, capacidad, precio)


# --------------------------------------------------------------------------
# BP-05 Datos de garantía
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DatosGarantia:
    numero_boleta: str | None = None
    sku: str | None = None
    problema: str | None = None


def extraer_garantia(cliente: GeminiClient, mensaje: str) -> DatosGarantia:
    mensaje = _limpiar(mensaje)
    if not mensaje:
        return DatosGarantia()
    try:
        obj = parsear_json(cliente.generar(BP05, mensaje))
    except ErrorIA:
        return DatosGarantia()

    def texto(clave):
        v = obj.get(clave)
        return v.strip() if isinstance(v, str) and v.strip() else None

    boleta, sku, problema = texto("numero_boleta"), texto("sku"), texto("problema")
    if boleta and _alnum(boleta) not in _alnum(mensaje):
        boleta = None
    if sku and _alnum(sku) not in _alnum(mensaje):
        sku = None
    return DatosGarantia(boleta, sku, problema)


# --------------------------------------------------------------------------
# Redacción (BP-03/04/06/07) con guardas
# --------------------------------------------------------------------------
_RE_MONTO = re.compile(r"S/\s*([\d.,]+\d)")
_RE_FECHA = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b")


def _montos(texto: str) -> set[Decimal]:
    out = set()
    for m in _RE_MONTO.findall(texto):
        try:
            out.add(n.redondear(n.a_decimal(m)))
        except (ValueError, InvalidOperation):
            out.add(Decimal("-1"))  # monto ilegible: nunca estará permitido
    return out


def redaccion_valida(salida: str, entrada: str) -> bool:
    """El texto sirve si: tiene contenido, <= 4 líneas, sin markdown que WhatsApp no
    entiende, y todo monto o fecha que menciona ya estaba en la entrada."""
    lineas = [l for l in salida.strip().splitlines() if l.strip()]
    if not lineas or len(lineas) > 4:
        return False
    if re.search(r"^\s*#", salida, re.M) or "**" in salida:
        return False
    if not _montos(salida) <= _montos(entrada):
        return False
    return set(_RE_FECHA.findall(salida)) <= set(_RE_FECHA.findall(entrada))


def redactar(cliente: GeminiClient, prompt: Prompt, datos: dict, respaldo: str) -> str:
    """Redacta con el modelo; si falla o la guarda rechaza, devuelve `respaldo`
    (plantilla determinista armada por el llamador con los mismos datos)."""
    entrada = json.dumps(datos, ensure_ascii=False)
    try:
        salida = cliente.generar(prompt, entrada).strip()
    except ErrorIA:
        return respaldo
    return salida if redaccion_valida(salida, entrada) else respaldo
