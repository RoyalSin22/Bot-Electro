"""Evalúa la capa de IA contra tests/mensajes_prueba.json (20 mensajes).

Uso (requiere GEMINI_API_KEY):  python evaluar_ia.py
Sale con código 1 si no se alcanzan los umbrales.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import ia
import negocio as n

RUTA = Path(__file__).resolve().parent / "tests" / "mensajes_prueba.json"
UMBRAL_INTENCION = 0.90   # >= 18/20
UMBRAL_EXTRACCION = 1.0   # todas las extracciones esperadas


def cargar_mensajes() -> list[dict]:
    return json.loads(RUTA.read_text(encoding="utf-8"))


def _norm(v):
    return n.normalizar(v) if isinstance(v, str) else v


def comparar_criterios(real: n.Criterios, esperado: dict) -> list[str]:
    errores = []
    for campo in ("categoria", "marca"):
        if _norm(getattr(real, campo)) != _norm(esperado[campo]):
            errores.append(f"{campo}: {getattr(real, campo)!r} != {esperado[campo]!r}")
    cap_real = n._compacto(real.capacidad) if real.capacidad else None
    cap_esp = n._compacto(esperado["capacidad"]) if esperado["capacidad"] else None
    if cap_real != cap_esp:
        errores.append(f"capacidad: {real.capacidad!r} != {esperado['capacidad']!r}")
    esp_precio = Decimal(str(esperado["precio_max"])) if esperado["precio_max"] is not None else None
    if real.precio_max != esp_precio:
        errores.append(f"precio_max: {real.precio_max!r} != {esp_precio!r}")
    return errores


def comparar_garantia(real: ia.DatosGarantia, esperado: dict) -> list[str]:
    errores = []
    for campo in ("numero_boleta", "sku"):
        if _norm(getattr(real, campo)) != _norm(esperado[campo]):
            errores.append(f"{campo}: {getattr(real, campo)!r} != {esperado[campo]!r}")
    if bool(real.problema) != esperado["problema"]:
        errores.append(f"problema: {real.problema!r} (se esperaba {'texto' if esperado['problema'] else 'null'})")
    return errores


@dataclass
class Resultado:
    total_intencion: int = 0
    aciertos_intencion: int = 0
    total_extraccion: int = 0
    aciertos_extraccion: int = 0
    fallos: list[str] = field(default_factory=list)

    @property
    def exactitud_intencion(self) -> float:
        return self.aciertos_intencion / self.total_intencion if self.total_intencion else 0.0

    @property
    def exactitud_extraccion(self) -> float:
        return self.aciertos_extraccion / self.total_extraccion if self.total_extraccion else 1.0

    @property
    def aprobado(self) -> bool:
        return self.exactitud_intencion >= UMBRAL_INTENCION and self.exactitud_extraccion >= UMBRAL_EXTRACCION


def evaluar(cliente: ia.GeminiClient, mensajes: list[dict], pausa: float = 0.0) -> Resultado:
    r = Resultado()
    for m in mensajes:
        c = ia.clasificar_intencion(cliente, m["mensaje"])
        r.total_intencion += 1
        if c.intencion == m["intencion"]:
            r.aciertos_intencion += 1
        else:
            r.fallos.append(f"#{m['id']} intención {c.intencion} ({c.confianza:.2f}, {c.motivo_derivacion}) != {m['intencion']}: {m['mensaje']}")
        if "criterios" in m:
            errs = comparar_criterios(ia.extraer_criterios(cliente, m["mensaje"]), m["criterios"])
            r.total_extraccion += 1
            r.aciertos_extraccion += not errs
            r.fallos += [f"#{m['id']} BP-02 {e}" for e in errs]
        if "garantia" in m:
            errs = comparar_garantia(ia.extraer_garantia(cliente, m["mensaje"]), m["garantia"])
            r.total_extraccion += 1
            r.aciertos_extraccion += not errs
            r.fallos += [f"#{m['id']} BP-05 {e}" for e in errs]
        if pausa:
            time.sleep(pausa)  # respetar el límite de la capa gratuita
    return r


def main() -> int:
    clave = os.environ.get("GEMINI_API_KEY", "")
    if not clave:
        print("Falta GEMINI_API_KEY: no se puede evaluar contra el modelo real.", file=sys.stderr)
        return 2
    r = evaluar(ia.GeminiClient(clave), cargar_mensajes(), pausa=1.0)
    print(f"Intención:  {r.aciertos_intencion}/{r.total_intencion} ({r.exactitud_intencion:.0%})  umbral {UMBRAL_INTENCION:.0%}")
    print(f"Extracción: {r.aciertos_extraccion}/{r.total_extraccion} ({r.exactitud_extraccion:.0%})  umbral {UMBRAL_EXTRACCION:.0%}")
    for f in r.fallos:
        print("  FALLO", f)
    print("APROBADO" if r.aprobado else "NO APROBADO")
    return 0 if r.aprobado else 1


if __name__ == "__main__":
    sys.exit(main())
