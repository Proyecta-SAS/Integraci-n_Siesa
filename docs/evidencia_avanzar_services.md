# Evidencias de integración Avanzar Services

Fecha: 2026-11-18, zona America/Bogota. Entrega en la rama `feat/avanzar-services-integration`, basada en `6e9660d12596a922eab4bf7fbebbfbf90c80062f`. Consultar el historial de la rama para el commit de entrega. No hay revisión desplegada de estos cambios. No se incluyen contraseñas, cookies, tokens o secretos.

## Producción existente

Aplicación: `https://siesa.avanzarsoluciones.com/`. Railway, entorno production, servicio `e4702d2c-5e42-47f7-b054-a6043b2ca180`. Último despliegue SUCCESS consultado: `6116a6d8-ac73-4d68-9071-fa6f82298e3f`, commit base anterior, región `us-east4-eqdc4a`.

| Escenario | Resultado observado |
|---|---|
| Inventario conectado de servicios y configuración | Un entorno production, PostgreSQL privado y volumen `/data`; sin variables Avanzar Services |
| Crear cuenta solicitada por el propietario | `superadmin@avanzarsoluciones.com`: consola privada SSH devolvió «Cuenta creada» usando `python -m siesa_payments.manage create-user` ya desplegado |
| Login local de la cuenta | POST `/api/auth/login`: HTTP 200 |
| Sesión local | GET `/api/auth/me`: HTTP 200, correo coincide |
| Logout con CSRF | POST `/api/auth/logout`: HTTP 200 |
| Revocación posterior | GET `/api/auth/me`: HTTP 401 |
| Seguridad de la verificación | Contraseña introducida en prompt oculto; no quedó en archivos. No se ejecutaron envíos Siesa/Alegra ni se desplegó código |

El nombre del correo no representa un perfil administrativo nuevo. Conserva los permisos locales existentes. La cuenta corporativa de Keycloak y la autorización del portal no se han creado ni verificado.

## Proveedor corporativo

GET público al discovery proporcionado: respuesta JSON accesible, emisor exacto `https://keycloak-dev-375092879765.us-central1.run.app/realms/avanzar-dev`. Declara `code`, `S256`, `RS256` y `client_secret_basic`, con endpoints del mismo host. Esto prueba disponibilidad/metadatos del proveedor; no prueba registro del cliente, claims del usuario, credenciales, reutilización de sesión ni recorrido E2E. Los grants deshabilitados deben verificarse en el cliente exclusivo, no inferirse del listado general del realm.

## Pruebas locales automatizadas

Entorno: Windows, Python 3.14.6, SQLite temporal aislado, Authlib 1.9.9, joserfc 1.8.0, requests 2.34.2. Proveedor HTTP simulado con ID tokens firmados mediante claves RSA reales de prueba. No se utilizan credenciales de producción.

Comandos reproducibles (con dependencias de `requirements.txt` instaladas):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/web_app.test.cjs tests/sheets_writeback.test.cjs
git diff --check
```

Resultado: 107 pruebas Python y 13 pruebas JavaScript aprobadas; revisión de espacios de diff aprobada. Las suites se ejecutaron nuevamente el 18 de noviembre de 2026 antes de publicar la rama, con el mismo resultado. La cobertura nueva está en `tests/test_avanzar.py` y conserva las pruebas existentes de autenticación, negocio, jobs, histórico y frontend.

| Escenario | Resultado / evidencia local |
|---|---|
| Flujo backend de código, S256, basic, callback y sesión | Aprobado contra proveedor simulado; se inspecciona verifier, challenge, redirect_uri, scope, grant y header basic |
| Firma y algoritmo | Firma de otra clave y HS256 rechazados; RS256 válido aceptado |
| Claims | Emisor, audiencia, azp, nonce, sub, iat, exp, nbf, correo/dominio/verificación inválidos o ausentes rechazados; texto `"true"` rechazado |
| Solicitud original | CSRF, state, cookie inicial, vencimiento, parámetros inesperados/duplicados y callback repetido rechazados |
| PKCE inválido | Proveedor simulado devuelve invalid_grant; no se crea sesión |
| Límites del proveedor | Respuesta mayor que 256 KiB y redirección HTTP rechazadas |
| Vínculos | Primer enlace por correo; posteriores por emisor/sub aunque cambie correo; conflicto de sujeto no sobrescribe cuenta; inactivo/inexistente rechazados |
| Sesión | Persistencia en otra instancia Auth/OIDC sobre misma base; renovación de token/CSRF y revocación de sesión anterior; baja local impide usar sesión |
| Aprovisionamiento | 201 inicial, 200 repetición con mismo ID, 409 datos/perfil/teléfono/estado distinto; cuenta sin contraseña local utilizable |
| Concurrencia | Cuatro solicitudes al mismo correo crean una cuenta y devuelven el mismo ID |
| Errores de API | 401, 405, 413, 415, 422, 503 y 500 comprobados; SQL/trazas y secretos no salen en errores/auditoría |
| Protección de aplicación | Acceso directo sin sesión protegido; perfil consulta no puede enviar ni activar; logout exige CSRF |
| Incrustación | CSP exacta, sin X-Frame-Options contradictorio en servidor local, cookies Secure/HttpOnly/SameSite=None, recuperación top-level si falta sesión |
| Retornos | URL externa por parámetro rechazada; sesión vigente retorna solo al portal configurado |
| Regresiones | Tests existentes de Siesa, Alegra, ledger, jobs, respuestas, Sheets y frontend aprobados |

## Aceptación pendiente

No se ha desplegado el nuevo código ni conectado el cliente al portal. Por tanto permanecen pendientes, con responsables/condiciones en la ficha:

- Inicio real desde Avanzar, sesión previa de Keycloak y autorización de apertura.
- Callback real firmado por Keycloak, correo verificado y vínculo con cuenta local autorizada.
- Retorno real al portal e incrustación con cookies del navegador.
- Formularios, navegación, descargas, escritorio/móvil y funciones permitidas/no permitidas dentro del portal.
- Expiración/logout/desactivación coordinados entre aplicación, Keycloak y portal.
- Aprovisionamiento real desde backend de Avanzar, catálogo autorizado y rotación de secretos.
- Migración/concurrencia en PostgreSQL del despliegue y persistencia tras cambio de instancia.
- Revisión con tráfico, configuración/secrets y aceptación repetida después de un segundo despliegue.

No se considera completada la integración de extremo a extremo con estas pruebas locales.
