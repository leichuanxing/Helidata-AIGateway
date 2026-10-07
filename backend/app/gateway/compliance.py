"""Check requested and routed models before Provider admission; one audit record."""
import asyncio,json
from time import monotonic
import anyio
from sqlalchemy import select,text
from app.core.database import session_factory
from app.core.exceptions import APIError
from app.models.compliance import CompliancePolicy,AuditWord,AuditSample
from app.services.compliance_sources import word_matches
from app.services.vector_service import embed,version
from app.services.route_vectors import encode_vector
from app.services import compliance_logs

def content(ctx):
 body=ctx.payload or {}
 if body.get('previous_response_id'):raise APIError(400,'COMPLIANCE_CONTEXT_UNAVAILABLE','审核策略启用时请发送完整文本上下文')
 if ctx.operation=='images':value=body.get('prompt','')
 elif ctx.operation=='embeddings':value=body.get('input','')
 elif ctx.operation=='rerank':value=[body.get('query',''),body.get('documents',[])]
 else:value=body.get('messages',body.get('input',''))
 texts=[]
 def visit(item):
  if isinstance(item,str):texts.append(item)
  elif isinstance(item,list):
   for v in item:visit(v)
  elif isinstance(item,dict):
   if item.get('type') in ('image','image_url','input_image','input_audio','audio','input_file','file','video'):raise APIError(400,'COMPLIANCE_MEDIA_UNSUPPORTED','当前审核仅支持完整文本，请移除非文本输入')
   if item.get('type')=='tool_use' and isinstance(item.get('input'),dict):
    texts.append(json.dumps(item['input'],ensure_ascii=False));return
   for key in ('content','text','arguments','tool_calls','function','input','output'):
    if key in item:visit(item[key])
 visit(value)
 for tool_field in ('tools','functions'):
  if body.get(tool_field):texts.append(json.dumps(body[tool_field],ensure_ascii=False))
 if ctx.operation=='messages':visit(body.get('system'))
 if ctx.operation=='responses' and isinstance(body.get('instructions'),str):texts.append(body['instructions'])
 result='\n'.join(texts)
 if len(result)>16000 or len(result.encode())>64000:raise APIError(400,'COMPLIANCE_INPUT_TOO_LARGE','内容审核文本上限16000字符及64KB')
 if ctx.operation=='embeddings' and not (isinstance(value,str) or isinstance(value,list) and value and all(isinstance(v,str) for v in value)):
  raise APIError(400,'COMPLIANCE_TEXT_REQUIRED','启用审核策略时Embedding输入须为文本')
 return result
async def load(db,ctx,model=None):
 rows=(await db.scalars(select(CompliancePolicy).where(CompliancePolicy.status=='enabled').order_by(CompliancePolicy.id))).all()
 checked=set(ctx.deferred.get('_compliance_policy_ids',[]))
 policies=[{k:getattr(r,k) for k in ('id','name','action','risk','description','word_ids','sample_ids','group_ids','models','threshold')} for r in rows if r.id not in checked and (not r.group_ids or ctx.group.id in r.group_ids) and (not r.models or (model or ctx.logical_model) in r.models)]
 ids={i for p in policies for i in p['word_ids']};samples={i for p in policies for i in p['sample_ids']}
 words=[{k:getattr(r,k) for k in ('id','pattern','kind','risk','status')} for r in (await db.scalars(select(AuditWord).where(AuditWord.id.in_(ids)).order_by(AuditWord.id))).all()] if ids else []
 source=[{k:getattr(r,k) for k in ('id','revision','vector_status','risk','status','text')} for r in (await db.scalars(select(AuditSample).where(AuditSample.id.in_(samples)).order_by(AuditSample.id))).all()] if samples else []
 from app.services.operations_settings import governance
 if governance['semantic_threshold'] is not None:
  for policy in policies:policy['threshold']=governance['semantic_threshold']
 return policies,words,source
async def semantic(db,ids,vectors):
 result={}
 for vector in vectors:
  encoded,_=encode_vector(vector)
  rows=(await db.execute(text("SELECT s.id,s.risk,s.text,1-(v.embedding <=> CAST(:v AS vector)) AS similarity FROM review_samples s JOIN review_vectors v ON s.id=v.sample_id WHERE s.id=ANY(CAST(:ids AS bigint[])) AND s.status='enabled' AND s.vector_status='ready' AND v.sample_revision=s.revision AND v.model_version=:model AND vector_dims(v.embedding)=:dimensions ORDER BY similarity DESC LIMIT 500"),dict(v=encoded,ids=list(ids),model=version(),dimensions=len(vector)))).mappings()
  for row in rows:
   old=result.get(row['id'])
   if old is None or row['similarity']>old['similarity']:result[row['id']]={'source':'sample','id':row['id'],'risk':row['risk'],'text':row['text'],'similarity':max(-1,min(1,row['similarity']))}
 return result
async def check(db,ctx,*,routed=False,model=None):
 from app.services.operations_settings import governance
 if not governance['compliance_enabled']:ctx.deferred['compliance']='disabled';return
 if ctx.operation=='preflight':ctx.deferred['compliance']='preflight_not_checked';return
 if ctx.deferred.get('_compliance_parent_checked'):return
 if not routed and getattr(ctx.request.state,'compliance_checked',False):
  ctx.deferred['_compliance_parent_checked']=True;ctx.deferred['compliance']='parent_checked';return
 started=monotonic();snapshot=await load(db,ctx,model);policies,words,samples=snapshot
 if not policies:
  ctx.deferred.setdefault('compliance','not_applicable');return
 active=[w for w in words if w['status']=='enabled']
 value=content(ctx) if active or any(s['status']=='enabled' and s['vector_status']=='ready' for s in samples) else ''
 hits=await asyncio.to_thread(word_matches,active,value)
 matches=[]
 for p in policies:
  selected=[dict(h,risk=p['risk'] or h['risk']) for h in hits if h['id'] in p['word_ids']]
  if selected:matches.append({'policy_id':p['id'],'policy_name':p['name'],'action':p['action'],'risk':p['risk'],'description':p['description'],'threshold':p['threshold'],'hit_count':len(selected),'evidence':selected[:20]})
 # Cheap blocking rules always prevent even local semantic work.
 if not any(m['action']=='block' for m in matches):
  requested={i for p in policies for i in p['sample_ids']}
  semantic_ids={s['id'] for s in samples if s['id'] in requested and s['status']=='enabled' and s['vector_status']=='ready'}
  if semantic_ids:
   await db.commit()
   vectors=await embed(value,ctx.user.id,ctx.client_ip)
   async with session_factory() as local_db:
    if await load(local_db,ctx,model)!=snapshot:raise APIError(409,'COMPLIANCE_CHANGED','审核策略或样本已变化，请重试')
    found=await semantic(local_db,semantic_ids,vectors)
   for p in policies:
    selected=[dict(h,risk=p['risk'] or h['risk']) for i,h in found.items() if i in p['sample_ids'] and h['similarity']>=p['threshold']]
    if selected:matches.append({'policy_id':p['id'],'policy_name':p['name'],'action':p['action'],'risk':p['risk'],'description':p['description'],'threshold':p['threshold'],'hit_count':len(selected),'evidence':sorted(selected,key=lambda h:-h['similarity'])[:20]})
 previous=ctx.deferred.get('compliance')
 previous=previous if isinstance(previous,dict) else {}
 matches=previous.get('matches',[])+matches
 action='block' if any(m['action']=='block' for m in matches) else 'audit' if matches else 'pass'
 ctx.deferred['compliance']={'action':action,'matches':matches,'elapsed_ms':round(previous.get('elapsed_ms',0)+(monotonic()-started)*1000,2),'log_delivery':'pending'}
 ctx.deferred['_compliance_policy_ids']=list(dict.fromkeys(ctx.deferred.get('_compliance_policy_ids',[])+[p['id'] for p in policies]))
 # Deliver once at pipeline completion, including routing failures and cancellation.
 await db.commit()
 if action=='block':raise APIError(403,'CONTENT_BLOCKED','请求命中内容阻断策略')
 ctx.request.state.compliance_checked=True

async def finalize(ctx):
 result=ctx.deferred.get('compliance')
 if not isinstance(result,dict) or result.get('log_delivery')!='pending':return
 with anyio.CancelScope(shield=True):
  result['log_delivery']=await compliance_logs.write(dict(request_id=ctx.request_id,user_id=ctx.user.id,group_id=ctx.group.id,model=ctx.original_model or ctx.logical_model,protocol=ctx.operation,status_code=403 if result['action']=='block' else 200,action=result['action'],matches=result['matches'],elapsed_ms=result['elapsed_ms'],created_at=ctx.received_at))
