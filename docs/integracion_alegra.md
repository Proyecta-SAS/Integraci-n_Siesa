# Siesa y Alegra en un solo portal

`/alegra` integra las cuatro cuentas de Activadores-Alegras (Antiguo, Lidera,
Alianza y Prosperar). Comparte el inicio de sesión y cierre de sesión de Siesa,
la navegación lateral, el tema claro/oscuro y `/configuracion`.

El módulo Siesa conserva sus rutas, validaciones, preflight, simulación, envío
de recibos e histórico. Entrar a Alegra no consulta Sheets ni ejecuta operaciones
de Siesa. Los botones de Alegra requieren confirmación.

## Conexiones de Alegra

Configurar en el entorno del servidor las direcciones existentes de
`services/automation_webhook_service.py` del proyecto Activadores-Alegras:

| Cuenta | Variable |
| --- | --- |
| Antiguo | `ALEGRA_WEBHOOK_ANTIGUO` |
| Lidera | `ALEGRA_WEBHOOK_LIDERA` |
| Alianza | `ALEGRA_WEBHOOK_ALIANZA` |
| Prosperar | `ALEGRA_WEBHOOK_PROSPERAR` |

Se conserva el POST JSON original `{"activador":"ON"}`. Las direcciones HTTPS
se leen del servidor y no aparecen en el HTML, JavaScript ni respuestas de estado.
Una cuenta sin configurar muestra **Conexión pendiente** y no permite ejecutar.
No se incluyen direcciones de webhooks en el repositorio.

`GET /api/alegra/status` y `POST /api/alegra/activate` requieren sesión de Siesa;
el POST también exige origen válido y token CSRF. La espera de 15 minutos es
por cuenta, compartida entre usuarios y persistida en `alegra_activations` en la
misma base de datos. La tabla se crea de forma aditiva al iniciar Application,
tanto en SQLite como PostgreSQL. Dos solicitudes simultáneas no generan dos
envíos. Un error de transporte mantiene la espera porque la orden podría haber
llegado al destino; se debe revisar el resultado antes de reintentar.

## Vista local para revisión

Desde la raíz del proyecto:

```powershell
python scripts/preview_portal.py --port 5052
```

Abrir <http://127.0.0.1:5052/demo>. Este servidor escucha únicamente en loopback.
Crea una sesión local de demostración, usa datos Siesa de ejemplo y simula las
cuatro activaciones Alegra. No carga `.env`, no consulta Sheets y bloquea el envío
real a Siesa. Su base de datos está separada en `.state/portal-preview/portal.sqlite3`.
El acceso `/demo` existe exclusivamente en este script, no en el servidor normal.

Para usar las conexiones reales se ejecuta el servidor habitual con sus variables
Siesa y las cuatro nuevas variables Alegra configuradas. No usar el script de
demostración para desplegar ni como prueba de entrega real de los webhooks.

## Validación

```powershell
python -B -m unittest discover -s tests
node --test tests/web_app.test.cjs tests/sheets_writeback.test.cjs
```

Las pruebas de Alegra usan transporte simulado: validan las cuatro cuentas,
el payload original, la espera persistente, la concurrencia, el aislamiento de
Siesa y la autenticación/CSRF compartidos sin llamar a los webhooks reales.
