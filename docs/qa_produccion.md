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
