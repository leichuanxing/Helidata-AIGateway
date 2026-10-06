from datetime import datetime
from sqlalchemy import BigInteger,CheckConstraint,DateTime,ForeignKey,Integer,String
from sqlalchemy.orm import Mapped,mapped_column
from app.models.user import Base

class QuotaBucket(Base):
    __tablename__='quota_buckets'
    __table_args__=(CheckConstraint('reported_tokens >= 0 AND unreported_budget >= 0 AND reserved_budget >= 0',name='ck_quota_bucket_nonnegative'),)
    group_id:Mapped[int]=mapped_column(ForeignKey('user_groups.id',ondelete='CASCADE'),primary_key=True)
    period:Mapped[str]=mapped_column(String(12),primary_key=True)
    period_start:Mapped[str]=mapped_column(String(10),primary_key=True)
    reported_tokens:Mapped[int]=mapped_column(BigInteger,default=0,server_default='0')
    unreported_budget:Mapped[int]=mapped_column(BigInteger,default=0,server_default='0')
    reserved_budget:Mapped[int]=mapped_column(BigInteger,default=0,server_default='0')

class QuotaReservation(Base):
    __tablename__='quota_reservations'
    __table_args__=(CheckConstraint('budget >= 0 AND (reported_tokens IS NULL OR reported_tokens >= 0)',name='ck_quota_reservation_nonnegative'),)
    id:Mapped[str]=mapped_column(String(80),primary_key=True)
    group_id:Mapped[int]=mapped_column(ForeignKey('user_groups.id',ondelete='CASCADE'),index=True)
    period:Mapped[str]=mapped_column(String(12))
    period_start:Mapped[str]=mapped_column(String(10))
    budget:Mapped[int]=mapped_column(BigInteger)
    reported_tokens:Mapped[int|None]=mapped_column(BigInteger)
    state:Mapped[str]=mapped_column(String(20),default='active',server_default='active')
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
