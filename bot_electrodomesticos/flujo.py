"""Orquestador del bot: mensaje -> intención -> código determinista -> redacción -> registro.

Principio: el modelo interpreta y redacta; precios, stock, cuotas y fechas salen
SIEMPRE de `negocio.py` leyendo la hoja. Cada respuesta del modelo pasa por las
guardas de `ia.py` y, si falla, se usa una plantilla fija con los mismos datos.

Estado de conversación: lo mínimo para completar datos faltantes (p. ej. la
boleta que el cliente da en el turno siguiente). Vive en memoria con
vencimiento; si el servicio se reinicia, el cliente simplemente vuelve a
escribir. Con varias instancias haría falta moverlo a la hoja o a Redis.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import ia
import negocio as n
import prompts as P
from sheets import Repositorio

log = logging.getLogger("bot.flujo")

TTL_PENDIENTE = 15 * 60  # segundos
MAX_INTENTOS = 3         # preguntas seguidas por el mismo dato antes de derivar

MSG_NO_TEXTO = "Por ahora solo puedo leer mensajes de texto."


@dataclass
class Pendiente:
    intencion: str
    datos: dict = field(default_factory=dict)
    intentos: int = 1
    expira: float = 0.0


def _nombre(p: n.Producto) -> str:
    return f"{p.marca} {p.modelo}"


def _fecha(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class Bot:
    def __init__(self, repo: Repositorio, cliente_ia, reloj: Callable[[], float] = time.monotonic):
        self.repo = repo
        self.ia = cliente_ia
        self._reloj = reloj
        self._pendientes: dict[str, Pendiente] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ API
    def procesar(self, telefono: str, texto: str) -> str:
        """Devuelve la respuesta y deja registrada la conversación (con su intención)."""
        try:
            intencion, respuesta = self._decidir(telefono, texto or "")
        except Exception:  # noqa: BLE001 - jamás dejar al cliente sin respuesta
            log.exception("error interno procesando mensaje")
            intencion, respuesta = "DERIVAR", self._derivar(telefono, texto, "error_interno")
        try:
            self.repo.registrar_conversacion(telefono, texto or "", intencion, respuesta)
        except Exception:  # noqa: BLE001 - un fallo de la hoja no impide responder
            log.exception("no se pudo registrar la conversación")
        return respuesta

    def procesar_no_texto(self, telefono: str, tipo: str) -> str:
        respuesta = MSG_NO_TEXTO + " " + self._derivar(telefono, f"[mensaje {tipo}]", "mensaje_no_texto")
        try:
            self.repo.registrar_conversacion(telefono, f"[mensaje {tipo}]", "DERIVAR", respuesta)
        except Exception:  # noqa: BLE001
            log.exception("no se pudo registrar la conversación")
        return respuesta

    # ------------------------------------------------------------- pendientes
    def _guardar_pendiente(self, telefono: str, intencion: str, datos: dict, intentos: int = 1) -> None:
        with self._lock:
            self._pendientes[telefono] = Pendiente(intencion, datos, intentos, self._reloj() + TTL_PENDIENTE)

    def _tomar_pendiente(self, telefono: str) -> Pendiente | None:
        with self._lock:
            p = self._pendientes.pop(telefono, None)
        return p if p and p.expira > self._reloj() else None

    # --------------------------------------------------------------- decisión
    def _decidir(self, telefono: str, texto: str) -> tuple[str, str]:
        if not texto.strip():
            return "DERIVAR", self._derivar(telefono, texto, "mensaje_vacio")

        pend = self._tomar_pendiente(telefono)
        if pend:
            if pend.intentos >= MAX_INTENTOS:
                return "DERIVAR", self._derivar(telefono, texto, f"datos_incompletos ({pend.intencion})")
            r = self._continuar(telefono, texto, pend)
            if r is not None:
                return r

        c = ia.clasificar_intencion(self.ia, texto)
        if c.intencion == "CATALOGO":
            return "CATALOGO", self._catalogo(telefono, texto, {}, 1)
        if c.intencion == "CUOTAS":
            return "CUOTAS", self._cuotas(telefono, texto, {}, 1)
        if c.intencion == "GARANTIA":
            return "GARANTIA", self._garantia(telefono, texto, {}, 1)
        if c.intencion == "HORARIOS":
            return "HORARIOS", self._horarios(telefono, texto)
        return "DERIVAR", self._derivar(telefono, texto, c.motivo_derivacion or "fuera_de_alcance")

    def _continuar(self, telefono: str, texto: str, pend: Pendiente) -> tuple[str, str] | None:
        """Retoma una consulta a medias. Devuelve None si el mensaje no aporta nada
        (el cliente cambió de tema): se clasifica como mensaje nuevo."""
        if pend.intencion == "GARANTIA":
            r = self._garantia(telefono, texto, pend.datos, pend.intentos + 1, continuando=True)
        elif pend.intencion == "CUOTAS":
            r = self._cuotas(telefono, texto, pend.datos, pend.intentos + 1, continuando=True)
        else:
            r = self._catalogo(telefono, texto, pend.datos, pend.intentos + 1, continuando=True)
        return None if r is None else (pend.intencion, r)

    # --------------------------------------------------------------- CATALOGO
    def _criterios(self, texto: str, previos: dict) -> tuple[n.Criterios, bool]:
        nuevo = ia.extraer_criterios(self.ia, texto)
        previo = n.Criterios(previos.get("categoria"), previos.get("marca"), previos.get("capacidad"), previos.get("precio_max"))
        fusion = n.Criterios(
            nuevo.categoria or previo.categoria, nuevo.marca or previo.marca,
            nuevo.capacidad or previo.capacidad, nuevo.precio_max or previo.precio_max,
        )
        return fusion, not nuevo.vacio

    @staticmethod
    def _dict_criterios(c: n.Criterios) -> dict:
        return {"categoria": c.categoria, "marca": c.marca, "capacidad": c.capacidad, "precio_max": c.precio_max}

    def _buscar(self, texto: str, criterios: n.Criterios) -> n.ResultadoBusqueda:
        catalogo = self.repo.catalogo()
        mencionados = n.productos_mencionados(catalogo, texto)
        if mencionados:
            return n.resultado_para_productos(catalogo, mencionados)
        return n.buscar_productos(catalogo, criterios)

    def _catalogo(self, telefono, texto, previos, intento, continuando=False) -> str | None:
        criterios, aporta = self._criterios(texto, previos)
        hay_modelo = bool(n.productos_mencionados(self.repo.catalogo(), texto))
        if continuando and not aporta and not hay_modelo:
            return None
        res = self._buscar(texto, criterios)
        if res.estado is n.EstadoBusqueda.SIN_CRITERIOS:
            self._guardar_pendiente(telefono, "CATALOGO", self._dict_criterios(criterios), intento)
            return self._pedir_dato("catalogo", ["tipo de producto, marca o presupuesto"],
                                    "¿Qué producto buscas? Dime el tipo (refrigeradora, lavadora, cocina, aire acondicionado o televisor), la marca o tu presupuesto.")
        return self._redactar_catalogo(res, criterios)

    def _redactar_catalogo(self, res: n.ResultadoBusqueda, criterios: n.Criterios) -> str:
        def ficha(p):
            return {"nombre": _nombre(p), "descripcion": p.descripcion, "capacidad": p.capacidad, "precio": n.formatear_soles(p.precio)}
        datos = {
            "estado": res.estado.value,
            "productos": [ficha(p) for p in res.productos],
            "alternativas": [ficha(p) for p in res.alternativas],
            "buscado": {"categoria": criterios.categoria, "marca": criterios.marca},
        }
        return ia.redactar(self.ia, P.BP03, datos, self._plantilla_catalogo(res))

    def _plantilla_catalogo(self, res: n.ResultadoBusqueda) -> str:
        def linea(p):
            return f"*{_nombre(p)}* {p.capacidad} — {n.formatear_soles(p.precio)}"
        e = n.EstadoBusqueda
        if res.estado is e.DISPONIBLES:
            return "\n".join(["Tengo estas opciones:"] + [linea(p) for p in res.productos[:3]])
        if res.estado is e.FUERA_DE_PRESUPUESTO:
            return "\n".join(["Con ese presupuesto no tengo opciones. Lo más económico:"] + [linea(p) for p in res.productos[:3]])
        if res.estado is e.SIN_STOCK:
            base = f"Por ahora *{_nombre(res.productos[0])}* no está disponible."
            if not res.alternativas:
                return base + " ¿Te ayudo con otro modelo?"
            return "\n".join([base + " Alternativas:"] + [linea(p) for p in res.alternativas[:2]])
        categorias = sorted({p.categoria.lower() for p in self.repo.catalogo()})
        return "Ese producto no lo manejamos en la tienda. Trabajamos con: " + ", ".join(categorias) + "."

    # ----------------------------------------------------------------- CUOTAS
    _RE_PLAZO = re.compile(r"\b(\d{1,2})\s*(?:cuotas?|meses|mes)\b", re.I)

    def _plazos_pedidos(self, texto: str) -> list[int]:
        ofrecidos = n.plazos_desde_config(self.repo.config())
        return [int(x) for x in self._RE_PLAZO.findall(texto) if int(x) in ofrecidos]

    def _cuotas(self, telefono, texto, previos, intento, continuando=False) -> str | None:
        criterios, aporta = self._criterios(texto, previos)
        hay_modelo = bool(n.productos_mencionados(self.repo.catalogo(), texto))
        plazos = sorted(set(self._plazos_pedidos(texto)) | set(previos.get("plazos", [])))
        if continuando and not aporta and not hay_modelo:
            return None
        guardar = {**self._dict_criterios(criterios), "plazos": plazos}
        if criterios.vacio and not hay_modelo:
            self._guardar_pendiente(telefono, "CUOTAS", guardar, intento)
            return self._pedir_dato("cuotas", ["producto"], "¿De qué producto quieres ver las cuotas? Dime el tipo y la marca o el modelo.")

        res = self._buscar(texto, criterios)
        if res.estado is not n.EstadoBusqueda.DISPONIBLES:
            return self._redactar_catalogo(res, criterios)  # no hay qué financiar: se informa disponibilidad
        # Hay varios candidatos: se pide elegir en vez de asumir.
        candidatos = [p for p in self.repo.catalogo() if p.stock > 0 and p in self._todos(texto, criterios)]
        if len(candidatos) != 1:
            opciones = [_nombre(p) for p in sorted(candidatos, key=lambda p: (p.precio, p.sku))[:3]]
            self._guardar_pendiente(telefono, "CUOTAS", guardar, intento)
            return self._pedir_dato("cuotas", ["modelo"], "¿De cuál modelo quieres las cuotas? " + ", ".join(opciones) + ".", opciones=opciones)
        return self._detalle_cuotas(candidatos[0], plazos)

    def _todos(self, texto: str, criterios: n.Criterios) -> list[n.Producto]:
        """Todas las coincidencias (sin el tope de 3 de la búsqueda) para saber si hay ambigüedad."""
        catalogo = self.repo.catalogo()
        mencionados = n.productos_mencionados(catalogo, texto)
        if mencionados:
            return mencionados
        sin_tope = n.Criterios(criterios.categoria, criterios.marca, criterios.capacidad, criterios.precio_max)
        return [p for p in catalogo if self._cumple(p, sin_tope)]

    @staticmethod
    def _cumple(p: n.Producto, c: n.Criterios) -> bool:
        return ((not c.categoria or n._coincide_categoria(p.categoria, c.categoria))
                and (not c.marca or n.normalizar(p.marca) == n.normalizar(c.marca))
                and (not c.capacidad or n._coincide_capacidad(p.capacidad, c.capacidad))
                and (c.precio_max is None or p.precio <= c.precio_max))

    def _detalle_cuotas(self, producto: n.Producto, plazos: list[int]) -> str:
        cfg = self.repo.config()
        plan = n.plan_de_cuotas(producto, cfg, plazos or None)
        fmt = n.formatear_soles
        datos = {
            "producto": _nombre(producto), "precio": fmt(producto.precio),
            "cuotas": [{"plazo": c.plazo, "cuota": fmt(c.monto_cuota), "total": fmt(c.total_a_pagar)} for c in plan],
        }
        ultimo = plan[-1]
        respaldo = "\n".join([
            f"*{_nombre(producto)}* — {fmt(producto.precio)}",
            " · ".join(f"{c.plazo} x {fmt(c.monto_cuota)}" for c in plan),
            f"Total a pagar en {ultimo.plazo} cuotas: {fmt(ultimo.total_a_pagar)}",
        ])
        return ia.redactar(self.ia, P.BP04, datos, respaldo)

    # --------------------------------------------------------------- GARANTIA
    def _garantia(self, telefono, texto, previos, intento, continuando=False) -> str | None:
        nuevo = ia.extraer_garantia(self.ia, texto)
        if continuando and not (nuevo.numero_boleta or nuevo.problema or nuevo.sku):
            return None
        datos = {
            "numero_boleta": nuevo.numero_boleta or previos.get("numero_boleta"),
            "sku": nuevo.sku or previos.get("sku"),
            "problema": nuevo.problema or previos.get("problema"),
        }
        if not datos["numero_boleta"]:
            self._guardar_pendiente(telefono, "GARANTIA", datos, intento)
            return self._pedir_dato("garantia", ["numero_boleta", "problema"],
                                    "Para revisar tu garantía, ¿me indicas el número de tu boleta? (ej. B001-0001)")

        g = n.evaluar_garantia(datos["numero_boleta"], self.repo.boletas(), self.repo.catalogo(), self.repo.config(),
                               self.repo.hoy(), datos["sku"], telefono=telefono)
        E = n.EstadoGarantia
        if g.estado is E.BOLETA_NO_ENCONTRADA:
            return "No encontré esa boleta asociada a este número. Revisa que esté bien escrita (ej. B001-0001) y que escribas desde el número con el que compraste."
        if g.estado is E.PRODUCTO_NO_COINCIDE:
            return "Ese producto no corresponde a la boleta indicada. Revisa el código del producto o el número de boleta."
        if g.estado is E.PRODUCTO_NO_EN_CATALOGO:
            return self._derivar(telefono, texto, f"boleta {g.boleta.numero_boleta} con producto fuera de catálogo")
        nombre = _nombre(g.producto)
        if g.estado is E.VENCIDA:
            return (f"La garantía de tu *{nombre}* venció el {_fecha(g.vence)}. "
                    f"La evaluación técnica tiene un costo de {n.formatear_soles(g.costo_evaluacion)}.")
        # VIGENTE
        if not datos["problema"]:
            self._guardar_pendiente(telefono, "GARANTIA", datos, intento)
            return f"Tu garantía del *{nombre}* está vigente hasta el {_fecha(g.vence)}. ¿Qué problema presenta?"
        ticket = self.repo.crear_ticket(telefono, g.boleta.numero_boleta, g.producto.sku, datos["problema"])
        return (f"Registré tu ticket *{ticket}* para tu *{nombre}*. Tu garantía está vigente hasta el {_fecha(g.vence)}. "
                "Un técnico se comunicará contigo.")

    # --------------------------------------------------------------- HORARIOS
    def _horarios(self, telefono: str, texto: str) -> str:
        cfg = self.repo.config()
        if "horario_atencion" not in cfg or "direccion" not in cfg:
            return self._derivar(telefono, texto, "config_incompleta (horario/direccion)")
        return f"Atendemos {cfg['horario_atencion']}.\nNos ubicamos en {cfg['direccion']}."

    # ---------------------------------------------------------------- DERIVAR
    def _derivar(self, telefono: str, texto, motivo: str) -> str:
        try:
            self.repo.registrar_derivacion(telefono, motivo, texto or "")
        except Exception:  # noqa: BLE001 - el cliente igual recibe su mensaje
            log.exception("no se pudo registrar la derivación")
        try:
            cfg = self.repo.config()
        except Exception:  # noqa: BLE001
            cfg = {}
        horario = cfg.get("horario_atencion")
        respaldo = "Te paso con un asesor de la tienda para que te ayude personalmente."
        if horario:
            respaldo += f"\nHorario de atención: {horario}."
        datos = {"motivo": motivo, **({"horario": horario} if horario else {})}
        try:
            return ia.redactar(self.ia, P.BP07, datos, respaldo)
        except Exception:  # noqa: BLE001
            return respaldo

    # ------------------------------------------------------------------ BP-06
    def _pedir_dato(self, contexto: str, faltantes: list[str], respaldo: str, opciones: list[str] | None = None) -> str:
        datos = {"contexto": contexto, "faltantes": faltantes}
        if opciones:
            datos["opciones"] = opciones
        return ia.redactar(self.ia, P.BP06, datos, respaldo)
