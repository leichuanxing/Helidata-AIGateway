"""Process-local HTTP pools. Credentials and cookies never belong to a pool."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from time import monotonic
import anyio
import httpx
from app.core.config import get_settings


class NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False


@dataclass
class Entry:
    client: httpx.AsyncClient
    active: int = 0
    touched: float = 0


class PoolCapacityError(Exception):
    pass


class ProviderPools:
    def __init__(self):
        self.entries = {}
        self.lock = asyncio.Lock()
        self.acquired = self.reused = self.evicted = self.rejected = 0

    @asynccontextmanager
    async def acquire(self, proxy=None):
        cfg = get_settings().gateway
        key = proxy or None
        async with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                if len(self.entries) >= cfg.http_proxy_pools:
                    idle = [(e.touched, k) for k, e in self.entries.items() if not e.active]
                    if not idle:
                        self.rejected += 1
                        raise PoolCapacityError()
                    _, victim = min(idle, key=lambda item: item[0])
                    await self.entries.pop(victim).client.aclose()
                    self.evicted += 1
                entry = Entry(httpx.AsyncClient(
                    proxy=proxy, trust_env=False, follow_redirects=False,
                    cookies=CookieJar(policy=NoCookies()),
                    limits=httpx.Limits(max_connections=cfg.http_max_connections,
                        max_keepalive_connections=cfg.http_max_keepalive,
                        keepalive_expiry=cfg.http_keepalive_expiry),
                    timeout=httpx.Timeout(120, connect=cfg.http_connect_timeout,
                        write=cfg.http_write_timeout, pool=cfg.http_pool_timeout)))
                self.entries[key] = entry
            else:
                self.reused += 1
            self.acquired += 1
            entry.active += 1
        try:
            yield entry.client
        finally:
            with anyio.CancelScope(shield=True):
                async with self.lock:
                    entry.active -= 1
                    entry.touched = monotonic()

    def snapshot(self):
        # Do not expose proxy URLs: they may contain passwords.
        return {'pools': len(self.entries), 'active_leases': sum(e.active for e in self.entries.values()),
            'acquired': self.acquired, 'reused': self.reused,
            'evicted': self.evicted, 'rejected': self.rejected}

    async def close(self):
        async with self.lock:
            entries, self.entries = self.entries, {}
            for entry in entries.values():
                await entry.client.aclose()


pools = ProviderPools()


def timeout(read):
    cfg = get_settings().gateway
    return httpx.Timeout(read, connect=cfg.http_connect_timeout,
        write=cfg.http_write_timeout, pool=cfg.http_pool_timeout)
