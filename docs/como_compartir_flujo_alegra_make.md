# Como compartir el flujo Alegra/Make

Para replicar el comportamiento actual de Alegra en Siesa necesito ver el escenario de Make, porque ahi viven las rutas, filtros y condicionales.

## Opcion ideal

Exportar el blueprint del escenario:

1. Abrir el escenario en Make.
2. Menu de tres puntos.
3. `Export Blueprint`.
4. Guardar el `.json`.
5. Ponerlo en este repo dentro de `references/make/`.

Con ese JSON puedo leer:

- modulos usados;
- rutas del router;
- filtros/condiciones;
- transformaciones de campos;
- webhooks;
- llamadas HTTP;
- manejo de errores;
- datos que se escriben o leen de Google Sheets.

## Opcion alternativa

Si no se puede exportar, sirven capturas de:

- pantalla completa del escenario;
- cada router abierto;
- cada filtro/condicion;
- modulo que lee o recibe datos de Sheets;
- modulo HTTP/API que envia a Alegra;
- mapeo de campos del modulo final;
- manejo de errores o reintentos.

## Datos que no deben enviarse en capturas

- tokens;
- passwords;
- headers secretos;
- URLs con credenciales;
- llaves privadas.

Si aparecen, se pueden tapar antes de compartir. Lo importante son nombres de campos, condiciones y estructura del flujo.
