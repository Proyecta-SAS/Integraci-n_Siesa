# Changelog

## 0.13.0 - 2026-09-11

- Ajusta el cruce operativo solicitado en reunion contable: el tipo de documento enviado a Siesa queda fijo como `RC`.
- Fija el auxiliar de documento aplicado como `28050505`.
- La visual deja de exigir tipo de documento cruce y auxiliar desde Sheets para este flujo.
- Mantiene el consecutivo, cuota, C.O., U.N. y sucursal desde la fila del Google Sheets.

## 0.9.0 - 2026-09-10

- Agrega cruce dinamico de cartera desde columnas de Google Sheets.
- Permite `Documento cruce` completo como `FVE-00000006-00` o columnas separadas de tipo, consecutivo y cuota.
- Mantiene variables `SIESA_*` como respaldo para QA cuando el Sheets todavia no trae cruce por fila.
- Muestra en la visual si el cruce sale de Sheets, de `.env` o esta incompleto.
- Prepara despliegue Railway con `Procfile` y soporte de puerto dinamico `PORT`.
- Documenta evidencia QA desde Sheets: recibo `RC-00000007`, cliente `1000033853`, valor `$1,000`, fecha `2026-06-30`.

## 0.6.0 - 2026-09-09

- Valida envio real en QA del conector `142888 - API_v1_ReciboCaja` contra Apigee/Siesa.
- Agrega soporte para `client_id`, `client_secret`, `idEcoSistema` y URL completa del conector.
- Ajusta `F_CIA` separado de `idCompania` y agrega seccion `Final` exigida por el contrato Siesa.
- Formatea valores, consecutivos y cuota con los largos fijos requeridos por el Documentador.
- Mapea transferencia/consignacion temporalmente como `EFE` para desbloquear QA mientras Siesa confirma la parametrizacion bancaria `CG1`.
- Deja muestra QA `samples/siesa_qa_vargas.csv` validada en ERP como `RC-00000006` por $1,000 el 2026-06-30.
- Mantiene pendiente productivo el ruteo de las 4 fuentes Alegra/Make y la confirmacion de bancos para consignacion/transferencia.
## 0.2.0 - 2026-09-04

- Ajusta la visual para manejar solo la fuente `ALEGRA - ALIANZA JURIDICA AVANZAR`.
- Elimina selector de multiples companias Alegra de la consola.
- Actualiza documentacion para reflejar un unico Google Sheets operativo.
- Adapta el cliente HTTP al formato Siesa/Connekta con `Connikey`, `Connitoken`, `idCompania`, `idDocumento` y `nombreDocumento`.
- Agrega soporte de payloads por secciones `Inicial`, `ReciboCaja` y `Final`.
- Documenta como compartir el escenario Alegra/Make para replicar rutas, filtros y condicionales.
- Copia y analiza el blueprint Make `Alianza Juridica Avanzar`.
- Extrae reglas, rutas y catalogos Make/Alegra a JSON versionable.
- Agrega clasificacion de ruta operativa en la auditoria del sincronizador.

## 0.1.0 - 2026-09-04

- Crea base del Activador Siesa con identidad visual Avanzar.
- Agrega consola web local para companias, bandeja de pagos, estado API y trazabilidad.
- Implementa sincronizador Python para leer pagos desde CSV/Sheets, validar, mapear y enviar a Siesa HUB.
- Agrega configuracion del conector `142888 - API_v1_ReciboCaja`.
- Agrega scripts PowerShell para ejecucion manual y tarea programada.
- Documenta flujo equivalente a Alegra, mapeo de campos y plan QA/produccion.
- Incluye pruebas unitarias para lectura, validacion, mapeo y envio simulado.
