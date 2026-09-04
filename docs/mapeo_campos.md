# Mapeo de pagos Alegra a Siesa ReciboCaja

Modulo destino confirmado:

```text
Financiero > Cuentas x cobrar > Recibos de caja > Clientes
```

## Entrada confirmada en Google Sheets

Las hojas `ALEGRA - LIDERA`, `ALEGRA - ALIANZA JURIDICA AVANZAR` y `ALEGRA - PROSPERAR` comparten el encabezado base:

| Campo Sheets | Campo canonico | Uso |
| --- | --- | --- |
| Cuenta bancaria | `bank_account` | Caja/cuenta de recaudo. |
| Fecha | `payment_date` | Fecha del recibo de caja. |
| Tipo de Transaccion | `transaction_type` | Debe ser `Ingreso` para pagos de clientes. |
| Metodo de pago | `payment_method` | Medio de pago enviado a Siesa. |
| Centro de costos | `cost_center` | Centro de costo operativo, si aplica. |
| Concepto | `concept` | Concepto contable/comercial del pago. |
| Cantidad | `quantity` | Cantidad del detalle. |
| Valor | `amount` | Valor del pago, mayor que cero. |
| Nota | `note` | Referencia visible del pago. |
| Observaciones | `observations` | Texto de soporte/trazabilidad. |
| Tipo de identificacion | `identity_type` | Tipo de documento del tercero. |
| Numero de identificacion | `identity_number` | Identificacion del cliente/tercero. |
| Nombre / Apellido | `first_name` / `last_name` | Nombre del tercero. |
| Municipio / Departamento | `municipality_department` | Ubicacion del tercero, si aplica. |
| Direccion | `address` | Direccion del tercero, si aplica. |

## Parametros Siesa requeridos para QA

La parametrizacion de recibos de caja de Siesa indica que varios valores son obligatorios y dependen del ERP del cliente. Por eso no se infieren desde la hoja y se cargan por ambiente:

| Variable | Descripcion |
| --- | --- |
| `SIESA_TIPO_DOCUMENTO` | Tipo de documento que pasara al ERP, usualmente un recibo de caja. |
| `SIESA_ESTADO_DOCUMENTO` | Estado permitido para sincronizacion; `1` representa aprobado. |
| `SIESA_ID_CAJA` | Caja a la cual se asociara el recibo. |
| `SIESA_MONEDA_RECAUDO` | Moneda del recaudo. |
| `SIESA_MONEDA_APLICACION` | Moneda de aplicacion contable. |
| `SIESA_CONCEPTO_FLUJO_EFECTIVO` | Concepto de flujo de efectivo para recaudos o anticipos. |

## Validaciones implementadas

- La transaccion debe ser `Ingreso`.
- `Valor` y `Cantidad` deben ser mayores que cero.
- Se requieren cuenta bancaria, metodo de pago, concepto, tipo/numero de identificacion y nombre.
- Fechas aceptadas: `dd/mm/yyyy`, `yyyy-mm-dd`, `dd-mm-yyyy`, `dd/mm/yy`.
- Montos aceptan formato colombiano (`480.000`) y decimal (`480000.50`).
- Cada pago genera `externalReference` e `Idempotency-Key` para evitar duplicados.

## Ajuste del contrato final

`config/siesa_recibo_caja_mapping.json` define el payload enviado a Siesa HUB. Cuando Siesa entregue el contrato exacto del conector `142888 - API_v1_ReciboCaja`, solo debe ajustarse `payload_template`; la lectura y validacion de la hoja no cambian.
