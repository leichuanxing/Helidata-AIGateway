import uvicorn
from app.core.config import get_settings

if __name__ == '__main__':
    settings = get_settings()
    uvicorn.run('app.main:app', host='127.0.0.1', port=settings.server.port,
                access_log=False, proxy_headers=False,
                log_level=settings.logging.level.lower())
