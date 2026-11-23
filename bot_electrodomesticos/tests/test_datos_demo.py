"""Valida que el catálogo y las boletas ficticios cumplan lo pedido
y sean consumibles por negocio.py tal como saldrían de la hoja."""
import csv
import sys
from collections import Counter
from pathlib import Path

import pytest

DATOS = Path(__file__).resolve().parent.parent / "datos"
sys.path.insert(0, str(DATOS))

import generar_datos as g  # noqa: E402
import negocio as n  # noqa: E402
from negocio import EstadoGarantia as EG  # noqa: E402

CONFIG = {"costo_evaluacion_tecnica": "50"}


@pytest.fixture(scope="module")
def filas_prod():
    return g.generar_productos()


@pytest.fixture(scope="module")
def prods(filas_prod):
    return n.productos_desde_filas(filas_prod)


@pytest.fixture(scope="module")
def bols(filas_prod):
    return n.boletas_desde_filas(g.generar_boletas(filas_prod))


def test_csv_en_disco_coincide_con_el_generador(filas_prod):
    for nombre, esperado in (("productos.csv", filas_prod), ("boletas.csv", g.generar_boletas(filas_prod))):
        with (DATOS / nombre).open(encoding="utf-8") as f:
            assert list(csv.DictReader(f)) == [{k: str(v) for k, v in fila.items()} for fila in esperado]


def test_cantidad_y_cobertura_de_categorias(prods):
    assert 40 <= len(prods) <= 60
    cuentas = Counter(p.categoria for p in prods)
    assert set(cuentas) == set(g.GARANTIA_MESES)
    assert all(c >= 8 for c in cuentas.values())


def test_marcas_pedidas_y_sku_unicos(prods):
    assert {"LG", "Samsung", "Mabe", "Indurama", "Bosch"} <= {p.marca for p in prods}
    assert len({p.sku for p in prods}) == len(prods)


def test_stock_variado_con_algunos_en_cero(prods):
    ceros = [p for p in prods if p.stock == 0]
    assert 5 <= len(ceros) <= 12
    assert len({p.stock for p in prods}) >= 6
    assert all(p.stock >= 0 for p in prods)


def test_garantia_12_o_24_segun_categoria(prods):
    assert {p.garantia_meses for p in prods} == {12, 24}
    assert all(p.garantia_meses == g.GARANTIA_MESES[p.categoria] for p in prods)


def test_precios_en_rangos_coherentes(prods):
    rangos = {"Refrigeradora": (900, 5000), "Lavadora": (700, 3200), "Cocina": (500, 3500),
              "Aire acondicionado": (1200, 4200), "Televisor": (1000, 7000)}
    for p in prods:
        lo, hi = rangos[p.categoria]
        assert lo <= p.precio <= hi, p.sku


def test_cada_categoria_con_stock_cero_tiene_alternativas(prods):
    for p in (x for x in prods if x.stock == 0):
        assert n.alternativas_misma_categoria(prods, [p]), p.sku


def test_boletas_cantidad_y_fechas_en_30_meses(bols):
    assert len(bols) == 15 and len({b.numero_boleta for b in bols}) == 15
    fechas = [b.fecha_compra for b in bols]
    assert max(fechas) <= g.FECHA_REFERENCIA
    assert min(fechas) >= n.sumar_meses(g.FECHA_REFERENCIA, -30)
    assert (max(fechas) - min(fechas)).days > 24 * 30  # bien repartidas


def test_boletas_apuntan_a_skus_existentes(prods, bols):
    assert all(n.producto_por_sku(prods, b.sku) for b in bols)


def test_hay_casos_dentro_y_fuera_de_garantia(prods, bols):
    estados = [n.evaluar_garantia(b.numero_boleta, bols, prods, CONFIG, g.FECHA_REFERENCIA).estado for b in bols]
    c = Counter(estados)
    assert set(c) == {EG.VIGENTE, EG.VENCIDA}
    assert c[EG.VIGENTE] == 9 and c[EG.VENCIDA] == 6


def test_casos_limite_incluidos(prods, bols):
    def ev(num): return n.evaluar_garantia(num, bols, prods, CONFIG, g.FECHA_REFERENCIA)
    assert ev("B001-0009").estado is EG.VIGENTE and ev("B001-0009").vence == g.FECHA_REFERENCIA  # vence hoy
    assert ev("B001-0008").estado is EG.VENCIDA and (g.FECHA_REFERENCIA - ev("B001-0008").vence).days == 3


def test_telefonos_ficticios_y_unicos(bols):
    assert all(b.telefono.startswith("51999") for b in bols)
    assert len({b.telefono for b in bols}) == len(bols)
