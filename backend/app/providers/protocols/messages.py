from app.providers.base import ProviderFailure
def validate(data,payload=None):
    if data.get('type')!='message' or data.get('role')!='assistant' or not isinstance(data.get('id'),str) or not data['id'] or not isinstance(data.get('model'),str) or not isinstance(data.get('content'),list) or any(not isinstance(x,dict) or not isinstance(x.get('type'),str) for x in data['content']) or not isinstance(data.get('stop_reason'),str):
        raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')

class Stream:
    def __init__(self):self.started=False;self.stopped=False;self.usage={};self.blocks=set()
    def read(self,event,data):
        kind=data.get('type')
        if not isinstance(kind,str) or event and event!=kind:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        if kind=='error':raise ProviderFailure('UPSTREAM_STREAM_ERROR')
        if kind=='ping':return False,False,{}
        if kind=='message_start':
            message=data.get('message')
            if self.started or not isinstance(message,dict) or message.get('type')!='message' or not isinstance(message.get('id'),str) or not isinstance(message.get('model'),str):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
            self.started=True;self.usage.update(message.get('usage') or {})
        elif not self.started:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        elif kind=='content_block_start':
            index=data.get('index')
            if type(index) is not int or index in self.blocks:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
            self.blocks.add(index)
        elif kind=='content_block_delta':
            if data.get('index') not in self.blocks:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        elif kind=='content_block_stop':
            if data.get('index') not in self.blocks:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
            self.blocks.remove(data['index'])
        elif kind=='message_delta':
            self.usage.update(data.get('usage') or {});self.stopped=bool((data.get('delta') or {}).get('stop_reason'))
        elif kind=='message_stop':
            if not self.stopped or self.blocks:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        else:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        delta=data.get('delta') or {};block=data.get('content_block') or {}
        effective=bool(delta.get('text') or delta.get('partial_json') or delta.get('thinking') or block.get('text') or block.get('name'))
        return kind=='message_stop',effective,{'usage':dict(self.usage)}
