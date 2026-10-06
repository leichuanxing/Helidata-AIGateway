"""Administrator-only compliance management and immutable audit evidence."""
import hashlib
from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,Query,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator
from sqlalchemy import select,func,text
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.compliance import AuditWord,AuditSample,CompliancePolicy
from app.models.user import UserGroup,LogicalModel
from app.services.compliance_sources import validate_pattern
from app.services.vector_service import version
from app.services.sessions import audit
router=APIRouter(prefix='/api/admin/compliance',tags=['内容合规'])
class Input(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class SourceInput(Input):
 risk:Literal['low','medium','high']='medium'
 status:Literal['enabled','disabled']='enabled'
 remark:str=Field(default='',max_length=2000)
 policy_id:int|None=Field(default=None,gt=0)
class WordInput(SourceInput):
 pattern:str=Field(min_length=1,max_length=256)
 kind:Literal['text','wildcard','regex']='text'
class SampleInput(SourceInput):
 text:str=Field(min_length=1,max_length=2000)
 build_vector:bool=False
 consent:bool=False
class PolicyInput(Input):
 name:str=Field(min_length=1,max_length=80)
 action:Literal['audit','block']='audit'
 risk:Literal['low','medium','high']|None=None
 description:str=Field(default='',max_length=2000)
 status:Literal['enabled','disabled']='disabled'
 word_ids:list[int]=Field(default_factory=list,max_length=500)
 sample_ids:list[int]=Field(default_factory=list,max_length=500)
 group_ids:list[int]=Field(default_factory=list,max_length=100)
 models:list[str]=Field(default_factory=list,max_length=100)
 threshold:float=Field(default=.85,ge=0,le=1,allow_inf_nan=False)
 @field_validator('word_ids','sample_ids','group_ids',mode='before')
 @classmethod
 def ids(cls,v):
  if not isinstance(v,list) or any(type(i) is not int or i<=0 for i in v) or len(set(v))!=len(v):raise ValueError('ID须为唯一正整数')
  return v
 @field_validator('models')
 @classmethod
 def names(cls,v):
  if any(not i.strip() or len(i)>100 for i in v) or len(set(v))!=len(v):raise ValueError('模型名无效或重复')
  return v
class StateInput(Input):status:Literal['enabled','disabled']
class ImportInput(Input):
 policy_id:int=Field(gt=0)
 lines:str=Field(min_length=1,max_length=128000)
 status:Literal['enabled','disabled']='enabled'
class BuildInput(Input):
 ids:list[int]=Field(default_factory=list,max_length=500)
 all:bool=False
 consent:bool=False
 @field_validator('ids',mode='before')
 @classmethod
 def valid_ids(cls,v):return PolicyInput.ids(v)
def public(r):return {c.name:getattr(r,c.name) for c in r.__table__.columns}
async def lock(db):await db.execute(text('SELECT pg_advisory_xact_lock(71017)'))
async def row(db,model,ident):
 r=await db.get(model,ident)
 if r is None:raise APIError(404,'COMPLIANCE_NOT_FOUND','审核资源不存在')
 return r
async def finish(db,r,actor,request,action):
 try:
  await db.flush();audit(db,actor.id,action,r.id,request.client.host if request.client else None,resource_type='compliance')
  await db.flush();await db.refresh(r);result=public(r);await db.commit();return {'data':result}
 except IntegrityError:
  await db.rollback();raise APIError(409,'COMPLIANCE_DUPLICATE','资源名称或样本文本重复') from None
async def limit(db,model,cap,added=1):
 if (await db.scalar(select(func.count()).select_from(model)))+added>cap:raise APIError(400,'COMPLIANCE_LIMIT','审核资源数量已达上限')
async def assign(db,r,policy_id,field):
 if policy_id is None:raise APIError(400,'COMPLIANCE_POLICY_REQUIRED','请选择所属策略组')
 target=await row(db,CompliancePolicy,policy_id)
 await db.flush()
 for p in (await db.scalars(select(CompliancePolicy))).all():
  ids=list(getattr(p,field))
  if p.id==target.id:
   if r.id not in ids:ids.append(r.id)
  elif r.id in ids:ids.remove(r.id)
  setattr(p,field,ids)
async def source_list(db,model,page,size,q,status,policy_id,vector_status=''):
 query=select(model)
 if q:query=query.where((model.pattern if model is AuditWord else model.text).icontains(q,autoescape=True))
 if status:query=query.where(model.status==status)
 if vector_status:query=query.where(model.vector_status==vector_status)
 policies=(await db.scalars(select(CompliancePolicy).order_by(CompliancePolicy.id))).all()
 field='word_ids' if model is AuditWord else 'sample_ids'
 if policy_id:
  chosen=next((p for p in policies if p.id==policy_id),None)
  query=query.where(model.id.in_(getattr(chosen,field) if chosen else []))
 total=await db.scalar(select(func.count()).select_from(query.subquery()))
 items=[]
 for r in (await db.scalars(query.order_by(model.id.desc()).offset((page-1)*size).limit(size))).all():
  item=public(r);item['policies']=[{'id':p.id,'name':p.name,'risk':p.risk,'action':p.action} for p in policies if r.id in getattr(p,field)]
  items.append(item)
 return {'data':{'items':items,'total':total,'model_version':version()}}
@router.get('/words')
async def words(actor=Depends(administrator),db=Depends(get_session),page:int=Query(1,ge=1,le=10000),page_size:int=Query(500,ge=1,le=500),q:str=Query('',max_length=256),status:Literal['','enabled','disabled']='',policy_id:int|None=Query(None,gt=0)):
 return await source_list(db,AuditWord,page,page_size,q,status,policy_id)
@router.post('/words/import')
async def import_words(body:ImportInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 await lock(db);policy=await row(db,CompliancePolicy,body.policy_id)
 values=list(dict.fromkeys(v.strip() for v in body.lines.splitlines() if v.strip()))
 if not values or len(values)>500 or any(len(v)>256 for v in values):raise APIError(400,'COMPLIANCE_IMPORT_INVALID','每行一个敏感词，最多500条，每条不超过256字符')
 existing=(await db.scalars(select(AuditWord))).all();seen={r.pattern for r in existing if r.id in policy.word_ids and r.kind=='text'}
 original=len(values);values=[v for v in values if v not in seen];await limit(db,AuditWord,500,len(values))
 for value in values:
  r=AuditWord(pattern=value,kind='text',risk=policy.risk or 'medium',status=body.status,remark='');db.add(r);await assign(db,r,body.policy_id,'word_ids')
 audit(db,actor.id,'import_audit_words',body.policy_id,request.client.host if request.client else None,resource_type='compliance');await db.commit()
 return {'data':{'created':len(values),'skipped':original-len(values)}}
@router.post('/words')
async def add_word(body:WordInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 validate_pattern(body.kind,body.pattern);await lock(db);await limit(db,AuditWord,500)
 r=AuditWord(**body.model_dump(exclude={'policy_id'}));db.add(r);await assign(db,r,body.policy_id,'word_ids');return await finish(db,r,actor,request,'create_audit_word')
@router.put('/words/{ident}')
async def edit_word(ident:int,body:WordInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 validate_pattern(body.kind,body.pattern);await lock(db);r=await row(db,AuditWord,ident)
 for k,v in body.model_dump(exclude={'policy_id'}).items():setattr(r,k,v)
 if 'policy_id' in body.model_fields_set:await assign(db,r,body.policy_id,'word_ids')
 return await finish(db,r,actor,request,'update_audit_word')
@router.get('/samples')
async def samples(actor=Depends(administrator),db=Depends(get_session),page:int=Query(1,ge=1,le=10000),page_size:int=Query(20,ge=1,le=500),q:str=Query('',max_length=256),status:Literal['','pending','processing','ready','failed','not_built']='',enabled:Literal['','enabled','disabled']='',policy_id:int|None=Query(None,gt=0)):
 return await source_list(db,AuditSample,page,page_size,q,enabled,policy_id,status)
@router.post('/samples/build')
async def build_samples(body:BuildInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 if body.all and body.ids or not body.all and not body.ids:raise APIError(400,'COMPLIANCE_BUILD_SELECTION','请选择样本或构建全部')
 if version().startswith('upstream:') and not body.consent:raise APIError(400,'VECTOR_CONSENT_REQUIRED','构建上游向量可能产生费用，请明确确认')
 await lock(db);query=select(AuditSample).with_for_update()
 if not body.all:query=query.where(AuditSample.id.in_(body.ids))
 records=(await db.scalars(query)).all()
 if not body.all and len(records)!=len(body.ids):raise APIError(404,'COMPLIANCE_NOT_FOUND','部分审核样本不存在')
 queued=0
 for r in records:
  if r.vector_status in ('pending','processing'):continue
  r.revision+=1;r.vector_status='pending';r.vector_error=None;r.job_started_at=None;queued+=1
 audit(db,actor.id,'build_audit_samples',None,request.client.host if request.client else None,resource_type='compliance');await db.commit()
 return {'data':{'queued':queued,'total':len(records)}}
@router.post('/samples')
async def add_sample(body:SampleInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 if body.build_vector and version().startswith('upstream:') and not body.consent:raise APIError(400,'VECTOR_CONSENT_REQUIRED','构建上游向量可能产生费用，请明确确认')
 await lock(db);await limit(db,AuditSample,500)
 r=AuditSample(**body.model_dump(exclude={'build_vector','policy_id','consent'}),text_hash=hashlib.sha256(body.text.encode()).hexdigest(),vector_status='pending' if body.build_vector else 'not_built')
 db.add(r)
 try:await assign(db,r,body.policy_id,'sample_ids')
 except IntegrityError:await db.rollback();raise APIError(409,'COMPLIANCE_DUPLICATE','样本文本重复') from None
 return await finish(db,r,actor,request,'create_audit_sample')
@router.put('/samples/{ident}')
async def edit_sample(ident:int,body:SampleInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 if body.build_vector and version().startswith('upstream:') and not body.consent:raise APIError(400,'VECTOR_CONSENT_REQUIRED','构建上游向量可能产生费用，请明确确认')
 await lock(db);r=await db.scalar(select(AuditSample).where(AuditSample.id==ident).with_for_update())
 if not r:raise APIError(404,'COMPLIANCE_NOT_FOUND','审核样本不存在')
 changed=r.text!=body.text
 for k,v in body.model_dump(exclude={'policy_id','build_vector','consent'}).items():setattr(r,k,v)
 if changed or body.build_vector:
  r.text_hash=hashlib.sha256(body.text.encode()).hexdigest();r.revision+=1;r.vector_status='pending' if body.build_vector else 'not_built';r.vector_error=None;r.job_started_at=None
 if 'policy_id' in body.model_fields_set:
  try:await assign(db,r,body.policy_id,'sample_ids')
  except IntegrityError:await db.rollback();raise APIError(409,'COMPLIANCE_DUPLICATE','样本文本重复') from None
 return await finish(db,r,actor,request,'update_audit_sample')
@router.post('/samples/{ident}/vectorize')
async def retry(ident:int,request:Request,body:dict|None=None,actor=Depends(administrator),db=Depends(get_session)):
 return await build_samples(BuildInput(ids=[ident],consent=bool(body and body.get('consent') is True)),request,actor,db)
@router.get('/policies')
async def policies(actor=Depends(administrator),db=Depends(get_session),q:str=Query('',max_length=80),status:Literal['','enabled','disabled']=''):
 query=select(CompliancePolicy)
 if q:query=query.where(CompliancePolicy.name.icontains(q,autoescape=True))
 if status:query=query.where(CompliancePolicy.status==status)
 items=[public(r) for r in (await db.scalars(query.order_by(CompliancePolicy.id))).all()]
 return {'data':{'items':items,'total':len(items)}}
async def save_policy(body,request,actor,db,ident=None):
 await lock(db)
 if ident:r=await row(db,CompliancePolicy,ident)
 else:await limit(db,CompliancePolicy,100);r=CompliancePolicy()
 for model,ids in ((AuditWord,body.word_ids),(AuditSample,body.sample_ids),(UserGroup,body.group_ids)):
  if ids and await db.scalar(select(func.count()).select_from(model).where(model.id.in_(ids)))!=len(ids):raise APIError(400,'COMPLIANCE_REFERENCE_INVALID','引用资源不存在')
 if body.models and await db.scalar(select(func.count()).select_from(LogicalModel).where(LogicalModel.name.in_(body.models)))!=len(body.models):raise APIError(400,'COMPLIANCE_REFERENCE_INVALID','引用模型不存在')
 values=body.model_dump(exclude_unset=bool(ident))
 for k,v in values.items():setattr(r,k,v)
 if not ident:db.add(r)
 return await finish(db,r,actor,request,'update_compliance_policy' if ident else 'create_compliance_policy')
@router.post('/policies')
async def add_policy(body:PolicyInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await save_policy(body,request,actor,db)
@router.put('/policies/{ident}')
async def edit_policy(ident:int,body:PolicyInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await save_policy(body,request,actor,db,ident)
@router.patch('/{resource}/{ident}/status')
async def state(resource:Literal['words','samples','policies'],ident:int,body:StateInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 await lock(db);r=await row(db,{'words':AuditWord,'samples':AuditSample,'policies':CompliancePolicy}[resource],ident);r.status=body.status
 return await finish(db,r,actor,request,'toggle_compliance_'+resource)
async def remove(model,ident,request,actor,db,source=None):
 await lock(db);r=await row(db,model,ident)
 if model is CompliancePolicy:
  if r.word_ids or r.sample_ids:raise APIError(409,'COMPLIANCE_IN_USE','策略组仍有敏感词或样本，请先移除或转移')
 elif source:
  for p in (await db.scalars(select(CompliancePolicy))).all():
   if ident in getattr(p,source):setattr(p,source,[i for i in getattr(p,source) if i!=ident])
 audit(db,actor.id,'delete_'+model.__tablename__,ident,request.client.host if request.client else None,resource_type='compliance');await db.delete(r);await db.commit();return {'data':{'deleted':True}}
@router.delete('/words/{ident}')
async def del_word(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await remove(AuditWord,ident,request,actor,db,'word_ids')
@router.delete('/samples/{ident}')
async def del_sample(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await remove(AuditSample,ident,request,actor,db,'sample_ids')
@router.delete('/policies/{ident}')
async def del_policy(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await remove(CompliancePolicy,ident,request,actor,db)
@router.get('/logs')
async def logs(actor=Depends(administrator),db=Depends(get_session),page:int=Query(1,ge=1,le=10000),request_id:str=Query('',max_length=80),q:str=Query('',max_length=256),action:Literal['','audit','block','pass']='',risk:Literal['','low','medium','high','critical']='',source:Literal['','word','sample']='',policy_id:int|None=Query(None,gt=0),start:datetime|None=None,end:datetime|None=None):
 clauses=['TRUE'];params={}
 if request_id:clauses.append('l.request_id=:request_id');params['request_id']=request_id
 else:
  end=end or datetime.now(timezone.utc);start=start or end-timedelta(days=7)
  if not start.tzinfo or not end.tzinfo or start>=end or end-start>timedelta(days=31):raise APIError(400,'COMPLIANCE_TIME_INVALID','时间范围须有时区且不超过31天')
  clauses.append('l.created_at>=:start AND l.created_at<:end');params.update(start=start,end=end)
 if action:clauses.append('l.action=:action');params['action']=action
 if q:
  clauses.append("(l.request_id ILIKE :q OR l.model ILIKE :q OR l.matches::text ILIKE :q)")
  params['q']='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
 if policy_id:clauses.append("EXISTS (SELECT 1 FROM jsonb_array_elements(l.matches) p WHERE p->>'policy_id'=:policy)");params['policy']=str(policy_id)
 if risk or source:
  conditions=[]
  if risk:conditions.append("COALESCE(p->>'risk',e->>'risk')=:risk");params['risk']=risk
  if source:conditions.append("e->>'source'=:source");params['source']=source
  clauses.append("EXISTS (SELECT 1 FROM jsonb_array_elements(l.matches) p CROSS JOIN LATERAL jsonb_array_elements(p->'evidence') e WHERE "+' AND '.join(conditions)+')')
 where=' AND '.join(clauses)
 total=await db.scalar(text('SELECT count(*) FROM compliance_logs l WHERE '+where),params);params['offset']=(page-1)*20
 items=[dict(r) for r in (await db.execute(text('SELECT l.* FROM compliance_logs l WHERE '+where+' ORDER BY l.id DESC OFFSET :offset LIMIT 20'),params)).mappings()]
 return {'data':{'items':items,'total':total}}
