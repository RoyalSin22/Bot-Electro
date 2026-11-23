import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import whatsapp as wa  # noqa: E402


def payload(*mensajes, estados=None):
    valor = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "123"}, "messages": list(mensajes)}
    if estados:
        valor["statuses"] = estados
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": valor}]}]}


def texto(id_, de, cuerpo):
    return {"from": de, "id": id_, "timestamp": "1", "type": "text", "text": {"body": cuerpo}}


def test_parsea_mensaje_de_texto():
    ms = wa.parsear_webhook(payload(texto("wamid.1", "51999000009", "hola")))
    assert ms == [wa.MensajeEntrante("51999000009", "wamid.1", "text", "hola")]


def test_parsea_varios_y_tipos_no_texto():
    audio = {"from": "519", "id": "wamid.2", "type": "audio", "audio": {"id": "x"}}
    ms = wa.parsear_webhook(payload(texto("wamid.1", "519", "a"), audio))
    assert [(m.tipo, m.texto) for m in ms] == [("text", "a"), ("audio", None)]


def test_ignora_estados_de_entrega():
    assert wa.parsear_webhook({"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}) == []


@pytest.mark.parametrize("basura", [None, [], "x", {}, {"entry": None}, {"entry": [None]}, {"entry": [{"changes": [{"value": None}]}]},
                                    {"entry": [{"changes": [{"value": {"messages": [{"id": "1"}]}}]}]}])
def test_estructuras_inesperadas_no_rompen(basura):
    assert wa.parsear_webhook(basura) == []


def test_firma_valida_e_invalida():
    cuerpo = b'{"a":1}'
    firma = wa.firmar(cuerpo, "secreto")
    assert wa.verificar_firma(cuerpo, firma, "secreto")
    assert not wa.verificar_firma(cuerpo + b" ", firma, "secreto")        # cuerpo alterado
    assert not wa.verificar_firma(cuerpo, firma, "otro")
    assert not wa.verificar_firma(cuerpo, None, "secreto")
    assert not wa.verificar_firma(cuerpo, "sha256=", "secreto")
    assert not wa.verificar_firma(cuerpo, "md5=abc", "secreto")
    assert not wa.verificar_firma(cuerpo, firma, "")                       # sin secreto no se "valida" nada


def test_verificacion_de_suscripcion():
    assert wa.verificar_suscripcion("subscribe", "tok", "12345", "tok") == "12345"
    assert wa.verificar_suscripcion("subscribe", "mal", "12345", "tok") is None
    assert wa.verificar_suscripcion("unsubscribe", "tok", "1", "tok") is None
    assert wa.verificar_suscripcion("subscribe", "", "1", "") is None      # token vacío nunca verifica
    assert wa.verificar_suscripcion("subscribe", "tok", None, "tok") is None


def cliente(handler, **kw):
    return wa.ClienteWhatsApp("TOKEN-SECRETO", "555", http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def test_envia_texto_con_formato_de_cloud_api():
    vistos = []
    def h(req):
        vistos.append(req)
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})
    cliente(h).enviar_texto("51999000009", "Hola *mundo*")
    r = vistos[0]
    assert str(r.url) == "https://graph.facebook.com/v23.0/555/messages"
    assert r.headers["Authorization"] == "Bearer TOKEN-SECRETO"
    assert json.loads(r.content) == {"messaging_product": "whatsapp", "to": "51999000009", "type": "text",
                                     "text": {"body": "Hola *mundo*", "preview_url": False}}


def test_version_configurable_y_texto_largo_se_recorta():
    vistos = []
    cliente(lambda r: vistos.append(r) or httpx.Response(200, json={}), version="v26.0").enviar_texto("1", "x" * 9000)
    assert "/v26.0/" in str(vistos[0].url) and len(json.loads(vistos[0].content)["text"]["body"]) == wa.MAX_TEXTO


def test_error_de_meta_no_filtra_el_token():
    c = cliente(lambda r: httpx.Response(401, json={"error": {"message": "Invalid OAuth access token"}}))
    with pytest.raises(wa.ErrorWhatsApp) as e:
        c.enviar_texto("1", "x")
    assert "401" in str(e.value) and "TOKEN-SECRETO" not in str(e.value)


def test_error_de_red_no_filtra_el_token():
    def h(r): raise httpx.ConnectError("sin red")
    with pytest.raises(wa.ErrorWhatsApp) as e:
        cliente(h).enviar_texto("1", "x")
    assert "TOKEN-SECRETO" not in str(e.value)


def test_cliente_requiere_credenciales():
    with pytest.raises(ValueError):
        wa.ClienteWhatsApp("", "555")
