from sqlalchemy import text
from app.services.usage import source_query

async def rankings(db,start,end,grain):
    cte,params=source_query(start,end,grain,{})
    sql=cte+", dimensions AS (SELECT 'provider'::text AS kind,provider_id::text AS dimension,total_tokens_sum,total_tokens_count,requests,failure FROM filtered UNION ALL SELECT 'model',coalesce(nullif(logical_model,''),nullif(request_model,''),''),total_tokens_sum,total_tokens_count,requests,failure FROM filtered), summed AS (SELECT kind,dimension,sum(total_tokens_sum) AS tokens,sum(total_tokens_count) AS token_samples,sum(requests) AS requests,sum(failure) AS failure FROM dimensions GROUP BY kind,dimension), ordered AS (SELECT *,row_number() OVER (PARTITION BY kind ORDER BY tokens DESC,requests DESC,dimension) AS position FROM summed) SELECT kind,CASE WHEN position<=10 THEN dimension ELSE NULL END AS dimension,sum(tokens) AS tokens,sum(token_samples) AS token_samples,sum(requests) AS requests,sum(failure) AS failure,min(position) AS position FROM ordered GROUP BY kind,CASE WHEN position<=10 THEN dimension ELSE NULL END ORDER BY kind,min(position)"
    rows=(await db.execute(text(sql),params)).mappings().all()
    result={'provider':[],'model':[]}
    for row in rows:
        result[row['kind']].append({'dimension':row['dimension'],'other':row['dimension'] is None,
            'total_tokens':int(row['tokens']) if row['token_samples'] else None,'token_samples':int(row['token_samples']),
            'requests':int(row['requests']),'failure':int(row['failure'])})
    return result
