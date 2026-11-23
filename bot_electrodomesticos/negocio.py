"""Reglas de negocio deterministas. SIN IA, SIN red, SIN Google Sheets.

Entrada: filas como `list[dict]` (el formato de `gspread.get_all_records()`).
Salida: dataclasses inmutables con datos ya resueltos; el modelo de lenguaje
solo los redacta. Ningún precio, stock, cuota o fecha sale de otro lugar.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

CENTAVO = Decimal("0.01")
MAX_OPCIONES = 3


# --------------------------------------------------------------------------
# Utilidades de parseo y formato
# --------------------------------------------------------------------------
def a_decimal(valor) -> Decimal:
    """Convierte un valor de celda a Decimal.

    Acepta int/float/Decimal y texto como '1299', '1,299.00', '1.299,00',
    'S/ 1,299.00' o '3,5'. Lanza ValueError si no es un número.
    """
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, bool):
        raise ValueError(f"No es un número: {valor!r}")
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    texto = re.sub(r"[^\d,.\-]", "", str(valor))
    if not texto or texto in {"-", ",", "."}:
        raise ValueError(f"No es un número: {valor!r}")
    if "," in texto and "." in texto:
        # El separador que aparece último es el decimal.
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        partes = texto.split(",")
        # '1,299' (grupo de 3 dígitos, una sola coma) es miles; '3,5' es decimal.
        if len(partes) == 2 and len(partes[1]) == 3 and partes[0].lstrip("-").isdigit() and len(partes[0].lstrip("-")) <= 3:
            texto = texto.replace(",", "")
        else:
            texto = texto.replace(",", ".")
    return Decimal(texto)


def redondear(monto: Decimal) -> Decimal:
    return monto.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def formatear_soles(monto) -> str:
    """S/ 1,299.00"""
    return f"S/ {redondear(a_decimal(monto)):,.2f}"


def normalizar(texto) -> str:
    """Minúsculas, sin tildes ni espacios sobrantes."""
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _compacto(texto) -> str:
    return normalizar(texto).replace(" ", "")


def _a_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no reconocida: {valor!r} (use AAAA-MM-DD o DD/MM/AAAA)")


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Producto:
    sku: str
    categoria: str
    marca: str
    modelo: str
    descripcion: str
    capacidad: str
    precio: Decimal
    stock: int
    garantia_meses: int

    @classmethod
    def desde_fila(cls, fila: dict) -> "Producto":
        return cls(
            sku=str(fila["sku"]).strip(),
            categoria=str(fila["categoria"]).strip(),
            marca=str(fila["marca"]).strip(),
            modelo=str(fila["modelo"]).strip(),
            descripcion=str(fila.get("descripcion", "")).strip(),
            capacidad=str(fila.get("capacidad", "")).strip(),
            precio=a_decimal(fila["precio"]),
            stock=int(a_decimal(fila["stock"])),
            garantia_meses=int(a_decimal(fila["garantia_meses"])),
        )


@dataclass(frozen=True)
class Boleta:
    numero_boleta: str
    fecha_compra: date
    sku: str
    cliente: str
    telefono: str

    @classmethod
    def desde_fila(cls, fila: dict) -> "Boleta":
        return cls(
            numero_boleta=str(fila["numero_boleta"]).strip(),
            fecha_compra=_a_fecha(fila["fecha_compra"]),
            sku=str(fila["sku"]).strip(),
            cliente=str(fila.get("cliente", "")).strip(),
            telefono=str(fila.get("telefono", "")).strip(),
        )


def productos_desde_filas(filas: list[dict]) -> list[Producto]:
    return [Producto.desde_fila(f) for f in filas if str(f.get("sku", "")).strip()]


def boletas_desde_filas(filas: list[dict]) -> list[Boleta]:
    return [Boleta.desde_fila(f) for f in filas if str(f.get("numero_boleta", "")).strip()]


def config_desde_filas(filas: list[dict]) -> dict[str, str]:
    """Hoja Config (clave | valor) -> dict."""
    return {str(f["clave"]).strip(): str(f["valor"]).strip() for f in filas if str(f.get("clave", "")).strip()}


# --------------------------------------------------------------------------
# Catálogo / stock
# --------------------------------------------------------------------------
class EstadoBusqueda(str, Enum):
    DISPONIBLES = "DISPONIBLES"                # hay stock y entra en el presupuesto
    FUERA_DE_PRESUPUESTO = "FUERA_DE_PRESUPUESTO"  # existe con stock, pero sobre precio_max
    SIN_STOCK = "SIN_STOCK"                    # existe en catálogo, stock = 0
    NO_MANEJADO = "NO_MANEJADO"                # no está en el catálogo
    SIN_CRITERIOS = "SIN_CRITERIOS"            # consulta ambigua: pedir aclaración


@dataclass(frozen=True)
class ResultadoBusqueda:
    estado: EstadoBusqueda
    productos: tuple[Producto, ...] = ()
    alternativas: tuple[Producto, ...] = ()


@dataclass(frozen=True)
class Criterios:
    categoria: str | None = None
    marca: str | None = None
    capacidad: str | None = None
    precio_max: Decimal | None = None

    @property
    def vacio(self) -> bool:
        return not any([self.categoria, self.marca, self.capacidad, self.precio_max])


def _coincide_capacidad(producto_cap: str, pedida: str) -> bool:
    prod, ped = _compacto(producto_cap), _compacto(pedida)
    if not ped:
        return True
    if prod == ped:
        return True
    # Pedida solo con número ('350'): compara con la parte numérica del producto.
    if re.fullmatch(r"\d+(\.\d+)?", ped):
        m = re.match(r"(\d+(?:\.\d+)?)", prod)
        return bool(m) and Decimal(m.group(1)) == Decimal(ped)
    return False


def _coincide_categoria(producto_cat: str, pedida: str) -> bool:
    p, q = normalizar(producto_cat), normalizar(pedida)
    return p == q or p.rstrip("s") == q.rstrip("s")


def _por_precio(p: Producto):
    return (p.precio, p.sku)


def buscar_productos(catalogo: list[Producto], criterios: Criterios) -> ResultadoBusqueda:
    """Busca en el catálogo. Nunca inventa: si no hay coincidencia -> NO_MANEJADO."""
    if criterios.vacio:
        return ResultadoBusqueda(EstadoBusqueda.SIN_CRITERIOS)

    coincidencias = [
        p for p in catalogo
        if (not criterios.categoria or _coincide_categoria(p.categoria, criterios.categoria))
        and (not criterios.marca or normalizar(p.marca) == normalizar(criterios.marca))
        and (not criterios.capacidad or _coincide_capacidad(p.capacidad, criterios.capacidad))
    ]
    if not coincidencias:
        return ResultadoBusqueda(EstadoBusqueda.NO_MANEJADO)

    def en_presupuesto(p: Producto) -> bool:
        return criterios.precio_max is None or p.precio <= criterios.precio_max

    con_stock = [p for p in coincidencias if p.stock > 0]
    if con_stock:
        dentro = sorted((p for p in con_stock if en_presupuesto(p)), key=_por_precio)
        if dentro:
            return ResultadoBusqueda(EstadoBusqueda.DISPONIBLES, tuple(dentro[:MAX_OPCIONES]))
        # Hay stock pero todo sobrepasa el presupuesto: se informa lo más barato.
        return ResultadoBusqueda(
            EstadoBusqueda.FUERA_DE_PRESUPUESTO,
            tuple(sorted(con_stock, key=_por_precio)[:MAX_OPCIONES]),
        )

    # Existe pero stock = 0: no se promete reposición; se ofrecen alternativas.
    return ResultadoBusqueda(
        EstadoBusqueda.SIN_STOCK,
        tuple(sorted(coincidencias, key=_por_precio)[:MAX_OPCIONES]),
        alternativas_misma_categoria(catalogo, coincidencias, criterios.precio_max),
    )


def alternativas_misma_categoria(
    catalogo: list[Producto],
    agotados: list[Producto],
    precio_max: Decimal | None = None,
) -> tuple[Producto, ...]:
    categorias = {normalizar(p.categoria) for p in agotados}
    excluir = {p.sku for p in agotados}
    alts = [
        p for p in catalogo
        if normalizar(p.categoria) in categorias
        and p.sku not in excluir
        and p.stock > 0
        and (precio_max is None or p.precio <= precio_max)
    ]
    return tuple(sorted(alts, key=_por_precio)[:MAX_OPCIONES])


def producto_por_sku(catalogo: list[Producto], sku: str) -> Producto | None:
    return next((p for p in catalogo if normalizar(p.sku) == normalizar(sku)), None)


def _alnum(texto) -> str:
    return re.sub(r"[^a-z0-9]", "", normalizar(texto))


def productos_mencionados(catalogo: list[Producto], texto: str) -> list[Producto]:
    """Productos cuyo modelo o SKU aparece escrito en el mensaje (p. ej. 'WT-19',
    'wt19', 'LAV-006'). Resuelve en código, sin pedirle al modelo que adivine."""
    t = _alnum(texto)
    return [
        p for p in catalogo
        if (len(_alnum(p.modelo)) >= 4 and _alnum(p.modelo) in t) or _alnum(p.sku) in t
    ]


def resultado_para_productos(catalogo: list[Producto], productos: list[Producto]) -> ResultadoBusqueda:
    """Mismo contrato que buscar_productos, para productos ya identificados."""
    if not productos:
        return ResultadoBusqueda(EstadoBusqueda.NO_MANEJADO)
    con_stock = sorted((p for p in productos if p.stock > 0), key=_por_precio)
    if con_stock:
        return ResultadoBusqueda(EstadoBusqueda.DISPONIBLES, tuple(con_stock[:MAX_OPCIONES]))
    return ResultadoBusqueda(
        EstadoBusqueda.SIN_STOCK,
        tuple(sorted(productos, key=_por_precio)[:MAX_OPCIONES]),
        alternativas_misma_categoria(catalogo, productos),
    )


# --------------------------------------------------------------------------
# Cuotas (amortización francesa)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Cuota:
    plazo: int            # número de cuotas
    monto_cuota: Decimal  # redondeado a centavos
    total_a_pagar: Decimal
    interes_total: Decimal


def calcular_cuota(principal, tasa_mensual_pct, n: int) -> Cuota:
    """cuota = P * i / (1 - (1+i)^-n), con i = tasa mensual (en %) / 100.

    Con tasa 0 la fórmula es indeterminada (0/0): se usa P / n.
    El total se calcula como cuota_redondeada * n (lo que el cliente paga de verdad).
    """
    P = a_decimal(principal)
    tasa = a_decimal(tasa_mensual_pct)
    if P <= 0:
        raise ValueError("El monto a financiar debe ser mayor que cero")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ValueError("El plazo debe ser un entero positivo de cuotas")
    if tasa < 0:
        raise ValueError("La tasa no puede ser negativa")

    i = tasa / Decimal(100)
    if i == 0:
        cuota = P / n
    else:
        cuota = P * i / (1 - (1 + i) ** -n)
    cuota = redondear(cuota)
    total = cuota * n
    return Cuota(n, cuota, total, total - P)


def tasa_mensual_desde_config(config: dict[str, str]) -> Decimal:
    """Clave Config: `tasa_mensual_pct` (p. ej. 3.5 significa 3.5 % mensual)."""
    if "tasa_mensual_pct" not in config:
        raise KeyError("Falta 'tasa_mensual_pct' en la hoja Config")
    return a_decimal(config["tasa_mensual_pct"])


def plazos_desde_config(config: dict[str, str]) -> list[int]:
    """Clave Config: `plazos_cuotas` (p. ej. '3,6,12,18')."""
    if "plazos_cuotas" not in config:
        raise KeyError("Falta 'plazos_cuotas' en la hoja Config")
    plazos = sorted({int(x) for x in re.findall(r"\d+", config["plazos_cuotas"]) if int(x) > 0})
    if not plazos:
        raise ValueError("'plazos_cuotas' no contiene plazos válidos")
    return plazos


def plan_de_cuotas(producto: Producto, config: dict[str, str], plazos: list[int] | None = None) -> list[Cuota]:
    """Cuotas de un producto para los plazos pedidos (o todos los de Config)."""
    tasa = tasa_mensual_desde_config(config)
    disponibles = plazos_desde_config(config)
    if plazos is not None:
        invalidos = [n for n in plazos if n not in disponibles]
        if invalidos:
            raise ValueError(f"Plazos no ofrecidos: {invalidos}. Disponibles: {disponibles}")
        disponibles = sorted(set(plazos))
    return [calcular_cuota(producto.precio, tasa, n) for n in disponibles]


# --------------------------------------------------------------------------
# Garantía
# --------------------------------------------------------------------------
def sumar_meses(inicio: date, meses: int) -> date:
    """Suma meses de calendario; si el día no existe, usa el último del mes
    (31-ene + 1 mes = 28/29-feb)."""
    idx = inicio.month - 1 + meses
    anio, mes = inicio.year + idx // 12, idx % 12 + 1
    dia = min(inicio.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


class EstadoGarantia(str, Enum):
    VIGENTE = "VIGENTE"
    VENCIDA = "VENCIDA"
    BOLETA_NO_ENCONTRADA = "BOLETA_NO_ENCONTRADA"
    PRODUCTO_NO_COINCIDE = "PRODUCTO_NO_COINCIDE"  # el SKU dicho no es el de la boleta
    PRODUCTO_NO_EN_CATALOGO = "PRODUCTO_NO_EN_CATALOGO"


@dataclass(frozen=True)
class ResultadoGarantia:
    estado: EstadoGarantia
    boleta: Boleta | None = None
    producto: Producto | None = None
    vence: date | None = None
    costo_evaluacion: Decimal | None = None  # solo si está VENCIDA

    @property
    def requiere_ticket(self) -> bool:
        """Se crea ticket cuando la garantía está vigente."""
        return self.estado is EstadoGarantia.VIGENTE


def mismo_telefono(a: str, b: str) -> bool:
    """Compara teléfonos por sus últimos 9 dígitos (tolera +51, espacios y guiones)."""
    da, db = re.sub(r"\D", "", str(a)), re.sub(r"\D", "", str(b))
    return len(da) >= 9 and len(db) >= 9 and da[-9:] == db[-9:]


def evaluar_garantia(
    numero_boleta: str,
    boletas: list[Boleta],
    catalogo: list[Producto],
    config: dict[str, str],
    hoy: date,
    sku: str | None = None,
    *,
    telefono: str,
) -> ResultadoGarantia:
    """Vigente si hoy <= fecha_compra + garantia_meses (el día de vencimiento
    aún cubre). `hoy` se inyecta para que sea comprobable.

    `telefono` es el número desde el que escribe el cliente y es obligatorio:
    solo el titular de la boleta puede consultarla. Si no coincide se responde
    igual que si la boleta no existiera, para no confirmar su existencia a un
    tercero."""
    boleta = next((b for b in boletas if normalizar(b.numero_boleta) == normalizar(numero_boleta)), None)
    if boleta is None or not mismo_telefono(boleta.telefono, telefono):
        return ResultadoGarantia(EstadoGarantia.BOLETA_NO_ENCONTRADA)
    if sku and normalizar(sku) != normalizar(boleta.sku):
        return ResultadoGarantia(EstadoGarantia.PRODUCTO_NO_COINCIDE, boleta=boleta)
    producto = producto_por_sku(catalogo, boleta.sku)
    if producto is None:
        return ResultadoGarantia(EstadoGarantia.PRODUCTO_NO_EN_CATALOGO, boleta=boleta)

    vence = sumar_meses(boleta.fecha_compra, producto.garantia_meses)
    if hoy <= vence:
        return ResultadoGarantia(EstadoGarantia.VIGENTE, boleta, producto, vence)
    if "costo_evaluacion_tecnica" not in config:
        raise KeyError("Falta 'costo_evaluacion_tecnica' en la hoja Config")
    return ResultadoGarantia(
        EstadoGarantia.VENCIDA, boleta, producto, vence,
        costo_evaluacion=a_decimal(config["costo_evaluacion_tecnica"]),
    )
