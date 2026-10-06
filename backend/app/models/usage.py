"""Metadata for migration-managed inference aggregates."""
from sqlalchemy import Table,Column,DateTime,Integer,String,Float,BigInteger,Numeric,Index
from app.models.user import Base
from app.services.usage import DIMS,COUNTERS


def aggregate(name):
    table=Table(name,Base.metadata,
        Column('bucket',DateTime(timezone=True),primary_key=True),
        *[Column(k,Integer() if k.endswith('_id') else String(100),primary_key=True) for k in DIMS],
        *[Column(k,Float() if k in ('ttft_sum','tps_sum') else Numeric(38,0) if k.endswith('_tokens_sum') else BigInteger(),nullable=False) for k in COUNTERS])
    Index('ix_'+name+'_user_bucket',table.c.user_id,table.c.bucket)
    return table
usage_hourly=aggregate('usage_hourly')
usage_daily=aggregate('usage_daily')
