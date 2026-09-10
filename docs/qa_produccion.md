# Plan QA y produccion

## QA

1. Confirmar URL QA, `Connikey`, `Connitoken`, `idCompania`, `idDocumento` y `nombreDocumento` del conector 142888.
2. Ejecutar `python -m siesa_payments.cli validate-connector` para validar que la configuracion minima esta cargada.
3. Exportar una muestra de la hoja Alegra a CSV o configurar `SIESA_SHEETS_CSV_URL`.
4. Ejecutar `python -m siesa_payments.cli sync --input-csv <archivo.csv> --dry-run`.
5. Revisar `logs/siesa_payments.jsonl` y comparar payload contra el Body real copiado desde el Documentador de Siesa.
6. Enviar un solo pago con `--send` y confirmar en Siesa:
   - recibo de caja creado;
   - tercero correcto;
   - fecha y valor correctos;
   - caja, moneda, concepto de flujo efectivo y medio de pago correctos;
   - numero/documento devuelto por HUB guardado en trazabilidad.
7. Ejecutar lote pequeno en QA y conciliar total de registros y sumatoria de valores.

## Produccion

1. Usar un archivo de estado independiente para produccion.
2. Activar `SIESA_ENV=prod` y `SIESA_DRY_RUN=false`.
3. Ejecutar inicialmente con una ventana controlada de pagos.
4. Conservar `logs/siesa_payments.jsonl` como auditoria tecnica y cruzarlo con el reporte de Siesa HUB.
5. Programar la tarea solo despues de validar que la deduplicacion evita reenvios del mismo pago.
## Evidencia QA - 2026-09-09

Prueba enviada contra `implementacion02app6.siesacloud.com` usando Apigee QA y el conector `142888 - API_v1_ReciboCaja`.

- Archivo: `samples/siesa_qa_vargas.csv`.
- Cliente: `1000456076 - VARGAS LUQUE JEYDY VANESSA`.
- Documento aplicado: `FVE-00000001`.
- Fecha del recibo: `2026-06-30`.
- Valor enviado: `$1,000`.
- Respuesta API: `codigo=0`, `mensaje=Transaccion Exitosa`, `detalle=Importacion exitosa`.
- Verificacion ERP: `Consulta de movimiento de caja`, documento `RC-00000006`, medio `EFE-EFECTIVO`, caja `01`, debito `$1,000.00`.

Pendiente antes de produccion:

- Confirmar con Siesa si transferencia/consignacion debe quedar como `CG1` y cuales son `F358_ID_BANCO`, `F358_NRO_CUENTA` y `f358_docto_banco_cg` validos.
- Validar el ruteo completo de las 4 fuentes Alegra/Make antes de automatizar lotes reales.

## Evidencia QA desde Google Sheets - 2026-09-10

Prueba enviada contra Apigee QA leyendo la fila real de `Ingreso / Egreso` en Google Sheets.

- Cliente: `1000033853 - LANCHEROS PEÑA JUAN CAMILO`.
- Documento aplicado: `FVE-00000006-00`.
- Fecha del recibo: `2026-06-30`.
- Valor enviado: `$1,000`.
- Respuesta API: `codigo=0`, `mensaje=Transaccion Exitosa`, `detalle=Importacion exitosa`.
- Verificacion ERP: `Consulta de movimiento de caja`, documento `RC-00000007`, medio `EFE-EFECTIVO`, caja `01`, debito `$1,000.00`.

## Produccion Siesa

Siesa documenta dos accesos del Gestor de Integraciones: QA para pruebas y CORE para produccion. El paso productivo es viable cuando Siesa/Avanzar entregue la Request URL de CORE/produccion del conector `142888 - API_v1_ReciboCaja`, headers productivos `Connikey`/`Connitoken` y confirme que el documento `RC`, caja, cobrador, unidad de negocio, flujo efectivo y medio de pago existen igual en productivo.

No se debe reutilizar el endpoint ni token QA en produccion. Antes del primer envio real se debe ejecutar un dry-run con filas productivas, validar que cada fila traiga documento cruce desde Sheets y activar deduplicacion con estado persistente.
