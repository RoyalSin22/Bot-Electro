"""Hoja de cálculo simulada: mismas filas que devolvería gspread.get_all_records()."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import negocio as n  # noqa: E402

FILAS_PRODUCTOS = [
    {"sku": "REF-001", "categoria": "Refrigeradora", "marca": "Samsung", "modelo": "RT35", "descripcion": "No Frost 2 puertas", "capacidad": "350 L", "precio": 1999, "stock": 4, "garantia_meses": 24},
    {"sku": "REF-002", "categoria": "Refrigeradora", "marca": "LG", "modelo": "GT32", "descripcion": "No Frost", "capacidad": "315 L", "precio": 1599.9, "stock": 2, "garantia_meses": 24},
    {"sku": "REF-003", "categoria": "Refrigeradora", "marca": "Mabe", "modelo": "RMA300", "descripcion": "Frost", "capacidad": "300 L", "precio": 1099, "stock": 0, "garantia_meses": 12},
    {"sku": "REF-004", "categoria": "Refrigeradora", "marca": "Samsung", "modelo": "RT20", "descripcion": "Compacta", "capacidad": "200 L", "precio": 899, "stock": 7, "garantia_meses": 12},
    {"sku": "LAV-001", "categoria": "Lavadora", "marca": "LG", "modelo": "WT19", "descripcion": "Carga superior", "capacidad": "19 kg", "precio": "1,299.00", "stock": 3, "garantia_meses": 24},
    {"sku": "LAV-002", "categoria": "Lavadora", "marca": "Samsung", "modelo": "WA13", "descripcion": "Carga superior", "capacidad": "13 kg", "precio": 999, "stock": 0, "garantia_meses": 12},
    {"sku": "TV-001", "categoria": "Televisor", "marca": "Sony", "modelo": "X80", "descripcion": "55 pulgadas 4K", "capacidad": "55 in", "precio": 2499, "stock": 5, "garantia_meses": 12},
    {"sku": "MIC-001", "categoria": "Microondas", "marca": "Oster", "modelo": "OM20", "descripcion": "Digital", "capacidad": "20 L", "precio": 299, "stock": 10, "garantia_meses": 6},
]

FILAS_BOLETAS = [
    {"numero_boleta": "B001-0001", "fecha_compra": "2025-01-15", "sku": "REF-001", "cliente": "Cliente Uno", "telefono": "51900000001"},
    {"numero_boleta": "B001-0002", "fecha_compra": "2024-01-31", "sku": "MIC-001", "cliente": "Cliente Dos", "telefono": "51900000002"},
    {"numero_boleta": "B001-0003", "fecha_compra": "2024-02-29", "sku": "TV-001", "cliente": "Cliente Tres", "telefono": "51900000003"},
    {"numero_boleta": "B001-0004", "fecha_compra": "15/03/2025", "sku": "XXX-999", "cliente": "Cliente Cuatro", "telefono": "51900000004"},
]

FILAS_CONFIG = [
    {"clave": "tasa_mensual_pct", "valor": "3.5"},
    {"clave": "plazos_cuotas", "valor": "3,6,12,18"},
    {"clave": "costo_evaluacion_tecnica", "valor": "50"},
    {"clave": "horario", "valor": "Lun-Sab 9:00-19:00"},
]


@pytest.fixture
def catalogo():
    return n.productos_desde_filas(FILAS_PRODUCTOS)


@pytest.fixture
def boletas():
    return n.boletas_desde_filas(FILAS_BOLETAS)


@pytest.fixture
def config():
    return n.config_desde_filas(FILAS_CONFIG)
