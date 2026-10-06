"""Bound bytes before JSON parsing, including requests without Content-Length."""
from fastapi.responses import JSONResponse
from app.core.config import get_settings


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST','PUT','PATCH','DELETE'):
            return await self.app(scope, receive, send)
        limit = get_settings().gateway.max_body_bytes
        lengths = [v for k,v in scope.get('headers',[]) if k.lower() == b'content-length']
        invalid = len(lengths) > 1 or bool(lengths and (not lengths[0].isdigit() or len(lengths[0]) > 12))
        if invalid:
            return await self.reject(scope,receive,send,400,'INVALID_CONTENT_LENGTH')
        if lengths and int(lengths[0]) > limit:
            return await self.reject(scope,receive,send,413,'REQUEST_TOO_LARGE')
        chunks = []; size = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body',b''); size += len(chunk)
            if size > limit:
                return await self.reject(scope,receive,send,413,'REQUEST_TOO_LARGE')
            chunks.append(chunk)
            if not message.get('more_body',False):
                break
        body = b''.join(chunks)
        chunks.clear()
        delivered = False

        async def bounded_receive():
            nonlocal delivered, body
            if not delivered:
                delivered = True
                message = {'type':'http.request','body':body,'more_body':False}
                body = b''
                return message
            return await receive()
        await self.app(scope,bounded_receive,send)

    async def reject(self,scope,receive,send,status,code):
        state = scope.setdefault('state',{})
        state['failure_code'] = code
        rid = state.get('request_id','')
        error = {'type':'gateway_error','code':code,'message':'请求体超出限制' if status==413 else '请求长度无效','request_id':rid}
        body = {'error':error}
        if scope.get('path') == '/v1/messages':
            body = {'type':'error','error':{**error,'type':'invalid_request_error'},'request_id':rid}
        await JSONResponse(body,status_code=status)(scope,receive,send)
