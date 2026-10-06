"""Protocol-specific adapters. Business routers never branch on vendor names."""
import json,time
from urllib.parse import quote
from abc import ABC,abstractmethod
import httpx
from app.core.config import get_settings
from app.providers.pool import pools, timeout as request_timeout, PoolCapacityError


class ProviderFailure(Exception):
    def __init__(self,code,status=None,network=False,auth='unknown',latency_ms=0):
        self.code,self.status,self.network,self.auth,self.latency_ms=code,status,network,auth,latency_ms
        super().__init__(code)


class BaseProvider(ABC):
    def __init__(self,base_url,key='',proxy=None):
        self.base_url=base_url.rstrip('/')
        self.key=key
        self.proxy=proxy
        self.http_status=None
        self.latency_ms=0
        self.request_id=None

    def headers(self):
        return {'Authorization':'Bearer '+self.key} if self.key else {}

    async def request(self,method,path,payload=None,timeout=10,max_bytes=1024*1024):
        if payload and payload.get('stream'):
            raise ProviderFailure('STREAM_NOT_IMPLEMENTED')
        start=time.monotonic()
        status=None
        try:
            headers=self.headers()
            if self.request_id: headers['X-Request-ID']=self.request_id
            async with pools.acquire(self.proxy) as client:
                async with client.stream(method,self.base_url+path,headers=headers,json=payload,timeout=request_timeout(timeout)) as response:
                    status=response.status_code
                    self.http_status=status
                    self.latency_ms=round((time.monotonic()-start)*1000)
                    if not 200<=status<300:
                        code='UPSTREAM_AUTH_FAILED' if status in (401,403) else 'UPSTREAM_HTTP_ERROR'
                        raise ProviderFailure(code,status,True,'failed' if status in (401,403) else 'unknown',self.latency_ms)
                    chunks=[];size=0
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>max_bytes:
                            raise ProviderFailure('UPSTREAM_RESPONSE_TOO_LARGE',status,True,'unknown',self.latency_ms)
                        chunks.append(chunk)
                    data=json.loads(b''.join(chunks))
                    if not isinstance(data,dict):
                        raise ValueError('object required')
                    self.latency_ms=round((time.monotonic()-start)*1000)
                    return data
        except ProviderFailure:
            raise
        except (PoolCapacityError,httpx.PoolTimeout):
            raise ProviderFailure('UPSTREAM_POOL_EXHAUSTED') from None
        except httpx.TimeoutException:
            raise ProviderFailure('UPSTREAM_TIMEOUT',status,status is not None,'unknown',round((time.monotonic()-start)*1000)) from None
        except (httpx.HTTPError,OSError):
            raise ProviderFailure('UPSTREAM_NETWORK_ERROR',status,status is not None,'unknown',round((time.monotonic()-start)*1000)) from None
        except (ValueError,UnicodeError):
            raise ProviderFailure('UPSTREAM_INVALID_RESPONSE',status,True,'unknown',round((time.monotonic()-start)*1000)) from None

    async def open_stream(self,path,payload,resources,idle_timeout):
        headers={**self.headers(),'Accept':'text/event-stream'}
        if self.request_id:headers['X-Request-ID']=self.request_id
        try:
            client=await resources.enter_async_context(pools.acquire(self.proxy))
            response=await resources.enter_async_context(client.stream('POST',self.base_url+path,headers=headers,json=payload,timeout=request_timeout(idle_timeout)))
            self.http_status=response.status_code
            if not 200<=response.status_code<300:
                raise ProviderFailure('UPSTREAM_AUTH_FAILED' if response.status_code in (401,403) else 'UPSTREAM_HTTP_ERROR',response.status_code)
            if response.headers.get('content-type','').split(';')[0].strip().lower()!='text/event-stream':raise ProviderFailure('UPSTREAM_INVALID_RESPONSE',response.status_code)
            return response
        except (PoolCapacityError,httpx.PoolTimeout):raise ProviderFailure('UPSTREAM_POOL_EXHAUSTED') from None
        except httpx.TimeoutException:raise ProviderFailure('UPSTREAM_TIMEOUT') from None
        except httpx.HTTPError:raise ProviderFailure('UPSTREAM_NETWORK_ERROR') from None

    def parse_models(self,data,field='data',id_field='id'):
        rows=data.get(field)
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get(id_field),str) for r in rows):
            raise ProviderFailure('UPSTREAM_INVALID_RESPONSE',self.http_status,True,'unknown',self.latency_ms)
        return [{'id':r[id_field]} for r in rows]

    @abstractmethod
    async def list_models(self): ...

    async def chat_completion(self,payload): raise ProviderFailure('UNSUPPORTED_OPERATION')
    async def open_chat_stream(self,payload,resources,idle_timeout): raise ProviderFailure('UNSUPPORTED_OPERATION')
    async def responses(self,payload): raise ProviderFailure('UNSUPPORTED_OPERATION')
    async def messages(self,payload): raise ProviderFailure('UNSUPPORTED_OPERATION')
    async def embeddings(self,payload): raise ProviderFailure('UNSUPPORTED_OPERATION')
    async def rerank(self,payload): raise ProviderFailure('UNSUPPORTED_OPERATION')
    async def image_generation(self,payload): raise ProviderFailure('UNSUPPORTED_OPERATION')


class OpenAIProvider(BaseProvider):
    async def open_chat_stream(self,payload,resources,idle_timeout):
        return await self.open_stream('/chat/completions',payload,resources,idle_timeout)
    async def list_models(self): return self.parse_models(await self.request('GET','/models'))
    async def chat_completion(self,payload): return await self.request('POST','/chat/completions',payload,timeout=get_settings().gateway.nonstream_timeout,max_bytes=8*1024*1024)
    async def responses(self,payload): return await self.request('POST','/responses',payload)
    async def embeddings(self,payload): return await self.request('POST','/embeddings',payload)
    async def image_generation(self,payload): return await self.request('POST','/images/generations',payload)


class CustomOpenAIProvider(OpenAIProvider):
    async def rerank(self,payload): return await self.request('POST','/rerank',payload)


class AnthropicProvider(BaseProvider):
    def headers(self): return {'x-api-key':self.key,'anthropic-version':'2023-06-01'}
    async def list_models(self):
        start=time.monotonic();path='/models?limit=1000';models=[];cursors=set()
        for _ in range(20):
            data=await self.request('GET',path);models.extend(self.parse_models(data))
            if len(models)>10000: raise ProviderFailure('UPSTREAM_RESPONSE_TOO_LARGE',self.http_status,True,'unknown',self.latency_ms)
            if not data.get('has_more'):
                self.latency_ms=round((time.monotonic()-start)*1000);return models
            cursor=data.get('last_id')
            if not isinstance(cursor,str) or not cursor or len(cursor)>200 or cursor in cursors:
                raise ProviderFailure('UPSTREAM_INVALID_RESPONSE',self.http_status,True,'unknown',self.latency_ms)
            cursors.add(cursor);path='/models?limit=1000&after_id='+quote(cursor,safe='')
            if time.monotonic()-start>30: raise ProviderFailure('UPSTREAM_TIMEOUT',self.http_status,True,'unknown',self.latency_ms)
        raise ProviderFailure('UPSTREAM_RESPONSE_TOO_LARGE',self.http_status,True,'unknown',self.latency_ms)
    async def messages(self,payload): return await self.request('POST','/messages',payload)


class OllamaProvider(BaseProvider):
    async def list_models(self): return self.parse_models(await self.request('GET','/api/tags'),'models','name')
    async def chat_completion(self,payload): return await self.request('POST','/api/chat',{**payload,'stream':False})
    async def embeddings(self,payload): return await self.request('POST','/api/embed',payload)

