"""Simulador local de WhatsApp (sin Meta, sin celular): escribes como si fueras el cliente.

    python simulador.py                           # hoja de demostración en memoria
    python simulador.py --telefono 51999000009    # ser el titular de la boleta B001-0009
    python simulador.py -m "tienen refrigeradoras LG?"   # un solo mensaje y termina
    python simulador.py --hoja-real               # tu Google Sheet (GOOGLE_SHEET_ID / GOOGLE_CREDENTIALS_JSON)

Requiere GEMINI_API_KEY. Comandos:
    /registros        muestra lo que el bot dejó en Conversaciones, Derivaciones y Tickets
    /telefono <n>     cambia el número desde el que "escribes" (la garantía solo responde al titular)
    /salir
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, Iterable

from flujo import Bot
from ia import GeminiClient
from sheets import ENCABEZADOS, HojaGoogle, HojaSimulada, Repositorio

TABLAS_REGISTRO = ("Conversaciones", "Derivaciones", "Tickets")


def mostrar_registros(hoja, imprimir: Callable[[str], None]) -> None:
    for tabla in TABLAS_REGISTRO:
        filas = hoja.leer(tabla)
        imprimir(f"-- {tabla} ({len(filas)})")
        for f in filas:
            imprimir("   " + " | ".join(str(f.get(c, "")) for c in ENCABEZADOS[tabla]))


def ejecutar(bot: Bot, hoja, telefono: str, lineas: Iterable[str], imprimir: Callable[[str], None] = print) -> None:
    """Bucle del simulador separado de la entrada/salida para poder probarlo."""
    for linea in lineas:
        texto = linea.strip()
        if texto == "/salir":
            return
        if texto == "/registros":
            mostrar_registros(hoja, imprimir)
        elif texto.startswith("/telefono"):
            nuevo = texto.split(maxsplit=1)[1:] or [""]
            if nuevo[0].strip():
                telefono = nuevo[0].strip()
            imprimir(f"(escribes desde {telefono})")
        elif texto:
            respuesta = bot.procesar(telefono, texto)
            conv = hoja.leer("Conversaciones")
            intencion = conv[-1]["intencion"] if conv else "?"
            imprimir(f"\nbot [{intencion}]> " + respuesta.replace("\n", "\n     ") + "\n")


def _entrada() -> Iterable[str]:
    while True:
        try:
            yield input("cliente> ")
        except (EOFError, KeyboardInterrupt):
            return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoja-real", action="store_true")
    ap.add_argument("--telefono", default="51900000000")
    ap.add_argument("-m", "--mensaje", help="envía UN mensaje, imprime la respuesta y termina")
    args = ap.parse_args()

    clave = os.environ.get("GEMINI_API_KEY", "")
    if not clave:
        print("Falta GEMINI_API_KEY", file=sys.stderr)
        return 2
    hoja = (HojaGoogle(os.environ["GOOGLE_SHEET_ID"], os.environ["GOOGLE_CREDENTIALS_JSON"])
            if args.hoja_real else HojaSimulada.desde_csv_demo())
    bot = Bot(Repositorio(hoja, ttl=5), GeminiClient(clave))
    if args.mensaje:
        ejecutar(bot, hoja, args.telefono, [args.mensaje])
        return 0
    print(f"Simulador ({'hoja real' if args.hoja_real else 'hoja demo'}) como {args.telefono}. "
          "Comandos: /registros /telefono <n> /salir\n")
    ejecutar(bot, hoja, args.telefono, _entrada())
    return 0


if __name__ == "__main__":
    sys.exit(main())
