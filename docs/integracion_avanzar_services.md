# Integración de Siesa y Alegra con Avanzar Services

Estado al 18 de noviembre de 2026: implementación preparada para entrega en la rama `feat/avanzar-services-integration`, con commit y push autorizados por el propietario. No se despliega ni activa la integración en esta entrega; `main` está conectado al despliegue automático de producción en Railway. No se declara aceptado el recorrido real del portal. La única escritura realizada en producción fue crear la cuenta local solicitada; no se ejecutaron activadores contables.

El propietario autorizó usar la aplicación productiva con el portal/realm DEV proporcionado. Esta excepción requiere `AVANZAR_PERMITIR_DEV_EN_PROD=true`; el software la rechaza por defecto. El cliente y las dos credenciales seguirán siendo exclusivos de esta integración. Un futuro realm productivo requiere configuración y revisión de vínculos propias.

## Ficha de entrega

### Identificación

| Campo | Valor |
|---|---|
| Nombre | Integración Siesa y Alegra |
| Código propuesto para Avanzar Services | `INTEGRACION_SIESA_ALEGRA`, pendiente de acuerdo |
| Descripción | Recibos de caja Siesa desde Sheets, histórico y activadores de las cuatro cuentas Alegra |
| Responsable técnico | Equipo mantenedor de Proyecta-SAS; persona por designar |
| Contacto | Pendiente de entregar por el propietario; sin fecha asignada |
| Responsable que aprueba perfiles y accesos | Pendiente de designar por el propietario; antes de activar aprovisionamiento |
| Tecnología y tipo de aplicación | Python 3.11+, backend HTTP, frontend HTML/CSS/JavaScript, PostgreSQL; cliente OIDC confidencial. SQLite solo para pruebas/desarrollo |

Siesa y Alegra aquí son módulos de una sola aplicación y comparten usuarios y sesión. Esta ficha no integra ni modifica el servicio independiente Activadores-Alegra de Railway.

### Entorno y despliegue

| Campo | Valor |
|---|---|
| Entorno | Aplicación: `production`. Identidad y portal: `avanzar-dev`, por excepción explícita |
| URL pública | `https://siesa.avanzarsoluciones.com/` |
| Proyecto o infraestructura | Railway, proyecto Integracion Siesa, `5f5dbe1d-1c27-4d71-a6f0-d899f597367b` |
| Servicio y región | Integraci-n_Siesa, `e4702d2c-5e42-47f7-b054-a6043b2ca180`, `us-east4-eqdc4a` |
| Cuenta de ejecución | Contenedor del servicio Railway; no se identificó una cuenta IAM de Google. Identidad de acceso a secretos: pendiente de acordar con Infraestructura |
| Repositorio, rama y commit | `https://github.com/Proyecta-SAS/Integraci-n_Siesa`, `feat/avanzar-services-integration`, sobre la base `6e9660d12596a922eab4bf7fbebbfbf90c80062f`; consultar el historial de la rama para identificar el commit de entrega |
| Versión o revisión desplegada | 0.3.1, deployment `6116a6d8-ac73-4d68-9071-fa6f82298e3f`, 2026-11-17 |
| Revisión que recibe tráfico | Último deployment SUCCESS anterior; pendiente de reconfirmar después del despliegue de integración, que aún no existe |

La inspección conectada encontró un solo entorno (`production`), PostgreSQL privado y volumen `/data`. No estaban definidas variables de integración. No se leyeron sus valores secretos.

### Navegación e integración visual

| Campo | Valor |
|---|---|
| URL de inicio SSO desde el portal | `https://siesa.avanzarsoluciones.com/portal/iniciar-sso` |
| Callback OIDC exacto | `https://siesa.avanzarsoluciones.com/sso/callback` |
| URL de retorno al portal | `https://avanzar-dev.avanzarsoluciones.com/?abrir=INTEGRACION_SIESA_ALEGRA` |
| URL de presentación embebida | `https://siesa.avanzarsoluciones.com/resumen?portal_embed=1` |
| Origen permitido por CSP | `https://avanzar-dev.avanzarsoluciones.com` cuando se habilita el modo embebido |
| Comportamiento cuando no existe sesión | Acceso directo: login local con opción corporativa si está habilitada. Embebido: aviso 401 y enlace con `target=_top` para iniciar SSO. No se carga Keycloak en iframe |
| Comportamiento cuando la sesión vence | API devuelve 401; la interfaz vuelve a la pantalla de acceso. En modo embebido presenta el enlace de recuperación en ventana principal |

GET de inicio comprueba la cuenta/sesión y retorna al portal si sigue vigente. Si falta sesión, entrega formulario con CSRF para POST `/sso/iniciar`. Callback e inicio SSO tienen `frame-ancestors 'none'`. No hay retornos externos recibidos por parámetros. `/portal/volver` solo redirige al inicio del portal configurado. No se usa `postMessage`.

El modo embebido conserva la navegación de negocio, oculta la marca duplicada y conserva `portal_embed=1` durante navegación interna. Conserva las reglas adaptativas existentes. Los botones de escritura se ocultan para consulta y el backend rechaza sus POST, incluso al entrar por URL directa. No hay nuevos endpoints de descarga; las exportaciones/funciones actuales requieren verificación real conjunta.

### Identidad

| Campo | Valor |
|---|---|
| Emisor y realm | `https://keycloak-dev-375092879765.us-central1.run.app/realms/avanzar-dev`; realm `avanzar-dev` |
| Client ID solicitado o asignado | Propuesto `integracion-siesa-alegra-dev`; aún no registrado/verificado |
| Referencia del secreto OIDC y versión | Variable de ejecución `SSO_SECRETO_CLIENTE`; referencia de almacén y versión pendientes de Avanzar/Infraestructura. No existe un secreto entregado |
| Cuenta de ejecución que necesita leerlo | Servicio Railway indicado; mecanismo de lectura desde el almacén acordado pendiente de Infraestructura |
| Claims requeridos | `iss`, `aud`, `exp`, `iat`, `sub`, `nonce`, `email`, `email_verified` booleano true; `azp` si existe o hay múltiples audiencias |
| Migración o mecanismo de vínculo local | Tablas nuevas `app_oidc_identities`, `app_oidc_requests`, `app_user_profiles`, `integration_audit`; índice único de correo normalizado. Inicialización transaccional, aditiva y repetible |
| Política de primer enlace | Solo correo corporativo verificado de cuenta local existente y activa. Dominios pendientes de confirmación: `avanzarsoluciones.com` y `avanzarsoluciones.co` |
| Procedimiento ante conflicto de identidad | Rechazo sin sobrescritura. Mantenedor revisa emisor/sub y titularidad con Avanzar, revoca sesiones, respalda vínculo y aplica corrección administrativa auditada. No hay endpoint que reasigne identidades automáticamente |

La clave es la pareja exacta `issuer + subject`; existe también unicidad `issuer + user_id`. Un cambio de correo posterior no cambia el vínculo, siempre que el nuevo correo recibido sea corporativo y verificado. El login nunca crea usuarios ni cambia perfiles. Recrear usuarios en Keycloak o cambiar de realm exige revisión explícita.

Authlib implementa Authorization Code, PKCE S256 y `client_secret_basic`; joserfc verifica RS256/JWKS y claims. Discovery debe declarar emisor exacto y capacidades del contrato. Los endpoints deben ser HTTPS y del mismo host del emisor. No se siguen redirecciones de proveedor; se rechazan respuestas no 200. Documentación utilizada: [cliente OAuth de Authlib](https://docs.authlib.org/en/stable/oauth2/client/http/index.html) y [JWT de joserfc](https://jose.authlib.org/en/guide/jwt/).

Solicitudes pendientes: 600 segundos desde preparación, una sola utilización; CSRF y navegador almacenados mediante hashes en SQL. Nonce, verifier y state solo en backend. Callback consume la solicitud incluso si falla; no se aceptan parámetros repetidos, respuestas inesperadas, error del proveedor ni ausencia de la cookie inicial. Cambiar emisor, cliente, callback, retorno o dominios invalida solicitudes pendientes. La cookie inicial es host-only, Secure, HttpOnly, SameSite=Lax. No se guardan ID/access/refresh tokens después de validar.

Límites por petición al proveedor: 3 segundos para conexión, 5 para lectura, 256 KiB descomprimidos; comprobación de tiempo transcurrido de 15 segundos durante lectura por byte (una lectura bloqueante puede añadir hasta 5 segundos). Resolución DNS depende del sistema operativo. No hay reintentos de intercambio de código. Iat debe pertenecer a la solicitud, con tolerancia de reloj de 30 segundos; exp debe estar estrictamente en el futuro.

### Aprovisionamiento

| Campo | Valor |
|---|---|
| URL de POST /api/v1/crear-usuarios | `https://siesa.avanzarsoluciones.com/api/v1/crear-usuarios` (implementada localmente, no desplegada) |
| Referencia de la credencial y versión | Variable `AVANZAR_SERVICES_API_TOKEN`; secreto y versión pendientes, independiente de OIDC, mínimo 32 caracteres aleatorios |
| Procedimiento seguro para autorizar consumo por Avanzar | Generar con CSPRNG en almacén acordado; otorgar lectura al servicio y backend de Avanzar con mínimo privilegio, inyectar en ejecución. No compartir valor por Git, documentación o chat. Pendiente acordar almacén, identidades y referencias/versiones |
| Perfiles locales permitidos | Implementados `consulta` y `operador`; catálogo de integración vacío hasta aprobación. `superadmin` y cualquier valor distinto están prohibidos en esta API |
| Descripción y permisos de cada perfil | `consulta`: lectura de ambos módulos/histórico, sin simulación POST ni envíos. `operador`: alcance operativo preexistente, incluyendo simulación, envíos Siesa y activaciones Alegra, con CSRF, bloqueos, ventanas y validaciones vigentes |
| Restricciones adicionales | Sin administración de usuarios por HTTP. Usuarios existentes sin fila de perfil conservan alcance operador. El nombre de correo no concede privilegios. Límite 16 KiB, campos exactos, correo normalizado único, X-Request-Id obligatorio con 1–128 caracteres `[A-Za-z0-9._:-]`. Credencial inválida: 401; catálogo vacío/no válido: 503 |
| Tipo de ID local | Cadena de 32 caracteres hexadecimales, UUID4 sin guiones, estable |
| Operaciones adicionales disponibles | CLI administrativa `deactivate-user --email` y `revoke-sessions --email`; no hay API de actualización, baja o revocación |

Solicitud sanitizada:

```http
POST /api/v1/crear-usuarios
Authorization: Bearer <credencial-inyectada-en-ejecucion>
Content-Type: application/json
X-Request-Id: prueba-integracion-001

{"correo":"persona@avanzarsoluciones.com","nombre":"Persona de prueba","perfil_local":"consulta","telefono":"3000000000"}
```

Respuesta ilustrativa HTTP 201 (ID ficticio):

```json
{"ok":true,"usuario":{"id":"11111111111141118111111111111111","correo":"persona@avanzarsoluciones.com","nombre":"Persona de prueba","perfil_local":"consulta","telefono":"3000000000","activo":true,"creado":true},"request_id":"prueba-integracion-001"}
```

Repetir datos devuelve HTTP 200, el mismo ID y `creado=false`. X-Request-Id correlaciona auditoría; la idempotencia está basada en correo/datos, no en reutilizar un request ID. Diferencias de nombre, perfil, teléfono o estado devuelven 409 sin modificar. Teléfono ausente equivale a cadena vacía; nombre/teléfono se comparan sin espacios exteriores, correo se normaliza a minúsculas. Las cuentas preexistentes sin perfil/nombre de aprovisionamiento generan conflicto en vez de completar datos silenciosamente.

Otros códigos: 401 credencial inválida/ausente, 405 método distinto de POST (`Allow: POST`), 413 más de 16 KiB, 415 tipo incorrecto, 422 datos/campos/perfil/JSON/request ID inválidos, 503 catálogos sin configurar, 500 error interno sanitizado. Se rechazan claves JSON duplicadas, cuerpos chunked y longitudes ambiguas. La cuenta creada tiene marcador de contraseña no verificable por el login local. No recibe una contraseña corporativa o temporal.

Auditoría SQL: request ID, código de resultado, ID local y fecha; nunca cuerpo, credencial ni token. Si la base no está disponible, se registra únicamente ID de solicitud/resultado y falta de auditoría. La cuenta solicitada por el propietario se creó administrativamente con el código ya desplegado, no mediante esta API ni con un perfil `superadmin`.

### Sesiones y operación

| Campo | Valor |
|---|---|
| Duración e inactividad | 8 horas absolutas desde login, sin renovación deslizante ni límite adicional por inactividad; se conserva la política existente |
| Persistencia entre instancias | Usuarios, sesiones, vínculos y solicitudes OIDC en PostgreSQL común. Cambio de instancia no pierde autenticación. El estado de envíos contables conserva sus requisitos previos de volumen compartido y una instancia |
| Comportamiento de logout | POST con CSRF revoca sesión local y expira cookie. No cierra sesión de Keycloak ni del portal; un nuevo inicio puede reutilizar identidad corporativa |
| Comportamiento de baja y revocación | Cuenta local inactiva se rechaza en cada petición. CLI de baja también borra sesiones. Retirar asignación del portal, deshabilitar SSO o desactivar solo en Keycloak no revoca por sí solo sesiones locales; ejecutar baja/revocación local según el caso. No se implementa backchannel logout |
| Procedimiento de rotación de secretos | Crear nueva versión en almacén; coordinar activación con Keycloak o backend del portal; actualizar referencia/variable de ejecución y reiniciar/desplegar; comprobar salud, login o aprovisionamiento; retirar versión anterior. Solo una credencial de aprovisionamiento activa, requiere ventana coordinada |
| Procedimiento de reversión | Deshabilitar flags SSO/embed, retirar credencial de API y revocar sesiones si procede. Restaurar revisión anterior sin borrar tablas nuevas ni índice. Mantener respaldo de PostgreSQL; cuentas corporativas conservan contraseña local inutilizable al volver atrás |
| Contacto para incidentes | Pendiente por el propietario/equipo técnico; sin fecha asignada |

En modo embebido la cookie local es Secure, HttpOnly y SameSite=None, sin atributo Domain. Fuera de ese modo es SameSite=Lax (Secure en producción/SSO). Navegadores que bloquean cookies de terceros pueden impedir incrustación aunque SameSite=None esté presente. Debe probarse con el portal real en escritorio/móvil; la URL corporativa de esta aplicación y la del portal comparten dominio registrable, pero no se asume aceptación sin pruebas. El enlace de recuperación evita autenticar Keycloak dentro del iframe.

### Validación

| Campo | Valor |
|---|---|
| Cuenta de prueba autorizada, sin contraseña | Cuenta local `superadmin@avanzarsoluciones.com` creada a petición del propietario; identidad corporativa y asignación al portal pendientes. No se documenta su contraseña |
| Escenario o cuenta sin autorización | Cuenta inexistente/inactiva y perfil consulta probados con datos sintéticos; falta que Avanzar asigne una cuenta real sin permiso de apertura |
| Pruebas realizadas | Suite Python, suite JavaScript, proveedor OIDC simulado con firmas RSA reales, HTTP local y cuenta productiva; ver evidencia separada |
| Evidencias | `docs/evidencia_avanzar_services.md`; entorno y límites explícitos |
| Pendientes | Cliente, claims, secretos, dominios/perfiles aprobados, catálogo del portal, despliegue y recorrido completo real |
| Responsable y fecha de cada pendiente | Matriz siguiente; fechas externas no asignadas, deben acordarse antes de activar |

## Configuración y procedimiento de entrega

Correspondencia exacta de los ocho nombres solicitados: se usan literalmente `SSO_HABILITADO`, `SSO_EMISOR`, `SSO_CLIENTE_ID`, `SSO_URL_RETORNO`, `SSO_SECRETO_CLIENTE`, `PORTAL_EMBED_HABILITADO`, `AVANZAR_SERVICES_API_TOKEN` y `AVANZAR_SERVICES_ROLES_PERMITIDOS`. Además se requieren `AVANZAR_URL_BASE`, `AVANZAR_CODIGO_APLICACION`, `PORTAL_ORIGEN`, `AVANZAR_DOMINIOS_CORREO` y la excepción descrita. No se solicita un callback distinto: se deriva exclusivamente de `AVANZAR_URL_BASE + /sso/callback`.

La propuesta sin secretos está en `config/avanzar_services.production-proposed.json`. Los nombres que comienzan con `_` son comentarios y no son variables para importar. Los flags permanecen apagados y catálogos vacíos. `.env.example` no incluye valores secretos.

1. Revisar y subir el cambio local cuando el propietario lo decida. Antes de subir, verificar el despliegue automático del repositorio `main` en Railway.
2. Respaldar PostgreSQL y comprobar que no existan colisiones de `lower(trim(email))`. La migración falla sin fusionar usuarios si encuentra una colisión.
3. Desplegar inicialmente con flags apagados. La inicialización crea las tablas de forma aditiva; no ejecuta envíos ni cambia perfiles existentes.
4. Avanzar registra cliente confidencial con callback exacto, Code+S256, `client_secret_basic`, RS256 y scopes `openid email profile`; desactiva implicit/password grant y entrega claims de correo en ID token.
5. Acordar referencias/versiones de secretos, dominios y catálogo de perfiles. Inyectarlos en runtime, en el entorno del servicio; nunca en el bundle o frontend. Los despliegues no deben reemplazar variables existentes ni publicar `.env`.
6. Ejecutar `python -m siesa_payments.manage check-integration` dentro del entorno configurado: solo muestra valores públicos y booleanos de presencia de secretos. Configuración incompleta con SSO habilitado falla en arranque.
7. Habilitar flags y registrar el servicio en Avanzar. El portal debe navegar al inicio SSO en ventana principal y revalidar autorización después del retorno.
8. Registrar commit, deployment activo, fecha, configuración sanitizada y pruebas E2E. Repetir después de un segundo despliegue sin cambiar configuración para acreditar persistencia. No marcar aceptación si solo carga callback o iframe.

### Matriz de pendientes

| Pendiente | Responsable | Fecha prevista / condición |
|---|---|---|
| Nombre/contacto técnico, aprobador e incidentes | Propietario | Sin fecha asignada; antes de entrega operativa |
| Código y Client ID definitivos | Avanzar Services + mantenedor | Sin fecha asignada; antes de registrar catálogo |
| Registro de cliente, callback y mappers de email | Avanzar Services / Keycloak | Sin fecha asignada; antes de habilitar SSO |
| Almacén, referencias/versiones, IAM y rotación de dos secretos | Infraestructura + Avanzar | Sin fecha asignada; antes de activar |
| Aprobar dominios y perfiles | Responsable de accesos por designar | Sin fecha asignada; antes de habilitar API |
| Publicar código y desplegar implementación | Mantenedor + propietario | Código preparado para entrega en rama de integración; despliegue y activación pendientes |
| Catálogo, asignaciones, permisos de apertura y API backend | Avanzar Services | Sin fecha asignada; después de URLs/cliente acordados |
| Cuentas corporativas autorizada y no autorizada | Avanzar Services | Sin fecha asignada; antes de E2E |
| Validar PostgreSQL real para nuevas tablas, concurrencia y migración | Equipo mantenedor | En despliegue; pruebas locales usan SQLite |
| Navegación, formularios, descargas, móvil, expiración y cookies reales | QA conjunto | Después del despliegue y conexión al portal |
| Revocación conjunta y procedimiento de soporte | Avanzar + mantenedor | Antes de aceptación |
| Confirmar tráfico y persistencia tras segundo despliegue | Infraestructura + QA | Después de activar y volver a desplegar |
