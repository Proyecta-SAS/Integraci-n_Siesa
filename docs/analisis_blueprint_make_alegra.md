# Analisis blueprint Make/Alegra - Alianza Juridica Avanzar

## Archivo revisado

- Fuente local: `C:\Users\avzte\Downloads\Alianza Juridica Avanzar.blueprint.json`
- Copia versionada: `references/make/alianza_juridica_avanzar.blueprint.json`
- Escenario: `Alianza Juridica Avanzar`
- Google Sheet: `ALEGRA - ALIANZA JURIDICA AVANZAR`
- Spreadsheet ID: `1TuXSZESNm1xJGJvXLMKTq2bAY1ZvmCl6n8Aez1FRVp8`
- Pestaña operativa: `Ingreso / Egreso`

## Estructura Make

El escenario tiene tres bloques principales:

1. Webhook personalizado.
2. Busqueda de filas en Google Sheets.
3. Router principal con rutas para recibos y creacion de clientes/proveedores.

El filtro inicial solo procesa datos cuando el webhook trae:

```text
activador == ON
```

La busqueda en Sheets lee hasta 1000 filas y ordena por `__ROW_NUMBER__` descendente.

## Rutas operativas

| Ruta | Condicion Make | Accion Alegra actual | Equivalente Siesa |
| --- | --- | --- | --- |
| `existing_contact_receipt` | `Cliente` no contiene `CREAR` | Crea pago usando contacto mapeado | Crear recibo de caja contra tercero existente |
| `create_person_contact_receipt` | `Cliente` contiene `CREAR` y documento CC/persona natural | Crea contacto persona natural y luego pago | Crear/validar tercero persona natural y luego recibo |
| `create_legal_contact_receipt` | `Cliente` contiene `CREAR` y documento NIT/persona juridica | Crea contacto juridico y luego pago | Crear/validar tercero juridico y luego recibo |
| `create_client_provider_receipt` | `Cliente / Proveedor` | Crea contacto con doble rol y luego pago | Crear/validar tercero con roles requeridos y luego recibo |

Despues de un envio exitoso, Make elimina la fila procesada de la hoja. En nuestro backend no se elimina por defecto; se registra estado en `.state/siesa_payments_state.json` y auditoria en `logs/siesa_payments.jsonl` para trazabilidad.

## Campos base detectados

| Indice Make | Campo normalizado |
| --- | --- |
| `0` | `bank_account` |
| `1` | `payment_date` |
| `2` | `contact` |
| `3` | `transaction_type` |
| `4` | `payment_method` |
| `5` | `cost_center` |
| `6` | `concept` |
| `7` | `quantity` |
| `8` | `amount` |
| `9` | `note` |
| `10` | `observations` |
| `12` | `customer_action` |
| `13` | `person_type` |
| `14` | `identity_type` |
| `15` | `identity_number` |
| `16` | `first_name` |
| `17` | `last_name` |
| `18` | `tax_person_type` |
| `19` | `tax_responsibility` |
| `20` | `municipality_department` |
| `21` | `address` |

## Catalogos extraidos

Se agrego `scripts/extract_make_blueprint.py` para convertir formulas largas de Make en JSON versionable.

Salidas generadas:

- `config/alegra_flow_rules.json`: rutas, condiciones y mapas pequeños.
- `config/alegra_catalogs_from_make.json`: catalogos grandes.
- `docs/make_blueprint_inventory.json`: inventario de modulos del escenario.

Conteos extraidos:

- Contactos Alegra: `1713`.
- Conceptos/cuentas Alegra: `1522`.
- Cuentas bancarias: `9`.
- Metodos de pago: `6`.
- Responsabilidades tributarias: `6`.

## Decision para Siesa

El flujo Siesa debe conservar la misma decision operativa que Make:

1. Si `Cliente` contiene `CREAR`, se debe crear o validar el tercero antes del recibo.
2. Si `Cliente` no contiene `CREAR`, se debe ubicar un tercero existente.
3. En ambos casos, el destino final es `142888 - API_v1_ReciboCaja`.
4. Falta confirmar con el Documentador de Siesa si el conector `ReciboCaja` permite crear el tercero dentro del mismo payload o si se requiere un conector previo de terceros/clientes.

## Pendiente critico

El blueprint resuelve la logica de negocio, pero los IDs de Alegra no sirven directamente para Siesa. Hay que crear equivalencias Siesa para:

- bancos/cajas;
- terceros;
- conceptos/cuentas;
- centros de costo;
- medios de pago;
- tipo de documento de recibo.
