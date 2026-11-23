# Guía paso a paso

Hay dos partes. La **Parte A funciona hoy**, solo necesita una clave de Gemini. La **Parte B** (ver la
respuesta dentro de un chat de WhatsApp) necesita elegir un canal; ver al final.

---

## Parte A — Probar el bot desde la terminal (sin WhatsApp, sin Meta)

### 1. Requisitos
- Python 3.11 o superior (`python --version`)
- Git
- Una clave de Gemini (gratis): <https://aistudio.google.com/apikey> → *Create API key*

### 2. Descargar el código
```bash
git clone https://github.com/RoyalSin22/Bot-Electro.git
cd Bot-Electro
git checkout ccr-d2ce404e-tpojau
cd bot_electrodomesticos
```

### 3. Instalar
```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Comprobar que todo está bien (no usa clave ni internet)
```bash
python -m pytest -q
```
Debe terminar con `233 passed, 1 skipped` (la omitida es la prueba contra Gemini real).

### 5. Poner tu clave (nunca la escribas en un archivo del repositorio)
```bash
export GEMINI_API_KEY="tu-clave"                 # Windows PowerShell:  $env:GEMINI_API_KEY="tu-clave"
```

### 6. (Opcional) Medir la calidad de la IA con los 20 mensajes de prueba
```bash
python evaluar_ia.py
```
Imprime aciertos de intención y extracción, los fallos uno por uno y `APROBADO` / `NO APROBADO`
(umbral: 18 de 20 intenciones y todas las extracciones). Si falla algo, copia la salida y la
revisamos: se ajustan los prompts.

### 7. Hablar con el bot
Un solo mensaje por comando (imprime la respuesta y termina):
```bash
python simulador.py -m "tienen refrigeradoras LG?"
```
O una conversación continua:
```bash
python simulador.py
```
Dentro del simulador: `/registros` (ver lo que el bot anotó), `/telefono 51999000015` (cambiar el
número desde el que "escribes") y `/salir`.

### 8. Qué probar y qué esperar
El texto exacto lo redacta Gemini; **los números salen siempre de la hoja**.

| Escribes | Debe ocurrir |
|---|---|
| `tienen refrigeradoras LG?` | Ofrece LG GT-29 (S/ 1,799.00) y GT-37 (S/ 2,399.00). No ofrece la GS-65 (sin stock). |
| `lavadora Mabe de 17 kilos` | Dice que no está disponible y ofrece alternativas de lavadoras. No promete reposición. |
| `tienen cafeteras Oster?` | Dice que no lo manejan. No inventa modelos ni precios. |
| `quiero algo` | Pide aclarar qué producto buscas. Respóndele `una lavadora LG` y continúa. |
| `cuotas de la LG WT-19 a 12 meses` | Muestra 12 cuotas de **S/ 196.52** (total S/ 2,358.24) sobre S/ 1,899.00. |
| `a qué hora abren` | Horario y dirección de la pestaña `Config`. |
| `quiero hablar con un vendedor` | Mensaje de derivación; queda una fila en `Derivaciones` (`/registros`). |

Garantía (solo responde al **titular** de la boleta; por eso hay que cambiar de teléfono):
```
/telefono 51999000015
mi refrigeradora hace ruido, boleta B001-0015     → crea ticket T-0001 (garantía vigente hasta 20/10/2028)
/telefono 51999000001
mi cocina no enciende, boleta B001-0001           → garantía vencida el 01/06/2025, evaluación S/ 50.00
/telefono 51911111111
mi cocina no enciende, boleta B001-0001           → "No encontré esa boleta…" (otro número no ve nada)
/registros
```
> La vigencia depende de la fecha de hoy. B001-0015 y B001-0001 se eligieron porque no cambian de estado
> en años. B001-0009 (vence 23/11/2026) y B001-0008 son casos límite solo válidos cerca de esa fecha.

### 9. Usar tu Google Sheet en vez de la hoja de demostración (opcional)
Hace falta una *cuenta de servicio* de Google, porque el programa corre en tu equipo y no con tu sesión:
1. <https://console.cloud.google.com> → crear proyecto → *APIs y servicios* → habilitar **Google Sheets API**.
2. *IAM y administración → Cuentas de servicio* → crear → pestaña *Claves* → *Agregar clave* → JSON.
3. Abre tu hoja → **Compartir** → pega el `client_email` del JSON como *Editor*.
4. ```bash
   export GOOGLE_SHEET_ID="1wRiGtXyluF61GvQdgrjeORxTWMNEX_yZ5E-ZvyGwiW4"
   export GOOGLE_CREDENTIALS_JSON="$(cat ruta/al/archivo.json)"
   python simulador.py --hoja-real
   ```
Los tickets, conversaciones y derivaciones quedarán escritos en tu hoja. **No subas el JSON a git.**

---

## Parte B — Ver la respuesta en un chat de WhatsApp

Para que un mensaje llegue **a un chat de WhatsApp** hace falta un canal; no existe uno sin cuenta ni
conexión. Hay dos:

| Canal | Qué es | Pros | Contras |
|---|---|---|---|
| **Meta Cloud API** (oficial) | Número de prueba gratis de Meta; tu celular es el único destinatario | Estable, permitido, ya está programado (`main.py`, `whatsapp.py`) | Requiere crear una app en Meta |
| **Puente no oficial** (WhatsApp Web) | Vincula tu propio WhatsApp con un QR, como un dispositivo más | Sin cuenta de Meta | Va contra los términos de WhatsApp: pueden **bloquear tu número**. Aún no está programado |

Pasos del canal oficial: están en `README.md`, sección *Conectar WhatsApp*. Con `NUMEROS_PERMITIDOS=51TU_NUMERO`
el bot ignora a cualquier otro número, así que solo tu WhatsApp recibe respuesta.
