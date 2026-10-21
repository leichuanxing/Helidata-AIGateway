"""Owner-scoped, bounded playground transcripts; no attachment bytes or API keys."""
import json
from datetime import datetime
from uuid import UUID
from typing import Literal
from fastapi import APIRouter,Depends,Query
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator
from sqlalchemy import select,delete,func,Text,String,DateTime,ForeignKey,Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column,defer
from app.models.user import Base,User
from app.core.dependencies import administrator
from app.core.database import get_session
from app.core.security import now
from app.core.exceptions import APIError

class ChatHistory(Base):
 __tablename__='chat_test_history'
 __table_args__=(Index('ix_chat_history_owner_updated','user_id','updated_at'),)
 id:Mapped[str]=mapped_column(String(36),primary_key=True)
 user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),nullable=False)
 title:Mapped[str]=mapped_column(String(100))
 model:Mapped[str]=mapped_column(String(100))
 model_type:Mapped[str]=mapped_column(String(20))
 transcript:Mapped[dict]=mapped_column(JSONB)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
 updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class Strict(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class AttachmentInfo(Strict):
 name:str=Field(max_length=200)
 size:int=Field(ge=0,le=3*1024*1024)
 kind:Literal['image','pdf','text']
class HistoryUsage(Strict):
 input_tokens:int|None=Field(default=None,ge=0,le=10**12)
 output_tokens:int|None=Field(default=None,ge=0,le=10**12)
 total_tokens:int|None=Field(default=None,ge=0,le=10**12)
 image_count:int|None=Field(default=None,ge=0,le=10)
class HistoryTurn(Strict):
 kind:Literal['chat','image']='chat'
 usage:HistoryUsage|None=None
 prompt:str=Field(max_length=16000)
 answer:str=Field(default='',max_length=1024*1024)
 reasoning:str=Field(default='',max_length=1024*1024)
 status:Literal['done','error','cancelled']
 error:str=Field(default='',max_length=4000)
 requestId:str=Field(default='',max_length=80)
 compliance:str=Field(default='',max_length=40)
 elapsed:int=Field(default=0,ge=0,le=86400000)
 rounds:int=Field(default=0,ge=0,le=1000)
 finish:str=Field(default='',max_length=100)
 attachments:list[AttachmentInfo]=Field(default_factory=list,max_length=4)
 images:list[str]=Field(default_factory=list,max_length=4)
 @field_validator('images')
 @classmethod
 def urls(cls,values):
  from urllib.parse import urlsplit
  for value in values:
   try:
    url=urlsplit(value)
    if len(value)>16384 or url.scheme not in ('http','https') or not url.hostname or url.username or url.password:raise ValueError()
   except ValueError:raise ValueError('invalid image URL') from None
  return values
class Parameters(Strict):
 system:str=Field(default='',max_length=16000)
 temperature:float=Field(default=.7,ge=0,le=2)
 max_tokens:int=Field(default=5000,ge=1,le=65535)
 stream:bool=True
 image_count:int=Field(default=1,ge=1,le=4)
 image_size:str=Field(default='',max_length=32)
class HistoryInput(Strict):
 model:str=Field(min_length=1,max_length=100)
 model_type:Literal['text','reasoning','multimodal','image']
 parameters:Parameters
 turns:list[HistoryTurn]=Field(min_length=1,max_length=100)
 @model_validator(mode='after')
 def bounded(self):
  if len(json.dumps(self.model_dump(),ensure_ascii=False).encode())>4*1024*1024:raise ValueError('history exceeds 4 MiB')
  return self
router=APIRouter(prefix='/api/admin/chat-test/history',tags=['对话测试历史'])
def summary(row):
 return {k:getattr(row,k) for k in ('id','title','model','model_type','created_at','updated_at')}
async def owned(db,ident,user):
 row=await db.scalar(select(ChatHistory).where(ChatHistory.id==str(ident),ChatHistory.user_id==user.id))
 if not row:raise APIError(404,'CHAT_HISTORY_NOT_FOUND','对话历史不存在或已删除')
 return row
@router.get('')
async def listing(page:int=Query(1,ge=1,le=100),page_size:int=Query(20,ge=1,le=50),q:str=Query('',max_length=100),user=Depends(administrator),db=Depends(get_session)):
 query=select(ChatHistory).where(ChatHistory.user_id==user.id)
 if q:query=query.where(ChatHistory.title.contains(q,autoescape=True)|ChatHistory.model.contains(q,autoescape=True))
 total=await db.scalar(select(func.count()).select_from(query.with_only_columns(ChatHistory.id).subquery()))
 rows=(await db.scalars(query.options(defer(ChatHistory.transcript,raiseload=True)).order_by(ChatHistory.updated_at.desc(),ChatHistory.id).offset((page-1)*page_size).limit(page_size))).all()
 return {'data':{'items':[summary(r) for r in rows],'total':total}}
@router.get('/{ident}')
async def detail(ident:UUID,user=Depends(administrator),db=Depends(get_session)):
 row=await owned(db,ident,user)
 return {'data':{**summary(row),**row.transcript}}
@router.put('/{ident}')
async def save(ident:UUID,body:HistoryInput,user=Depends(administrator),db=Depends(get_session)):
 # Serialize owner updates, eviction and deletion across workers.
 await db.scalar(select(User.id).where(User.id==user.id).with_for_update())
 row=await db.get(ChatHistory,str(ident))
 if row and row.user_id!=user.id:raise APIError(404,'CHAT_HISTORY_NOT_FOUND','对话历史不存在或已删除')
 if not row:
  row=ChatHistory(id=str(ident),user_id=user.id);db.add(row)
 row.model=body.model;row.model_type=body.model_type;row.title=body.turns[0].prompt[:100] or '附件测试'
 row.transcript={'parameters':body.parameters.model_dump(),'turns':[t.model_dump() for t in body.turns]};row.updated_at=now()
 await db.flush()
 stale=select(ChatHistory.id).where(ChatHistory.user_id==user.id).order_by(ChatHistory.updated_at.desc(),ChatHistory.id).offset(50)
 await db.execute(delete(ChatHistory).where(ChatHistory.id.in_(stale)))
 await db.commit()
 return {'data':summary(row)}
@router.delete('/{ident}')
async def remove(ident:UUID,user=Depends(administrator),db=Depends(get_session)):
 await db.scalar(select(User.id).where(User.id==user.id).with_for_update())
 row=await owned(db,ident,user);await db.delete(row);await db.commit()
 return {'data':{'deleted':True}}
