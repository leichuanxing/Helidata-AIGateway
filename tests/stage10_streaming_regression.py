"""Real streaming HTTP fixtures; disposable DB identities, no paid credentials."""
import asyncio
import json
import logging
import select as socket_select
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from sqlalchemy import delete
from starlette.requests import Request
import stage10_nonstream_regression as seed
from app.gateway.pipeline import GatewayPipeline
from app.gateway.sse import events
from app.providers.base import ProviderFailure

active=set(); ended={}; started={}; lock=threading.Lock(); captures=[]

def chunk(delta=None, choices=True):
    return {'id':'chatcmpl-fixture','object':'chat.completion.chunk','created':1791110000,
            'model':'private-upstream-model','choices':[{'index':0,'delta':delta or {'content':'你好'},'finish_reason':None}] if choices else [],
            **({} if choices else {'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}})}

def frame(value):
    return ('data: '+json.dumps(value,ensure_ascii=False)+'\r\n\r\n').encode()

class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers.get('Authorization')=='Bearer '+seed.SECRET
        assert payload['stream'] is True and payload['model']=='private-upstream-model'
        rid=self.headers['X-Request-ID']; mode=self.path.split('/')[1]
        captures.append(payload)
        with lock: active.add(rid); started[rid]=time.monotonic()
        try:
            if mode=='headers':
                ready,_,_=socket_select.select([self.connection],[],[],5)
                assert ready and self.connection.recv(1)==b''
                return
            self.send_response(401 if mode=='auth' else 429 if mode=='rate' else 200)
            self.send_header('Content-Type','application/json' if mode in ('auth','rate','type') else 'text/event-stream; charset=utf-8')
            self.end_headers()
            if mode in ('auth','rate','type'):
                self.wfile.write(json.dumps({'error':seed.SECRET+' '+seed.KEY}).encode());return
            self.wfile.write(b': fixture heartbeat\r\n\r\n'+frame(chunk({'role':'assistant','content':''})));self.wfile.flush()
            if mode=='cancel':
                ready,_,_=socket_select.select([self.connection],[],[],5)
                assert ready and self.connection.recv(1)==b''
                return
            if mode=='idle': time.sleep(.4)
            if mode=='invalid': self.wfile.write(b'data: invalid '+seed.SECRET.encode()+b'\n\n');return
            if mode=='error': self.wfile.write(frame({'error':seed.SECRET+' '+seed.KEY}));return
            if mode=='big': self.wfile.write(b'data: '+b'x'*(1024*1024+1)+b'\n\n');return
            if mode=='eof': return
            time.sleep(.18)
            # UTF-8 and CRLF split across arbitrary network writes.
            raw=frame(chunk({'content':'你好','reasoning_content':'fixture reasoning'}))
            for part in (raw[:7],raw[7:123],raw[123:-1],raw[-1:]): self.wfile.write(part);self.wfile.flush()
            time.sleep(.18)
            self.wfile.write(frame(chunk({'tool_calls':[{'index':0,'id':'call-fixture','type':'function','function':{'name':'lookup','arguments':'{"id":'}}]})))
            self.wfile.write(frame(chunk({'tool_calls':[{'index':0,'function':{'arguments':'1}'}}]})))
            self.wfile.write(frame(chunk(choices=False))+b'data: [DONE]\r\n\r\n');self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError): pass
        finally:
            with lock: active.discard(rid);ended[rid]=time.monotonic()

async def wait_until(predicate,timeout=2):
    start=time.monotonic()
    while not predicate():
        assert time.monotonic()-start<timeout,'upstream connection did not close promptly'
        await asyncio.sleep(.02)

async def parser_checks():
    async def pieces(raw):
        for byte in raw: yield bytes([byte])
    got=[x async for x in events(pieces(b'\xef\xbb\xbf:data heartbeat\r\ndata: '+ '你'.encode()+b'\r\ndata: ok\r\n\r\ndata: [DONE]\r\r'))]
    assert got==[('heartbeat',''),('', '你\nok'),('', '[DONE]')],got
    try:
        [x async for x in events(pieces(b'data: unfinished'))]
        raise AssertionError('partial frame accepted')
    except ProviderFailure as error: assert error.code=='UPSTREAM_STREAM_INTERRUPTED'
    print('PASS: SSE BOM, UTF-8 byte boundaries, split CRLF, lone CR, multiline data and partial EOF')

async def resource_checks():
    leases=[0,0]; logs=[]
    @asynccontextmanager
    async def lease(ctx,index):
        leases[index]+=1
        try: yield
        finally: leases[index]-=1
    class Capture(logging.Handler):
        def emit(self,record): logs.append((record.request_id,json.loads(record.getMessage())))
    logger=logging.getLogger('app.gateway.calls');previous_level=logger.level;logger.setLevel(logging.INFO);handler=Capture();logger.addHandler(handler)
    try:
        for mode in ('normal','cancel','eof','idle'):
            await seed.change(seed.Provider,'provider',base_url=seed.URL+'/'+mode+'/v1')
            disconnected=asyncio.Event();received=[]
            async def receive():
                await disconnected.wait();return {'type':'http.disconnect'}
            async def send(message):
                if message['type']=='http.response.body':
                    received.append(message.get('body',b''))
                    if mode=='cancel' and b'data:' in received[-1]: disconnected.set()
            scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'method':'POST','path':'/v1/chat/completions',
                   'headers':[(b'authorization',('Bearer '+seed.KEY).encode())],'state':{'request_id':'req_resource_'+mode}}
            request=Request(scope,receive)
            timeout=.05 if mode=='idle' else 300
            with patch('app.gateway.concurrency.acquire',lambda ctx:lease(ctx,0)),patch('app.gateway.provider_concurrency.acquire',lambda ctx:lease(ctx,1)),patch('app.gateway.upstream.get_settings',lambda:SimpleNamespace(gateway=SimpleNamespace(stream_idle_timeout=timeout))):
                async with seed.session_factory() as db:
                    response=await GatewayPipeline().run(request,db,'chat',seed.NAME,{'model':seed.NAME,'messages':[{'role':'user','content':'fixture'}],'stream':True})
                assert leases==[1,1] and not response.upstream.is_closed
                assert not any(rid==scope['state']['request_id'] for rid,_ in logs),'premature terminal log'
                await asyncio.wait_for(response(scope,receive,send),3)
                assert leases==[0,0] and response.upstream.is_closed
                records=[record for rid,record in logs if rid==scope['state']['request_id']];assert len(records)==1
                expected='success' if mode=='normal' else 'client_cancelled' if mode=='cancel' else 'failure'
                assert records[0]['outcome']==expected,records
                if mode=='idle': assert b'UPSTREAM_TIMEOUT' in b''.join(received)
        print('PASS: ASGI 2.4 idle disconnect, DB session closed before body, leases/HTTP connection released on success/cancel/error/timeout; one terminal log')
    finally: logger.removeHandler(handler);logger.setLevel(previous_level)

def curl_check():
    config='url = "http://127.0.0.1/v1/chat/completions"\nheader = "Authorization: Bearer '+seed.KEY+'"\nheader = "Content-Type: application/json"\ndata = '+json.dumps(json.dumps({'model':seed.NAME,'messages':[{'role':'user','content':'fixture'}],'stream':True}))+'\n'
    proc=subprocess.Popen(['curl','-sS','-N','-K','-'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    proc.stdin.write(config.encode());proc.stdin.close();start=time.monotonic();first=None;lines=[]
    for line in proc.stdout:
        if line.startswith(b'data:') and first is None:first=time.monotonic()-start
        lines.append(line)
    assert proc.wait(timeout=5)==0 and first is not None and time.monotonic()-start-first>.25
    assert b''.join(lines).count(b'data: [DONE]')==1
    print('PASS: actual curl -N receives first data before completion (unbuffered Nginx/FastAPI/HTTPX)')

async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True
    seed.URL='http://127.0.0.1:'+str(server.server_port)
    threading.Thread(target=server.serve_forever,daemon=True).start();await seed.seed()
    payload={'model':seed.NAME,'messages':[{'role':'user','content':'fixture'}],'stream':True,'stream_options':{'include_usage':True}}
    try:
        await parser_checks()
        async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+seed.KEY},timeout=10) as client:
            await seed.change(seed.Provider,'provider',base_url=seed.URL+'/normal/v1')
            start=time.monotonic();first=None;lines=[]
            async with client.stream('POST','/v1/chat/completions',json=payload) as response:
                assert response.status_code==200 and response.headers['content-type'].startswith('text/event-stream')
                async for line in response.aiter_lines():
                    if line.startswith('data:') and first is None:first=time.monotonic()-start
                    lines.append(line)
            assert time.monotonic()-start-first>.25
            frames=[json.loads(line[6:]) for line in lines if line.startswith('data: ') and line!='data: [DONE]']
            assert len(frames)==5 and all(frame['model']==seed.NAME for frame in frames)
            assert frames[-1]['usage']['total_tokens']==6 and frames[-1]['choices']==[]
            assert frames[1]['choices'][0]['delta']['content']=='你好'
            assert lines.count('data: [DONE]')==1 and captures[-1]['stream_options']=={'include_usage':True}
            await asyncio.to_thread(curl_check)
            for mode,code,status in [('auth','UPSTREAM_AUTH_FAILED',502),('rate','UPSTREAM_RATE_LIMITED',503),('type','UPSTREAM_INVALID_RESPONSE',502),('invalid','UPSTREAM_INVALID_RESPONSE',200),('error','UPSTREAM_STREAM_ERROR',200),('big','UPSTREAM_EVENT_TOO_LARGE',200),('eof','UPSTREAM_STREAM_INTERRUPTED',200)]:
                await seed.change(seed.Provider,'provider',base_url=seed.URL+'/'+mode+'/v1')
                response=await client.post('/v1/chat/completions',json=payload)
                assert response.status_code==status and code in response.text,(mode,response.status_code,response.text[:100])
                assert seed.SECRET not in response.text and seed.KEY not in response.text
                assert 'data: [DONE]' not in response.text
                if status==200: assert 'event: error' in response.text and response.headers['X-Request-ID'] in response.text
            print('PASS: upstream header failures use JSON; midstream protocol/size/EOF failures use sanitized SSE error without DONE')
            await seed.change(seed.Provider,'provider',base_url=seed.URL+'/cancel/v1')
            for _ in range(12):
                async with client.stream('POST','/v1/chat/completions',json=payload) as response:
                    rid=response.headers['X-Request-ID']
                    async for line in response.aiter_lines():
                        if line.startswith('data:'): break
                await wait_until(lambda:rid in ended)
                assert ended[rid]-started[rid]<1.5
                print('CANCEL_REQUEST_ID='+rid)
            await seed.change(seed.Provider,'provider',base_url=seed.URL+'/headers/v1')
            before=set(started);task=asyncio.create_task(client.post('/v1/chat/completions',json=payload))
            await wait_until(lambda:bool(set(started)-before));rid=(set(started)-before).pop();task.cancel()
            try: await task
            except asyncio.CancelledError: pass
            await wait_until(lambda:rid in ended);assert ended[rid]-started[rid]<1.5
            print('CANCEL_REQUEST_ID='+rid)
            print('PASS: 12 actual idle-body cancellations and pre-header cancellation close upstream promptly')
        await resource_checks();await wait_until(lambda:not active)
        print('PASS: no fixture connections remain')
    finally:
        server.shutdown();server.server_close()
        async with seed.session_factory.begin() as db:
            await db.execute(delete(seed.User).where(seed.User.id==seed.ids['user']))
            await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==seed.ids['ug']))
            await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.id==seed.ids['mg']))
            await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id==seed.ids['provider']))
            await db.execute(delete(seed.Provider).where(seed.Provider.id==seed.ids['provider']))
            await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([seed.NAME,seed.EMBED])))
        from app.core.redis import redis_client
        keys=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
        if keys: await redis_client.delete(*keys)
        await redis_client.aclose()
        await seed.engine.dispose()

if __name__=='__main__': asyncio.run(main())
