"""Endpoints del webhook con TestClient (las tareas en segundo plano corren antes de volver)."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as M  # noqa: E402
import whatsapp as wa  # noqa: E402
from config import Settings  # noqa: E402

SECRETO = "app-secret"


class BotFalso:
    def __init__(self):
        self.textos, self.no_textos = [], []
    def procesar(self, tel, txt):
        self.textos.append((tel, txt))
        return f"eco: {txt}"
    def procesar_no_texto(self, tel, tipo):
        self.no_textos.append((tel, tipo))
        return "solo texto"


class WaFalso:
    def __init__(self, falla=False):
        self.enviados, self.falla = [], falla
    def enviar_texto(self, tel, txt):
        if self.falla:
            raise wa.ErrorWhatsApp("HTTP 500")
        self.enviados.append((tel, txt))


def montar(secreto=SECRETO, wa_falso=None):
    bot, w = BotFalso(), wa_falso or WaFalso()
    s = Settings("", "", "", "tok-verif", "", "", whatsapp_app_secret=secreto)
    return TestClient(M.crear_app(M.Servicios(bot, w, s))), bot, w


def cuerpo(*msgs):
    valor = {"messaging_product": "whatsapp", "messages": list(msgs)}
    return json.dumps({"entry": [{"changes": [{"field": "messages", "value": valor}]}]}).encode()


def msg(id_="wamid.1", de="51999000009", txt="hola"):
    return {"from": de, "id": id_, "type": "text", "text": {"body": txt}}


def post(client, body, secreto=SECRETO, firma=True):
    h = {"Content-Type": "application/json"}
    if firma:
        h["X-Hub-Signature-256"] = wa.firmar(body, secreto)
    return client.post("/webhook", content=body, headers=h)


def test_health():
    c, *_ = montar()
    assert c.get("/health").json() == {"status": "ok"}


def test_verificacion_get_devuelve_el_challenge():
    c, *_ = montar()
    r = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "tok-verif", "hub.challenge": "98765"})
    assert r.status_code == 200 and r.text == "98765"


@pytest.mark.parametrize("params", [
    {"hub.mode": "subscribe", "hub.verify_token": "mal", "hub.challenge": "1"},
    {"hub.mode": "subscribe", "hub.challenge": "1"},
    {},
])
def test_verificacion_get_rechaza_token_incorrecto(params):
    c, *_ = montar()
    assert c.get("/webhook", params=params).status_code == 403


def test_mensaje_de_texto_se_procesa_y_se_responde_al_mismo_numero():
    c, bot, w = montar()
    r = post(c, cuerpo(msg(txt="tienen lavadoras?")))
    assert r.status_code == 200
    assert bot.textos == [("51999000009", "tienen lavadoras?")]
    assert w.enviados == [("51999000009", "eco: tienen lavadoras?")]


def test_firma_invalida_o_ausente_se_rechaza_sin_procesar():
    c, bot, w = montar()
    assert post(c, cuerpo(msg()), secreto="otro").status_code == 403
    assert post(c, cuerpo(msg()), firma=False).status_code == 403
    assert bot.textos == [] and w.enviados == []


def test_sin_secreto_configurado_no_se_exige_firma():
    c, bot, _ = montar(secreto="")
    assert post(c, cuerpo(msg()), firma=False).status_code == 200 and len(bot.textos) == 1


def test_mensaje_duplicado_de_meta_se_procesa_una_sola_vez():
    c, bot, w = montar()
    b = cuerpo(msg("wamid.7"))
    post(c, b); post(c, b)
    assert len(bot.textos) == 1 and len(w.enviados) == 1


def test_mensajes_distintos_en_un_mismo_webhook():
    c, bot, _ = montar()
    post(c, cuerpo(msg("a", "519", "uno"), msg("b", "518", "dos")))
    assert bot.textos == [("519", "uno"), ("518", "dos")]


def test_mensaje_no_texto_va_por_la_ruta_de_derivacion():
    c, bot, w = montar()
    post(c, cuerpo({"from": "519", "id": "w9", "type": "audio", "audio": {"id": "z"}}))
    assert bot.no_textos == [("519", "audio")] and w.enviados == [("519", "solo texto")] and bot.textos == []


def test_estados_de_entrega_se_ignoran():
    c, bot, w = montar()
    body = json.dumps({"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "delivered"}]}}]}]}).encode()
    assert post(c, body).status_code == 200 and bot.textos == [] and w.enviados == []


def test_json_invalido_es_400():
    c, *_ = montar()
    assert post(c, b"no es json").status_code == 400


def test_fallo_al_enviar_no_rompe_el_webhook():
    c, bot, w = montar(wa_falso=WaFalso(falla=True))
    assert post(c, cuerpo(msg())).status_code == 200


def test_sin_configuracion_el_servicio_responde_503_pero_health_vive(monkeypatch):
    for k in ("GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS_JSON", "GEMINI_API_KEY", "WEBHOOK_VERIFY_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    c = TestClient(M.crear_app())
    assert c.get("/health").status_code == 200
    assert c.post("/webhook", content=b"{}").status_code == 503
    assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"}).status_code == 403


def test_solo_atiende_los_numeros_permitidos():
    bot, w = BotFalso(), WaFalso()
    s = Settings("", "", "", "t", "", "", whatsapp_app_secret=SECRETO, numeros_permitidos=("+51 999 111 222",))
    c = TestClient(M.crear_app(M.Servicios(bot, w, s)))
    post(c, cuerpo(msg("a", "51999111222", "soy yo"), msg("b", "51988777666", "soy un extraño")))
    assert bot.textos == [("51999111222", "soy yo")]
    assert w.enviados == [("51999111222", "eco: soy yo")]       # al extraño ni se le responde


def test_lista_vacia_atiende_a_todos():
    c, bot, _ = montar()
    post(c, cuerpo(msg("a", "51988777666", "hola")))
    assert len(bot.textos) == 1


def test_numeros_permitidos_se_leen_del_entorno(monkeypatch):
    import config
    monkeypatch.setenv("NUMEROS_PERMITIDOS", " 51999111222 , 51988000000 ,")
    assert config.cargar_settings().numeros_permitidos == ("51999111222", "51988000000")
