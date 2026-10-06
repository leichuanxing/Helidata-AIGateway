"""Semantic conversion checks: tools, images, unsupported fields and incremental JSON."""
import json
from app.providers.translator import *
from app.core.exceptions import APIError
from app.providers.protocols.usage import normalized

def error(action):
 try:action()
 except APIError as e:assert e.detail['code']=='PROTOCOL_ERROR'
 else:raise AssertionError('lossy conversion accepted')
chat={'model':'logical','messages':[{'role':'system','content':'policy'},{'role':'user','content':[{'type':'text','text':'look'},{'type':'image_url','image_url':{'url':'data:image/png;base64,aGVsbG8='}}]},{'role':'assistant','content':None,'tool_calls':[{'id':'call1','type':'function','function':{'name':'lookup','arguments':'{"q":"你好"}'}}]},{'role':'tool','tool_call_id':'call1','content':'result'}],'max_tokens':32,'tools':[{'type':'function','function':{'name':'lookup','description':'lookup','parameters':{'type':'object','properties':{'q':{'type':'string'}}}}}],'tool_choice':{'type':'function','function':{'name':'lookup'}}}
m=chat_to_messages(chat);assert m['system']==[{'type':'text','text':'policy'}] and m['messages'][0]['content'][1]['source']['type']=='base64';assert m['messages'][1]['content'][0]['input']=={'q':'你好'} and m['messages'][2]['content'][0]['tool_use_id']=='call1'
c=messages_to_chat(m);assert c['messages'][0]['content']=='policy' and c['messages'][2]['tool_calls'][0]['function']['name']=='lookup' and c['messages'][3]['tool_call_id']=='call1';assert c['tool_choice']['function']['name']=='lookup'
error(lambda:chat_to_messages({**chat,'response_format':{'type':'json_object'}}));error(lambda:messages_to_chat({**m,'thinking':{'type':'enabled'}}));error(lambda:chat_to_messages({**chat,'n':2}));error(lambda:chat_to_messages({**chat,'messages':[{'role':'user','content':[{'type':'input_audio','input_audio':{}}]}]}))
message={'id':'id','type':'message','role':'assistant','model':'upstream','content':[{'type':'text','text':'你好'},{'type':'tool_use','id':'call1','name':'lookup','input':{'q':'你好'}}],'stop_reason':'tool_use','stop_sequence':None,'usage':{'input_tokens':4,'output_tokens':2,'cache_read_input_tokens':1,'cache_creation_input_tokens':2}}
result=messages_result_to_chat(message);assert result['usage']['total_tokens']==9 and result['choices'][0]['finish_reason']=='tool_calls';assert chat_result_to_messages(result)['content'][1]['input']=={'q':'你好'}
t=MessagesToChatStream();t.convert('message_start',{'type':'message_start','message':{'id':'id'}},{})
first=t.convert('content_block_start',{'type':'content_block_start','index':7,'content_block':{'type':'tool_use','id':'call1','name':'lookup','input':{}}},{})[0][1]
assert first['choices'][0]['delta']['tool_calls'][0]['index']==0
fragment=t.convert('content_block_delta',{'type':'content_block_delta','index':7,'delta':{'type':'input_json_delta','partial_json':'{"q":'}},{})[0][1];assert fragment['choices'][0]['delta']['tool_calls'][0]['function']['arguments']=='{"q":'
t=ChatToMessagesStream();base={'id':'id','model':'model','choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'call1','type':'function','function':{'name':'lookup','arguments':'{"q":'}}]},'finish_reason':None}]};out=t.convert('',base,{})
assert any(x[0]=='content_block_start' for x in out)
t.convert('',{'id':'id','choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"你好"}'}}]},'finish_reason':'tool_calls'}]},{});out=t.convert('','[DONE]',{'prompt_tokens':5,'completion_tokens':2,'cached_tokens':1});assert out[-1][0]=='message_stop' and out[-2][1]['usage']=={'input_tokens':4,'output_tokens':2,'cache_read_input_tokens':1}
assert normalized('messages',{'usage':{'output_tokens':2}})=={'completion_tokens':2}
error(lambda:messages_to_chat({**m,'max_tokens':0}))
error(lambda:messages_result_to_chat({**message,'content':[{'type':'text','text':'quoted','citations':[{'start':0}]}]}))
print('PASS: system/image/tool request and result conversion, sparse tool indexes, streamed JSON and cache semantics; unsupported semantics fail explicitly')
