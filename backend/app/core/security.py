import asyncio
import re
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from starlette.concurrency import run_in_threadpool
from app.core.config import get_settings

password_slots = asyncio.Semaphore(4)
hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(24))


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def now():
    return datetime.now(timezone.utc)


def validate_password(value: str):
    classes = sum((any(c.islower() for c in value), any(c.isupper() for c in value),
                   any(c.isdigit() for c in value), any(not c.isalnum() for c in value)))
    return 12 <= len(value) <= 128 and classes >= 3


async def hash_password(value: str):
    async with password_slots:
        return await run_in_threadpool(hasher.hash, value)


async def verify_password(hash_value: str, password: str):
    def check():
        try:
            return hasher.verify(hash_value, password)
        except (VerificationError, InvalidHashError):
            return False
    async with password_slots:
        return await run_in_threadpool(check)


def access_token(user, session_id):
    settings = get_settings().security
    return jwt.encode({'sub': str(user.id), 'sid': session_id, 'ver': user.auth_version,
                       'iat': now(), 'exp': now()+timedelta(seconds=settings.jwt_expire),
                       'iss': 'helidata-gateway', 'aud': 'helidata-web', 'type': 'access'},
                      settings.jwt_secret.get_secret_value(), algorithm='HS256')


def decode_token(token):
    try:
        value = jwt.decode(token, get_settings().security.jwt_secret.get_secret_value(),
                           algorithms=['HS256'], issuer='helidata-gateway', audience='helidata-web',
                           options={'require': ['sub','sid','ver','iat','exp','iss','aud','type']})
        if value['type'] != 'access':
            raise ValueError()
        if not isinstance(value['sub'],str) or not re.fullmatch(r'[1-9][0-9]{0,18}',value['sub']) or int(value['sub']) > 2147483647:
            raise ValueError()
        if type(value['ver']) is not int or value['ver'] < 0 or value['ver'] > 2147483647:
            raise ValueError()
        if not isinstance(value['sid'],str) or str(uuid.UUID(value['sid'])) != value['sid']:
            raise ValueError()
        if type(value['iat']) is not int or type(value['exp']) is not int:
            raise ValueError()
        return value
    except (jwt.InvalidTokenError, ValueError, TypeError):
        from app.core.exceptions import APIError
        raise APIError(401, 'SESSION_INVALID', '登录已失效，请重新登录') from None
