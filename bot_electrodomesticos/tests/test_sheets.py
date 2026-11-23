import sys
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import negocio as n  # noqa: E402
import sheets as S  # noqa: E402

AHORA = datetime(2026, 11, 23, 15, 30, 5, tzinfo=S.LIMA)


@pytest.fixture
def hoja():
    return S.HojaSimulada.desde_csv_demo()


@pytest.fixture
def repo(hoja):
    return S.Repositorio(hoja, ahora=lambda: AHORA)


# ------------------------------ lectura ------------------------------------
def test_repositorio_lee_y_parsea_la_hoja_demo(repo):
    assert len(repo.catalogo()) == 57 and len(repo.boletas()) == 15
    assert n.tasa_mensual_desde_config(repo.config()) == D("3.5")
    assert n.plazos_desde_config(repo.config()) == [3, 6, 12, 18]
    assert repo.hoy() == date(2026, 11, 23)


def test_la_logica_de_negocio_funciona_sobre_lo_leido_de_la_hoja(repo):
    plan = n.plan_de_cuotas(n.producto_por_sku(repo.catalogo(), "LAV-006"), repo.config(), [12])
    assert plan[0].monto_cuota == n.calcular_cuota(D("1899"), D("3.5"), 12).monto_cuota
    g = n.evaluar_garantia("B001-0009", repo.boletas(), repo.catalogo(), repo.config(), repo.hoy(), telefono="51999000009")
    assert g.estado is n.EstadoGarantia.VIGENTE


def test_cache_evita_lecturas_repetidas_y_expira():
    class Contador(S.HojaSimulada):
        lecturas = 0
        def leer(self, pestana):
            Contador.lecturas += 1
            return super().leer(pestana)

    reloj = [0.0]
    r = S.Repositorio(Contador.desde_csv_demo(), ttl=60, reloj=lambda: reloj[0])
    r.catalogo(); r.catalogo(); r.catalogo()
    assert Contador.lecturas == 1
    reloj[0] = 61
    r.catalogo()
    assert Contador.lecturas == 2


def test_cambio_en_la_hoja_se_ve_tras_invalidar(hoja):
    r = S.Repositorio(hoja)
    assert n.producto_por_sku(r.catalogo(), "REF-001").stock == 6
    hoja._tablas["Productos"][0]["stock"] = "0"
    assert n.producto_por_sku(r.catalogo(), "REF-001").stock == 6   # aún cacheado
    r.invalidar()
    assert n.producto_por_sku(r.catalogo(), "REF-001").stock == 0


# ------------------------------ escritura ----------------------------------
def test_registrar_conversacion(repo, hoja):
    repo.registrar_conversacion("51911", "tienen lavadoras?", "CATALOGO", "Sí, tenemos...")
    assert hoja.leer("Conversaciones") == [{"fecha": "2026-11-23 15:30:05", "telefono": "51911",
                                            "mensaje": "tienen lavadoras?", "intencion": "CATALOGO", "respuesta": "Sí, tenemos..."}]


def test_registrar_derivacion_queda_pendiente(repo, hoja):
    repo.registrar_derivacion("51911", "baja_confianza", "quiero algo")
    fila = hoja.leer("Derivaciones")[0]
    assert fila["motivo"] == "baja_confianza" and fila["mensaje_original"] == "quiero algo" and fila["atendido"] == "NO"


def test_tickets_con_id_correlativo(repo, hoja):
    assert repo.crear_ticket("51999000009", "B001-0009", "COC-001", "no enciende") == "T-0001"
    assert repo.crear_ticket("51999000012", "B001-0012", "LAV-008", "no centrifuga") == "T-0002"
    t = hoja.leer("Tickets")
    assert t[1]["id"] == "T-0002" and t[0]["estado"] == "ABIERTO" and t[0]["problema"] == "no enciende"


def test_ticket_ignora_ids_raros_al_calcular_el_siguiente(hoja):
    hoja.agregar("Tickets", ["T-0007", "x", "x", "x", "x", "x", "ABIERTO"])
    hoja.agregar("Tickets", ["manual", "x", "x", "x", "x", "x", "ABIERTO"])
    assert S.Repositorio(hoja, ahora=lambda: AHORA).crear_ticket("1", "b", "s", "p") == "T-0008"


def test_textos_largos_se_recortan(repo, hoja):
    repo.registrar_conversacion("51911", "x" * 10_000, "DERIVAR", "ok")
    assert len(hoja.leer("Conversaciones")[0]["mensaje"]) == S.MAX_CELDA


def test_none_se_guarda_vacio(repo, hoja):
    repo.crear_ticket("51911", "B", "S", None)
    assert hoja.leer("Tickets")[0]["problema"] == ""


# ------------------------------ HojaGoogle (gspread simulado) ---------------
class FakeWS:
    def __init__(self, filas=None, falla=False):
        self.filas, self.falla, self.escrituras = filas or [], falla, []
    def get_all_records(self, **kw):
        if self.falla:
            raise RuntimeError("quota exceeded: SECRETO")
        self.kw = kw
        return self.filas
    def append_row(self, values, value_input_option=None):
        self.escrituras.append((values, value_input_option))


class FakeLibro:
    def __init__(self, hojas): self.hojas = hojas
    def worksheet(self, nombre): return self.hojas[nombre]


class FakeGC:
    def __init__(self, libro): self.libro = libro
    def open_by_key(self, key):
        self.key = key
        return self.libro


def test_hoja_google_lee_como_texto_y_escribe_en_raw():
    ws = FakeWS([{"sku": "A"}])
    h = S.HojaGoogle("ID", "", gc=FakeGC(FakeLibro({"Productos": ws, "Conversaciones": ws})))
    assert h.leer("Productos") == [{"sku": "A"}]
    assert ws.kw == {"numericise_ignore": ["all"]}
    h.agregar("Conversaciones", ["2026", "51", "=HYPERLINK(\"http://malo\")", "DERIVAR", 5])
    valores, modo = ws.escrituras[0]
    assert modo == "RAW"                       # '=' no se evalúa como fórmula
    assert valores[2].startswith("=") and valores[4] == "5"


def test_errores_de_hoja_no_filtran_detalles_sensibles():
    h = S.HojaGoogle("ID", "", gc=FakeGC(FakeLibro({"Productos": FakeWS(falla=True)})))
    with pytest.raises(S.ErrorHoja) as e:
        h.leer("Productos")
    assert "SECRETO" not in str(e.value) and "RuntimeError" in str(e.value)


def test_no_se_puede_abrir_la_hoja():
    class Mal:
        def open_by_key(self, k): raise PermissionError("403 SECRETO")
    with pytest.raises(S.ErrorHoja) as e:
        S.HojaGoogle("ID", "", gc=Mal())
    assert "SECRETO" not in str(e.value)


@pytest.mark.parametrize("sheet,cred,msg", [("", "{}", "GOOGLE_SHEET_ID"), ("ID", "", "GOOGLE_CREDENTIALS_JSON"), ("ID", "no-json", "JSON válido")])
def test_configuracion_invalida(sheet, cred, msg):
    with pytest.raises(ValueError, match=msg):
        S.HojaGoogle(sheet, cred)


def test_encabezados_coinciden_con_la_hoja_real_generada():
    assert S.ENCABEZADOS["Productos"] == ["sku", "categoria", "marca", "modelo", "descripcion", "capacidad", "precio", "stock", "garantia_meses"]
    assert S.ENCABEZADOS["Config"] == ["clave", "valor"]


def test_valores_tal_como_los_devuelve_la_hoja_real_con_configuracion_regional_es():
    """Capturado de la hoja real: la tasa llega como '3,5' (coma decimal) y todo como texto."""
    filas_config = [["tasa_mensual_pct", "3,5"], ["plazos_cuotas", "3,6,12,18"], ["costo_evaluacion_tecnica", "50"]]
    cfg = n.config_desde_filas([{"clave": k, "valor": v} for k, v in filas_config])
    assert n.tasa_mensual_desde_config(cfg) == D("3.5")
    assert n.plazos_desde_config(cfg) == [3, 6, 12, 18]
    p = n.Producto.desde_fila({"sku": "REF-001", "categoria": "Refrigeradora", "marca": "Indurama", "modelo": "RI-289",
                               "descripcion": "x", "capacidad": "280 L", "precio": "1499", "stock": "6", "garantia_meses": "24"})
    assert (p.precio, p.stock, p.garantia_meses) == (D("1499"), 6, 24)
    b = n.Boleta.desde_fila({"numero_boleta": "B001-0009", "fecha_compra": "2025-11-23", "sku": "COC-001",
                             "cliente": "x", "telefono": "51999000009"})
    assert b.fecha_compra == date(2025, 11, 23)
