# Flujo equivalente a Alegra

## Objetivo

Cuando una fila nueva llegue a Google Sheets, el proceso debe tomarla, validarla, crear el recibo de caja de cliente en Siesa y dejar trazabilidad para no procesarla dos veces.

## Modulo Siesa confirmado

La captura de Siesa Cloud SBS para `ALIANZA JURIDICA AVANZAR SAS` confirma el modulo operativo destino:

```text
Financiero > Cuentas x cobrar > Recibos de caja > Clientes
```

Esto alinea el desarrollo con el conector `142888 - API_v1_ReciboCaja`. En este flujo, la fila de Sheets no debe crear una factura de venta; debe registrar el pago del cliente como recibo de caja en cuentas por cobrar.

## Componentes necesarios

| Componente | Necesario | Uso |
| --- | --- | --- |
| Visual Avanzar | Si | Panel interno para seleccionar compania/modulo, revisar estados y activar envios. |
| Google Sheets | Si | Bandeja de entrada con la estructura ya usada por Alegra. |
| PowerShell | Si | Ejecuta el sincronizador manualmente o por tarea programada. |
| Python `siesa_payments` | Si | Lee, valida, mapea y envia a Siesa HUB. |
| Credenciales Siesa HUB | Si | Token, host QA/prod y path real del conector. |
| Contrato del conector | Si | Define el JSON final que acepta Siesa. |
| Catalogos Siesa | Si | Tipo documento, caja, moneda, concepto flujo efectivo, medio pago y centro de costo. |
| IA de Alegra | Solo si aplica | Si hoy esa IA limpia/extrrae datos antes de escribir en Sheets, se mantiene como paso previo. No deberia ser necesaria para enviar a Siesa si la hoja ya queda normalizada. |

## Secuencia operativa

1. La automatizacion actual escribe la fila en Sheets.
2. Windows Task Scheduler ejecuta `scripts/Invoke-SiesaPaymentSync.ps1`.
3. El sincronizador lee la pestaña por URL CSV o un CSV exportado.
4. Se validan campos obligatorios y tipo de transaccion `Ingreso`.
5. Se genera `externalReference` para idempotencia.
6. Se envia el payload a `142888 - API_v1_ReciboCaja`.
7. Se guarda auditoria en `logs/siesa_payments.jsonl`.
8. Se guarda estado en `.state/siesa_payments_state.json` para evitar duplicados.

## Punto pendiente critico

Falta abrir `Clientes` en Siesa y capturar los campos obligatorios de la pantalla o el contrato JSON del HUB. Con eso se ajusta `config/siesa_recibo_caja_mapping.json` para que el payload replique exactamente la captura manual.

## Comandos

Dry-run QA:

```powershell
.\scripts\Invoke-SiesaPaymentSync.ps1 -Environment qa -InputCsv .\samples\alegra_payments.csv
```

Envio QA:

```powershell
.\scripts\Invoke-SiesaPaymentSync.ps1 -Environment qa -InputCsv .\samples\alegra_payments.csv -Send
```

Registrar tarea cada 5 minutos en QA:

```powershell
.\scripts\Register-SiesaPaymentSyncTask.ps1 -Environment qa -EveryMinutes 5 -TaskName SiesaPaymentSyncQA
```

## Siguiente fase: APIs

1. Sacar o confirmar endpoint base de Siesa HUB QA.
2. Validar autenticacion y permisos del conector `142888`.
3. Obtener contrato JSON exacto de `API_v1_ReciboCaja`.
4. Ajustar `config/siesa_recibo_caja_mapping.json`.
5. Conectar la visual con el backend para listar filas, validar y enviar.
