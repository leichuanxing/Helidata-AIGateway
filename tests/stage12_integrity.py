"""Host final evidence and cleanup limited to owned acceptance fixtures."""
import hashlib
import json
from pathlib import Path
import subprocess

APP='helidata-ai-gateway'
def run(code,data=None):
    result=subprocess.run(['docker','exec','-i',APP,'python','-c',code],input=data,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return result.stdout

ids=[line.split('=',1)[1].strip() for line in Path('acceptance-stage12-streaming.log').read_text().splitlines() if line.startswith('CANCEL_REQUEST_ID=')]
assert len(ids)==13
logs=subprocess.check_output(['docker','logs',APP],stderr=subprocess.STDOUT,text=True)
for rid in ids:
    rows=[line for line in logs.splitlines() if 'app.gateway.calls' in line and 'request_id='+rid+' ' in line]
    assert len(rows)==1,(rid,len(rows))
    assert json.loads(rows[0][rows[0].index('{'):])['outcome']=='client_cancelled'

code='''import asyncio,json,sys
from datetime import datetime,timezone
from sqlalchemy import delete,select,func,text
from app.core.database import session_factory
from app.models.call_log import CallLog
from app.models.user import User,UserGroup,ApiKey,Provider
from app.models.quota import QuotaReservation
from app.core.redis import redis_client
from app.gateway.provider_concurrency import LOAD
async def main():
 ids=json.loads(sys.stdin.read())
 async with session_factory() as db:
  rows=(await db.scalars(select(CallLog).where(CallLog.request_id.in_(ids)))).all()
  assert len(rows)==13 and all(row.status=='client_cancelled' and row.error_code=='CLIENT_DISCONNECTED' for row in rows)
  assert sum(row.http_status==200 and row.stream for row in rows)==12 and sum(row.http_status==499 for row in rows)==1
  for code in ('QUEUE_FULL','QUEUE_TIMEOUT'):
   row=await db.scalar(select(CallLog).where(CallLog.error_code==code,CallLog.request_model.startswith('stage12_',autoescape=True)).order_by(CallLog.id.desc()).limit(1))
   assert row is not None and 'concurrency' in row.trace['stages'] and row.trace['stages'][-2:]==['usage','call_log']
 print('PASS:13 unique durable cancellations:12 SSE200 and1 pre-header499; queue errors include concurrency and terminal stages')
 async with session_factory.begin() as db:
  # The two anonymous model-auth probes are identified by their captured test IDs and precise Core run interval.
  anonymous=['req_a4f57c35f3b940e0815c2965e74a1c2b','req_bcbd1393384743848097b4286b06f0ec']
  rows=(await db.scalars(select(CallLog).where(CallLog.request_id.in_(anonymous)))).all()
  for row in rows:
   assert row.operation=='models' and row.error_code=='INVALID_API_KEY' and row.user_id is None and row.client_ip=='127.0.0.1'
   assert datetime(2026,10,4,17,44,46,tzinfo=timezone.utc)<=row.created_at<datetime(2026,10,4,17,44,47,tzinfo=timezone.utc)
  owned=(CallLog.username_snapshot.startswith('stage12_',autoescape=True)|CallLog.username_snapshot.startswith('stage12core_',autoescape=True)|
      CallLog.request_model.startswith('stage12_',autoescape=True)|CallLog.request_model.startswith('stage12core_',autoescape=True)|CallLog.request_id.in_(anonymous))
  await db.execute(delete(CallLog).where(owned))
  await db.execute(delete(User).where(User.username=='stage12_ui_20261005'))
 async with session_factory() as db:
  assert await db.scalar(text('SELECT version_num FROM alembic_version'))=='0008'
  assert await db.scalar(select(func.count()).select_from(User).where(User.username.startswith('stage12_',autoescape=True)|User.username.startswith('stage12core_',autoescape=True)))==0
  assert await db.scalar(select(func.count()).select_from(Provider).where(Provider.name.startswith('stage12_',autoescape=True)|Provider.name.startswith('stage12core_',autoescape=True)))==0
  print('PASS: owned test users/Providers/call logs removed; migration0008; remaining call_logs='+str(await db.scalar(select(func.count()).select_from(CallLog))))
  print('quota_reservations='+str(await db.scalar(select(func.count()).select_from(QuotaReservation))))
  print('enabled_real_providers='+str(await db.scalar(select(func.count()).select_from(Provider).where(Provider.status=='enabled'))))
  valid={'provider':set((await db.scalars(select(Provider.id))).all()),'apikey':set((await db.scalars(select(ApiKey.id))).all()),'group':set((await db.scalars(select(UserGroup.id))).all())}
 keys=[]
 async for k in redis_client.scan_iter(match='sticky:*'):
  if int(k.split(':')[1]) not in valid['apikey']:keys.append(k)
 for kind in valid:
  async for k in redis_client.scan_iter(match=kind+':*:concurrency'):
   assert await redis_client.eval(LOAD,1,k)==0
   if int(k.split(':')[1]) not in valid[kind]:keys.append(k)
 if keys:await redis_client.delete(*keys)
 assert await redis_client.eval(LOAD,1,'gateway:concurrency')==0 and await redis_client.zcard('gateway:queue')==0
 await redis_client.aclose()
 print('PASS: global active=0/queued=0; remaining four-level counts0; only orphan fixture Sticky/counter keys removed')
asyncio.run(main())'''
evidence=run(code,json.dumps(ids))
Path('acceptance-stage12-cancellation-log.txt').write_text('PASS:13 final-container stdout terminal records, exactly one per Request ID.\n'+evidence.splitlines()[0]+'\n')
print(evidence,end='')
raw=subprocess.check_output(['docker','exec',APP,'runuser','-u','postgres','--','psql','-d','helidata_gateway','-At','-c',
    'SELECT id,username,password_hash,role,status,must_change_password,created_at,auth_version FROM users ORDER BY id'])
assert hashlib.sha256(raw).hexdigest()==Path('.deployment/stage12-users-before.sha256').read_text().split()[0]
print('PASS: original users and password state unchanged')
print(run("from app.core.config import get_settings\ns=get_settings().gateway\nassert (s.max_concurrency,s.queue_size,s.queue_timeout,s.stream_idle_timeout)==(500,1000,30,300)\nfrom pathlib import Path\np=Path('/data/logs/call-log-outbox')\nassert p.stat().st_mode&0o777==0o700 and not list(p.glob('*.json'))\nprint('PASS: config500/1000/30/300 restored, protected outbox has no pending JSON records')"),end='')
assert not list(Path('.deployment').glob('stage12-startup-*'))
print('PASS: isolated startup volumes removed')
print(subprocess.check_output(['curl','-fsS','http://127.0.0.1:18080/health/detail'],text=True))
print(subprocess.check_output(['docker','ps','--format','{{.Names}} {{.Status}}'],text=True))
