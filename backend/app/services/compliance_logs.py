"""Best-effort audit delivery with protected disk outbox and idempotent replay."""
import asyncio,json,os,logging
from pathlib import Path
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert
from app.core.database import session_factory
from app.models.compliance import ComplianceLog
ROOT=Path('/data/logs/compliance-outbox')
logger=logging.getLogger(__name__)
async def persist(record):
 async with asyncio.timeout(2):
  async with session_factory.begin() as db:
   await db.execute(insert(ComplianceLog).values(**record).on_conflict_do_nothing(index_elements=['request_id']))
def spool(record):
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(ROOT,0o700)
 target=ROOT/(record['request_id']+'.json');temporary=ROOT/(record['request_id']+'.tmp')
 with temporary.open('w',encoding='utf-8') as f:
  os.chmod(temporary,0o600);json.dump(record,f,ensure_ascii=False,default=lambda v:v.isoformat());f.flush();os.fsync(f.fileno())
 os.replace(temporary,target)
async def write(record):
 try:await persist(record);return 'stored'
 except Exception:
  try:await asyncio.to_thread(spool,record);return 'pending'
  except Exception:logger.error('Compliance audit unavailable');return 'unavailable'
async def replay():
 while True:
  try:
   if ROOT.exists():
    for path in sorted(ROOT.glob('req_*.json'))[:100]:
     data=json.loads(path.read_text(encoding='utf-8'));data['created_at']=datetime.fromisoformat(data['created_at']);await persist(data);path.unlink()
  except asyncio.CancelledError:raise
  except Exception:pass
  await asyncio.sleep(5)
