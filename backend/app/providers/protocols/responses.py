from app.providers.base import ProviderFailure
def validate(data,payload=None):
    if data.get('object')!='response' or not isinstance(data.get('id'),str) or not data['id'] or not isinstance(data.get('model'),str) or not isinstance(data.get('output'),list) or any(not isinstance(x,dict) or not isinstance(x.get('type'),str) for x in data['output']) or data.get('status') not in ('completed','incomplete'):
        raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')

class Stream:
    def __init__(self):self.started=False
    def read(self,event,data):
        kind=data.get('type')
        if not isinstance(kind,str) or event and event!=kind:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        if kind=='response.created':
            if self.started or not isinstance(data.get('response'),dict) or data['response'].get('object')!='response':raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
            self.started=True
        if not self.started:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        if kind in ('error','response.failed'):raise ProviderFailure('UPSTREAM_STREAM_ERROR')
        final=kind in ('response.completed','response.incomplete')
        response=data.get('response')
        if final:
            if not isinstance(response,dict):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
            validate(response)
            if response['status']!=kind.split('.')[1]:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        effective=kind in ('response.output_text.delta','response.function_call_arguments.delta','response.refusal.delta','response.reasoning_text.delta') and bool(data.get('delta'))
        return final,effective,response or {}
