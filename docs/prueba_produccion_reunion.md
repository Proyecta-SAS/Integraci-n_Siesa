# Prueba controlada en produccion

Objetivo: crear un recibo de caja real en Siesa produccion con una fila controlada de Google Sheets, validando trazabilidad antes de automatizar lotes.

## Antes de la reunion

1. Confirmar que el acceso usado es CORE/produccion, no QA.
2. Tener la Request URL productiva del conector `142888 - API_v1_ReciboCaja`.
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
   - Documento cruce de cartera.
6. Mantener `SIESA_ALLOW_SEND=false` mientras se valida configuracion y payload.

## Variables productivas esperadas

```text
SIESA_ENV=prod
SIESA_DRY_RUN=true
SIESA_ALLOW_SEND=false
SIESA_CONNECTOR_URL=<Request URL CORE del conector 142888>
SIESA_CONN_KEY=<Connikey CORE>
SIESA_CONN_TOKEN=<Connitoken CORE>
SIESA_ID_COMPANIA=<idCompania CORE>
SIESA_F_CIA=<compania ERP>
SIESA_ID_CO=<centro operacion recibo>
SIESA_TIPO_DOCUMENTO=RC
SIESA_ID_CAJA=<caja productiva>
SIESA_ID_COBRADOR=<cobrador productivo>
SIESA_ID_UN=<unidad negocio>
SIESA_ID_FE=<flujo efectivo>
SIESA_SHEETS_CSV_URL=<export CSV hoja productiva>
```

Los datos del documento aplicado deben venir por fila en Sheets:

```text
Documento cruce
C.O. cruce
U.N. cruce
Sucursal cruce
Auxiliar cruce
```

## Secuencia de prueba

1. Abrir la app de Railway.
2. Presionar `Revisar Sheets`.
3. Confirmar que la fila de prueba sale como `Lista`, con `cross_source=sheet`.
4. Presionar `Preflight`.
5. Confirmar:
   - `ready=true`
   - `send_unlocked=false`
   - `invalid_rows=[]`
   - `missing_cross_rows=[]`
   - `ready_rows=1`
6. Presionar `Probar QA` o endpoint dry-run equivalente ya apuntando a produccion con `SIESA_DRY_RUN=true`.
7. Revisar el payload en logs y confirmar tercero, fecha, valor, caja, medio de pago y documento cruce.
8. Solo durante la ventana autorizada, cambiar `SIESA_ALLOW_SEND=true`.
9. Presionar `Enviar QA` una sola vez, aunque el ambiente sea productivo hasta renombrar el boton.
10. Volver a dejar `SIESA_ALLOW_SEND=false`.
11. Consultar en Siesa:
    - Recibo de caja creado.
    - Tercero correcto.
    - Valor correcto.
    - Documento aplicado correcto.
    - Movimiento de caja correcto.

## Criterio de exito

La prueba queda aprobada si Siesa responde transaccion exitosa, el recibo aparece en `Financiero > Cuentas x cobrar > Recibos de caja > Clientes`, el movimiento de caja refleja el valor correcto y la app conserva trazabilidad del intento.

## Criterios de bloqueo

- La Request URL sigue apuntando a QA.
- Faltan headers productivos.
- La fila no trae documento cruce.
- El documento cruce no tiene saldo disponible.
- El valor a aplicar supera el saldo del documento.
- Contabilidad no confirma caja, cobrador, U.N. o flujo efectivo productivo.
