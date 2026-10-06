"""Hourly and daily inference aggregates, with historic backfill."""
from alembic import op
import sqlalchemy as sa
DIMS=('user_id','user_group_id','api_key_id','provider_id','request_model','logical_model','protocol')
TOKENS=('input_tokens','output_tokens','cached_tokens','total_tokens')
COUNTERS=('requests','success','failure','usage_unavailable')+tuple(x+y for x in TOKENS for y in ('_sum','_count'))+('ttft_sum','ttft_count','tps_sum','tps_count')

def log_projection():
    fields=["created_at AS bucket"]+[f"coalesce({k},{'0' if k.endswith('_id') else chr(39)+chr(39)}) AS {k}" for k in DIMS]
    fields += ["1::bigint AS requests","(status='success')::int AS success","(status<>'success')::int AS failure","(input_tokens IS NULL OR output_tokens IS NULL OR total_tokens IS NULL)::int AS usage_unavailable"]
    for k in TOKENS:fields += [f'coalesce({k},0) AS {k}_sum',f'({k} IS NOT NULL)::int AS {k}_count']
    for prefix,k in [('ttft','ttft_ms'),('tps','tokens_per_second')]:fields += [f'coalesce({k},0) AS {prefix}_sum',f'({k} IS NOT NULL)::int AS {prefix}_count']
    return ','.join(fields)



revision='0009'
down_revision='0008'
branch_labels=None
depends_on=None


def upgrade():
    for table,grain in [('usage_hourly','hour'),('usage_daily','day')]:
        fields=[sa.Column('bucket',sa.DateTime(timezone=True),primary_key=True)]
        fields += [sa.Column(k,sa.Integer() if k.endswith('_id') else sa.String(100),primary_key=True) for k in DIMS]
        fields += [sa.Column(k,sa.Float() if k in ('ttft_sum','tps_sum') else sa.BigInteger(),nullable=False) for k in COUNTERS]
        op.create_table(table,*fields)
        op.create_index('ix_'+table+'_user_bucket',table,['user_id','bucket'])
        time=f"date_trunc('{grain}',bucket AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai'"
        op.execute(sa.text(f"INSERT INTO {table} SELECT {time},"+','.join(DIMS)+','+','.join('sum('+k+')' for k in COUNTERS)+f" FROM (SELECT {log_projection()} FROM call_logs WHERE operation='chat') facts GROUP BY {time},"+','.join(DIMS)))


def downgrade():
    op.drop_table('usage_daily');op.drop_table('usage_hourly')
