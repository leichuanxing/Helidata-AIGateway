import asyncio
from app.providers.base import OpenAIProvider,ProviderFailure
async def main():
    adapter=OpenAIProvider('https://api.deepseek.com')
    try:
        models=await adapter.list_models()
        print('Public upstream probe: HTTP',adapter.http_status,'network reachable; no credential supplied; models=',len(models))
    except ProviderFailure as error:
        print('Public upstream probe: network_connected=',error.network,'HTTP=',error.status,'code=',error.code,'latency_ms=',error.latency_ms)
    print('No user upstream credential or paid generation request was used.')
asyncio.run(main())
