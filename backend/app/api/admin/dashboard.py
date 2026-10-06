import asyncio
from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends
from sqlalchemy import select,func,text,case
from redis.exceptions import RedisError
from app.core.dependencies import administrator
from app.core.database import get_session
from app.core.config import get_settings
from app.models.user import Provider,UserGroup
from app.gateway.provider_health import state
from app.services.usage import statistics,ZONE
from app.services.dashboard import rankings
from app.services import dashboard_live
from app.services.group_access import concurrency_limits
router=APIRouter(prefix='/api/admin/dashboard',tags=['Dashboard'])

@router.get('')
async def dashboard(period:Literal['1h','24h','7d','30d']='24h',actor=Depends(administrator),db=Depends(get_session)):
    end=datetime.now(timezone.utc);start=end-timedelta(hours={'1h':1,'24h':24,'7d':168,'30d':720}[period])
    today=end.astimezone(ZONE).replace(hour=0,minute=0,second=0,microsecond=0);grain='hour' if period in ('1h','24h') else 'day'
    await db.commit()
    async with db.begin():
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        usage=await statistics(db,start,end,grain,{})
        today_usage=await statistics(db,today,end,'hour',{})
        rank=await rankings(db,start,end,grain)
        providers=(await db.scalars(select(Provider).where(Provider.deleted_at.is_(None)).order_by(case((Provider.health_status=='unhealthy',0),else_=1),Provider.id).limit(100))).all()
        groups=(await db.scalars(select(UserGroup).order_by(UserGroup.id).limit(100))).all()
        provider_total=await db.scalar(select(func.count()).select_from(Provider).where(Provider.deleted_at.is_(None)))
        group_total=await db.scalar(select(func.count()).select_from(UserGroup))
        ids=[int(r['dimension']) for r in rank['provider'] if r['dimension'] and r['dimension']!='0']
        names=dict((await db.execute(select(Provider.id,Provider.name).where(Provider.id.in_(ids),Provider.deleted_at.is_(None)))).all()) if ids else {}
    for row in rank['provider']:
        identity=int(row['dimension']) if row['dimension'] is not None else None
        row['provider_id']=identity if identity and identity in names else None
        row['label']='其他' if row['other'] else names.get(identity,'未选择账号' if identity==0 else f'已删除账号 #{identity}')
    for row in rank['model']:row['label']='其他' if row['other'] else row['dimension'] or '未选择模型'
    cfg=get_settings().gateway
    live={'available':False,'active':None,'streaming':None,'queued':None,'timestamp':None,'max_concurrency':cfg.max_concurrency,'queue_size':cfg.queue_size}
    history=[];history_available=True;counts={}
    history_grain='minute' if period=='1h' else grain
    slots=[f'provider:{p.id}:concurrency' for p in providers]+[f'group:{g.id}:concurrency' for g in groups]
    try:
        measured=await dashboard_live.snapshot(slots);counts=dict(zip(slots,measured.pop('loads')));live.update(measured,available=True)
    except RedisError:pass
    try:history=await dashboard_live.history(start,end,history_grain)
    except RedisError:history_available=False
    return {'data':{'period':period,'start':start,'end':end,'timezone':'Asia/Shanghai','grain':grain,
        'summary':usage['summary'],'today':today_usage['summary'],'today_start':today,'series':usage['series'],
        'rankings':rank,'live':live,'concurrency_series':history,'concurrency_grain':history_grain,'history_available':history_available,
        'concurrency_note':'每10秒采样，按分钟记录峰值，保留31天；图表展示时段内已采样峰值，空缺表示未采集。',
        'providers':[{'id':p.id,'name':p.name,'status':p.status,'health_status':p.health_status,'scheduling_state':state(p),'current_concurrency':counts.get(f'provider:{p.id}:concurrency'),'max_concurrency':p.max_concurrency} for p in providers],
        'groups':[{'id':g.id,'name':g.name,'status':g.status,'current_concurrency':counts.get(f'group:{g.id}:concurrency'),'max_concurrency':concurrency_limits(g,cfg.max_concurrency)[0]} for g in groups],
        'provider_total':provider_total,'group_total':group_total,'resource_limit':100}}
