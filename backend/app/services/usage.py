"""Atomic aggregates. Exact partial-hour edges read only bounded indexed logs."""
from datetime import timezone,timedelta
from sqlalchemy import text,select
from app.core.exceptions import APIError

DIMS=('user_id','user_group_id','api_key_id','provider_id','request_model','logical_model','protocol','operation')
TOKENS=('input_tokens','output_tokens','cached_tokens','total_tokens')
COUNTERS=('requests','success','failure','usage_unavailable')+tuple(x+y for x in TOKENS for y in ('_sum','_count'))+('ttft_sum','ttft_count','tps_sum','tps_count')
ZONE=timezone(timedelta(hours=8))
BREAKDOWN_DIMS=('request_model','logical_model','provider_id','user_id','user_group_id','api_key_id','protocol','operation')


def contribution(record):
    result={'requests':1,'success':int(record['status']=='success'),'failure':int(record['status']!='success'),
        'usage_unavailable':int(any(record.get(x) is None for x in ('input_tokens','output_tokens','total_tokens')))}
    for field in TOKENS:
        value=record.get(field);result[field+'_sum']=value or 0;result[field+'_count']=int(value is not None)
    for prefix,field in [('ttft','ttft_ms'),('tps','tokens_per_second')]:
        value=record.get(field);result[prefix+'_sum']=value or 0;result[prefix+'_count']=int(value is not None)
    return result


async def accumulate(db,record):
    if record['operation'] not in ('chat','responses','messages','embeddings','rerank','images'):return
    dims={k:record.get(k) or (0 if k.endswith('_id') else '') for k in DIMS}
    values={**dims,**contribution(record)}
    date=record['created_at'].astimezone(ZONE)
    for table,bucket in [('usage_hourly',date.replace(minute=0,second=0,microsecond=0)),('usage_daily',date.replace(hour=0,minute=0,second=0,microsecond=0))]:
        data={**values,'bucket':bucket};columns=list(data)
        sql=f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(':'+k for k in columns)}) ON CONFLICT (bucket,{','.join(DIMS)}) DO UPDATE SET "+','.join(f'{k}={table}.{k}+excluded.{k}' for k in COUNTERS)
        await db.execute(text(sql),data)


def log_projection():
    fields=["created_at AS bucket"]+[f"coalesce({k},{'0' if k.endswith('_id') else chr(39)+chr(39)}) AS {k}" for k in DIMS]
    fields += ["1::bigint AS requests","(status='success')::int AS success","(status<>'success')::int AS failure","(input_tokens IS NULL OR output_tokens IS NULL OR total_tokens IS NULL)::int AS usage_unavailable"]
    for k in TOKENS:fields += [f'coalesce({k},0) AS {k}_sum',f'({k} IS NOT NULL)::int AS {k}_count']
    for prefix,k in [('ttft','ttft_ms'),('tps','tokens_per_second')]:fields += [f'coalesce({k},0) AS {prefix}_sum',f'({k} IS NOT NULL)::int AS {prefix}_count']
    return ','.join(fields)


def source_query(start,end,grain,filters):
    # Fully covered hours use aggregates; at most two partial hours use indexed call_logs.
    lo=start.replace(minute=0,second=0,microsecond=0)
    if lo<start:lo+=timedelta(hours=1)
    hi=end.replace(minute=0,second=0,microsecond=0)
    day_lo=lo.astimezone(ZONE).replace(hour=0,minute=0,second=0,microsecond=0)
    if day_lo<lo:day_lo+=timedelta(days=1)
    day_hi=hi.astimezone(ZONE).replace(hour=0,minute=0,second=0,microsecond=0)
    params={'start':start,'end':end,'lo':lo,'hi':hi,'day_lo':day_lo,'day_hi':day_hi}
    conditions=[]
    for key,value in filters.items():
        if value is None or value=='':continue
        params[key]=value
        conditions.append('(request_model=:model OR logical_model=:model)' if key=='model' else key+'=:'+key)
    where=' AND '.join(conditions) or 'TRUE'
    projection='bucket,'+','.join(DIMS+COUNTERS)
    aggregate=f"SELECT {projection} FROM usage_hourly WHERE bucket>=:lo AND bucket<:hi"
    if grain=="day":aggregate=f"SELECT {projection} FROM usage_daily WHERE bucket>=:day_lo AND bucket<:day_hi UNION ALL SELECT {projection} FROM usage_hourly WHERE bucket>=:lo AND bucket<:hi AND (bucket<:day_lo OR bucket>=:day_hi)"
    cte=f"WITH source AS ({aggregate} UNION ALL SELECT {log_projection()} FROM call_logs WHERE operation IN ('chat','responses','messages','embeddings','rerank','images') AND created_at>=:start AND created_at<least(:lo,:end) UNION ALL SELECT {log_projection()} FROM call_logs WHERE operation IN ('chat','responses','messages','embeddings','rerank','images') AND created_at>=greatest(:hi,:lo,:start) AND created_at<:end), filtered AS (SELECT * FROM source WHERE {where}) "
    return cte,params


def public_metrics(row):
    result={k:int(row[k]) for k in ('requests','success','failure','usage_unavailable','active_users')}
    result['failure_rate']=round(result['failure']/result['requests']*100,3) if result['requests'] else 0
    result['success_rate']=round(result['success']/result['requests']*100,3) if result['requests'] else 0
    result['token_coverage']=round((result['requests']-result['usage_unavailable'])/result['requests']*100,3) if result['requests'] else None
    for k in TOKENS:
        count=int(row[k+'_count']);result[k]=int(row[k+'_sum']) if count or not result['requests'] else None;result[k+'_samples']=count
    for prefix,out in [('ttft','average_ttft_ms'),('tps','average_tokens_per_second')]:
        count=int(row[prefix+'_count']);result[out]=round(float(row[prefix+'_sum'])/count,3) if count else None;result[prefix+'_samples']=count
    return result


async def statistics(db,start,end,grain,filters,dimension=None):
    if dimension is not None and dimension not in BREAKDOWN_DIMS:
        raise APIError(422,'USAGE_DIMENSION_INVALID','不支持的统计维度')
    cte,params=source_query(start,end,grain,filters)
    time=f"date_trunc('{grain}',bucket AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'"
    # One statement snapshot yields internally consistent totals and timeline.
    dim_fields=f',CAST({dimension} AS text) AS dimension_value,grouping({dimension}) AS dimension_total' if dimension else ''
    sets=f'(),({time})'+(f',({dimension})' if dimension else '')
    aggregate=f"SELECT {time} AS bucket,grouping({time}) AS is_summary{dim_fields},count(distinct nullif(user_id,0)) AS active_users,"+','.join(f'coalesce(sum({k}),0) AS {k}' for k in COUNTERS)+f' FROM filtered GROUP BY GROUPING SETS ({sets})'
    if dimension:
        query=cte+', totals AS ('+aggregate+'), ranked AS (SELECT *,row_number() OVER (PARTITION BY is_summary,dimension_total ORDER BY total_tokens_sum DESC,requests DESC,dimension_value) AS rank,count(*) OVER (PARTITION BY is_summary,dimension_total) AS dimension_count FROM totals) SELECT * FROM ranked WHERE is_summary=0 OR dimension_total=1 OR rank<=200 ORDER BY bucket NULLS FIRST,rank'
    else:query=cte+aggregate+' ORDER BY bucket NULLS FIRST'
    rows=(await db.execute(text(query),params)).mappings().all()
    summary=next(public_metrics(r) for r in rows if r['is_summary'] and (not dimension or r['dimension_total']))
    timeline={r['bucket']:public_metrics(r) for r in rows if not r['is_summary']}
    step=timedelta(hours=1) if grain=='hour' else timedelta(days=1)
    bucket=start.astimezone(ZONE).replace(minute=0,second=0,microsecond=0)
    if grain=='day':bucket=bucket.replace(hour=0)
    zero=public_metrics({**dict.fromkeys(COUNTERS,0),'active_users':0})
    series=[]
    while bucket<end:
        series.append({'bucket':bucket,**timeline.get(bucket,zero)});bucket+=step
    breakdown=[{'value':r['dimension_value'],**public_metrics(r)} for r in rows if dimension and r['is_summary'] and not r['dimension_total']]
    total_dimensions=next((int(r['dimension_count']) for r in rows if dimension and r['is_summary'] and not r['dimension_total']),0)
    if dimension:await label_dimensions(db,dimension,breakdown)
    for r in breakdown:
        r['request_share']=round(r['requests']/summary['requests']*100,3) if summary['requests'] else 0
        r['token_share']=round(r['total_tokens']/summary['total_tokens']*100,3) if r['total_tokens'] is not None and summary['total_tokens'] else None
    return {'summary':summary,'series':series,'breakdown':breakdown,'dimension':dimension,'dimension_count':total_dimensions,'breakdown_limit':200,
        'start':start,'end':end,'timezone':'Asia/Shanghai','grain':grain,'operation':filters.get('operation') or 'all_inference','storage':('daily_hourly_with_exact_boundary_logs' if grain=='day' else 'hourly_with_exact_boundary_logs')}


async def label_dimensions(db,dimension,rows):
    from app.models.user import User,UserGroup,ApiKey,Provider
    tables={'user_id':(User,User.username,'未认证 / 系统请求'),'user_group_id':(UserGroup,UserGroup.name,'未分配用户组'),
            'api_key_id':(ApiKey,ApiKey.name,'未使用 API Key'),'provider_id':(Provider,Provider.name,'未选择账号')}
    if dimension in tables:
        model,column,empty=tables[dimension];ids=[int(r['value']) for r in rows if r['value'] and r['value']!='0']
        names=dict((await db.execute(select(model.id,column).where(model.id.in_(ids)))).all()) if ids else {}
        for r in rows:r['label']=empty if r['value']=='0' else names.get(int(r['value']),f'历史记录 #{r["value"]}')
    else:
        for r in rows:r['label']=r['value'] or '未选择模型 / 协议'
