"""Simulador local de WhatsApp (sin Meta): escribe como si fueras un cliente.

    python simulador.py                 # hoja de demostración en memoria
    python simulador.py --hoja-real     # tu Google Sheet (GOOGLE_SHEET_ID / GOOGLE_CREDENTIALS_JSON)
    python simulador.py --telefono 51999000009   # simular ser el titular de una boleta

Requiere GEMINI_API_KEY. Comandos: /salir
"""
from __future__ import annotations

import argparse
import os
import sys

from flujo import Bot
from ia import GeminiClient
from sheets import HojaGoogle, HojaSimulada, Repositorio


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoja-real", action="store_true")
    ap.add_argument("--telefono", default="51900000000")
    args = ap.parse_args()

    clave = os.environ.get("GEMINI_API_KEY", "")
    if not clave:
        print("Falta GEMINI_API_KEY", file=sys.stderr)
        return 2
    hoja = (HojaGoogle(os.environ["GOOGLE_SHEET_ID"], os.environ["GOOGLE_CREDENTIALS_JSON"])
            if args.hoja_real else HojaSimulada.desde_csv_demo())
    repo = Repositorio(hoja, ttl=5)
    bot = Bot(repo, GeminiClient(clave))
    print(f"Simulador ({'hoja real' if args.hoja_real else 'hoja demo'}) como {args.telefono}. /salir para terminar.\n")
    while True:
        try:
            texto = input("cliente> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if texto == "/salir":
            return 0
        if texto:
            print("\nbot>", bot.procesar(args.telefono, texto).replace("\n", "\n     "), "\n")


if __name__ == "__main__":
    sys.exit(main())
