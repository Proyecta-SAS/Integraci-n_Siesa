# Integracion Siesa - Recibos de Caja

Servicio para registrar automaticamente en Siesa HUB los pagos de clientes que llegan a una hoja operativa de Avanzar. El destino operativo confirmado es `Financiero > Cuentas x cobrar > Recibos de caja > Clientes`.

## Hoja operativa compartida

Se toma como fuente operativa la hoja nativa de Google Sheets compartida por Avanzar. Aunque el archivo conserva el nombre `ALEGRA - ALIANZA JURIDICA AVANZAR`, para este proyecto se usa como bandeja de entrada de recibos de caja Siesa.

- Spreadsheet ID: `1TuXSZESNm1xJGJvXLMKTq2bAY1ZvmCl6n8Aez1FRVp8`
- Pestana operativa: `Ingreso / Egreso`
- Pestana de catalogos: `ID`
- Configuracion local: `config/google_sheet_operativa.json`

La estructura de entrada confirmada usa los encabezados `A1:V1`:

```text
Cuenta bancaria, Fecha, Contacto, Tipo de Transaccion, Metodo de pago,
Centro de costos, Concepto, Cantidad, Valor, Nota, Observaciones,
Cliente, Tipo, Tipo de identificacion, Numero de identificacion,
Nombre, Apellido, Tipo de persona, Responsabilidad tributaria,
Municipio / Departamento, Direccion
```

La pestana `ID` funciona como catalogo de seleccion de la hoja. Para Siesa se deja el mapeo final en `config/siesa_recibo_caja_mapping.json` porque los codigos contables/documentales del conector 142888 dependen de la parametrizacion del ERP.

## Flujo

1. Leer filas desde CSV local o export CSV de Google Sheets.
2. Normalizar encabezados y valores.
3. Clasificar la fila con la misma logica del router Make/Alegra.
4. Validar que la fila represente un pago de cliente registrable.
5. Construir payload para `142888 - API_v1_ReciboCaja`.
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
- `SIESA_ID_DOCUMENTO`: parametro `idDocumento`; por defecto `142888`.
- `SIESA_NOMBRE_DOCUMENTO`: parametro `nombreDocumento`; por defecto `API_v1_ReciboCaja`.
- `SIESA_HUB_CONNECTOR_ID`: por defecto `142888`.
- `SIESA_HUB_OPERATION`: por defecto `API_v1_ReciboCaja`.
- `SIESA_INPUT_CSV`: archivo CSV local.
- `SIESA_SHEETS_CSV_URL`: URL de exportacion CSV de Google Sheets.
- `SIESA_DRY_RUN`: `true` para validar y generar payloads sin enviar.

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

## Visual operativa

La primera visual local esta en `web/index.html`. Se puede abrir directamente en el navegador y representa el flujo:

```text
Sheets -> Validacion -> Siesa HUB -> Recibos de caja / Clientes -> Trazabilidad
```

## Estado QA validado

El 2026-09-09 se ejecuto una prueba real en QA con respuesta exitosa de Siesa y verificacion visual en ERP: recibo `RC-00000006`, cliente `1000456076`, fecha `2026-06-30`, valor `$1,000`, caja `01`, medio `EFE-EFECTIVO`.

Esta version deja probado el envio de recibo de caja. Para produccion falta confirmar con Siesa la parametrizacion bancaria de transferencia/consignacion y cerrar el ruteo de las 4 fuentes Alegra/Make.
## QA y paso a produccion

Checklist minimo:

- Confirmar con Siesa el contrato JSON exacto del conector `142888 - API_v1_ReciboCaja`.
- Ajustar `config/siesa_recibo_caja_mapping.json` a los nombres/codigos exigidos por el conector.
- Ejecutar `sync --dry-run` con muestra real de la hoja.
- Ejecutar en QA con 1 pago, verificar recibo de caja en el modulo operativo/financiero de Siesa.
- Ejecutar lote QA pequeno y comparar total, tercero, fecha, cuenta, medio de pago, concepto y centro de costo.
- Activar produccion solo despues de verificar trazabilidad: `externalReference`, respuesta del HUB y numero/documento creado.

## Pruebas

```powershell
python -m unittest discover -s tests
```
