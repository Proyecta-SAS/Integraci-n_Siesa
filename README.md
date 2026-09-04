# Integracion Siesa - Recibos de Caja

Servicio para registrar automaticamente en Siesa HUB los pagos de clientes que hoy siguen la estructura operativa usada en las hojas de Alegra. El destino operativo confirmado es `Financiero > Cuentas x cobrar > Recibos de caja > Clientes`.

## Hallazgos de la hoja Alegra

Se revisaron hojas nativas de Google Sheets encontradas en Drive:

- `ALEGRA - LIDERA`, pestaña `DB`.
- `ALEGRA - ALIANZA JURIDICA AVANZAR`, pestaña `Ingreso / Egreso`.
- `ALEGRA - PROSPERAR`, pestaña `db`.

La estructura de entrada confirmada usa los encabezados `A1:V1`:

```text
Cuenta bancaria, Fecha, Contacto, Tipo de Transaccion, Metodo de pago,
Centro de costos, Concepto, Cantidad, Valor, Nota, Observaciones,
Cliente, Tipo, Tipo de identificacion, Numero de identificacion,
Nombre, Apellido, Tipo de persona, Responsabilidad tributaria,
Municipio / Departamento, Direccion
```

La pestaña `ID` funciona como catalogo para Alegra. Para Siesa se deja el mapeo en `config/siesa_recibo_caja_mapping.json` porque los codigos contables/documentales del conector 142888 dependen de la parametrizacion del ERP.

## Flujo

1. Leer filas desde CSV local o export CSV de Google Sheets.
2. Normalizar encabezados y valores.
3. Validar que la fila represente un pago de cliente registrable.
4. Construir payload para `142888 - API_v1_ReciboCaja`.
5. Enviar a Siesa HUB en QA o produccion.
6. Registrar trazabilidad local en JSONL y deduplicar por llave idempotente.

## Configuracion

Copie `.env.example` a `.env` o exporte variables equivalentes.

Variables principales:

- `SIESA_HUB_BASE_URL`: host QA o productivo de Siesa HUB.
- `SIESA_HUB_TOKEN`: token de integracion.
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

Validar metadata del conector, si el HUB expone el endpoint configurado:

```powershell
python -m siesa_payments.cli validate-connector
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
