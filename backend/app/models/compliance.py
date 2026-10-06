"""Content policy sources and immutable request evidence; no client bodies."""
from datetime import datetime
from sqlalchemy import BigInteger,DateTime,Float,Integer,String,Text,ForeignKey,CheckConstraint,UniqueConstraint,Index,func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column
from app.models.user import Base
from app.models.routing import Vector
class AuditWord(Base):
 __tablename__='sensitive_words'
 __table_args__=(CheckConstraint("kind IN ('text','wildcard','regex')",name='ck_audit_word_kind'),CheckConstraint("status IN ('enabled','disabled')",name='ck_audit_word_status'))
 id:Mapped[int]=mapped_column(primary_key=True)
 pattern:Mapped[str]=mapped_column(String(256))
 kind:Mapped[str]=mapped_column(String(20))
 risk:Mapped[str]=mapped_column(String(20),default='medium',server_default='medium')
 status:Mapped[str]=mapped_column(String(20),default='enabled',server_default='enabled')
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
class AuditSample(Base):
 __tablename__='review_samples'
 __table_args__=(UniqueConstraint('text_hash',name='uq_audit_sample_hash'),CheckConstraint("vector_status IN ('pending','processing','ready','failed')",name='ck_audit_sample_status'),CheckConstraint('revision>0',name='ck_audit_sample_revision'))
 id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
 text:Mapped[str]=mapped_column(Text)
 text_hash:Mapped[str]=mapped_column(String(64))
 risk:Mapped[str]=mapped_column(String(20),default='medium',server_default='medium')
 revision:Mapped[int]=mapped_column(Integer,default=1,server_default='1')
 vector_status:Mapped[str]=mapped_column(String(20),default='pending',server_default='pending')
 vector_error:Mapped[str|None]=mapped_column(String(80))
 job_started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
class AuditVector(Base):
 __tablename__='review_vectors'
 __table_args__=(CheckConstraint('vector_dims(embedding) BETWEEN 1 AND 4096 AND vector_norm(embedding)>0',name='ck_audit_vector_valid'),)
 sample_id:Mapped[int]=mapped_column(ForeignKey('review_samples.id',ondelete='CASCADE'),primary_key=True)
 embedding:Mapped[object]=mapped_column(Vector())
 model_version:Mapped[str]=mapped_column(String(100))
 sample_revision:Mapped[int]=mapped_column(Integer)
class CompliancePolicy(Base):
 __tablename__='compliance_policies'
 __table_args__=(CheckConstraint("action IN ('audit','block')",name='ck_compliance_action'),CheckConstraint("status IN ('enabled','disabled')",name='ck_compliance_status'),CheckConstraint('threshold>=0 AND threshold<=1',name='ck_compliance_threshold'))
 id:Mapped[int]=mapped_column(primary_key=True)
 name:Mapped[str]=mapped_column(String(80),unique=True)
 action:Mapped[str]=mapped_column(String(20))
 status:Mapped[str]=mapped_column(String(20),default='disabled',server_default='disabled')
 word_ids:Mapped[list]=mapped_column(JSONB,default=list,server_default='[]')
 sample_ids:Mapped[list]=mapped_column(JSONB,default=list,server_default='[]')
 group_ids:Mapped[list]=mapped_column(JSONB,default=list,server_default='[]')
 models:Mapped[list]=mapped_column(JSONB,default=list,server_default='[]')
 threshold:Mapped[float]=mapped_column(Float,default=.85,server_default='.85')
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
class ComplianceLog(Base):
 __tablename__='compliance_logs'
 __table_args__=(Index('ix_compliance_log_created', 'created_at'),)
 id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
 request_id:Mapped[str]=mapped_column(String(80),unique=True)
 user_id:Mapped[int|None]=mapped_column(Integer)
 group_id:Mapped[int|None]=mapped_column(Integer)
 model:Mapped[str|None]=mapped_column(String(100))
 action:Mapped[str]=mapped_column(String(20))
 matches:Mapped[list]=mapped_column(JSONB)
 elapsed_ms:Mapped[float]=mapped_column(Float)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
