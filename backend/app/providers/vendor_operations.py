"""Bounded vendor-specific rerank/image wire conversion; no extra billable calls."""
import asyncio,time
from app.providers.base import CustomOpenAIProvider,ProviderFailure
from app.core.config import get_settings

class AliyunProvider(CustomOpenAIProvider):
    async def image_generation(self,payload):
        # Native mode is explicit in the configured base URL. Never retry a
        # possibly billable compatible request through a second endpoint.
        if not self.base_url.endswith('/api/v1'):
            return await super().image_generation(payload)
        allowed={'model','prompt','n','size','stream','response_format','negative_prompt','seed',
                 'prompt_extend','prompt_extend_mode','enable_thinking','watermark'}
        if (set(payload)-allowed or payload.get('stream') or payload.get('response_format','url')!='url'
                or type(payload.get('n',1)) is not int or not 1<=payload.get('n',1)<=6
                or not payload['model'].startswith(('qwen-image-3.0','qwen-image-2.1'))):
            raise ProviderFailure('UPSTREAM_REQUEST_REJECTED',status=400,safe_to_retry=True)
        parameters={k:v for k,v in payload.items() if k not in ('model','prompt','stream','response_format','size')}
        size=payload.get('size')
        if size and size!='auto':
            import re
            if not isinstance(size,str) or not re.fullmatch(r'[1-9][0-9]{1,4}x[1-9][0-9]{1,4}',size):
                raise ProviderFailure('UPSTREAM_REQUEST_REJECTED',status=400,safe_to_retry=True)
            parameters['size']=size.replace('x','*')
        result=await self.request('POST','/services/aigc/multimodal-generation/generation',
            {'model':payload['model'],'input':{'messages':[{'role':'user','content':[{'text':payload['prompt']}]}]},'parameters':parameters},
            timeout=get_settings().gateway.nonstream_timeout,max_bytes=32*1024*1024)
        try:
            choices=result['output']['choices']
            if not isinstance(choices,list) or not choices:raise ValueError()
            rows=[]
            for choice in choices:
                if choice.get('finish_reason') not in (None,'stop'):raise ValueError()
                content=choice['message']['content']
                if not isinstance(content,list):raise ValueError()
                for part in content:
                    if not isinstance(part,dict):raise ValueError()
                    if 'image' in part:
                        if not isinstance(part['image'],str) or not part['image']:raise ValueError()
                        rows.append({'url':part['image']})
            if not rows or len(rows)>payload.get('n',1):raise ValueError()
        except (KeyError,TypeError,ValueError,AttributeError):
            raise ProviderFailure('UPSTREAM_INVALID_RESPONSE') from None
        return {'created':int(time.time()),'data':rows,
                **({'usage':result['usage']} if isinstance(result.get('usage'),dict) else {}),
                **({'id':result['request_id']} if isinstance(result.get('request_id'),str) else {})}

    async def list_models(self):
        if not self.base_url.endswith('/api/v1'):
            return await super().list_models()
        # Native DashScope differs from the OpenAI-compatible catalog. Preserve
        # the configured origin, paginate completely and fail instead of silently
        # marking a model missing from a truncated first page.
        models=[];seen=set()
        try:
            async with asyncio.timeout(10):
                for page in range(1,101):
                    result=await self.request('GET',f'/models?page_no={page}&page_size=100')
                    if 'data' in result and page==1:return self.parse_models(result)
                    output=result.get('output')
                    if result.get('success') is False or not isinstance(output,dict):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
                    rows=output.get('models');total=output.get('total')
                    if not isinstance(rows,list) or any(not isinstance(row,dict) or not isinstance(row.get('model'),str) or not row['model'].strip() for row in rows):
                        raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
                    if total is not None and (type(total) is not int or not 0<=total<=10000):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
                    before=len(seen)
                    for row in rows:
                        name=row['model']
                        if name not in seen:seen.add(name);models.append({'id':name})
                    if total is not None and len(seen)>=total or total is None and len(rows)<100:return models
                    if not rows or len(seen)==before:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
                raise ProviderFailure('UPSTREAM_RESPONSE_TOO_LARGE')
        except TimeoutError:raise ProviderFailure('UPSTREAM_TIMEOUT') from None

    async def rerank(self,payload):
        # Preserve the configured origin/private proxy; never send credentials to a
        # different host while translating the old compatible-mode base path.
        if self.base_url.endswith('/compatible-mode/v1'):
            self.base_url=self.base_url[:-len('/compatible-mode/v1')]+'/api/v1'
        parameters={k:v for k,v in payload.items() if k not in ('model','query','documents','stream')}
        result=await self.request('POST','/services/rerank/text-rerank/text-rerank',
            {'model':payload['model'],'input':{'query':payload['query'],'documents':payload['documents']},'parameters':parameters},
            timeout=get_settings().gateway.nonstream_timeout,max_bytes=8*1024*1024)
        output=result.get('output')
        if not isinstance(output,dict) or not isinstance(output.get('results'),list):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        return {'results':output['results'],**({'usage':result['usage']} if isinstance(result.get('usage'),dict) else {}),
                **({'id':result['request_id']} if isinstance(result.get('request_id'),str) else {})}

class SiliconFlowProvider(CustomOpenAIProvider):
    async def image_generation(self,payload):
        if payload.get('n',1)!=1 or payload.get('response_format','url')!='url' or 'batch_size' in payload:
            raise ProviderFailure('UPSTREAM_REQUEST_REJECTED',status=400,safe_to_retry=True)
        body={k:v for k,v in payload.items() if k not in ('n','stream','response_format','size')}
        if 'size' in payload:
            if 'image_size' in body and body['image_size']!=payload['size']:raise ProviderFailure('UPSTREAM_REQUEST_REJECTED',status=400,safe_to_retry=True)
            body['image_size']=payload['size']
        result=await self.request('POST','/images/generations',body,
            timeout=get_settings().gateway.nonstream_timeout,max_bytes=8*1024*1024)
        rows=result.get('images')
        if not isinstance(rows,list):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        return {'created':int(time.time()),'data':rows,**({'usage':result['usage']} if isinstance(result.get('usage'),dict) else {})}
