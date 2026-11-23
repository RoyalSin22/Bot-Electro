# Bot de WhatsApp — tienda de electrodomésticos (demo)

El modelo (Gemini) **interpreta y redacta**. Precios, stock, cuotas y fechas de garantía los
resuelve código determinista (`negocio.py`) leyendo la Google Sheet. Cada texto del modelo pasa
por guardas (`ia.py`) y, si inventa un monto o una fecha, se reemplaza por una plantilla fija.

```
main.py (webhook) → flujo.py (orquestador) → ia.py + prompts.py (Gemini)
                                           → negocio.py (reglas) ← sheets.py (Google Sheets)
whatsapp.py (enviar/parsear/firma)         simulador.py (prueba local sin Meta)
```

## Pruebas
```
pip install -r requirements.txt
python -m pytest -q                          # offline: 225 pruebas, sin claves
GEMINI_API_KEY=... python evaluar_ia.py      # los 20 mensajes contra Gemini real
```

## Probar sin WhatsApp (simulador)
```
export GEMINI_API_KEY=...
python simulador.py                          # hoja demo en memoria
python simulador.py --telefono 51999000009   # ser el titular de la boleta B001-0009
python simulador.py --hoja-real              # tu Google Sheet (ver paso 2)
```

## Conectar WhatsApp: lista de pasos

### 1. Gemini
Clave en <https://aistudio.google.com/apikey> → `GEMINI_API_KEY`.

### 2. Cuenta de servicio de Google (para que el bot lea/escriba la hoja)
1. Google Cloud Console → crear proyecto → habilitar **Google Sheets API**.
2. IAM → Cuentas de servicio → crear → *Claves* → JSON.
3. Abre tu hoja → **Compartir** → pega el `client_email` de la cuenta (rol *Editor*).
4. `GOOGLE_SHEET_ID` = el tramo entre `/d/` y `/edit` de la URL.
5. `GOOGLE_CREDENTIALS_JSON` = el contenido del JSON, en una sola línea. **Nunca al repositorio.**

La hoja debe tener las pestañas `Productos`, `Boletas`, `Tickets`, `Conversaciones`,
`Derivaciones` y `Config` con los encabezados de `sheets.ENCABEZADOS`.

### 3. Meta (WhatsApp Cloud API)
> No necesitas la app WhatsApp Business ni registrar tu número: Meta da un **número de prueba gratuito**.
> Tu WhatsApp personal solo actúa como cliente (destinatario autorizado) que le escribe a ese número.
> Si no quieres usar ni tu celular, usa el simulador local (`python simulador.py`).

1. <https://developers.facebook.com> → crear app (tipo *Business*) → añadir el producto **WhatsApp**.
2. *WhatsApp → API Setup*: Meta da un **número de prueba**. Copia el *Phone number ID* → `WHATSAPP_PHONE_ID`
   y el *token temporal* (dura 24 h) → `WHATSAPP_TOKEN`.
3. En el mismo panel, **agrega tu celular como destinatario** (te llega un código por WhatsApp).
4. *App settings → Basic → App secret* → `WHATSAPP_APP_SECRET` (el bot rechaza peticiones sin firma válida).
5. Inventa un texto cualquiera para `WEBHOOK_VERIFY_TOKEN` (el mismo que pondrás en Meta).

### 4. Desplegar (Render, capa gratuita)
1. Render → New → **Blueprint** → elige este repositorio (usa `render.yaml`).
2. Carga en el panel las 7 variables del paso anterior (no están en el repo).
3. Cuando esté arriba, comprueba `https://TU-SERVICIO.onrender.com/health` → `{"status":"ok"}`.

> La capa gratuita duerme tras ~15 min sin tráfico: el primer mensaje puede tardar ~1 min
> (Meta reintenta). Para una demo en vivo, abre `/health` unos segundos antes.

### 5. Enlazar el webhook
*WhatsApp → Configuration → Webhook*: URL `https://TU-SERVICIO.onrender.com/webhook`,
token = `WEBHOOK_VERIFY_TOKEN` → **Verify and save** → suscribe el campo **messages**.

### 6. Probar
Desde tu celular (el agregado como destinatario) escribe al número de prueba.
Mensajes sugeridos (la boleta solo responde al teléfono titular; con el número de prueba usa
el simulador o cambia el teléfono de una boleta en la hoja por el tuyo):
- `tienen refrigeradoras LG?` · `lavadora Mabe de 17 kilos` (sin stock) · `tienen cafeteras?`
- `cuotas de la LG WT-19 a 12 meses`
- `a qué hora abren`
- `quiero hablar con un vendedor` → revisa la pestaña `Derivaciones`

## Límites conocidos
- El estado de conversación (datos a medias) vive en memoria: se pierde al reiniciar.
- Una sola instancia: con varias, el dedupe de mensajes y el estado no se comparten.
- Los tickets usan un correlativo `T-0001`; con alta concurrencia habría que usar ids únicos.
- El token temporal de Meta caduca en 24 h; para uso continuo hay que crear un token permanente.
- Datos 100 % ficticios.
