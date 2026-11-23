import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import simulador  # noqa: E402
from test_flujo import GuionIA, montar  # noqa: E402


def correr(lineas, **guion):
    bot, hoja, _, _ = montar(**guion)
    salida = []
    simulador.ejecutar(bot, hoja, "51900", lineas, salida.append)
    return "\n".join(salida), hoja


def test_muestra_respuesta_con_la_intencion():
    out, _ = correr(["a qué hora abren"], clasif={"a qué hora abren": ("HORARIOS", 0.97)})
    assert "bot [HORARIOS]>" in out and "Lun-Sab 9:00-19:00" in out


def test_registros_muestra_conversacion_derivacion_y_ticket():
    msg = "mi cocina no enciende, boleta B001-0009"
    out, hoja = correr(
        ["/telefono 51999000009", msg, "quiero cerrar la compra", "/registros"],
        clasif={msg: ("GARANTIA", 0.95), "quiero cerrar la compra": ("DERIVAR", 0.9)},
        garantia={msg: {"numero_boleta": "B001-0009", "problema": "no enciende"}})
    assert "-- Conversaciones (2)" in out and "-- Derivaciones (1)" in out and "-- Tickets (1)" in out
    assert "T-0001" in out and "fuera_de_alcance" in out


def test_cambiar_de_telefono_afecta_la_garantia():
    msg = "mi tv falla, boleta B001-0008"
    g = dict(clasif={msg: ("GARANTIA", 0.9)}, garantia={msg: {"numero_boleta": "B001-0008", "problema": "falla"}})
    ajeno, _ = correr([msg], **g)
    titular, _ = correr(["/telefono 51999000008", msg], **g)
    assert "No encontré esa boleta" in ajeno and "venció el 20/11/2026" in titular


def test_salir_termina_el_bucle():
    out, hoja = correr(["/salir", "a qué hora abren"], clasif={"a qué hora abren": ("HORARIOS", 0.9)})
    assert out == "" and hoja.leer("Conversaciones") == []
