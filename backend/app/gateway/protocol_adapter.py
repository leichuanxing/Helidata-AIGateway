from app.providers.registry import build_adapter
from app.services.provider_crypto import decrypt_secret


def bind(ctx):
    ctx.adapter = build_adapter(ctx.provider, decrypt_secret(ctx.provider.api_key_encrypted),ctx.operation)
