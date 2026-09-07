# Revision documentacion Siesa

Fecha: 2026-09-04

## Fuentes revisadas

- Siesa HUB: https://www.siesa.com/siesa-hub
- Guia Modulo de Conectividad / Gestor de Integraciones: https://interfaces-y-soluciones-interno.github.io/Documentacion/si_mc_guia.html
- Manuales soporte Siesa: https://www.siesacustomersupport.com/manuales-3/

## Hallazgos aplicables

- Siesa HUB funciona como capa centralizada de APIs para conectar el ERP con sistemas externos.
- El HUB/Gestor maneja seguridad, gobierno, trazabilidad, reportes y limites de consumo.
- Los conectores del Gestor de Integraciones se usan para importar informacion al ERP.
- El Documentador del Gestor permite ver guia y anexo de cada conector.
- Para consumir un conector se requiere un request tipo POST.
- La guia del conector entrega:
  - Base URL / Request URL;
  - headers `Connikey` y `Connitoken`;
  - params `idCompania`, `idDocumento`, `nombreDocumento`;
  - Body JSON con secciones como `Inicial`, seccion funcional y `Final`.
- La seccion/anexo del conector funciona como diccionario de datos: tipo, obligatoriedad, tamano, observaciones y valores posibles.

## Decision tecnica

El proyecto no debe enviar un JSON generico propio. Debe copiar el Body del Documentador del conector `142888 - API_v1_ReciboCaja` y completar ese contrato con datos de Google Sheets.

Por eso se adapto el motor para:

- configurar headers `Connikey` y `Connitoken`;
- configurar params del conector;
- construir payloads por secciones;
- mantener el mapeo en `config/siesa_recibo_caja_mapping.json`;
- permitir dry-run antes de enviar a QA.

## Pendiente del cliente/Siesa

Entrar al Gestor de Integraciones QA y copiar del conector `142888 - API_v1_ReciboCaja`:

- Request URL;
- `Connikey`;
- `Connitoken`;
- `idCompania`;
- `idDocumento`;
- `nombreDocumento`;
- Body vacio;
- anexo/diccionario de campos.

## Captura operativa del contrato

1. Copiar el Body JSON exacto del Documentador.
2. Guardarlo localmente como `config/siesa_recibo_caja_contract.json`.
3. Compararlo contra el mapeo actual:

```powershell
python -m siesa_payments.cli inspect-contract --contract-file config/siesa_recibo_caja_contract.json
```

El comando devuelve:

- `missing_in_mapping`: campos que existen en Siesa y aun no estan mapeados.
- `not_in_contract`: campos provisionales locales que no aparecen en el Body real.

No guardar `Connikey`, `Connitoken` ni URLs privadas dentro de archivos versionados. Esos valores deben quedar en `.env` o variables de entorno.
