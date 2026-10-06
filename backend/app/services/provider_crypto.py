"""Persistent 256-bit key, independent of JWT; never replace a missing key for existing ciphertext."""
import asyncio,base64,os,secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select,func
from app.core.database import session_factory,engine
from app.core.exceptions import APIError
from app.models.user import Provider
KEY_PATH=Path('/data/config/provider-encryption.key')
AAD=b'helidata-provider-key:v1'


def read_key():
    try:
        key=KEY_PATH.read_bytes()
        if len(key)!=32:
            raise ValueError('invalid length')
        return key
    except (OSError,ValueError):
        raise APIError(503,'PROVIDER_KEY_UNAVAILABLE','上游密钥加密文件不可用，请由服务器管理员恢复备份') from None


def encrypt_secret(raw):
    nonce=secrets.token_bytes(12)
    encrypted=AESGCM(read_key()).encrypt(nonce,raw.encode('utf-8'),AAD)
    return 'v1:'+base64.b64encode(nonce+encrypted).decode('ascii')


def decrypt_secret(value):
    if value is None:
        return ''
    try:
        if not value.startswith('v1:'):
            raise ValueError('unknown version')
        data=base64.b64decode(value[3:],validate=True)
        return AESGCM(read_key()).decrypt(data[:12],data[12:],AAD).decode('utf-8')
    except APIError:
        raise
    except Exception:
        raise APIError(503,'PROVIDER_KEY_DECRYPT_FAILED','上游密钥解密失败，请检查加密文件和备份') from None


async def ensure_key():
    if not KEY_PATH.exists():
        async with session_factory() as db:
            count=await db.scalar(select(func.count(Provider.id)).where(Provider.api_key_encrypted.is_not(None)))
        if count:
            raise RuntimeError('Provider encryption key missing; restore protected key backup before startup')
        with KEY_PATH.open('xb') as handle:
            os.chmod(KEY_PATH,0o600)
            handle.write(secrets.token_bytes(32))
    read_key()
    async with session_factory() as db:
        encrypted=(await db.scalars(select(Provider.api_key_encrypted).where(Provider.api_key_encrypted.is_not(None)))).all()
        for value in encrypted:
            decrypt_secret(value)
    await engine.dispose()


if __name__=='__main__':
    asyncio.run(ensure_key())
    print('Provider encryption key validated.')

