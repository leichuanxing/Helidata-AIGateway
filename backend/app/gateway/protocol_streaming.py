"""Native event streams and incremental cross-protocol frames; share lease ownership."""
import asyncio,json
from time import monotonic
import httpx
from pydantic import ValidationError
from app.core.exceptions import APIError
from app.providers.base import ProviderFailure
from app.providers.operations import CODECS
from app.providers.protocols.usage import normalized
from app.providers.translator import MessagesToChatStream,ChatToMessagesStream
from app.schemas.chat import ChatCompletionChunk
from app.gateway.streaming import GatewayStreamingResponse,frame
from app.gateway.sse import events
from app.gateway.quota import observe
from app.gateway.usage import effective

class ProtocolStreamingResponse(GatewayStreamingResponse):
    async def chunks(self):
        wire=self.ctx.wire_operation
        reader=CODECS[wire].Stream() if wire!='chat' else None
        translator=(MessagesToChatStream() if self.ctx.operation=='chat' else ChatToMessagesStream()) if self.ctx.operation!=wire else None
        try:
            async for event,raw in events(self.upstream.aiter_bytes()):
                if event=='heartbeat':yield b': keep-alive\n\n';continue
                if event=='error':raise ProviderFailure('UPSTREAM_STREAM_ERROR')
                if raw.strip()=='[DONE]':
                    if wire!='chat':raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
                    data='[DONE]';final=True;content=False;usage={}
                else:
                    data=json.loads(raw)
                    if not isinstance(data,dict) or 'error' in data:raise ProviderFailure('UPSTREAM_STREAM_ERROR')
                    if wire=='responses' and data.get('type')=='response.failed' and isinstance(data.get('response'),dict):
                        observe(self.ctx,{'usage':normalized(wire,data['response'])})
                    if reader:final,content,usage=reader.read(event,data)
                    else:
                        ChatCompletionChunk.model_validate(data);final=False;content=effective(data);usage=data
                    observe(self.ctx,{'usage':normalized(wire,usage)})
                if content:
                    if self.ctx.first_effective is None:self.ctx.first_effective=monotonic()
                    self.ctx.generation_end=monotonic()
                frames=translator.convert(event,data,self.ctx.usage_snapshot) if translator else [(event,data)]
                for kind,item in frames:
                    if isinstance(item,dict):
                        item=dict(item)
                        if 'model' in item or item.get('object')=='chat.completion.chunk':item['model']=self.ctx.original_model or self.ctx.logical_model
                        for nested in ('message','response'):
                            if isinstance(item.get(nested),dict) and 'model' in item[nested]:item[nested]={**item[nested],'model':self.ctx.original_model or self.ctx.logical_model}
                        encoded=json.dumps(item,ensure_ascii=False,separators=(',',':'))
                    else:encoded=item
                    from app.services.body_logs import response as capture
                    capture(self.ctx,item,stream=True)
                    self.ctx.stream_chunks+=1;yield frame(encoded,kind or None)
                if final:
                    self.ctx.generation_end=monotonic();self.outcome,self.code='success',None;return
            raise ProviderFailure('UPSTREAM_STREAM_INTERRUPTED')
        except asyncio.CancelledError:
            self.ctx.generation_end=monotonic();raise
        except (ProviderFailure,httpx.HTTPError,ValueError,ValidationError,APIError,KeyError,TypeError) as error:
            self.ctx.generation_end=monotonic();self.outcome='failure'
            self.code=error.detail['code'] if isinstance(error,APIError) else error.code if isinstance(error,ProviderFailure) else 'UPSTREAM_TIMEOUT' if isinstance(error,httpx.TimeoutException) else 'UPSTREAM_NETWORK_ERROR' if isinstance(error,httpx.HTTPError) else 'UPSTREAM_INVALID_RESPONSE'
            yield self.error_frame()
        except Exception:
            self.ctx.generation_end=monotonic();self.outcome,self.code='failure','INTERNAL_ERROR';yield self.error_frame()

    def error_frame(self):
        if self.ctx.operation!='messages':return super().error_frame()
        return frame(json.dumps({'type':'error','error':{'type':'api_error','code':self.code,'message':'上游流式响应中断'},'request_id':self.ctx.request_id},ensure_ascii=False),'error')
