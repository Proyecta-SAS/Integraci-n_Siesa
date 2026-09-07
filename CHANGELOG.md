# Changelog

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
