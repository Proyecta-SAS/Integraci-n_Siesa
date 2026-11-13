# Integracion Siesa - Recibos de Caja

Servicio para registrar automaticamente en Siesa HUB los pagos de clientes que llegan a una hoja operativa de Avanzar. El destino operativo confirmado para este flujo es `Financiero > Cuentas x cobrar > Recibos de caja > Otros ingresos`.

## Hoja operativa compartida

Se toma como fuente operativa la hoja nativa de Google Sheets compartida por Avanzar. Aunque el archivo conserva el nombre `ALEGRA - ALIANZA JURIDICA AVANZAR`, para este proyecto se usa como bandeja de entrada de recibos de caja Siesa.

- Spreadsheet ID: `1TuXSZESNm1xJGJvXLMKTq2bAY1ZvmCl6n8Aez1FRVp8`
- Pestana operativa: `Ingreso / Egreso`
- Pestana de catalogos: `ID`
- Configuracion local: `config/google_sheet_operativa.json`
- Activadores conectados: `config/siesa_activators.json` (cada activador tiene su propia hoja, estado y bitacora).

El equipo operativo solo llena el bloque verde `A:K` de `Ingreso / Egreso`:

```text
Cuenta bancaria, Fecha, Contacto, Tipo de Transaccion, Metodo de pago,
Centro de costos, Concepto, Cantidad, Valor, Nota, Observaciones
```

Las columnas posteriores pertenecen al flujo historico de Alegra y no se usan para crear el recibo. `Consumidor Final` se homologa al tercero Siesa `222222222222`; para cada contacto nuevo se debe registrar antes su tercero Siesa.

El flujo principal queda parametrizado como `SIESA_RECIBO_FLUJO=otros_ingresos`: crea recibos tipo `RC`, no aplica cartera `FVE` y registra el ingreso en el auxiliar `28050505` (`ANTICIPO POR IDENTIFICAR`).

### Dos pagos iguales del mismo cliente

Cada fila pendiente se envia a Siesa aunque coincidan fecha, tercero, valor,
nota y cuenta bancaria con otra fila. La pantalla muestra `Posible duplicado`
y la bitacora y el resultado de la activacion conservan el aviso. La coincidencia
no bloquea el envio ni exige cambiar la nota.

Cada ocurrencia del mismo pago mantiene su propia llave: la primera conserva
la llave historica y las siguientes agregan un ordinal, sin depender del numero
absoluto de fila. Asi, dos filas iguales crean dos recibos y repetir la activacion
no vuelve a crear esos recibos. Agregar otra fila igual permite un recibo adicional.
Las filas ya confirmadas aparecen como `Ya registrado` y no se suman al importe
pendiente. Una nota diferente sigue representando un nuevo pago.

Conserve las filas de la bandeja y no edite sus datos una vez enviadas. Si se
eliminan pagos iguales, no es posible distinguirlos entre si por su contenido.
Las respuestas sin confirmar y los estados historicos `Cargado` sin comprobante
individual requieren conciliacion antes de reintentar; no se borran automaticamente.

Actualizacion de soporte del 2026-10-29: con el plano Connekta corregido, las dos referencias se envian como fecha del pago `AAAAMMDD` y los importes como decimales simples, sin signo `+` ni ceros de relleno. La llave interna de deduplicacion se conserva. Ver [correccion, muestra exitosa y validacion pendiente](docs/mapeo_campos.md#correccion-comunicada-por-soporte-el-2026-10-29).

Soporte confirmo despues que el conector corregido es `261128 - API_v2_ReciboCaja` y que su muestra se cargo en produccion. Deben actualizarse tanto los identificadores como `SIESA_CONNECTOR_URL`, que tiene prioridad sobre ellos. Este conector no devuelve numero de recibo: conciliar en ERP por referencia, tercero, fecha, valor y nota; conservar vacio `Recibo Siesa` cuando no venga explicitamente en la respuesta.

El sistema conserva soporte opcional para cruce de cartera si se cambia `SIESA_RECIBO_FLUJO=cartera`. En ese caso se pueden agregar columnas al final de la hoja sin romper la estructura actual:

```text
Documento cruce, C.O. cruce, U.N. cruce, Sucursal cruce, Auxiliar cruce
```

`Documento cruce` puede venir completo como `FVE-00000006-00` solo en modo cartera. El sistema toma tipo, consecutivo y cuota de esa celda para aplicar el saldo abierto. Ese no es el modo recomendado para la prueba actual.

Tambien quedan preparadas columnas de trazabilidad para resultado operativo:

```text
Estado Siesa, Recibo Siesa, Fecha envio, Respuesta Siesa, Error Siesa
```

La integracion lee la hoja por export CSV y puede escribir los resultados en la misma pestana mediante el webhook incluido en `scripts/sheets_writeback.gs`. Los estados son `Pendiente`, `Pendiente por corregir` y `Cargado`. La escritura se habilita con `SIESA_SHEETS_WRITEBACK_ENABLED=true` despues de configurar el webhook; las simulaciones nunca escriben en la hoja. Consulte [configuracion y comportamiento de estados](docs/estados_sheets.md).

La pestana `ID` funciona como catalogo de seleccion de la hoja. Para Siesa se deja el mapeo final en `config/siesa_recibo_caja_mapping.json` porque los codigos contables/documentales del conector 261128 dependen de la parametrizacion del ERP.

## Flujo

1. Leer filas desde CSV local o export CSV de Google Sheets.
2. Normalizar encabezados y valores.
3. Clasificar la fila con la misma logica del router Make/Alegra.
4. Validar que la fila represente un pago de cliente registrable.
5. Construir payload para `261128 - API_v2_ReciboCaja`.
6. Enviar a Siesa HUB en QA o produccion.
7. Registrar trazabilidad local en JSONL y deduplicar por llave idempotente.

## Blueprint Make/Alegra

El blueprint `Alianza Juridica Avanzar` queda como referencia versionada en `references/make/alianza_juridica_avanzar.blueprint.json`.

Archivos derivados:

- `docs/analisis_blueprint_make_alegra.md`: lectura funcional del escenario.
- `config/alegra_flow_rules.json`: rutas, condiciones y mapas pequenos.
- `config/alegra_catalogs_from_make.json`: contactos y conceptos extraidos desde formulas Make.
- `docs/make_blueprint_inventory.json`: inventario tecnico de modulos.

## Configuracion

Copie `.env.example` a `.env` o exporte variables equivalentes.

Variables principales:

- `SIESA_CONNECTOR_URL`: URL completa copiada desde la guia del conector, si esta disponible.
- `SIESA_HUB_BASE_URL`: host QA o productivo de Siesa HUB/Gestor de Integraciones.
- `SIESA_CONN_KEY`: header `Connikey` copiado desde el Documentador.
- `SIESA_CONN_TOKEN`: header `Connitoken` copiado desde el Documentador.
- `SIESA_ID_COMPANIA`: parametro `idCompania` del conector.
- `SIESA_ID_DOCUMENTO`: parametro `idDocumento`; por defecto `261128`.
- `SIESA_NOMBRE_DOCUMENTO`: parametro `nombreDocumento`; por defecto `API_v2_ReciboCaja`.
- `SIESA_HUB_CONNECTOR_ID`: por defecto `261128`.
- `SIESA_HUB_OPERATION`: por defecto `API_v2_ReciboCaja`.
- `SIESA_INPUT_CSV`: archivo CSV local.
- `SIESA_SHEETS_CSV_URL`: URL de exportacion CSV de Google Sheets.
- `SIESA_DRY_RUN`: `true` para validar y generar payloads sin enviar.
- `SIESA_ALLOW_SEND`: `true` habilita envio real. Debe quedar `false` salvo durante una ventana controlada.
- `SIESA_SEND_COOLDOWN_MINUTES`: minutos de bloqueo entre activaciones reales; por defecto `15`.
- `SIESA_RECIBO_FLUJO`: `otros_ingresos` para el flujo actual validado con contabilidad; `cartera` solo si se requiere aplicar documentos `FVE`.
- `SIESA_AUXILIAR_OTRO_ING`: auxiliar de otros ingresos; para Avanzar queda `28050505`.

## Uso

Validar y ver payloads sin enviar:

```powershell
.\scripts\Invoke-SiesaPaymentSync.ps1 -Environment qa -InputCsv .\samples\alegra_payments.csv
```

Enviar contra QA:

```powershell
.\scripts\Invoke-SiesaPaymentSync.ps1 -Environment qa -InputCsv .\samples\alegra_payments.csv -Send
```

Validar que la configuracion minima del conector esta cargada:

```powershell
python -m siesa_payments.cli validate-connector
```

Comparar el Body real copiado desde el Documentador Siesa contra el mapeo:

```powershell
python -m siesa_payments.cli inspect-contract --contract-file config/siesa_recibo_caja_contract.json
```

Programar ejecucion automatica cada 5 minutos:

```powershell
.\scripts\Register-SiesaPaymentSyncTask.ps1 -Environment qa -EveryMinutes 5 -TaskName SiesaPaymentSyncQA
```

Ver tambien `docs/flujo_equivalente_alegra.md`.
Para la reunion de paso a produccion use `docs/prueba_produccion_reunion.md`.

## Visual operativa

La primera visual local esta en `web/index.html`. Se puede abrir directamente en el navegador y representa el flujo:

```text
Sheets -> Validacion -> Siesa HUB -> Recibos de caja / Otros ingresos -> Trazabilidad
```

Para Railway el repositorio incluye `Procfile`:

```text
web: python -m siesa_payments.web_server --host 0.0.0.0
```

Railway debe recibir las variables `SIESA_*` como variables de entorno. Para produccion se debe usar un estado persistente o volumen para `SIESA_STATE_FILE`, porque el filesystem del contenedor puede reiniciarse.

### Lotes que tardan varios minutos

La activacion real responde inmediatamente con HTTP `202` y el identificador
del lote. El servidor procesa los pagos en segundo plano; la pantalla consulta
`GET /api/sync/job?activator=alianza` cada dos segundos y muestra filas procesadas,
recibos confirmados y novedades. El operador puede cerrar la pagina y volver
a abrir el modulo para recuperar el avance o el resultado de la ultima activacion.
Una perdida de conexion de seguimiento solo reintenta consultas, nunca el envio.

El estado del ultimo lote se guarda junto a `SIESA_STATE_FILE`, en
`<archivo-de-estado>.job.json`; ambos deben quedar dentro del volumen persistente.
El bloqueo `<archivo-de-estado>.send.lock` permite un solo lote real por fuente,
incluso cuando varias personas activan a la vez. Una segunda solicitud durante
el proceso devuelve el mismo lote. El despliegue previsto usa una instancia
del servidor y su volumen; este bloqueo requiere un filesystem compartido para
coordinar procesos, no coordina replicas con discos independientes.

Si el servidor se reinicia, el lote se muestra como `interrupted` y no se retoma
automaticamente. Cada pago se marca como sin confirmar antes de llamar al ERP
y se conserva asi si se pierde la respuesta o se interrumpe el proceso. Los
recibos confirmados permanecen registrados; concilie cualquier pago sin confirmar
en Siesa antes de resolverlo y activar los pendientes. El numero de recibo sigue
requiriendo la consulta en ERP cuando el conector no lo devuelve.

### Respuestas lentas y sin confirmar

El servicio permite configurar la espera de red del POST al ERP con
`SIESA_REQUEST_TIMEOUT_SECONDS`; el valor predeterminado es 120 segundos y debe
ser un entero positivo. Este ajuste se aplica al cliente de Siesa, sin cambiar
el payload, las referencias contables ni la llave interna del pago. El timeout
de `urllib` corresponde a operaciones de red bloqueantes; no es un limite total
garantizado para toda la transaccion.
La consulta de estado muestra el valor efectivo como `request_timeout_seconds`.

La auditoria registra duracion y espera configurada. Si no se obtiene una
respuesta, tambien conserva la categoria del fallo y el tipo de excepcion en
la auditoria y el estado pendiente. No guarda el texto bruto de la excepcion,
que podria contener una URL privada o credenciales.

Ampliar la espera reduce cortes del cliente ante respuestas lentas; no evita
una caida de Siesa ni un limite anterior del intermediario. No se agrega ningun
reintento automatico de creacion: el recibo podria existir aunque se pierda la
respuesta. Los pagos previamente sin confirmar mantienen su bloqueo y requieren
conciliacion; este ajuste no los desbloquea ni los reenvia.

Para resolver automaticamente la incertidumbre hace falta un contrato de
consulta del resultado por identificador unico, o soporte de idempotencia
confirmado por Siesa. El proyecto envia `Idempotency-Key`, pero no tiene una
garantia documentada de deduplicacion del lado del conector. Las referencias
contables por fecha pueden repetirse y no bastan para identificar un recibo.
No se debe inventar una consulta ni cambiar las referencias validadas para
suplir esa falta de contrato.

Referencias: [timeout de urllib](https://docs.python.org/3/library/urllib.request.html)
y [reintentos de solicitudes no idempotentes, RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2).

## Estado QA validado

El 2026-09-09 se ejecuto una prueba real en QA con respuesta exitosa de Siesa y verificacion visual en ERP: recibo `RC-00000006`, cliente `1000456076`, fecha `2026-06-30`, valor `$1,000`, caja `01`, medio `EFE-EFECTIVO`.

El 2026-09-10 se ejecuto una prueba real desde Google Sheets contra QA con respuesta exitosa de Siesa y verificacion visual en ERP: recibo `RC-00000007`, cliente `1000033853`, fecha `2026-06-30`, valor `$1,000`, caja `01`, medio `EFE-EFECTIVO`.

Esta version deja probado el envio de recibo de caja. Para produccion falta confirmar con Siesa la parametrizacion bancaria de transferencia/consignacion y cerrar el ruteo de las 4 fuentes Alegra/Make.
## QA y paso a produccion

Checklist minimo:

- Confirmar con Siesa el contrato JSON exacto del conector `261128 - API_v2_ReciboCaja`.
- Ajustar `config/siesa_recibo_caja_mapping.json` a los nombres/codigos exigidos por el conector.
- Ejecutar `sync --dry-run` con muestra real de la hoja.
- Ejecutar en QA con 1 pago, verificar recibo de caja en el modulo operativo/financiero de Siesa.
- Ejecutar lote QA pequeno y comparar total, tercero, fecha, cuenta, medio de pago, concepto y centro de costo.
- Activar produccion solo despues de verificar trazabilidad: referencias del payload, respuesta del HUB y recibo localizado en ERP. La API v2 no devuelve el numero de recibo.

## Acceso privado y base de datos

La interfaz y todas las API operativas requieren una sesion iniciada en `/login`.
No existe registro publico. Las contrasenas se almacenan como hashes PBKDF2;
la cookie de sesion es HttpOnly, SameSite y Secure en produccion. Las acciones
POST requieren el token CSRF de la sesion y un origen valido.

Instalar las dependencias del proyecto con `python -m pip install .`. Configurar
`SIESA_DATABASE_URL` con la URL privada de PostgreSQL en produccion. En Railway
se utiliza la referencia `${{Postgres.DATABASE_URL}}`; no exponer PostgreSQL por
un dominio o proxy publico. El servicio comprueba la base antes de aceptar
solicitudes y no permite usar SQLite cuando `SIESA_ENV` es `prod` o `production`.
En desarrollo se admite `sqlite:///.state/application.db`.

Antes del primer inicio, generar un hash mediante:

```powershell
python -m siesa_payments.manage hash-password
```

Configurar `SIESA_BOOTSTRAP_ADMIN_EMAIL` (usuario o correo) y
`SIESA_BOOTSTRAP_ADMIN_PASSWORD_HASH` con ese resultado. El primer arranque crea
la cuenta solo si no existen usuarios; reiniciar nunca cambia su contrasena.
No guardar contrasenas en Git ni pasarlas como argumentos del comando. Para
crear cuentas adicionales en el entorno conectado a la base:

```powershell
python -m siesa_payments.manage create-user --email contabilidad@empresa.com
```

La contrasena se solicita de forma interactiva. Tras cinco intentos incorrectos,
la cuenta espera 15 minutos antes de admitir otro intento. Las sesiones duran
ocho horas y cerrar sesion las revoca en la base de datos.

## Historico y recuperacion

`/historico` permite consultar por fuente, estado, texto y posibles duplicados,
con paginas de 50 registros. Al arrancar, el servicio recupera los archivos de
auditoria JSONL y de estado de las fuentes configuradas desde el volumen
persistente. Antes de importarlos conserva copias originales en
`history_migration_backups`, junto al archivo de estado. La importacion es
repetible, conserva puntos de lectura y vuelve a actualizar el indice cada
30 segundos. Las lineas completas no interpretables se registran como incidencias.

Los archivos originales de estado y sus bloqueos siguen controlando los envios
a Siesa. El indice SQL no los reemplaza ni los modifica. Recuperar el historico
no llama al ERP ni reenvia recibos. Se puede repetir de forma administrativa con
`python -m siesa_payments.manage recover`.

Se recupera la evidencia que aun existe en los archivos disponibles, no un
inventario completo del ERP. Un pago confirmado puede no tener numero de recibo
porque el conector no lo devuelve. Un resultado sin confirmar conserva ese
estado y exige conciliacion en Siesa. Los eventos de reenvio evitado se agrupan
por llave del pago: no se cuentan como recibos nuevos.

La etiqueta **Posible duplicado** refleja una advertencia original o una
coincidencia de tercero, fecha, valor, nota y medio de pago compatible entre
llaves distintas de la misma fuente. Requiere revision contable: no demuestra
que haya dos documentos en el ERP, no cambia el estado confirmado y no agrega
un bloqueo nuevo al flujo de integracion. Los registros antiguos sin ambiente
documentado mantienen esa ausencia; no se les atribuye produccion por suposicion.

## Pruebas

```powershell
python -m unittest discover -s tests
node --test tests/web_app.test.cjs tests/sheets_writeback.test.cjs
```
