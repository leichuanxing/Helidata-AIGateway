"""Keep each native inference operation independently filterable in aggregates."""
from alembic import op
import sqlalchemy as sa
revision='0011'
down_revision='0010'
branch_labels=None
depends_on=None
DIMS=['user_id','user_group_id','api_key_id','provider_id','request_model','logical_model','protocol']
TOKENS=('input_tokens','output_tokens','cached_tokens','total_tokens')
COUNTERS=('requests','success','failure','usage_unavailable')+tuple(x+y for x in TOKENS for y in ('_sum','_count'))+('ttft_sum','ttft_count','tps_sum','tps_count')

def log_projection():
    fields=["created_at AS bucket"]+[f"coalesce({k},{'0' if k.endswith('_id') else chr(39)+chr(39)}) AS {k}" for k in DIMS]
    fields += ["1::bigint AS requests","(status='success')::int AS success","(status<>'success')::int AS failure","(input_tokens IS NULL OR output_tokens IS NULL OR total_tokens IS NULL)::int AS usage_unavailable"]
    for k in TOKENS:fields += [f'coalesce({k},0) AS {k}_sum',f'({k} IS NOT NULL)::int AS {k}_count']
    for prefix,k in [('ttft','ttft_ms'),('tps','tokens_per_second')]:fields += [f'coalesce({k},0) AS {prefix}_sum',f'({k} IS NOT NULL)::int AS {prefix}_count']
    return ','.join(fields)




def upgrade():
    for table in ('usage_hourly','usage_daily'):
        op.add_column(table,sa.Column('operation',sa.String(100),nullable=False,server_default='chat'))
        op.drop_constraint(table+'_pkey',table,type_='primary')
        op.create_primary_key(table+'_pkey',table,['bucket']+DIMS+['operation'])
        grain='hour' if table=='usage_hourly' else 'day'
        bucket=f"date_trunc('{grain}',bucket AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'"
        op.execute(sa.text(f"INSERT INTO {table} (bucket,{','.join(DIMS)},operation,{','.join(COUNTERS)}) SELECT {bucket},"+','.join(DIMS)+',operation,'+','.join('sum('+k+')' for k in COUNTERS)+f" FROM (SELECT {log_projection()},operation FROM call_logs WHERE operation IN ('responses','messages','embeddings','rerank','images')) facts GROUP BY {bucket},"+','.join(DIMS)+',operation'))
def downgrade():
    # Prior application versions only know Chat. Keep Chat rows and reconstruct other protocols on re-upgrade from logs.
    for table in ('usage_hourly','usage_daily'):
        op.execute(sa.text(f"DELETE FROM {table} WHERE operation<>'chat'"))
        op.drop_constraint(table+'_pkey',table,type_='primary')
        op.drop_column(table,'operation')
        op.create_primary_key(table+'_pkey',table,['bucket']+DIMS)
