"""Avanzar contract: configuration, provisioning and exact local identity links."""
from __future__ import annotations

import hmac
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from uuid import uuid4

from .auth import normalize_email

PROFILES = frozenset({'operador', 'consulta'})


class IntegrationError(Exception):
    def __init__(self, message='Solicitud de integracion no valida', status=400):
        super().__init__(message)
        self.status = status


def https_url(value):
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in value)):
        raise ValueError('La integracion requiere URLs HTTPS exactas')
    return parsed


@dataclass(frozen=True)
class IntegrationConfig:
    sso: bool = False
    embed: bool = False
    issuer: str = ''
    client_id: str = ''
    secret: str = field(default='', repr=False)
    base_url: str = ''
    portal_origin: str = ''
    return_url: str = ''
    code: str = ''
    domains: tuple[str, ...] = ()
    api_token: str = field(default='', repr=False)
    profiles: tuple[str, ...] = ()

    @property
    def callback(self):
        return self.base_url + '/sso/callback'

    @classmethod
    def from_env(cls):
        config = cls(
            sso=os.getenv('SSO_HABILITADO', 'false').lower() == 'true',
            embed=os.getenv('PORTAL_EMBED_HABILITADO', 'false').lower() == 'true',
            issuer=os.getenv('SSO_EMISOR', ''), client_id=os.getenv('SSO_CLIENTE_ID', ''),
            secret=os.getenv('SSO_SECRETO_CLIENTE', ''), base_url=os.getenv('AVANZAR_URL_BASE', ''),
            portal_origin=os.getenv('PORTAL_ORIGEN', ''), return_url=os.getenv('SSO_URL_RETORNO', ''),
            code=os.getenv('AVANZAR_CODIGO_APLICACION', ''),
            domains=tuple(x.strip().lower() for x in os.getenv('AVANZAR_DOMINIOS_CORREO', '').split(',') if x.strip()),
            api_token=os.getenv('AVANZAR_SERVICES_API_TOKEN', ''),
            profiles=tuple(x.strip() for x in os.getenv('AVANZAR_SERVICES_ROLES_PERMITIDOS', '').split(',') if x.strip()))
        config.validate()
        return config

    def validate(self):
        if self.sso or self.embed:
            for value in (self.base_url, self.portal_origin):
                parsed = https_url(value)
                if parsed.path or parsed.query or parsed.params:
                    raise ValueError('Configure origenes sin ruta ni barra final')
            if not re.fullmatch(r'[A-Z][A-Z0-9_]{2,63}', self.code):
                raise ValueError('Codigo de aplicacion no valido')
            if self.return_url != self.portal_origin + '/?abrir=' + self.code:
                raise ValueError('El retorno debe coincidir exactamente con el portal y codigo configurados')
        if self.sso:
            parsed = https_url(self.issuer)
            if parsed.query or parsed.params or self.issuer.endswith('/'):
                raise ValueError('Emisor no valido')
            if not self.client_id or not self.secret or not self.domains:
                raise ValueError('Configuracion OIDC incompleta')
        if self.api_token and (len(self.api_token) < 32 or self.api_token == self.secret):
            raise ValueError('La credencial de aprovisionamiento debe ser independiente y tener al menos 32 caracteres')
        if any(not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', d) for d in self.domains):
            raise ValueError('Catalogo de dominios no valido')
        if os.getenv('SIESA_ENV', '').lower() in {'prod', 'production'} and (self.sso or self.embed):
            if ('avanzar-dev' in self.issuer or 'avanzar-dev' in self.portal_origin) and os.getenv('AVANZAR_PERMITIR_DEV_EN_PROD', 'false').lower() != 'true':
                raise ValueError('No se permite activar configuracion DEV en produccion')


def corporate_email(value, domains):
    if not isinstance(value, str) or len(value) > 120:
        raise IntegrationError('Correo corporativo no valido', 422)
    try:
        email = normalize_email(value)
    except ValueError:
        raise IntegrationError('Correo corporativo no valido', 422) from None
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+", email) or email.rsplit('@', 1)[-1] not in domains:
        raise IntegrationError('Correo corporativo no valido', 422)
    local = email.split('@')[0]
    if local.startswith('.') or local.endswith('.') or '..' in local:
        raise IntegrationError('Correo corporativo no valido', 422)
    return email


class Provisioning:
    def __init__(self, db, config):
        self.db, self.config = db, config

    def authorized(self, header):
        expected = self.config.api_token
        return bool(expected and hmac.compare_digest(header.encode(), ('Bearer ' + expected).encode()))

    def audit(self, request_id, result, user_id=''):
        with self.db.transaction() as conn:
            self._audit(conn, request_id, result, user_id)

    @staticmethod
    def _audit(conn, request_id, result, user_id=''):
        conn.execute('INSERT INTO integration_audit(id,request_id,result,user_id,created_at) VALUES(?,?,?,?,?)',
                     (uuid4().hex, request_id, str(result), user_id, int(time.time())))

    def create(self, data, request_id):
        config = self.config
        if not config.profiles or not set(config.profiles) <= PROFILES or not config.domains:
            raise IntegrationError('Catalogo de perfiles o dominios de integracion sin configurar', 503)
        required = {'correo', 'nombre', 'perfil_local'}
        if not isinstance(data, dict) or not required <= data.keys() or data.keys() - (required | {'telefono'}):
            raise IntegrationError('Campos no permitidos o incompletos', 422)
        for name, limit in (('correo', 120), ('nombre', 120), ('perfil_local', 50), ('telefono', 40)):
            value = data.get(name, '')
            if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
                raise IntegrationError('Datos no permitidos', 422)
            if name in required and not value.strip():
                raise IntegrationError('Datos incompletos', 422)
        email = corporate_email(data['correo'], config.domains)
        name, profile, phone = data['nombre'].strip(), data['perfil_local'], data.get('telefono', '').strip()
        if profile not in config.profiles or profile not in PROFILES:
            raise IntegrationError('Perfil no permitido', 422)
        with self.db.transaction(write=True) as conn:
            user_id = uuid4().hex
            created = conn.execute('''INSERT INTO app_users(id,email,password_hash,active,created_at)
                VALUES(?,?,?,1,?) ON CONFLICT DO NOTHING''',
                (user_id, email, '!corporate-only', int(time.time()))).rowcount == 1
            if created:
                conn.execute('INSERT INTO app_user_profiles(user_id,name,profile,phone) VALUES(?,?,?,?)',
                             (user_id, name, profile, phone))
            row = conn.execute('''SELECT u.id,u.active,p.name,p.profile,p.phone FROM app_users u
                LEFT JOIN app_user_profiles p ON p.user_id=u.id WHERE lower(trim(u.email))=?''', (email,)).fetchone()
            if not row or (row['name'], row['profile'], row['phone'], row['active']) != (name, profile, phone, 1):
                self._audit(conn, request_id, '409', row['id'] if row else '')
                result = None
            else:
                status = 201 if created else 200
                self._audit(conn, request_id, status, row['id'])
                result = (status, {'ok': True, 'usuario': {'id': row['id'], 'correo': email, 'nombre': name,
                          'perfil_local': profile, 'telefono': phone, 'activo': True, 'creado': created}, 'request_id': request_id})
        if result is None:
            raise IntegrationError('El correo ya existe con datos, perfil o estado diferentes', 409)
        return result


def resolve_identity(conn, issuer, subject, email):
    """Called in the same transaction as session creation; never overwrites a link."""
    row = conn.execute('''SELECT u.* FROM app_oidc_identities i JOIN app_users u ON u.id=i.user_id
        WHERE i.issuer=? AND i.subject=?''', (issuer, subject)).fetchone()
    if row:
        return row if row['active'] else None
    lock = ' FOR UPDATE' if conn.postgres else ''
    user = conn.execute('SELECT * FROM app_users WHERE lower(trim(email))=?' + lock, (email,)).fetchone()
    if not user or not user['active']:
        return None
    conn.execute('''INSERT INTO app_oidc_identities(issuer,subject,user_id,created_at)
        VALUES(?,?,?,?) ON CONFLICT DO NOTHING''', (issuer, subject, user['id'], int(time.time())))
    link = conn.execute('SELECT user_id FROM app_oidc_identities WHERE issuer=? AND subject=?', (issuer, subject)).fetchone()
    return user if link and link['user_id'] == user['id'] else None
