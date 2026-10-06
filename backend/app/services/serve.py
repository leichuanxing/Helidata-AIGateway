import uvicorn
from app.core.config import get_settings

if __name__ == '__main__':
    settings = get_settings()
    uvicorn.run('app.main:app', host=settings.server.host, port=settings.server.port,
                access_log=False, proxy_headers=True, forwarded_allow_ips='127.0.0.1',
                log_level=settings.logging.level.lower())
