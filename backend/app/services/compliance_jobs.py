import asyncio,hashlib
from datetime import timedelta
from sqlalchemy import select,update,text
from app.core.database import session_factory
from app.core.security import now
from app.models.compliance import AuditSample
from app.services.local_embedding import embed,VERSION
from app.services.route_vectors import encode_vector
async def step():
 async with session_factory.begin() as db:
  await db.execute(update(AuditSample).where(AuditSample.vector_status=='processing',AuditSample.job_started_at<now()-timedelta(seconds=60)).values(vector_status='pending',revision=AuditSample.revision+1,job_started_at=None))
  row=await db.scalar(select(AuditSample).where(AuditSample.vector_status=='pending').order_by(AuditSample.id).limit(1).with_for_update(skip_locked=True))
  if not row:return False
  row.vector_status='processing';row.job_started_at=now();ident,revision,content=row.id,row.revision,row.text
 try:
  vectors=await embed(content)
  import numpy as np
  vector,_=encode_vector(np.mean(vectors,axis=0).tolist())
  async with session_factory.begin() as db:
   row=await db.scalar(select(AuditSample).where(AuditSample.id==ident).with_for_update())
   if row and row.revision==revision and row.vector_status=='processing':
    await db.execute(text('INSERT INTO review_vectors(sample_id,embedding,model_version,sample_revision) VALUES (:id,CAST(:v AS vector),:m,:r) ON CONFLICT(sample_id) DO UPDATE SET embedding=EXCLUDED.embedding,model_version=EXCLUDED.model_version,sample_revision=EXCLUDED.sample_revision'),dict(id=ident,v=vector,m=VERSION,r=revision))
    row.vector_status='ready';row.vector_error=None
 except asyncio.CancelledError:raise
 except Exception as error:
  code=getattr(error,'detail',{}).get('code','COMPLIANCE_VECTORIZATION_FAILED')
  async with session_factory.begin() as db:
   await db.execute(update(AuditSample).where(AuditSample.id==ident,AuditSample.revision==revision,AuditSample.vector_status=='processing').values(vector_status='failed',vector_error=code))
 return True
async def loop():
 while True:
  try:work=await step()
  except asyncio.CancelledError:raise
  except Exception:work=False
  await asyncio.sleep(.1 if work else 1)
