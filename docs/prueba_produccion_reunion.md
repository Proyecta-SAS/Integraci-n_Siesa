# Prueba controlada en produccion

Objetivo: crear un recibo de caja real en Siesa produccion con una fila controlada de Google Sheets, validando trazabilidad antes de automatizar lotes.

## Antes de la reunion

1. Confirmar que el acceso usado es Local/produccion, no QA.
2. Tener la Request URL productiva del conector `142888 - API_v1_ReciboCaja` sin placeholders.
3. Tener `Connikey` y `Connitoken` productivos.
4. Confirmar `idCompania`, `idDocumento=142888` y `nombreDocumento=API_v1_ReciboCaja`.
5. Confirmar con contabilidad los codigos productivos:
   - C.O. del recibo.
   - Tipo documento `RC`.
   - Caja.
   - Cobrador.
   - U.N.
   - Flujo efectivo.
   - Medio de pago.
   - Auxiliar de otros ingresos `28050505`.
6. Mantener `SIESA_ALLOW_SEND=false` mientras se valida configuracion y payload.

## Variables productivas esperadas

```text
SIESA_ENV=prod
SIESA_DRY_RUN=true
SIESA_ALLOW_SEND=false
SIESA_SEND_COOLDOWN_MINUTES=15
SIESA_CONNECTOR_URL=<Request URL Local/produccion del conector 142888 ya resuelta>
# Alternativa si Siesa entrega base URL + ecosistema:
SIESA_BASE_URL=<baseUrl Local/produccion sin placeholders>
SIESA_ID_ECOSISTEMA=<idEcoSistema productivo>
SIESA_CONN_KEY=<Connikey produccion>
SIESA_CONN_TOKEN=<Connitoken produccion>
SIESA_ID_COMPANIA=<idCompania produccion>
SIESA_F_CIA=<compania ERP>
SIESA_ID_CO=<centro operacion recibo>
SIESA_TIPO_DOCUMENTO=RC
SIESA_ID_CAJA=<caja productiva>
SIESA_ID_COBRADOR=<cobrador productivo>
SIESA_ID_UN=<unidad negocio>
SIESA_ID_FE=<flujo efectivo>
SIESA_SHEETS_CSV_URL=<export CSV hoja productiva>
SIESA_RECIBO_FLUJO=otros_ingresos
SIESA_AUXILIAR_OTRO_ING=28050505
```

Segun la validacion de contabilidad, el recibo debe crearse con tipo `RC` y como otros ingresos usando el auxiliar `28050505`. En este flujo no se debe cruzar cartera `FVE`.

La hoja tambien tiene estas columnas de trazabilidad listas para uso operativo:

```text
Estado Siesa
Recibo Siesa
Fecha envio
Respuesta Siesa
Error Siesa
```

Nota tecnica: Railway lee la hoja por export CSV. Para actualizar esas columnas automaticamente despues del envio hace falta conectar una credencial de escritura de Google Sheets o un webhook de Apps Script.

## Secuencia de prueba

1. Abrir la app de Railway.
2. Presionar `Revisar Sheets`.
3. Confirmar que la fila de prueba sale como `Lista`, con aplicacion `Otro ingreso 28050505`.
4. Presionar `Preflight`.
5. Confirmar:
   - `ready=true`
   - `send_unlocked=false`
   - `invalid_rows=[]`
   - `missing_cross_rows=[]` o cruce de cartera no aplica.
   - `ready_rows=1`
6. Presionar `Probar QA` o endpoint dry-run equivalente ya apuntando a produccion con `SIESA_DRY_RUN=true`.
7. Revisar el payload en logs y confirmar tercero, fecha, valor, caja, medio de pago y auxiliar `28050505`.
8. Solo durante la ventana autorizada, cambiar `SIESA_ALLOW_SEND=true`.
9. Presionar `Enviar QA` una sola vez, aunque el ambiente sea productivo hasta renombrar el boton.
10. Volver a dejar `SIESA_ALLOW_SEND=false`.
11. Consultar en Siesa:
    - Recibo de caja creado.
    - Tercero correcto.
    - Valor correcto.
    - Auxiliar de otros ingresos correcto.
    - Movimiento de caja correcto.

Despues de un envio real, el sistema bloquea otro envio durante 15 minutos. El bloqueo queda registrado en el estado local de la app y se ve en `/api/status` como `cooldown.cooldown_active=true`.

## Criterio de exito

La prueba queda aprobada si Siesa responde transaccion exitosa, el recibo aparece en `Financiero > Cuentas x cobrar > Recibos de caja > Otros ingresos`, el movimiento de caja refleja el valor correcto y la app conserva trazabilidad del intento.

## Criterios de bloqueo

- La Request URL sigue apuntando a QA.
- La Request URL conserva `{baseUrl}` o `{idEcoSistema}` sin reemplazar.
- Faltan headers productivos.
- El auxiliar `28050505` no existe o no esta habilitado en productivo.
- El envio anterior fue hace menos de 15 minutos.
- Contabilidad no confirma caja, cobrador, U.N. o flujo efectivo productivo.
