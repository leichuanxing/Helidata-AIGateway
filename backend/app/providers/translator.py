"""Explicit, loss-aware Chat ↔ Messages translation (text, images and function tools)."""
import json,time,re
from app.core.exceptions import APIError
from app.providers.protocols.usage import normalized

def fail():raise APIError(400,'PROTOCOL_ERROR','该请求或响应无法无损转换协议，请使用账号原生协议')
def fields(data,allowed):
    if not isinstance(data,dict) or any(k not in allowed and v is not None for k,v in data.items()):fail()
def blocks(content):
    if isinstance(content,str):return [{'type':'text','text':content}]
    if content is None:return []
    if not isinstance(content,list):fail()
    return content
def chat_content(content):
    result=[]
    for b in blocks(content):
        if b.get('type')=='text':
            fields(b,('type','text'));result.append(b)
        elif b.get('type')=='image_url':
            fields(b,('type','image_url'));image=b.get('image_url');fields(image,('url',))
            url=image.get('url')
            if not isinstance(url,str):fail()
            match=re.fullmatch(r'data:(image/(?:jpeg|png|gif|webp));base64,(.+)',url,re.S)
            source={'type':'base64','media_type':match[1],'data':match[2]} if match else {'type':'url','url':url}
            result.append({'type':'image','source':source})
        else:fail()
    return result
def anthropic_content(content):
    result=[]
    for b in blocks(content):
        if b.get('type')=='text':
            fields(b,('type','text'));result.append(b)
        elif b.get('type')=='image':
            fields(b,('type','source'));source=b.get('source') or {}
            if source.get('type')=='url':fields(source,('type','url'));url=source.get('url')
            elif source.get('type')=='base64':
                fields(source,('type','media_type','data'));url=f"data:{source.get('media_type')};base64,{source.get('data')}"
            else:fail()
            result.append({'type':'image_url','image_url':{'url':url}})
        else:fail()
    return result
def append_message(rows,role,content):
    if rows and rows[-1]['role']==role:rows[-1]['content'].extend(content)
    else:rows.append({'role':role,'content':content})

def chat_to_messages(payload):
    fields(payload,('model','messages','max_tokens','max_completion_tokens','temperature','top_p','stream','stop','tools','tool_choice','n','stream_options'))
    if payload.get('n',1)!=1:fail()
    if payload.get('stream_options') not in (None,{}, {'include_usage':True},{'include_usage':False}):fail()
    out={k:v for k,v in payload.items() if k in ('model','temperature','top_p','stream')}
    out['max_tokens']=payload.get('max_completion_tokens',payload.get('max_tokens',1024))
    rows=[];system=[]
    for m in payload['messages']:
        fields(m,('role','content','tool_calls','tool_call_id'))
        role=m['role']
        if role in ('system','developer'):
            if rows or m.get('tool_calls'):fail()
            content=chat_content(m.get('content'))
            if any(b['type']!='text' for b in content):fail()
            system.extend(content);continue
        if role=='tool':
            if not m.get('tool_call_id'):fail()
            append_message(rows,'user',[{'type':'tool_result','tool_use_id':m['tool_call_id'],'content':chat_content(m.get('content'))}]);continue
        if role not in ('user','assistant'):fail()
        content=chat_content(m.get('content'))
        for tool in m.get('tool_calls') or []:
            if role!='assistant' or tool.get('type')!='function':fail()
            fields(tool,('id','type','function'));f=tool.get('function');fields(f,('name','arguments'))
            try:arguments=json.loads(f['arguments'])
            except (KeyError,ValueError,TypeError):fail()
            if not isinstance(arguments,dict):fail()
            content.append({'type':'tool_use','id':tool['id'],'name':f['name'],'input':arguments})
        append_message(rows,role,content)
    if not rows:fail()
    out['messages']=rows
    if system:out['system']=system
    if payload.get('stop') is not None:out['stop_sequences']=[payload['stop']] if isinstance(payload['stop'],str) else payload['stop']
    if payload.get('tools'):
        out['tools']=[]
        for t in payload['tools']:
            fields(t,('type','function'))
            if t.get('type')!='function':fail()
            f=t.get('function');fields(f,('name','description','parameters'))
            out['tools'].append({'name':f['name'],'input_schema':f.get('parameters',{'type':'object','properties':{}}),**({'description':f['description']} if 'description' in f else {})})
    choice=payload.get('tool_choice')
    if isinstance(choice,str):out['tool_choice']={'type':{'auto':'auto','none':'none','required':'any'}[choice]}
    elif choice:
        fields(choice,('type','function'));f=choice.get('function');fields(f,('name',))
        if choice.get('type')!='function':fail()
        out['tool_choice']={'type':'tool','name':f['name']}
    return out

def messages_to_chat(payload):
    fields(payload,('model','messages','max_tokens','temperature','top_p','stream','system','stop_sequences','tools','tool_choice'))
    if payload.get('max_tokens')==0:fail()  # Cache-only Messages has no equivalent Chat request.
    out={k:v for k,v in payload.items() if k in ('model','max_tokens','temperature','top_p','stream')}
    rows=[]
    if payload.get('system'):
        sys=anthropic_content(payload['system'])
        if any(b['type']!='text' for b in sys):fail()
        rows.append({'role':'system','content':'\n'.join(b['text'] for b in sys)})
    for m in payload['messages']:
        fields(m,('role','content'));role=m['role'];content=[];calls=[];results=[]
        for b in blocks(m['content']):
            kind=b.get('type')
            if kind=='tool_use':
                fields(b,('type','id','name','input'))
                if role!='assistant' or not isinstance(b.get('input'),dict):fail()
                calls.append({'id':b['id'],'type':'function','function':{'name':b['name'],'arguments':json.dumps(b['input'],ensure_ascii=False)}})
            elif kind=='tool_result':
                fields(b,('type','tool_use_id','content'))
                if role!='user':fail()
                converted=anthropic_content(b.get('content',''))
                if any(x['type']!='text' for x in converted):fail()
                results.append({'role':'tool','tool_call_id':b['tool_use_id'],'content':'\n'.join(x['text'] for x in converted)})
            else:content.extend(anthropic_content([b]))
        rows.extend(results)
        if content or calls:rows.append({'role':role,'content':content or None,**({'tool_calls':calls} if calls else {})})
    out['messages']=rows
    if payload.get('stop_sequences') is not None:out['stop']=payload['stop_sequences']
    if payload.get('tools'):
        out['tools']=[]
        for t in payload['tools']:
            fields(t,('name','description','input_schema'))
            out['tools'].append({'type':'function','function':{'name':t['name'],'parameters':t['input_schema'],**({'description':t['description']} if 'description' in t else {})}})
    choice=payload.get('tool_choice')
    if choice:
        fields(choice,('type','name'))
        if choice.get('type')=='tool':out['tool_choice']={'type':'function','function':{'name':choice['name']}}
        elif choice.get('type') in ('auto','any','none'):out['tool_choice']={'auto':'auto','any':'required','none':'none'}[choice['type']]
        else:fail()
    if out.get('stream'):out['stream_options']={'include_usage':True}
    return out

TO_CHAT={'end_turn':'stop','stop_sequence':'stop','max_tokens':'length','tool_use':'tool_calls'}
TO_MESSAGES={'stop':'end_turn','length':'max_tokens','tool_calls':'tool_use'}
def messages_result_to_chat(data):
    text=[];calls=[]
    for b in data['content']:
        if b.get('type')=='text':
            fields(b,('type','text'));text.append(b['text'])
        elif b.get('type')=='tool_use':
            fields(b,('type','id','name','input'));calls.append({'id':b['id'],'type':'function','function':{'name':b['name'],'arguments':json.dumps(b['input'],ensure_ascii=False)}})
        else:fail()
    if data['stop_reason'] not in TO_CHAT:fail()
    return {'id':data['id'],'object':'chat.completion','created':int(time.time()),'model':data['model'],
        'choices':[{'index':0,'message':{'role':'assistant','content':''.join(text) or None,**({'tool_calls':calls} if calls else {})},'finish_reason':TO_CHAT[data['stop_reason']]}],
        'usage':normalized('messages',data)}
def chat_result_to_messages(data):
    if len(data['choices'])!=1:fail()
    c=data['choices'][0];m=c['message'];fields(m,('role','content','tool_calls'))
    if c['finish_reason'] not in TO_MESSAGES:fail()
    content=[{'type':'text','text':m['content']}] if m.get('content') else []
    for t in m.get('tool_calls') or []:
        if t.get('type')!='function':fail()
        try:args=json.loads(t['function']['arguments'])
        except (KeyError,ValueError,TypeError):fail()
        if not isinstance(args,dict):fail()
        content.append({'type':'tool_use','id':t['id'],'name':t['function']['name'],'input':args})
    u=data.get('usage') or {};usage={}
    for a,b in [('prompt_tokens','input_tokens'),('completion_tokens','output_tokens')]:
        if a in u:usage[b]=u[a]
    cached=(u.get('prompt_tokens_details') or {}).get('cached_tokens')
    if type(cached) is int and type(usage.get('input_tokens')) is int:
        usage['input_tokens']=max(0,usage['input_tokens']-cached);usage['cache_read_input_tokens']=cached
    return {'id':data['id'],'type':'message','role':'assistant','model':data['model'],'content':content,'stop_reason':TO_MESSAGES[c['finish_reason']],'stop_sequence':None,'usage':usage}

class MessagesToChatStream:
    def __init__(self):self.id='';self.tools={};self.reason=None
    def convert(self,event,data,usage):
        kind=data['type'];delta={};finish=None
        if kind=='message_start':self.id=data['message']['id'];delta={'role':'assistant','content':''}
        elif kind=='content_block_start':
            b=data['content_block'];i=data['index']
            if b['type']=='tool_use':
                fields(b,('type','id','name','input'))
                self.tools[i]=len(self.tools);delta={'tool_calls':[{'index':self.tools[i],'id':b['id'],'type':'function','function':{'name':b['name'],'arguments':''}}]}
                if b.get('input'):fail()
            elif b['type']=='text':
                fields(b,('type','text'));delta={'content':b.get('text','')}
            else:fail()
        elif kind=='content_block_delta':
            d=data['delta']
            if d['type']=='text_delta':delta={'content':d['text']}
            elif d['type']=='input_json_delta':delta={'tool_calls':[{'index':self.tools[data['index']],'function':{'arguments':d['partial_json']}}]}
            else:fail()
        elif kind=='message_delta':
            reason=data['delta'].get('stop_reason')
            if reason not in TO_CHAT:fail()
            finish=TO_CHAT[reason]
        elif kind=='message_stop':
            return [('',{'id':self.id,'object':'chat.completion.chunk','created':int(time.time()),'choices':[],'usage':usage}),('', '[DONE]')]
        else:return []
        return [('',{'id':self.id,'object':'chat.completion.chunk','created':int(time.time()),'choices':[{'index':0,'delta':delta,'finish_reason':finish}]})]

class ChatToMessagesStream:
    def __init__(self):self.started=False;self.blocks={};self.next=0;self.reason=None;self.arguments={}
    def convert(self,event,data,usage):
        output=[]
        def add(kind,**kw):output.append((kind,{'type':kind,**kw}))
        if data=='[DONE]':
            if not self.started or self.reason not in TO_MESSAGES:fail()
            for args in self.arguments.values():
                try:value=json.loads(args)
                except (ValueError,TypeError):fail()
                if not isinstance(value,dict):fail()
            for i in self.blocks.values():add('content_block_stop',index=i)
            u={}
            if 'prompt_tokens' in usage:u['input_tokens']=usage['prompt_tokens']
            if 'completion_tokens' in usage:u['output_tokens']=usage['completion_tokens']
            cached=usage.get('cached_tokens')
            if type(cached) is int and 'input_tokens' in u:
                u['input_tokens']=max(0,u['input_tokens']-cached);u['cache_read_input_tokens']=cached
            add('message_delta',delta={'stop_reason':TO_MESSAGES[self.reason],'stop_sequence':None},usage=u)
            add('message_stop');return output
        if not self.started:
            self.started=True;add('message_start',message={'id':data['id'],'type':'message','role':'assistant','model':data.get('model',''),'content':[],'stop_reason':None,'stop_sequence':None,'usage':{}})
        choices=data.get('choices',[])
        if len(choices)>1 or any(c['index']!=0 for c in choices):fail()
        for c in choices:
            d=c['delta'];fields(d,('role','content','tool_calls'))
            if d.get('content'):
                if 'text' not in self.blocks:self.blocks['text']=self.next;self.next+=1;add('content_block_start',index=self.blocks['text'],content_block={'type':'text','text':''})
                add('content_block_delta',index=self.blocks['text'],delta={'type':'text_delta','text':d['content']})
            for t in d.get('tool_calls') or []:
                fields(t,('index','id','type','function'))
                key=('tool',t['index']);f=t.get('function') or {}
                fields(f,('name','arguments'))
                if key not in self.blocks:
                    if not t.get('id') or not f.get('name'):fail()
                    self.blocks[key]=self.next;self.next+=1;add('content_block_start',index=self.blocks[key],content_block={'type':'tool_use','id':t['id'],'name':f['name'],'input':{}})
                    self.arguments[key]=''
                elif f.get('name') or t.get('id'):fail()
                if f.get('arguments'):
                    self.arguments[key]+=f['arguments']
                    if len(self.arguments[key].encode())>1024*1024:fail()
                    add('content_block_delta',index=self.blocks[key],delta={'type':'input_json_delta','partial_json':f['arguments']})
            if c.get('finish_reason'):
                if c['finish_reason'] not in TO_MESSAGES:fail()
                self.reason=c['finish_reason']
        return output
