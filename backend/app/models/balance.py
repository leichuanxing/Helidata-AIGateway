"""Independent virtual-model routes; physical nodes reuse existing mappings."""
from datetime import datetime
from sqlalchemy import CheckConstraint,DateTime,ForeignKey,Integer,String,Text,UniqueConstraint,Boolean,func
from sqlalchemy.orm import Mapped,mapped_column
from app.models.user import Base

class BalancedRoute(Base):
    __tablename__='balanced_routes'
    __table_args__=(CheckConstraint("strategy IN ('round_robin','weighted_round_robin','least_concurrency','random','priority')",name='ck_balanced_strategy'),
        CheckConstraint('max_concurrency BETWEEN 1 AND 10000 AND max_retries BETWEEN 0 AND 7 AND timeout_seconds BETWEEN 1 AND 3600 AND health_interval BETWEEN 10 AND 3600 AND cooldown_seconds BETWEEN 1 AND 3600 AND failure_threshold BETWEEN 1 AND 20',name='ck_balanced_limits'),
        CheckConstraint("status IN ('enabled','disabled')",name='ck_balanced_status'))
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(80),unique=True)
    model_name:Mapped[str]=mapped_column(ForeignKey('logical_models.name',ondelete='RESTRICT'),unique=True)
    strategy:Mapped[str]=mapped_column(String(30),default='round_robin',server_default='round_robin')
    status:Mapped[str]=mapped_column(String(20),default='enabled',server_default='enabled')
    description:Mapped[str]=mapped_column(Text,default='',server_default='')
    max_concurrency:Mapped[int]=mapped_column(Integer,default=100,server_default='100')
    max_retries:Mapped[int]=mapped_column(Integer,default=2,server_default='2')
    timeout_seconds:Mapped[int]=mapped_column(Integer,default=60,server_default='60')
    retry_uncertain:Mapped[bool]=mapped_column(Boolean,default=False,server_default='false')
    health_interval:Mapped[int]=mapped_column(Integer,default=30,server_default='30')
    cooldown_seconds:Mapped[int]=mapped_column(Integer,default=30,server_default='30')
    failure_threshold:Mapped[int]=mapped_column(Integer,default=3,server_default='3')
    config_version:Mapped[int]=mapped_column(Integer,default=0,server_default='0')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class BalancedNode(Base):
    __tablename__='balanced_nodes'
    __table_args__=(UniqueConstraint('route_id','mapping_id',name='uq_balanced_node_mapping'),
        CheckConstraint('weight BETWEEN 1 AND 100 AND max_concurrency BETWEEN 1 AND 10000 AND priority BETWEEN 0 AND 100000 AND failure_count>=0',name='ck_balanced_node_limits'),
        CheckConstraint("status IN ('enabled','disabled') AND health_status IN ('unknown','healthy','unhealthy')",name='ck_balanced_node_status'))
    id:Mapped[int]=mapped_column(primary_key=True)
    route_id:Mapped[int]=mapped_column(ForeignKey('balanced_routes.id',ondelete='CASCADE'),index=True)
    mapping_id:Mapped[int]=mapped_column(ForeignKey('provider_model_mappings.id',ondelete='RESTRICT'),index=True)
    weight:Mapped[int]=mapped_column(Integer,default=1,server_default='1')
    priority:Mapped[int]=mapped_column(Integer,default=0,server_default='0')
    max_concurrency:Mapped[int]=mapped_column(Integer,default=10,server_default='10')
    status:Mapped[str]=mapped_column(String(20),default='enabled',server_default='enabled')
    health_status:Mapped[str]=mapped_column(String(20),default='unknown',server_default='unknown')
    failure_count:Mapped[int]=mapped_column(Integer,default=0,server_default='0')
    cooldown_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    next_check_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    last_checked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    last_latency_ms:Mapped[int|None]=mapped_column(Integer)
    last_error_code:Mapped[str|None]=mapped_column(String(80))
