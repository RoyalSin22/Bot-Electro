from datetime import date
from decimal import Decimal as D

import pytest

import negocio as n
from negocio import Criterios, EstadoBusqueda as EB, EstadoGarantia as EG


# ------------------------------ formato y parseo ---------------------------
@pytest.mark.parametrize("entrada,esperado", [
    (1299, "S/ 1,299.00"), ("1299", "S/ 1,299.00"), (D("0.5"), "S/ 0.50"),
    (1599.9, "S/ 1,599.90"), (1234567.891, "S/ 1,234,567.89"), ("S/ 50", "S/ 50.00"),
])
def test_formatear_soles(entrada, esperado):
    assert n.formatear_soles(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("1,299.00", D("1299.00")), ("1.299,00", D("1299.00")), ("3,5", D("3.5")),
    ("3.5", D("3.5")), ("1,299", D("1299")), (7, D("7")), (2.5, D("2.5")),
])
def test_a_decimal(entrada, esperado):
    assert n.a_decimal(entrada) == esperado


@pytest.mark.parametrize("malo", ["", "abc", None, True])
def test_a_decimal_rechaza_basura(malo):
    with pytest.raises(ValueError):
        n.a_decimal(malo)


# ------------------------------ cuotas -------------------------------------
def test_cuota_valor_conocido():
    # 1000 al 2 % mensual a 12 meses: 94.5596... -> 94.56
    c = n.calcular_cuota(1000, 2, 12)
    assert c.monto_cuota == D("94.56")
    assert c.total_a_pagar == D("1134.72")
    assert c.interes_total == D("134.72")


def test_cuota_coincide_con_formula_independiente():
    P, i, k = 1299.0, 0.035, 12
    esperado = P * i / (1 - (1 + i) ** -k)
    assert abs(float(n.calcular_cuota(P, 3.5, k).monto_cuota) - esperado) <= 0.005


def test_cuota_tasa_cero_divide_en_partes_iguales():
    c = n.calcular_cuota(1200, 0, 12)
    assert c.monto_cuota == D("100.00") and c.interes_total == D("0.00")


def test_cuota_una_sola_cuota_es_principal_mas_interes():
    assert n.calcular_cuota(1000, 2, 1).monto_cuota == D("1020.00")


def test_cuota_mas_plazo_baja_cuota_y_sube_interes():
    c6, c12 = n.calcular_cuota(2000, 3.5, 6), n.calcular_cuota(2000, 3.5, 12)
    assert c12.monto_cuota < c6.monto_cuota
    assert c12.interes_total > c6.interes_total


@pytest.mark.parametrize("P,t,k", [(0, 3, 12), (-5, 3, 12), (1000, -1, 12), (1000, 3, 0), (1000, 3, -2), (1000, 3, 1.5)])
def test_cuota_entradas_invalidas(P, t, k):
    with pytest.raises(ValueError):
        n.calcular_cuota(P, t, k)


def test_plan_usa_tasa_y_plazos_de_config(catalogo, config):
    prod = n.producto_por_sku(catalogo, "LAV-001")
    plan = n.plan_de_cuotas(prod, config)
    assert [c.plazo for c in plan] == [3, 6, 12, 18]
    assert plan[2] == n.calcular_cuota(D("1299.00"), D("3.5"), 12)


def test_plan_plazo_no_ofrecido(catalogo, config):
    with pytest.raises(ValueError, match="no ofrecidos"):
        n.plan_de_cuotas(n.producto_por_sku(catalogo, "LAV-001"), config, [10])


def test_plan_sin_tasa_en_config_falla_en_vez_de_inventar(catalogo):
    with pytest.raises(KeyError):
        n.plan_de_cuotas(catalogo[0], {"plazos_cuotas": "3,6"})


# ------------------------------ catálogo / stock ---------------------------
def test_busqueda_disponible_ordenada_por_precio_y_maximo_tres(catalogo):
    r = n.buscar_productos(catalogo, Criterios(categoria="refrigeradora"))
    assert r.estado is EB.DISPONIBLES
    assert [p.sku for p in r.productos] == ["REF-004", "REF-002", "REF-001"]  # REF-003 sin stock


def test_busqueda_ignora_tildes_y_mayusculas(catalogo):
    r = n.buscar_productos(catalogo, Criterios(categoria="REFRIGERADORA", marca="samsung"))
    assert {p.sku for p in r.productos} == {"REF-001", "REF-004"}


def test_busqueda_plural_de_categoria(catalogo):
    assert n.buscar_productos(catalogo, Criterios(categoria="lavadoras")).productos[0].sku == "LAV-001"


@pytest.mark.parametrize("cap", ["350", "350 L", "350l"])
def test_busqueda_capacidad_flexible(catalogo, cap):
    r = n.buscar_productos(catalogo, Criterios(categoria="refrigeradora", capacidad=cap))
    assert [p.sku for p in r.productos] == ["REF-001"]


def test_capacidad_numerica_no_hace_coincidencia_parcial(catalogo):
    # '35' no debe encontrar '350 L'
    assert n.buscar_productos(catalogo, Criterios(capacidad="35")).estado is EB.NO_MANEJADO


def test_stock_cero_no_disponible_con_alternativas_misma_categoria(catalogo):
    r = n.buscar_productos(catalogo, Criterios(categoria="lavadora", marca="samsung"))
    assert r.estado is EB.SIN_STOCK
    assert [p.sku for p in r.productos] == ["LAV-002"]
    assert [p.sku for p in r.alternativas] == ["LAV-001"]
    assert all(p.categoria == "Lavadora" and p.stock > 0 for p in r.alternativas)


def test_stock_cero_sin_alternativas_no_inventa(catalogo):
    sin_alt = [p for p in catalogo if p.sku != "LAV-001"]
    r = n.buscar_productos(sin_alt, Criterios(categoria="lavadora"))
    assert r.estado is EB.SIN_STOCK and r.alternativas == ()


def test_producto_inexistente_es_no_manejado(catalogo):
    for crit in (Criterios(categoria="cafetera"), Criterios(categoria="televisor", marca="Philips")):
        r = n.buscar_productos(catalogo, crit)
        assert r.estado is EB.NO_MANEJADO and r.productos == () and r.alternativas == ()


def test_consulta_sin_criterios_pide_aclaracion(catalogo):
    assert n.buscar_productos(catalogo, Criterios()).estado is EB.SIN_CRITERIOS


def test_precio_max_filtra(catalogo):
    r = n.buscar_productos(catalogo, Criterios(categoria="refrigeradora", precio_max=D("1600")))
    assert [p.sku for p in r.productos] == ["REF-004", "REF-002"]


def test_precio_max_incluye_el_limite_exacto(catalogo):
    r = n.buscar_productos(catalogo, Criterios(categoria="refrigeradora", precio_max=D("899")))
    assert [p.sku for p in r.productos] == ["REF-004"]


def test_todo_sobre_presupuesto_se_informa_como_tal(catalogo):
    r = n.buscar_productos(catalogo, Criterios(categoria="televisor", precio_max=D("1000")))
    assert r.estado is EB.FUERA_DE_PRESUPUESTO and r.productos[0].sku == "TV-001"


def test_el_precio_sale_de_la_hoja_con_su_precision(catalogo):
    assert n.producto_por_sku(catalogo, "REF-002").precio == D("1599.9")
    assert n.producto_por_sku(catalogo, "LAV-001").precio == D("1299.00")  # texto '1,299.00'


# ------------------------------ garantía -----------------------------------
HOY = date(2026, 6, 1)


def test_suma_meses_ajusta_fin_de_mes():
    assert n.sumar_meses(date(2024, 1, 31), 1) == date(2024, 2, 29)   # bisiesto
    assert n.sumar_meses(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert n.sumar_meses(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert n.sumar_meses(date(2025, 11, 15), 3) == date(2026, 2, 15)  # cruce de año


def test_garantia_vigente(boletas, catalogo, config):
    r = n.evaluar_garantia("B001-0001", boletas, catalogo, config, hoy=HOY)  # vence 2027-01-15
    assert r.estado is EG.VIGENTE and r.vence == date(2027, 1, 15)
    assert r.requiere_ticket and r.costo_evaluacion is None


def test_garantia_el_dia_de_vencimiento_aun_cubre(boletas, catalogo, config):
    assert n.evaluar_garantia("B001-0001", boletas, catalogo, config, date(2027, 1, 15)).estado is EG.VIGENTE
    r = n.evaluar_garantia("B001-0001", boletas, catalogo, config, date(2027, 1, 16))
    assert r.estado is EG.VENCIDA


def test_garantia_vencida_informa_costo_de_config(boletas, catalogo, config):
    r = n.evaluar_garantia("B001-0003", boletas, catalogo, config, hoy=HOY)  # TV 12 m desde 2024-02-29
    assert r.estado is EG.VENCIDA and r.vence == date(2025, 2, 28)
    assert r.costo_evaluacion == D("50") and not r.requiere_ticket


def test_garantia_costo_cambia_con_config(boletas, catalogo, config):
    config["costo_evaluacion_tecnica"] = "S/ 80.50"
    assert n.evaluar_garantia("B001-0003", boletas, catalogo, config, HOY).costo_evaluacion == D("80.50")


def test_garantia_boleta_inexistente(boletas, catalogo, config):
    assert n.evaluar_garantia("B999-9999", boletas, catalogo, config, HOY).estado is EG.BOLETA_NO_ENCONTRADA


def test_garantia_numero_de_boleta_ignora_mayusculas_y_espacios(boletas, catalogo, config):
    assert n.evaluar_garantia(" b001-0001 ", boletas, catalogo, config, HOY).estado is EG.VIGENTE


def test_garantia_sku_que_no_corresponde_a_la_boleta(boletas, catalogo, config):
    r = n.evaluar_garantia("B001-0001", boletas, catalogo, config, HOY, sku="TV-001")
    assert r.estado is EG.PRODUCTO_NO_COINCIDE and not r.requiere_ticket


def test_garantia_sku_correcto_se_acepta(boletas, catalogo, config):
    assert n.evaluar_garantia("B001-0001", boletas, catalogo, config, HOY, sku="ref-001").estado is EG.VIGENTE


def test_garantia_boleta_con_sku_fuera_de_catalogo(boletas, catalogo, config):
    assert n.evaluar_garantia("B001-0004", boletas, catalogo, config, HOY).estado is EG.PRODUCTO_NO_EN_CATALOGO


def test_fecha_en_formato_dd_mm_aaaa(boletas):
    assert boletas[3].fecha_compra == date(2025, 3, 15)


def test_vencida_sin_costo_en_config_falla_en_vez_de_inventar(boletas, catalogo):
    with pytest.raises(KeyError):
        n.evaluar_garantia("B001-0003", boletas, catalogo, {}, HOY)
