# Mapeo de pagos a Siesa ReciboCaja

Modulo destino confirmado:

```text
Financiero > Cuentas x cobrar > Recibos de caja > Clientes
```

## Entrada confirmada en Google Sheets

Fuente operativa revisada:

- Archivo: `ALEGRA - ALIANZA JURIDICA AVANZAR`
- Spreadsheet ID: `1TuXSZESNm1xJGJvXLMKTq2bAY1ZvmCl6n8Aez1FRVp8`
- Pestana operativa: `Ingreso / Egreso`
- Rango de encabezado: `A1:V1`
- Pestana de catalogos/listas: `ID`

Aunque el archivo conserva nombre de Alegra, en esta integracion se usa como bandeja de captura para crear recibos de caja en Siesa.

| Campo Sheets | Campo canonico | Uso |
| --- | --- | --- |
| Cuenta bancaria | `bank_account` | Caja/cuenta de recaudo. |
| Fecha | `payment_date` | Fecha del recibo de caja. |
| Contacto | `contact` | Tercero/contacto existente cuando no se crea uno nuevo. |
| Tipo de Transaccion | `transaction_type` | Debe ser `Ingreso` para pagos de clientes. |
| Metodo de pago | `payment_method` | Medio de pago enviado a Siesa. |
| Centro de costos | `cost_center` | Centro de costo operativo, si aplica. |
| Concepto | `concept` | Concepto contable/comercial del pago. |
| Cantidad | `quantity` | Cantidad del detalle. |
| Valor | `amount` | Valor del pago, mayor que cero. |
| Nota | `note` | Referencia visible del pago. |
| Observaciones | `observations` | Texto de soporte/trazabilidad. |
| Cliente | `customer_action` | Define si se crea tercero (`CREAR`) o se usa contacto existente. |
| Tipo | `person_type` | Rol esperado: cliente, proveedor o cliente/proveedor. |
| Tipo de identificacion | `identity_type` | Tipo de documento del tercero. |
| Numero de identificacion | `identity_number` | Identificacion del cliente/tercero. |
| Nombre / Apellido | `first_name` / `last_name` | Nombre del tercero. |
| Tipo de persona | `tax_person_type` | Natural o juridica cuando aplica. |
| Responsabilidad tributaria | `tax_responsibility` | Regimen/responsabilidad tributaria. |
| Municipio / Departamento | `municipality_department` | Ubicacion del tercero, si aplica. |
| Direccion | `address` | Direccion del tercero, si aplica. |
| Documento cruce | `cross_document` | Documento completo usado como fuente de consecutivo/cuota, por ejemplo `FVE-00000006-00`. En Siesa se envia con tipo fijo `RC`. |
| Tipo docto cruce | `cross_document_type` | Campo historico soportado, pero el payload operativo usa `RC` fijo por definicion contable. |
| Consecutivo cruce | `cross_document_number` | Consecutivo del documento de cartera, por ejemplo `00000006`. |
| Cuota cruce | `cross_installment` | Cuota del documento, por ejemplo `00`. |
| C.O. cruce | `cross_co` | Centro de operacion del documento aplicado. |
| U.N. cruce | `cross_un` | Unidad de negocio del documento aplicado. |
| Sucursal cruce | `cross_branch` | Sucursal del documento aplicado. |
| Auxiliar cruce | `cross_auxiliary` | Campo historico soportado, pero el payload operativo usa `28050505` fijo. |

## Validaciones detectadas en la hoja

- `Cuenta bancaria`: lista desde `ID!B3:B11`.
- `Contacto`: lista desde `ID!S3:S1546`.
- `Tipo de Transaccion`: `Ingreso` o `Egreso`.
- `Metodo de pago`: `Transferencia`, `Efectivo`, `Consinacion`, `Cheque`, `tarjeta de credito`, `tarjeta de debito`.
- `Concepto`: lista desde `ID!H3:H1526`.
- `Cliente`: lista desde `ID!N4`.
- `Tipo`: lista desde `ID!N5:N7`.
- `Tipo de identificacion`: `CC - Cedula de ciudadania` o `NIT - Numero de identificacion tributaria`.
- `Tipo de persona`: lista desde `ID!O3:O4`.
- `Responsabilidad tributaria`: lista desde `ID!P3:P8`.
- `Municipio / Departamento`: lista desde `ID!Q3:Q1112`.

## Parametros Siesa requeridos para QA

La parametrizacion de recibos de caja de Siesa indica que varios valores son obligatorios y dependen del ERP del cliente. Por eso no se infieren desde la hoja y se cargan por ambiente:

| Variable | Descripcion |
| --- | --- |
| `SIESA_TIPO_DOCUMENTO` | Tipo de documento que pasara al ERP, usualmente un recibo de caja. |
| `SIESA_ID_CAJA` | Caja a la cual se asociara el recibo. |
| `SIESA_ID_COMPANIA` | Compania Siesa donde se crea el recibo. |
| `SIESA_ID_DOCUMENTO` | Documento/conector Siesa; por defecto `142888`. |
| `SIESA_NOMBRE_DOCUMENTO` | Nombre del documento; por defecto `API_v1_ReciboCaja`. |

## Validaciones implementadas

- La transaccion debe ser `Ingreso`.
- `Valor` y `Cantidad` deben ser mayores que cero.
- Se requieren cuenta bancaria, metodo de pago, concepto, tipo/numero de identificacion y nombre.
- Fechas aceptadas: `dd/mm/yyyy`, `yyyy-mm-dd`, `dd-mm-yyyy`, `dd/mm/yy`.
- Montos aceptan formato colombiano (`480.000`) y decimal (`480000.50`).
- Cada pago genera `externalReference` e `Idempotency-Key` para evitar duplicados.

## Ajuste del contrato final

`config/siesa_recibo_caja_mapping.json` define el payload enviado a Siesa HUB. El Body real levantado desde el Documentador usa estas secciones:

```json
{
  "Inicial": [{ "F_CIA": "..." }],
  "Caja": [{ "...": "..." }],
  "RCyotrosingresos": [{ "...": "..." }],
  "CxC": [{ "...": "..." }]
}
```

Los campos obligatorios del Body dependen de la parametrizacion de Siesa, especialmente centro de operacion, tipo de documento, caja, moneda, cobrador y documento de CxC a cruzar. Esos valores quedan en variables `SIESA_*` para no amarrar el codigo a una compania o ambiente.

La seccion `CxC` exige datos del documento/factura que recibe el pago: tipo de documento cruce, consecutivo, auxiliar, centro de operacion, unidad de negocio, sucursal y cuota. El mapeo toma primero los valores de cada fila de Sheets y, si vienen vacios, usa las variables `SIESA_*` como respaldo para pruebas QA controladas.
