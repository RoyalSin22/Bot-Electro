"""Genera el catálogo y las boletas FICTICIOS de la tienda de demostración.

Marcas reales del mercado peruano; modelos y precios son ilustrativos
(orden de magnitud en soles), NO reflejan el catálogo de ningún comercio.
Salida: productos.csv y boletas.csv (importables a Google Sheets con
Archivo > Importar, o cargables con gspread en la Fase 3).

Uso:  python datos/generar_datos.py
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

# Fecha de referencia con la que se diseñaron los casos dentro/fuera de garantía.
FECHA_REFERENCIA = date(2026, 11, 23)

GARANTIA_MESES = {
    "Refrigeradora": 24,
    "Lavadora": 24,
    "Aire acondicionado": 24,
    "Cocina": 12,
    "Televisor": 12,
}
PREFIJO = {"Refrigeradora": "REF", "Lavadora": "LAV", "Cocina": "COC", "Aire acondicionado": "CLI", "Televisor": "TV"}

# (categoria, marca, modelo, descripcion, capacidad, precio, stock)
_CATALOGO = [
    # --- Refrigeración ---
    ("Refrigeradora", "Indurama", "RI-289", "No Frost 2 puertas, acero inoxidable", "280 L", 1499, 6),
    ("Refrigeradora", "Indurama", "RI-350", "No Frost 2 puertas", "340 L", 1899, 4),
    ("Refrigeradora", "Indurama", "RI-480", "No Frost 2 puertas con dispensador de agua", "450 L", 2799, 0),
    ("Refrigeradora", "Mabe", "RMA-250", "Frost 2 puertas", "250 L", 1099, 9),
    ("Refrigeradora", "Mabe", "RMP-300", "No Frost 2 puertas", "300 L", 1599, 3),
    ("Refrigeradora", "Mabe", "RMS-520", "Side by Side No Frost", "520 L", 3299, 2),
    ("Refrigeradora", "LG", "GT-29", "No Frost Inverter 2 puertas", "290 L", 1799, 8),
    ("Refrigeradora", "LG", "GT-37", "No Frost Inverter 2 puertas", "370 L", 2399, 5),
    ("Refrigeradora", "LG", "GS-65", "Side by Side No Frost Inverter", "650 L", 4599, 0),
    ("Refrigeradora", "Samsung", "RT-32", "No Frost Digital Inverter 2 puertas", "320 L", 1899, 7),
    ("Refrigeradora", "Samsung", "RT-38", "No Frost Digital Inverter 2 puertas", "380 L", 2599, 3),
    ("Refrigeradora", "Samsung", "RS-60", "Side by Side Digital Inverter", "600 L", 4299, 1),
    ("Refrigeradora", "Bosch", "KGN-36", "No Frost 2 puertas, congelador inferior", "366 L", 3999, 2),
    # --- Lavado ---
    ("Lavadora", "Indurama", "LI-8", "Carga superior", "8 kg", 899, 12),
    ("Lavadora", "Indurama", "LI-13", "Carga superior", "13 kg", 1199, 6),
    ("Lavadora", "Mabe", "LMA-70", "Carga superior", "7 kg", 799, 10),
    ("Lavadora", "Mabe", "LMH-17", "Carga superior", "17 kg", 1399, 0),
    ("Lavadora", "LG", "WT-13", "Carga superior Smart Inverter", "13 kg", 1499, 5),
    ("Lavadora", "LG", "WT-19", "Carga superior Smart Inverter", "19 kg", 1899, 4),
    ("Lavadora", "LG", "F4-10", "Carga frontal Inverter Direct Drive", "10.5 kg", 2399, 3),
    ("Lavadora", "Samsung", "WA-13", "Carga superior Digital Inverter", "13 kg", 1599, 7),
    ("Lavadora", "Samsung", "WA-19", "Carga superior Digital Inverter", "19 kg", 2099, 0),
    ("Lavadora", "Samsung", "WW-11", "Carga frontal EcoBubble", "11 kg", 2699, 2),
    ("Lavadora", "Bosch", "WAJ-8", "Carga frontal Serie 4", "8 kg", 2899, 3),
    # --- Cocina ---
    ("Cocina", "Indurama", "Parma", "Cocina a gas con horno", "4 hornillas", 679, 8),
    ("Cocina", "Indurama", "Florencia", "Cocina a gas con horno y grill", "5 hornillas", 999, 5),
    ("Cocina", "Indurama", "Venecia", "Cocina a gas con horno, acero inoxidable", "6 hornillas", 1399, 0),
    ("Cocina", "Indurama", "Roma-E", "Cocina a gas empotrable", "4 hornillas", 1199, 6),
    ("Cocina", "Mabe", "EMC-4", "Cocina a gas con horno", "4 hornillas", 649, 10),
    ("Cocina", "Mabe", "Diamante", "Cocina a gas con horno y grill", "5 hornillas", 949, 4),
    ("Cocina", "LG", "LSG-5", "Cocina a gas con horno", "5 hornillas", 1299, 3),
    ("Cocina", "Samsung", "NX-58", "Cocina a gas con horno de convección", "5 hornillas", 1599, 2),
    ("Cocina", "Bosch", "HGA-4", "Cocina a gas empotrable Serie 4", "4 hornillas", 2199, 2),
    ("Cocina", "Bosch", "PIE-4", "Encimera de inducción", "4 zonas", 3199, 1),
    # --- Climatización ---
    ("Aire acondicionado", "LG", "Dual Inverter 9", "Split Dual Inverter, frío", "9000 BTU", 1799, 6),
    ("Aire acondicionado", "LG", "Dual Inverter 12", "Split Dual Inverter, frío", "12000 BTU", 2299, 4),
    ("Aire acondicionado", "LG", "Dual Inverter 18", "Split Dual Inverter, frío", "18000 BTU", 3199, 0),
    ("Aire acondicionado", "Samsung", "WindFree 12", "Split WindFree Inverter, frío/calor", "12000 BTU", 2499, 5),
    ("Aire acondicionado", "Samsung", "WindFree 18", "Split WindFree Inverter, frío/calor", "18000 BTU", 3499, 2),
    ("Aire acondicionado", "Mabe", "MS-9", "Split on/off, frío", "9000 BTU", 1399, 8),
    ("Aire acondicionado", "Mabe", "MI-12", "Split Inverter, frío", "12000 BTU", 1899, 3),
    ("Aire acondicionado", "Bosch", "Climate 5000-12", "Split Inverter, frío", "12000 BTU", 2799, 2),
    ("Aire acondicionado", "Bosch", "Climate 5000-18", "Split Inverter, frío", "18000 BTU", 3899, 1),
    # --- Televisores ---
    ("Televisor", "LG", "UR78-43", "Smart TV 4K UHD", "43 in", 1399, 9),
    ("Televisor", "LG", "UR78-50", "Smart TV 4K UHD", "50 in", 1699, 6),
    ("Televisor", "LG", "QNED-55", "Smart TV QNED 4K", "55 in", 2599, 4),
    ("Televisor", "LG", "QNED-65", "Smart TV QNED 4K", "65 in", 3799, 0),
    ("Televisor", "LG", "OLED-55", "Smart TV OLED evo 4K", "55 in", 5299, 2),
    ("Televisor", "Samsung", "CU-43", "Smart TV Crystal UHD 4K", "43 in", 1299, 10),
    ("Televisor", "Samsung", "CU-55", "Smart TV Crystal UHD 4K", "55 in", 1899, 7),
    ("Televisor", "Samsung", "CU-65", "Smart TV Crystal UHD 4K", "65 in", 2899, 3),
    ("Televisor", "Samsung", "QLED-55", "Smart TV QLED 4K", "55 in", 3199, 4),
    ("Televisor", "Samsung", "NEO-75", "Smart TV Neo QLED 4K", "75 in", 6499, 0),
    ("Televisor", "Sony", "X75-50", "Smart TV Google TV 4K", "50 in", 1899, 5),
    ("Televisor", "Sony", "X80-55", "Smart TV Google TV 4K", "55 in", 2399, 6),
    ("Televisor", "Sony", "X80-65", "Smart TV Google TV 4K", "65 in", 3399, 0),
    ("Televisor", "Sony", "A80-55", "Smart TV OLED Google TV 4K", "55 in", 5799, 1),
]

# (fecha_compra, categoria, indice dentro de la categoría (1-based), cliente)
# Diseñadas para FECHA_REFERENCIA: ~30 meses hacia atrás, con casos límite.
_BOLETAS = [
    (date(2024, 6, 1), "Cocina", 2, "Rosa Quispe Huamán"),            # 12 m -> vencida
    (date(2024, 7, 22), "Televisor", 6, "Luis Ramos Cárdenas"),        # 12 m -> vencida
    (date(2024, 9, 3), "Aire acondicionado", 6, "Carmen Flores Díaz"),  # 24 m -> vencida
    (date(2024, 11, 15), "Refrigeradora", 4, "Jorge Mendoza Salas"),   # vence 2026-11-15 -> vencida
    (date(2024, 12, 18), "Lavadora", 5, "Ana Paredes Vega"),           # vence 2026-12-18 -> vigente
    (date(2025, 2, 14), "Refrigeradora", 7, "Miguel Torres Rojas"),    # vigente
    (date(2025, 6, 10), "Cocina", 5, "Elena Castillo Núñez"),          # 12 m -> vencida
    (date(2025, 11, 20), "Televisor", 7, "Pedro Gutiérrez León"),      # vence 2026-11-20 -> vencida por 3 días
    (date(2025, 11, 23), "Cocina", 1, "Lucía Fernández Ortiz"),        # vence HOY -> vigente (límite)
    (date(2025, 11, 28), "Televisor", 1, "Diego Chávez Ponce"),        # vence en 5 días -> vigente
    (date(2025, 12, 2), "Aire acondicionado", 2, "Marta Vargas Silva"),  # vigente
    (date(2026, 1, 30), "Lavadora", 8, "Raúl Medina Campos"),          # vigente
    (date(2026, 5, 12), "Cocina", 7, "Sofía Alvarado Reyes"),          # vigente
    (date(2026, 8, 5), "Televisor", 3, "Andrés Herrera Muñoz"),        # vigente
    (date(2026, 10, 20), "Refrigeradora", 10, "Patricia Luna Aguirre"),  # vigente
]


def generar_productos() -> list[dict]:
    contadores: dict[str, int] = {}
    filas = []
    for cat, marca, modelo, desc, cap, precio, stock in _CATALOGO:
        contadores[cat] = contadores.get(cat, 0) + 1
        filas.append({
            "sku": f"{PREFIJO[cat]}-{contadores[cat]:03d}", "categoria": cat, "marca": marca,
            "modelo": modelo, "descripcion": desc, "capacidad": cap,
            "precio": f"{precio:.2f}", "stock": stock, "garantia_meses": GARANTIA_MESES[cat],
        })
    return filas


def generar_boletas(productos: list[dict]) -> list[dict]:
    por_categoria: dict[str, list[dict]] = {}
    for p in productos:
        por_categoria.setdefault(p["categoria"], []).append(p)
    filas = []
    for k, (fecha, cat, idx, cliente) in enumerate(sorted(_BOLETAS, key=lambda b: b[0]), start=1):
        filas.append({
            "numero_boleta": f"B001-{k:04d}", "fecha_compra": fecha.isoformat(),
            "sku": por_categoria[cat][idx - 1]["sku"], "cliente": cliente,
            "telefono": f"51999{k:06d}",  # ficticio
        })
    return filas


def _escribir(ruta: Path, filas: list[dict]) -> None:
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)


def main() -> None:
    destino = Path(__file__).resolve().parent
    productos = generar_productos()
    _escribir(destino / "productos.csv", productos)
    _escribir(destino / "boletas.csv", generar_boletas(productos))
    print(f"{len(productos)} productos y {len(_BOLETAS)} boletas en {destino}")


if __name__ == "__main__":
    main()
