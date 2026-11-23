"""Flujo completo con hoja simulada y Gemini guionado (sin red)."""
import json
import sys
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ia  # noqa: E402
import negocio as n  # noqa: E402
import sheets as S  # noqa: E402
from flujo import Bot  # noqa: E402

AHORA = datetime(2026, 11, 23, 12, 0, 0, tzinfo=S.LIMA)
NULOS_C = {"categoria": None, "marca": None, "capacidad": None, "precio_max": None}
NULOS_G = {"numero_boleta": None, "sku": None, "problema": None}


class GuionIA:
    """Sustituye a GeminiClient: responde según el mensaje, sin red."""

    def __init__(self, clasif=None, criterios=None, garantia=None, redaccion=None, cae=False):
        self.clasif, self.criterios, self.garantia = clasif or {}, criterios or {}, garantia or {}
        self.redaccion, self.cae, self.llamadas = redaccion, cae, []

    def generar(self, prompt, entrada):
        self.llamadas.append(prompt.id)
        if self.cae:
            raise ia.ErrorIA("caído")
        if prompt.id == "BP-01":
            i, c = self.clasif[entrada]
            return json.dumps({"intencion": i, "confianza": c})
        if prompt.id == "BP-02":
            return json.dumps({**NULOS_C, **self.criterios.get(entrada, {})})
        if prompt.id == "BP-05":
            return json.dumps({**NULOS_G, **self.garantia.get(entrada, {})})
        if self.redaccion:
            return self.redaccion(prompt, entrada)
        raise ia.ErrorIA("sin redacción guionada")  # fuerza la plantilla determinista


def montar(**kw):
    hoja = S.HojaSimulada.desde_csv_demo()
    repo = S.Repositorio(hoja, ahora=lambda: AHORA)
    reloj = [0.0]
    guion = GuionIA(**kw)
    return Bot(repo, guion, reloj=lambda: reloj[0]), hoja, guion, reloj


def ultima_conv(hoja):
    return hoja.leer("Conversaciones")[-1]


# ------------------------------ CATALOGO -----------------------------------
def test_catalogo_disponible_con_precios_de_la_hoja():
    bot, hoja, _, _ = montar(clasif={"tienen refris LG?": ("CATALOGO", 0.95)},
                             criterios={"tienen refris LG?": {"categoria": "Refrigeradora", "marca": "LG"}})
    r = bot.procesar("51900", "tienen refris LG?")
    assert "LG GT-29" in r and "S/ 1,799.00" in r and "S/ 2,399.00" in r
    assert "GS-65" not in r                                    # stock 0, no se ofrece como disponible
    assert len(r.splitlines()) <= 4
    assert ultima_conv(hoja)["intencion"] == "CATALOGO"


def test_stock_cero_se_informa_no_disponible_con_alternativas_y_sin_prometer_reposicion():
    bot, *_ = montar(clasif={"lavadora mabe de 17 kilos": ("CATALOGO", 0.95)},
                     criterios={"lavadora mabe de 17 kilos": {"categoria": "Lavadora", "marca": "Mabe", "capacidad": "17 kg"}})
    r = bot.procesar("51900", "lavadora mabe de 17 kilos")
    assert "no está disponible" in r and "LMH-17" in r
    assert "S/ 799.00" in r  # alternativa de la misma categoría (LMA-70)
    assert "repon" not in r.lower() and "llegar" not in r.lower()


def test_producto_inexistente_no_se_inventa():
    bot, hoja, *_ = montar(clasif={"tienen cafeteras Oster?": ("CATALOGO", 0.9)},
                           criterios={"tienen cafeteras Oster?": {"categoria": "Cafetera", "marca": "Oster"}})
    r = bot.procesar("51900", "tienen cafeteras Oster?")
    assert "no lo manejamos" in r and "S/" not in r


def test_consulta_ambigua_pide_aclaracion_y_se_completa_en_el_turno_siguiente():
    bot, hoja, guion, _ = montar(clasif={"quiero algo": ("CATALOGO", 0.8)}, criterios={"una lavadora LG": {"categoria": "Lavadora", "marca": "LG"}})
    r1 = bot.procesar("51900", "quiero algo")
    assert "¿Qué producto buscas?" in r1 and "S/" not in r1
    r2 = bot.procesar("51900", "una lavadora LG")
    assert "LG WT-13" in r2 and "S/ 1,499.00" in r2
    assert guion.llamadas.count("BP-01") == 1                   # el 2.º turno no se reclasifica
    assert [c["intencion"] for c in hoja.leer("Conversaciones")] == ["CATALOGO", "CATALOGO"]


def test_redaccion_con_precio_inventado_cae_a_plantilla_con_precio_real():
    bot, *_ = montar(clasif={"tienen refris LG?": ("CATALOGO", 0.95)},
                     criterios={"tienen refris LG?": {"categoria": "Refrigeradora", "marca": "LG"}},
                     redaccion=lambda p, e: "Te la dejo en S/ 100.00, es una oferta")
    r = bot.procesar("51900", "tienen refris LG?")
    assert "S/ 100.00" not in r and "S/ 1,799.00" in r


def test_redaccion_valida_del_modelo_se_acepta():
    bot, *_ = montar(clasif={"tienen refris LG?": ("CATALOGO", 0.95)},
                     criterios={"tienen refris LG?": {"categoria": "Refrigeradora", "marca": "LG"}},
                     redaccion=lambda p, e: "Tengo la *LG GT-29* de 290 L a S/ 1,799.00")
    assert bot.procesar("51900", "tienen refris LG?") == "Tengo la *LG GT-29* de 290 L a S/ 1,799.00"


def test_el_modelo_nunca_recibe_el_stock():
    capturado = []
    def red(p, e):
        capturado.append(e)
        raise ia.ErrorIA("x")
    bot, *_ = montar(clasif={"tienen refris LG?": ("CATALOGO", 0.95)},
                     criterios={"tienen refris LG?": {"categoria": "Refrigeradora", "marca": "LG"}}, redaccion=red)
    bot.procesar("51900", "tienen refris LG?")
    assert capturado and '"stock"' not in capturado[0]


# ------------------------------ CUOTAS -------------------------------------
def test_cuotas_por_modelo_y_plazo_con_calculo_en_codigo():
    msg = "cuánto es la cuota de la LG WT-19 a 12 meses"
    bot, *_ = montar(clasif={msg: ("CUOTAS", 0.95)})
    r = bot.procesar("51900", msg)
    c = n.calcular_cuota(D("1899"), D("3.5"), 12)
    assert n.formatear_soles(c.monto_cuota) in r and n.formatear_soles(c.total_a_pagar) in r
    assert "S/ 1,899.00" in r and "18 x" not in r             # solo el plazo pedido


def test_cuotas_sin_plazo_muestra_todos_los_de_config():
    msg = "cuotas de la lavadora LG WT-19"
    bot, *_ = montar(clasif={msg: ("CUOTAS", 0.95)})
    r = bot.procesar("51900", msg)
    assert all(f"{k} x" in r for k in (3, 6, 12, 18)) and len(r.splitlines()) <= 4


def test_cuotas_con_varios_modelos_pide_elegir_y_luego_calcula():
    bot, hoja, *_ = montar(clasif={"cuotas de una lavadora LG": ("CUOTAS", 0.9)},
                           criterios={"cuotas de una lavadora LG": {"categoria": "Lavadora", "marca": "LG"}})
    r1 = bot.procesar("51900", "cuotas de una lavadora LG")
    assert "¿De cuál modelo" in r1 and "WT-13" in r1 and "S/" not in r1
    r2 = bot.procesar("51900", "la WT-13 a 6 cuotas")
    assert n.formatear_soles(n.calcular_cuota(D("1499"), D("3.5"), 6).monto_cuota) in r2
    assert hoja.leer("Conversaciones")[-1]["intencion"] == "CUOTAS"


def test_cuotas_de_producto_sin_stock_informa_disponibilidad_no_financia():
    msg = "cuotas de la lavadora Mabe LMH-17"
    bot, *_ = montar(clasif={msg: ("CUOTAS", 0.9)})
    r = bot.procesar("51900", msg)
    assert "no está disponible" in r and " x S/" not in r


# ------------------------------ GARANTIA -----------------------------------
def test_garantia_vigente_con_problema_crea_ticket():
    msg = "mi cocina no enciende, boleta B001-0009"
    bot, hoja, *_ = montar(clasif={msg: ("GARANTIA", 0.95)}, garantia={msg: {"numero_boleta": "B001-0009", "problema": "no enciende"}})
    r = bot.procesar("51999000009", msg)
    assert "T-0001" in r and "23/11/2026" in r
    t = hoja.leer("Tickets")[0]
    assert (t["telefono"], t["numero_boleta"], t["sku"], t["problema"], t["estado"]) == ("51999000009", "B001-0009", "COC-001", "no enciende", "ABIERTO")
    assert ultima_conv(hoja)["intencion"] == "GARANTIA"


def test_garantia_pide_boleta_luego_problema_luego_crea_ticket():
    bot, hoja, guion, _ = montar(
        clasif={"se malogró mi cocina": ("GARANTIA", 0.9)},
        garantia={"se malogró mi cocina": {"problema": "se malogró"}, "B001-0009": {"numero_boleta": "B001-0009"}})
    r1 = bot.procesar("51999000009", "se malogró mi cocina")
    assert "número de tu boleta" in r1
    r2 = bot.procesar("51999000009", "B001-0009")                 # el problema ya se había dicho
    assert "T-0001" in r2
    assert guion.llamadas.count("BP-01") == 1 and len(hoja.leer("Tickets")) == 1


def test_garantia_vigente_sin_problema_lo_pregunta():
    bot, hoja, *_ = montar(clasif={"garantía B001-0009": ("GARANTIA", 0.9)}, garantia={
        "garantía B001-0009": {"numero_boleta": "B001-0009"}, "no prende": {"problema": "no prende"}})
    r1 = bot.procesar("51999000009", "garantía B001-0009")
    assert "vigente hasta el 23/11/2026" in r1 and "¿Qué problema presenta?" in r1 and hoja.leer("Tickets") == []
    assert "T-0001" in bot.procesar("51999000009", "no prende")


def test_garantia_vencida_informa_costo_de_config_y_no_crea_ticket():
    msg = "mi tv falla, boleta B001-0008"
    bot, hoja, *_ = montar(clasif={msg: ("GARANTIA", 0.9)}, garantia={msg: {"numero_boleta": "B001-0008", "problema": "falla"}})
    r = bot.procesar("51999000008", msg)
    assert "venció el 20/11/2026" in r and "S/ 50.00" in r and hoja.leer("Tickets") == []


def test_garantia_boleta_ajena_no_filtra_nada_ni_crea_ticket():
    msg = "mi tv falla, boleta B001-0008"
    bot, hoja, *_ = montar(clasif={msg: ("GARANTIA", 0.9)}, garantia={msg: {"numero_boleta": "B001-0008", "problema": "falla"}})
    r = bot.procesar("51911111111", msg)                           # otro teléfono
    assert "No encontré esa boleta" in r
    assert "Samsung" not in r and "CU-55" not in r and "20/11/2026" not in r
    assert hoja.leer("Tickets") == []


def test_garantia_boleta_inexistente():
    msg = "garantía boleta B999-0001"
    bot, *_ = montar(clasif={msg: ("GARANTIA", 0.9)}, garantia={msg: {"numero_boleta": "B999-0001"}})
    assert "No encontré esa boleta" in bot.procesar("51900", msg)


def test_garantia_sku_que_no_corresponde():
    msg = "boleta B001-0009 sku TV-001 no prende"
    bot, hoja, *_ = montar(clasif={msg: ("GARANTIA", 0.9)}, garantia={msg: {"numero_boleta": "B001-0009", "sku": "TV-001", "problema": "no prende"}})
    assert "no corresponde" in bot.procesar("51999000009", msg) and hoja.leer("Tickets") == []


# ------------------------------ HORARIOS / DERIVAR --------------------------
def test_horarios_con_datos_fijos_de_config():
    bot, hoja, *_ = montar(clasif={"a qué hora abren": ("HORARIOS", 0.97)})
    r = bot.procesar("51900", "a qué hora abren")
    assert "Lun-Sab 9:00-19:00" in r and "Av. Ficticia 123" in r
    assert ultima_conv(hoja)["intencion"] == "HORARIOS"


def test_derivacion_queda_registrada_con_motivo_y_mensaje():
    bot, hoja, *_ = montar(clasif={"quiero cerrar la compra": ("DERIVAR", 0.92)})
    r = bot.procesar("51900", "quiero cerrar la compra")
    assert "asesor" in r and "Lun-Sab 9:00-19:00" in r
    d = hoja.leer("Derivaciones")[0]
    assert (d["telefono"], d["mensaje_original"], d["motivo"], d["atendido"]) == ("51900", "quiero cerrar la compra", "fuera_de_alcance", "NO")
    assert ultima_conv(hoja)["intencion"] == "DERIVAR"


def test_baja_confianza_se_deriva_y_se_registra_el_motivo():
    bot, hoja, *_ = montar(clasif={"necesito algo": ("CATALOGO", 0.5)})
    bot.procesar("51900", "necesito algo")
    assert hoja.leer("Derivaciones")[0]["motivo"] == "baja_confianza"
    assert ultima_conv(hoja)["intencion"] == "DERIVAR"


def test_ia_caida_deriva_en_vez_de_dejar_sin_respuesta():
    bot, hoja, *_ = montar(cae=True)
    r = bot.procesar("51900", "hola")
    assert "asesor" in r and hoja.leer("Derivaciones")[0]["motivo"].startswith("error_ia")


def test_mensaje_no_texto_se_deriva():
    bot, hoja, *_ = montar()
    r = bot.procesar_no_texto("51900", "audio")
    assert "solo puedo leer mensajes de texto" in r and hoja.leer("Derivaciones")[0]["motivo"] == "mensaje_no_texto"


def test_mensaje_vacio_se_deriva_sin_llamar_a_la_ia():
    bot, hoja, guion, _ = montar()
    bot.procesar("51900", "   ")
    assert guion.llamadas == [] or set(guion.llamadas) <= {"BP-07"}
    assert hoja.leer("Derivaciones")[0]["motivo"] == "mensaje_vacio"


# ------------------------------ robustez -----------------------------------
def test_si_la_hoja_no_deja_registrar_igual_se_responde():
    bot, hoja, *_ = montar(clasif={"a qué hora abren": ("HORARIOS", 0.97)})
    def falla(*a, **k): raise S.ErrorHoja("cuota excedida")
    hoja.agregar = falla
    assert "Lun-Sab" in bot.procesar("51900", "a qué hora abren")


def test_error_inesperado_responde_con_derivacion():
    bot, hoja, *_ = montar(clasif={"a qué hora abren": ("HORARIOS", 0.97)})
    bot.repo.config = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    r = bot.procesar("51900", "a qué hora abren")
    assert "asesor" in r


def test_pendiente_vence_y_se_trata_como_mensaje_nuevo():
    bot, hoja, guion, reloj = montar(clasif={"quiero algo": ("CATALOGO", 0.8), "una lavadora LG": ("CATALOGO", 0.9)},
                                     criterios={"una lavadora LG": {"categoria": "Lavadora", "marca": "LG"}})
    bot.procesar("51900", "quiero algo")
    reloj[0] = 16 * 60
    bot.procesar("51900", "una lavadora LG")
    assert guion.llamadas.count("BP-01") == 2


def test_cliente_cambia_de_tema_con_pendiente_se_reclasifica():
    bot, hoja, guion, _ = montar(clasif={"se malogró mi cocina": ("GARANTIA", 0.9), "a qué hora abren": ("HORARIOS", 0.97)},
                                 garantia={"se malogró mi cocina": {"problema": "se malogró"}})
    bot.procesar("51900", "se malogró mi cocina")                 # pide boleta
    r = bot.procesar("51900", "a qué hora abren")                 # no aporta datos de garantía
    assert "Lun-Sab" in r and ultima_conv(hoja)["intencion"] == "HORARIOS"


def test_tras_tres_intentos_sin_dato_se_deriva():
    bot, hoja, *_ = montar(clasif={"mi cocina falla": ("GARANTIA", 0.9)}, garantia={"mi cocina falla": {"problema": "falla"}, "eh": {"problema": "eh"}})
    bot.procesar("51900", "mi cocina falla")
    bot.procesar("51900", "eh")
    bot.procesar("51900", "eh")
    r = bot.procesar("51900", "eh")
    assert "asesor" in r and "datos_incompletos" in hoja.leer("Derivaciones")[-1]["motivo"]


def test_estado_de_cada_cliente_es_independiente():
    bot, hoja, *_ = montar(clasif={"se malogró mi cocina": ("GARANTIA", 0.9), "una lavadora LG": ("CATALOGO", 0.9)},
                           garantia={"se malogró mi cocina": {"problema": "x"}}, criterios={"una lavadora LG": {"categoria": "Lavadora", "marca": "LG"}})
    bot.procesar("51900", "se malogró mi cocina")
    r = bot.procesar("51911", "una lavadora LG")
    assert "LG WT-13" in r
    assert len(bot._pendientes) == 1 and "51900" in bot._pendientes


def test_toda_conversacion_queda_registrada_con_intencion():
    bot, hoja, *_ = montar(clasif={"a qué hora abren": ("HORARIOS", 0.97), "hola": ("DERIVAR", 0.8)})
    bot.procesar("51900", "a qué hora abren")
    bot.procesar("51900", "hola")
    conv = hoja.leer("Conversaciones")
    assert [c["intencion"] for c in conv] == ["HORARIOS", "DERIVAR"] and all(c["respuesta"] for c in conv)
