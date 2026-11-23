"""Pruebas OFFLINE de la capa de IA: Gemini se simula con httpx.MockTransport."""
import json
import os
import sys
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import evaluar_ia as ev  # noqa: E402
import ia  # noqa: E402
import prompts as P  # noqa: E402


def respuesta_gemini(texto: str) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": texto}]}, "finishReason": "STOP"}]}


def cliente_con(respuestas, capturas=None, **kw):
    """`respuestas`: lista de (status, dict) que se entregan en orden (la última se repite)."""
    cola = list(respuestas)

    def handler(request: httpx.Request) -> httpx.Response:
        if capturas is not None:
            capturas.append(request)
        status, cuerpo = cola.pop(0) if len(cola) > 1 else cola[0]
        return httpx.Response(status, json=cuerpo)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ia.GeminiClient("CLAVE-SECRETA", http_client=http, pausa=lambda s: None, **kw)


def devuelve(obj) -> "ia.GeminiClient":
    texto = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return cliente_con([(200, respuesta_gemini(texto))])


# ------------------------------ cliente HTTP -------------------------------
def test_request_usa_endpoint_cabecera_y_parametros_del_prompt():
    caps = []
    c = cliente_con([(200, respuesta_gemini('{"intencion":"CATALOGO","confianza":0.95}'))], caps)
    ia.clasificar_intencion(c, "tienen lavadoras?")
    req = caps[0]
    assert str(req.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent"
    assert req.headers["X-goog-api-key"] == "CLAVE-SECRETA"
    assert "CLAVE-SECRETA" not in str(req.url)  # la clave solo viaja en la cabecera
    cuerpo = json.loads(req.content)
    assert cuerpo["generationConfig"]["temperature"] == 0
    assert cuerpo["generationConfig"]["responseMimeType"] == "application/json"
    assert cuerpo["generationConfig"]["responseSchema"]["properties"]["intencion"]["enum"] == list(P.INTENCIONES)
    assert cuerpo["systemInstruction"]["parts"][0]["text"] == P.BP01.sistema
    turnos = cuerpo["contents"]
    assert len(turnos) == 2 * len(P.BP01.ejemplos) + 1               # few-shot + mensaje real
    assert turnos[-1] == {"role": "user", "parts": [{"text": "tienen lavadoras?"}]}
    assert [t["role"] for t in turnos[:4]] == ["user", "model", "user", "model"]


def test_redaccion_usa_temperatura_04_y_sin_esquema():
    caps = []
    c = cliente_con([(200, respuesta_gemini("hola"))], caps)
    c.generar(P.BP03, "{}")
    cfg = json.loads(caps[0].content)["generationConfig"]
    assert cfg["temperature"] == 0.4 and "responseSchema" not in cfg and "responseMimeType" not in cfg


def test_reintenta_una_vez_ante_429_y_luego_funciona():
    caps = []
    c = cliente_con([(429, {}), (200, respuesta_gemini('{"intencion":"HORARIOS","confianza":0.9}'))], caps)
    assert ia.clasificar_intencion(c, "a qué hora abren").intencion == "HORARIOS"
    assert len(caps) == 2


def test_no_reintenta_ante_400():
    caps = []
    c = cliente_con([(400, {"error": "x"})], caps)
    with pytest.raises(ia.ErrorIA, match="HTTP 400"):
        c.generar(P.BP01, "hola")
    assert len(caps) == 1


def test_error_de_red_no_filtra_la_clave():
    def handler(request):
        raise httpx.ConnectError("sin red")
    c = ia.GeminiClient("CLAVE-SECRETA", http_client=httpx.Client(transport=httpx.MockTransport(handler)), pausa=lambda s: None)
    with pytest.raises(ia.ErrorIA) as e:
        c.generar(P.BP01, "hola")
    assert "CLAVE-SECRETA" not in str(e.value)


def test_sin_clave_no_se_puede_crear_cliente():
    with pytest.raises(ValueError):
        ia.GeminiClient("")


# ------------------------------ BP-01 clasificación -------------------------
@pytest.mark.parametrize("intencion", ["CATALOGO", "CUOTAS", "GARANTIA", "HORARIOS", "DERIVAR"])
def test_clasifica_con_confianza_suficiente(intencion):
    r = ia.clasificar_intencion(devuelve({"intencion": intencion, "confianza": 0.9}), "x")
    assert r.intencion == intencion and r.motivo_derivacion is None


def test_confianza_menor_a_07_se_trata_como_derivar():
    r = ia.clasificar_intencion(devuelve({"intencion": "CATALOGO", "confianza": 0.69}), "algo")
    assert (r.intencion, r.intencion_modelo, r.motivo_derivacion) == ("DERIVAR", "CATALOGO", "baja_confianza")


def test_confianza_exactamente_07_se_acepta():
    assert ia.clasificar_intencion(devuelve({"intencion": "CUOTAS", "confianza": 0.7}), "x").intencion == "CUOTAS"


@pytest.mark.parametrize("malo", [
    "no es json", "[1,2]", {"intencion": "COMPRAR", "confianza": 0.9}, {"intencion": "CATALOGO"},
    {"intencion": "CATALOGO", "confianza": "alta"}, {"intencion": "CATALOGO", "confianza": 1.7},
    {"intencion": None, "confianza": 0.9},
])
def test_respuesta_invalida_deriva(malo):
    r = ia.clasificar_intencion(devuelve(malo), "x")
    assert r.intencion == "DERIVAR" and r.motivo_derivacion in {"respuesta_invalida", "error_ia: JSON inválido", "error_ia: se esperaba un objeto JSON"}


def test_caida_del_modelo_deriva_en_vez_de_romper():
    r = ia.clasificar_intencion(cliente_con([(503, {})]), "hola")
    assert r.intencion == "DERIVAR" and r.motivo_derivacion.startswith("error_ia")


def test_mensaje_vacio_no_llama_al_modelo():
    caps = []
    r = ia.clasificar_intencion(cliente_con([(200, respuesta_gemini("{}"))], caps), "   ")
    assert r.intencion == "DERIVAR" and caps == []


def test_json_con_cercas_markdown_se_tolera():
    r = ia.clasificar_intencion(devuelve('```json\n{"intencion":"CUOTAS","confianza":0.9}\n```'), "x")
    assert r.intencion == "CUOTAS"


def test_mensaje_largo_se_trunca():
    caps = []
    ia.clasificar_intencion(cliente_con([(200, respuesta_gemini('{"intencion":"DERIVAR","confianza":0.9}'))], caps), "a" * 5000)
    enviado = json.loads(caps[0].content)["contents"][-1]["parts"][0]["text"]
    assert len(enviado) == ia.MAX_CHARS_MENSAJE


def test_respuesta_bloqueada_o_vacia_deriva():
    bloqueada = {"promptFeedback": {"blockReason": "SAFETY"}}
    assert ia.clasificar_intencion(cliente_con([(200, bloqueada)]), "x").intencion == "DERIVAR"


# ------------------------------ BP-02 criterios -----------------------------
def crit(salida, mensaje):
    return ia.extraer_criterios(devuelve(salida), mensaje)


def test_criterios_completos():
    c = crit({"categoria": "Lavadora", "marca": None, "capacidad": "19 kg", "precio_max": 1800},
             "busco una lavadora de 19 kilos que no pase de 1800 soles")
    assert (c.categoria, c.marca, c.capacidad, c.precio_max) == ("Lavadora", None, "19 kg", D("1800"))


def test_marca_inventada_se_descarta():
    c = crit({"categoria": "Televisor", "marca": "Sony", "capacidad": None, "precio_max": None}, "quiero un televisor")
    assert c.marca is None and c.categoria == "Televisor"


def test_marca_con_distinta_capitalizacion_se_respalda():
    assert crit({"categoria": "Televisor", "marca": "LG", "capacidad": None, "precio_max": None}, "una tele lg").marca == "LG"


def test_capacidad_inventada_se_descarta():
    c = crit({"categoria": "Refrigeradora", "marca": None, "capacidad": "350 L", "precio_max": None}, "busco una refri")
    assert c.capacidad is None


def test_precio_inventado_se_descarta_pero_mil_se_acepta():
    assert crit({"categoria": "Televisor", "marca": None, "capacidad": None, "precio_max": 1500}, "quiero una tele").precio_max is None
    assert crit({"categoria": "Televisor", "marca": None, "capacidad": None, "precio_max": 1500},
                "una tele de máximo mil quinientos").precio_max == D("1500")
    assert crit({"categoria": "Televisor", "marca": None, "capacidad": None, "precio_max": 1500},
                "tele hasta 1,500 soles").precio_max == D("1500")


@pytest.mark.parametrize("p", [0, -5, "gratis", "abc"])
def test_precio_invalido_se_descarta(p):
    assert crit({"categoria": "Televisor", "marca": None, "capacidad": None, "precio_max": p}, "tele de 0 soles gratis -5").precio_max is None


def test_falla_del_modelo_devuelve_criterios_vacios_para_pedir_aclaracion():
    assert ia.extraer_criterios(cliente_con([(500, {})]), "tele").vacio
    assert crit("basura", "tele").vacio


def test_categoria_inexistente_se_conserva_para_decir_que_no_se_maneja():
    c = crit({"categoria": "Cafetera", "marca": "Oster", "capacidad": None, "precio_max": None}, "¿Tienen cafeteras Oster?")
    assert (c.categoria, c.marca) == ("Cafetera", "Oster")


# ------------------------------ BP-05 garantía ------------------------------
def gar(salida, mensaje):
    return ia.extraer_garantia(devuelve(salida), mensaje)


def test_garantia_completa():
    d = gar({"numero_boleta": "B001-0010", "sku": "TV-001", "problema": "ya no prende"},
            "La tv ya no prende, boleta B001-0010, sku TV-001")
    assert (d.numero_boleta, d.sku, d.problema) == ("B001-0010", "TV-001", "ya no prende")


def test_boleta_inventada_se_descarta():
    assert gar({"numero_boleta": "B001-0001", "sku": None, "problema": "falla"}, "mi lavadora falla").numero_boleta is None


def test_boleta_escrita_con_espacios_se_respalda():
    assert gar({"numero_boleta": "B001-0010", "sku": None, "problema": None}, "mi boleta es b001 0010").numero_boleta == "B001-0010"


def test_sku_inventado_se_descarta():
    assert gar({"numero_boleta": None, "sku": "REF-001", "problema": "x"}, "mi refri falla").sku is None


def test_garantia_ante_falla_devuelve_vacio():
    assert ia.extraer_garantia(cliente_con([(500, {})]), "boleta B001-0001") == ia.DatosGarantia()


# ------------------------------ Redacción con guardas -----------------------
ENTRADA = json.dumps({"estado": "DISPONIBLES", "productos": [{"nombre": "LG GT-29", "precio": "S/ 1,799.00"}]}, ensure_ascii=False)
RESPALDO = "PLANTILLA"


@pytest.mark.parametrize("salida,valida", [
    ("*LG GT-29* a S/ 1,799.00", True),
    ("Tenemos la LG GT-29 por S/ 1799.00", True),                  # mismo monto, otro formato
    ("Tenemos la LG GT-29 por S/ 999.00", False),                  # precio inventado
    ("Cuesta S/ 1,799.00, o S/ 150.00 al mes", False),             # cuota inventada
    ("# Opciones\nLG GT-29", False),                                # encabezado markdown
    ("**LG GT-29** S/ 1,799.00", False),                           # negrita doble
    ("a\nb\nc\nd\ne", False),                                       # más de 4 líneas
    ("", False),
    ("Llega el 2026-12-01", False),                                 # fecha inventada
])
def test_guarda_de_redaccion(salida, valida):
    assert ia.redaccion_valida(salida, ENTRADA) is valida


def test_redactar_acepta_salida_valida():
    c = devuelve("Tengo la *LG GT-29* en S/ 1,799.00")
    assert ia.redactar(c, P.BP03, json.loads(ENTRADA), RESPALDO) == "Tengo la *LG GT-29* en S/ 1,799.00"


def test_redactar_usa_plantilla_si_el_modelo_inventa_un_precio():
    assert ia.redactar(devuelve("Te la dejo en S/ 1,000.00"), P.BP03, json.loads(ENTRADA), RESPALDO) == RESPALDO


def test_redactar_usa_plantilla_si_el_modelo_cae():
    assert ia.redactar(cliente_con([(500, {})]), P.BP03, json.loads(ENTRADA), RESPALDO) == RESPALDO


# ------------------------------ banco de prompts ----------------------------
def test_banco_completo_y_documentado():
    assert list(P.BANCO) == [f"BP-0{i}" for i in range(1, 8)]
    for p in P.BANCO.values():
        assert p.entrada_prueba.strip() and p.salida_esperada.strip() and p.sistema.strip()


def test_temperaturas():
    assert all(P.BANCO[i].temperatura == 0 for i in ("BP-01", "BP-02", "BP-05"))
    assert all(P.BANCO[i].temperatura == 0.4 for i in ("BP-03", "BP-04", "BP-06", "BP-07"))


def test_ejemplos_few_shot_cumplen_su_esquema():
    for p in (P.BP01, P.BP02, P.BP05):
        assert len(p.ejemplos) >= 4
        for _, salida in p.ejemplos:
            assert set(json.loads(salida)) == set(p.esquema["required"])
    assert {json.loads(s)["intencion"] for _, s in P.BP01.ejemplos} == set(P.INTENCIONES)  # cubre las 5


def test_entradas_de_prueba_de_redaccion_son_json_valido():
    for i in ("BP-03", "BP-04", "BP-06", "BP-07"):
        json.loads(P.BANCO[i].entrada_prueba)


def test_los_prompts_de_redaccion_prohiben_inventar_y_fijan_formato():
    for i in ("BP-03", "BP-04", "BP-06", "BP-07"):
        s = P.BANCO[i].sistema
        assert "4 líneas" in s and "No inventes" in s


# ------------------------------ set de 20 mensajes --------------------------
def test_set_de_prueba_tiene_20_mensajes_validos():
    msgs = ev.cargar_mensajes()
    assert len(msgs) == 20 and [m["id"] for m in msgs] == list(range(1, 21))
    assert {m["intencion"] for m in msgs} == set(P.INTENCIONES)
    assert all(m["intencion"] in P.INTENCIONES for m in msgs)


def test_set_de_prueba_no_se_filtra_a_los_few_shot():
    vistos = {e[0].strip().lower() for p in (P.BP01, P.BP02, P.BP05) for e in p.ejemplos}
    assert not any(m["mensaje"].strip().lower() in vistos for m in ev.cargar_mensajes())


def test_arnes_aprueba_con_un_modelo_perfecto_simulado():
    """Valida el ARNÉS (no el modelo real): un oráculo que responde lo esperado debe dar 100 %."""
    msgs = {m["mensaje"]: m for m in ev.cargar_mensajes()}

    def handler(request):
        cuerpo = json.loads(request.content)
        texto = cuerpo["contents"][-1]["parts"][0]["text"]
        m = msgs[texto]
        sistema = cuerpo["systemInstruction"]["parts"][0]["text"]
        if sistema == P.BP01.sistema:
            out = {"intencion": m["intencion"], "confianza": 0.95}
        elif sistema == P.BP02.sistema:
            out = m.get("criterios", {"categoria": None, "marca": None, "capacidad": None, "precio_max": None})
        else:
            g = m.get("garantia", {"numero_boleta": None, "sku": None, "problema": False})
            out = {**g, "problema": "falla" if g["problema"] else None}
        return httpx.Response(200, json=respuesta_gemini(json.dumps(out)))

    c = ia.GeminiClient("k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = ev.evaluar(c, ev.cargar_mensajes())
    assert r.aprobado and r.total_intencion == 20 and r.total_extraccion == 9, r.fallos


def test_arnes_detecta_un_modelo_malo():
    c = devuelve({"intencion": "DERIVAR", "confianza": 0.95})
    assert not ev.evaluar(c, ev.cargar_mensajes()).aprobado


# ------------------------------ prueba REAL (opcional) ----------------------
@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="requiere GEMINI_API_KEY")
def test_set_de_20_mensajes_contra_gemini_real():
    r = ev.evaluar(ia.GeminiClient(os.environ["GEMINI_API_KEY"]), ev.cargar_mensajes(), pausa=1.0)
    assert r.aprobado, "\n".join(r.fallos)
