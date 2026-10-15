# Estados de recibos de caja en Google Sheets

El cambio local permite escribir el resultado de cada fila procesada en la misma
pestana de origen. No requiere paquetes Python adicionales. Para activarlo hace
falta desplegar el Apps Script con una cuenta que pueda editar las hojas.

| Estado Siesa | Significado |
| --- | --- |
| Pendiente | Fila validada y marcada antes de intentar su envio. Si hay una respuesta no confirmada, Error Siesa pide verificar el ERP. |
| Pendiente por corregir | Datos incompletos/invalidos, configuracion faltante o rechazo informado por Siesa. Error Siesa indica el motivo. |
| Cargado | La integracion recibio una respuesta exitosa de Siesa, o reconoce un envio confirmado previamente en su estado local. |

Tambien se escriben `Recibo Siesa`, `Fecha envio`, `Respuesta Siesa` y `Error Siesa`.
Si la API no retorna explicitamente el numero del recibo, la columna de numero
queda vacia; no se inventa un consecutivo. Fecha envio guarda la fecha UTC del
envio confirmado. Al corregir y reenviar una fila se limpia el error anterior.

## Preparar el webhook

1. Cree un proyecto de Google Apps Script y copie el contenido de
   `scripts/sheets_writeback.gs`.
2. En Configuracion del proyecto > Propiedades de la secuencia de comandos agregue:
   - `SIESA_WEBHOOK_TOKEN`: un secreto aleatorio largo, por ejemplo generado con
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   - `SIESA_ALLOWED_SPREADSHEETS`: los IDs de los spreadsheets autorizados, separados
     por comas. Use los IDs de `config/siesa_activators.json` que quiera habilitar.
3. Implemente como Aplicacion web, ejecutando como el propietario con permiso de
   edicion sobre esas hojas. El acceso debe permitir solicitudes del servidor
   sin iniciar sesion (`Cualquier usuario`); el script valida el secreto del cuerpo
   y la lista de spreadsheets antes de acceder a ellos. Si la organizacion no
   permite ese acceso, este webhook requiere otro mecanismo de autenticacion.
4. Copie la URL de implementacion terminada en `/exec`, no la URL `/dev`.
5. Configure el entorno local (y, posteriormente, el del servidor):

```dotenv
SIESA_SHEETS_WRITEBACK_ENABLED=true
SIESA_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/ID_IMPLEMENTACION/exec
SIESA_SHEETS_WEBHOOK_TOKEN=EL_MISMO_SECRETO_DE_APPS_SCRIPT
```

No guarde el secreto en Git ni en las celdas. La configuracion de ejemplo mantiene
la escritura apagada. No se modifica `SIESA_ALLOW_SEND`: el permiso para crear
recibos sigue siendo independiente. Los modos de simulacion y las consultas de
filas no escriben nada, aunque la escritura este habilitada.

El destino se obtiene de la URL CSV de origen, incluidos su spreadsheet ID y gid.
Por eso los cuatro activadores usan sus propias hojas sin una URL de destino
global que pueda cruzar los resultados. Si la fuente es un CSV local, el sistema
rechaza habilitar la escritura en Sheets.

## Proteccion de las filas y reintentos

El webhook agrega las columnas que falten despues de todas las columnas existentes
y reutiliza las que ya tengan esos nombres exactos. No escribe sobre A:K ni sobre
las columnas historicas de Alegra. Antes de actualizar compara los valores visibles
de A:K con la fila leida desde CSV. Si una fila se edito, se ordeno o se movio, la
actualizacion se rechaza y se debe volver a leer la hoja. Evite editar u ordenar
durante una activacion: la comparacion no bloquea cambios humanos posteriores ni
distingue dos filas con A:K completamente identico.

Un fallo al marcar Pendiente impide enviar esa fila a Siesa. Los fallos al escribir
se incluyen en `result.sheet_errors`, en la bitacora y en el aviso de la pantalla.
El resto de las filas puede continuar. La CLI devuelve codigo 2 si hay errores de
escritura, validacion o envio.

Cada envio exitoso guarda inmediatamente su llave, respuesta, fecha y numero
disponible en el archivo de estado, antes de escribir Cargado en Sheets. Si esa
ultima escritura falla, la proxima activacion (respetando el cooldown) recupera
los datos guardados y repara Cargado sin crear otro recibo. Para recibos enviados
por versiones anteriores, se conserva el numero/fecha/respuesta que ya tenga la
hoja si el estado local no cuenta con esos datos.

Si una llamada a Siesa termina sin respuesta, la fila queda Pendiente con aviso
de verificacion y su llave se conserva en `uncertain_receipts` del archivo de
estado. Las siguientes activaciones no la reenvian automaticamente. Un responsable
debe conciliar el resultado en Siesa antes de liberar la llave: si el recibo existe,
incorpore su llave en `processed_keys` y sus datos en `receipts`; si se confirma que
no existe, retire la entrada de `uncertain_receipts`. Realice esa conciliacion con
el servicio detenido y una copia del archivo de estado. No borre el estado completo.

El webhook tampoco permite cambiar Cargado a Pendiente: si se perdio el estado
local, pide conciliar antes de enviar. Mantenga el archivo `SIESA_STATE_FILE` en
almacenamiento persistente, como requiere el flujo existente.

Se actualizan las filas incluidas en cada activacion; no se cambia toda la hoja
por abrir la pantalla. Si se selecciona una sola fila, solo esa fila recibe estado.
Las fechas y valores que no se pueden interpretar quedan Pendiente por corregir
sin detener las otras filas. Las filas vacias se ignoran.

## Verificacion local

```powershell
python -m unittest discover -s tests
node --test tests/sheets_writeback.test.cjs
node --check web/app.js
```

Las pruebas usan transportes simulados y una hoja en memoria: no crean recibos
ni escriben en Google. La prueba con una hoja real queda pendiente hasta desplegar
y configurar el webhook.

Referencias oficiales: [aplicaciones web de Apps Script](https://developers.google.com/apps-script/guides/web),
[lectura y escritura de rangos](https://developers.google.com/apps-script/reference/spreadsheet/range)
y [bloqueos de ejecucion](https://developers.google.com/apps-script/reference/lock/lock-service).
