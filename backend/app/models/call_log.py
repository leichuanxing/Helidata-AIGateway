from datetime import datetime
from sqlalchemy import BigInteger,Boolean,DateTime,Float,Index,Integer,String,Text,func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column
from app.models.user import Base


class CallLog(Base):
    __tablename__='call_logs'
    __table_args__=(Index('ix_call_logs_created_id','created_at','id'),
        Index('ix_call_logs_user_created','user_id','created_at'),
        Index('ix_call_logs_status_created','status','created_at'),
        *(Index('ix_call_logs_'+field+'_created_id',field,'created_at','id')
          for field in ('provider_id','api_key_id','user_group_id','request_model','logical_model')))
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    request_id:Mapped[str]=mapped_column(String(80),unique=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    operation:Mapped[str]=mapped_column(String(20))
    # Historical scalar IDs/snapshots deliberately survive deletion of source objects.
    user_id:Mapped[int|None]=mapped_column(Integer,index=True)
    user_group_id:Mapped[int|None]=mapped_column(Integer,index=True)
    api_key_id:Mapped[int|None]=mapped_column(Integer,index=True)
    username_snapshot:Mapped[str|None]=mapped_column(String(80))
    group_name_snapshot:Mapped[str|None]=mapped_column(String(80))
    key_name_snapshot:Mapped[str|None]=mapped_column(String(80))
    client_ip:Mapped[str]=mapped_column(String(64))
    protocol:Mapped[str|None]=mapped_column(String(30))
    request_model:Mapped[str|None]=mapped_column(String(100))
    logical_model:Mapped[str|None]=mapped_column(String(100))
    upstream_model:Mapped[str|None]=mapped_column(String(200))
    provider_id:Mapped[int|None]=mapped_column(Integer,index=True)
    provider_name_snapshot:Mapped[str|None]=mapped_column(String(80))
    stream:Mapped[bool]=mapped_column(Boolean)
    status:Mapped[str]=mapped_column(String(30))
    http_status:Mapped[int]=mapped_column(Integer)
    error_code:Mapped[str|None]=mapped_column(String(80))
    error_message:Mapped[str|None]=mapped_column(Text)
    input_tokens:Mapped[int|None]=mapped_column(BigInteger)
    output_tokens:Mapped[int|None]=mapped_column(BigInteger)
    cached_tokens:Mapped[int|None]=mapped_column(BigInteger)
    total_tokens:Mapped[int|None]=mapped_column(BigInteger)
    gateway_latency_ms:Mapped[float]=mapped_column(Float)
    upstream_latency_ms:Mapped[float|None]=mapped_column(Float)
    ttft_ms:Mapped[float|None]=mapped_column(Float)
    tokens_per_second:Mapped[float|None]=mapped_column(Float)
    trace:Mapped[dict]=mapped_column(JSONB)
    request_body:Mapped[dict|list|None]=mapped_column(JSONB,nullable=True)
    response_body:Mapped[dict|list|None]=mapped_column(JSONB,nullable=True)
