"""Bounded administrator-only source, policy and audit management."""
import hashlib,math
from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,Query,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from sqlalchemy import select,delete,func,text
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.compliance import AuditWord,AuditSample,CompliancePolicy,ComplianceLog,AuditVector
from app.models.user import UserGroup,LogicalModel
from app.services.compliance_sources import validate_pattern
from app.services.local_embedding import VERSION
from app.services.sessions import audit
router=APIRouter(prefix='/api/admin/compliance',tags=['内容合规'])
class Input(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class WordInput(Input):
 pattern:str=Field(min_length=1,max_length=256)
 kind:Literal['text','wildcard','regex']='text'
 risk:Literal['low','medium','high']='medium'
 status:Literal['enabled','disabled']='enabled'
 @model_validator(mode='after')
 def valid(self):validate_pattern(self.kind,self.pattern);return self
class SampleInput(Input):
 text:str=Field(min_length=1,max_length=2000)
 risk:Literal['low','medium','high']='medium'
class PolicyInput(Input):
 name:str=Field(min_length=1,max_length=80)
 action:Literal['audit','block']='audit'
 status:Literal['enabled','disabled']='disabled'
 word_ids:list[int]=Field(default_factory=list,max_length=100)
 sample_ids:list[int]=Field(default_factory=list,max_length=100)
 group_ids:list[int]=Field(default_factory=list,max_length=100)
 models:list[str]=Field(default_factory=list,max_length=100)
 threshold:float=Field(default=.85,ge=0,le=1,allow_inf_nan=False)
 @field_validator('word_ids','sample_ids','group_ids',mode='before')
 @classmethod
 def ids(cls,values):
  if not isinstance(values,list) or any(type(v) is not int or v<=0 for v in values) or len(set(values))!=len(values):raise ValueError('ID须为唯一正整数')
  return values
 @field_validator('models')
 @classmethod
 def names(cls,values):
  if any(not v.strip() or len(v)>100 for v in values) or len(set(values))!=len(values):raise ValueError('模型名无效或重复')
  return values
 @model_validator(mode='after')
 def sources(self):
  if not self.word_ids and not self.sample_ids:raise ValueError('策略至少引用一个敏感词或样本')
  return self

def public(row):return {c.name:getattr(row,c.name) for c in row.__table__.columns}
async def lock(db):await db.execute(text('SELECT pg_advisory_xact_lock(71017)'))
async def row(db,model,ident):
 r=await db.get(model,ident)
 if r is None:raise APIError(404,'COMPLIANCE_NOT_FOUND','审核资源不存在')
 return r
async def finish(db,r,actor,request,action):
 try:
  await db.flush()
  audit(db,actor.id,action,r.id,request.client.host if request.client else None,resource_type='compliance')
  await db.flush();await db.refresh(r);result=public(r);await db.commit();return {'data':result}
 except IntegrityError:
  await db.rollback();raise APIError(409,'COMPLIANCE_DUPLICATE','资源名称或样本文本重复') from None
async def limit(db,model,cap):
 if await db.scalar(select(func.count()).select_from(model))>=cap:raise APIError(400,'COMPLIANCE_LIMIT','审核资源数量已达上限')
@router.get('/words')
async def words(actor=Depends(administrator),db=Depends(get_session)):
 return {'data':{'items':[public(r) for r in (await db.scalars(select(AuditWord).order_by(AuditWord.id))).all()]}}
@router.post('/words')
async def add_word(body:WordInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 await lock(db);await limit(db,AuditWord,500);r=AuditWord(**body.model_dump());db.add(r);return await finish(db,r,actor,request,'create_audit_word')
@router.put('/words/{ident}')
async def edit_word(ident:int,body:WordInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 await lock(db);r=await row(db,AuditWord,ident)
 for k,v in body.model_dump().items():setattr(r,k,v)
 return await finish(db,r,actor,request,'update_audit_word')
@router.get('/samples')
async def samples(actor=Depends(administrator),db=Depends(get_session),page:int=Query(1,ge=1,le=10000),status:Literal['','pending','processing','ready','failed']=''):
 q=select(AuditSample)
 if status:q=q.where(AuditSample.vector_status==status)
 total=await db.scalar(select(func.count()).select_from(q.subquery()))
 return {'data':{'items':[public(r) for r in (await db.scalars(q.order_by(AuditSample.id.desc()).offset((page-1)*20).limit(20))).all()],'total':total,'model_version':VERSION}}
@router.post('/samples')
async def add_sample(body:SampleInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 await lock(db);await limit(db,AuditSample,500);r=AuditSample(**body.model_dump(),text_hash=hashlib.sha256(body.text.encode()).hexdigest());db.add(r);return await finish(db,r,actor,request,'create_audit_sample')
@router.put('/samples/{ident}')
async def edit_sample(ident:int,body:SampleInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 await lock(db);r=await db.scalar(select(AuditSample).where(AuditSample.id==ident).with_for_update())
 if not r:raise APIError(404,'COMPLIANCE_NOT_FOUND','审核样本不存在')
 r.text=body.text;r.risk=body.risk;r.text_hash=hashlib.sha256(body.text.encode()).hexdigest();r.revision+=1;r.vector_status='pending';r.vector_error=None;r.job_started_at=None
 return await finish(db,r,actor,request,'update_audit_sample')
@router.post('/samples/{ident}/vectorize')
async def retry(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):
 await lock(db);r=await db.scalar(select(AuditSample).where(AuditSample.id==ident).with_for_update())
 if not r:raise APIError(404,'COMPLIANCE_NOT_FOUND','审核样本不存在')
 r.revision+=1;r.vector_status='pending';r.vector_error=None;r.job_started_at=None
 return await finish(db,r,actor,request,'retry_audit_sample')
@router.get('/policies')
async def policies(actor=Depends(administrator),db=Depends(get_session)):
 return {'data':{'items':[public(r) for r in (await db.scalars(select(CompliancePolicy).order_by(CompliancePolicy.id))).all()]}}
async def save_policy(body,request,actor,db,ident=None):
 await lock(db)
 if ident:r=await row(db,CompliancePolicy,ident)
 else:await limit(db,CompliancePolicy,100);r=CompliancePolicy()
 for model,ids in ((AuditWord,body.word_ids),(AuditSample,body.sample_ids),(UserGroup,body.group_ids)):
  if ids and await db.scalar(select(func.count()).select_from(model).where(model.id.in_(ids)))!=len(ids):raise APIError(400,'COMPLIANCE_REFERENCE_INVALID','引用资源不存在')
 if body.models and await db.scalar(select(func.count()).select_from(LogicalModel).where(LogicalModel.name.in_(body.models)))!=len(body.models):raise APIError(400,'COMPLIANCE_REFERENCE_INVALID','引用模型不存在')
 if body.status=='enabled':
  if body.sample_ids:
   ready=await db.scalar(select(func.count()).select_from(AuditSample).join(AuditVector,AuditVector.sample_id==AuditSample.id).where(AuditSample.id.in_(body.sample_ids),AuditSample.vector_status=='ready',AuditVector.sample_revision==AuditSample.revision,AuditVector.model_version==VERSION))
   if ready!=len(body.sample_ids):raise APIError(409,'COMPLIANCE_SAMPLES_NOT_READY','启用前须等待所有审核样本向量就绪')
  elif not await db.scalar(select(func.count()).select_from(AuditWord).where(AuditWord.id.in_(body.word_ids),AuditWord.status=='enabled')):raise APIError(400,'COMPLIANCE_NO_ENABLED_RULE','策略至少需要一条启用规则')
 for k,v in body.model_dump().items():setattr(r,k,v)
 if not ident:db.add(r)
 return await finish(db,r,actor,request,'update_compliance_policy' if ident else 'create_compliance_policy')
@router.post('/policies')
async def add_policy(body:PolicyInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await save_policy(body,request,actor,db)
@router.put('/policies/{ident}')
async def edit_policy(ident:int,body:PolicyInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await save_policy(body,request,actor,db,ident)
async def remove(model,ident,request,actor,db,source=None):
 await lock(db);r=await row(db,model,ident)
 if source:
  refs=(await db.scalars(select(CompliancePolicy))).all()
  if any(ident in getattr(p,source) for p in refs):raise APIError(409,'COMPLIANCE_IN_USE','资源已被策略引用，请先修改或删除策略')
 audit(db,actor.id,'delete_'+model.__tablename__,ident,request.client.host if request.client else None,resource_type='compliance');await db.delete(r);await db.commit();return {'data':{'deleted':True}}
@router.delete('/words/{ident}')
async def del_word(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await remove(AuditWord,ident,request,actor,db,'word_ids')
@router.delete('/samples/{ident}')
async def del_sample(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await remove(AuditSample,ident,request,actor,db,'sample_ids')
@router.delete('/policies/{ident}')
async def del_policy(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):return await remove(CompliancePolicy,ident,request,actor,db)
@router.get('/logs')
async def logs(actor=Depends(administrator),db=Depends(get_session),page:int=Query(1,ge=1,le=10000),request_id:str=Query('',max_length=80),action:Literal['','audit','block']='',start:datetime|None=None,end:datetime|None=None):
 q=select(ComplianceLog)
 if request_id:q=q.where(ComplianceLog.request_id==request_id)
 else:
  end=end or datetime.now(timezone.utc);start=start or end-timedelta(days=7)
  if not start.tzinfo or not end.tzinfo or start>=end or end-start>timedelta(days=31):raise APIError(400,'COMPLIANCE_TIME_INVALID','时间范围须有时区且不超过31天')
  q=q.where(ComplianceLog.created_at>=start,ComplianceLog.created_at<end)
 if action:q=q.where(ComplianceLog.action==action)
 total=await db.scalar(select(func.count()).select_from(q.subquery()))
 return {'data':{'items':[public(r) for r in (await db.scalars(q.order_by(ComplianceLog.id.desc()).offset((page-1)*20).limit(20))).all()],'total':total}}
