"""Routing configuration, sample lifecycle and immutable decision metadata."""
from datetime import datetime
from sqlalchemy import BigInteger,Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType
from app.models.user import Base


class Vector(UserDefinedType):
    """Variable dimension pgvector; bind vectors through explicit SQL casts."""
    cache_ok = True

    def get_col_spec(self, **kw):
        return 'VECTOR'


class RouteConfig(Base):
    __tablename__ = 'route_configs'
    __table_args__ = (
        CheckConstraint("status IN ('enabled','disabled')", name='ck_route_config_status'),
        CheckConstraint('top_k BETWEEN 1 AND 50', name='ck_route_config_top_k'),
        CheckConstraint('similarity_threshold BETWEEN 0 AND 1', name='ck_route_config_threshold'),
        CheckConstraint('confidence_gap BETWEEN 0 AND 1', name='ck_route_config_gap'),
        CheckConstraint('vector_generation > 0', name='ck_route_config_generation'),
        CheckConstraint('simple_model_group <> complex_model_group', name='ck_route_config_distinct_groups'),
        CheckConstraint('virtual_model <> embedding_model', name='ck_route_config_embedding'),
        CheckConstraint("fallback IN ('error','simple','complex')", name='ck_route_config_fallback'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    virtual_model: Mapped[str] = mapped_column(ForeignKey('logical_models.name', ondelete='RESTRICT'), unique=True)
    embedding_model: Mapped[str] = mapped_column(ForeignKey('logical_models.name', ondelete='RESTRICT'))
    simple_model_group: Mapped[int] = mapped_column(ForeignKey('model_groups.id', ondelete='RESTRICT'))
    complex_model_group: Mapped[int] = mapped_column(ForeignKey('model_groups.id', ondelete='RESTRICT'))
    top_k: Mapped[int] = mapped_column(Integer, default=5, server_default='5')
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.75, server_default='0.75')
    confidence_gap: Mapped[float] = mapped_column(Float, default=0.1, server_default='0.1')
    fallback: Mapped[str] = mapped_column(String(20), default='error', server_default='error')
    status: Mapped[str] = mapped_column(String(20), default='disabled', server_default='disabled')
    vector_generation: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RouteSample(Base):
    __tablename__ = 'route_samples'
    __table_args__ = (
        UniqueConstraint('config_id', 'prompt_hash', name='uq_route_sample_prompt'),
        CheckConstraint("classification IN ('simple','complex')", name='ck_route_sample_class'),
        CheckConstraint("vector_status IN ('pending','processing','ready','failed','stale')", name='ck_route_sample_status'),
        CheckConstraint('revision > 0', name='ck_route_sample_revision'),
        CheckConstraint('length(prompt) BETWEEN 1 AND 65536', name='ck_route_sample_prompt'),
        CheckConstraint('similarity_threshold BETWEEN 0 AND 1',name='ck_route_sample_threshold'),
        Index('ix_route_samples_config_status', 'config_id', 'vector_status'),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    config_id: Mapped[int] = mapped_column(ForeignKey('route_configs.id', ondelete='CASCADE'))
    prompt: Mapped[str] = mapped_column(Text)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(20))
    similarity_threshold: Mapped[float | None]=mapped_column(Float)
    remark: Mapped[str]=mapped_column(Text,default='',server_default='')
    vector_requested: Mapped[bool]=mapped_column(Boolean,default=True,server_default='true')
    vector_status: Mapped[str] = mapped_column(String(20), default='pending', server_default='pending')
    vector_error: Mapped[str | None] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    requested_by: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    vector_request_id: Mapped[str | None] = mapped_column(String(80))
    job_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RouteVector(Base):
    __tablename__ = 'route_vectors'
    __table_args__ = (
        CheckConstraint('dimensions BETWEEN 1 AND 4096 AND vector_dims(embedding) = dimensions', name='ck_route_vector_dimensions'),
        CheckConstraint('vector_generation > 0 AND sample_revision > 0', name='ck_route_vector_revision'),
        CheckConstraint('vector_norm(embedding) > 0', name='ck_route_vector_nonzero'),
    )
    sample_id: Mapped[int] = mapped_column(ForeignKey('route_samples.id', ondelete='CASCADE'), primary_key=True)
    embedding: Mapped[str] = mapped_column(Vector())
    dimensions: Mapped[int] = mapped_column(Integer)
    embedding_model: Mapped[str] = mapped_column(String(100))
    vector_generation: Mapped[int] = mapped_column(Integer)
    sample_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RouteDecision(Base):
    __tablename__ = 'route_decisions'
    __table_args__ = (
        CheckConstraint("status IN ('classified','fallback','failed')", name='ck_route_decision_status'),
        CheckConstraint("classification IS NULL OR classification IN ('simple','complex')", name='ck_route_decision_class'),
        CheckConstraint('top_k BETWEEN 1 AND 50', name='ck_route_decision_top_k'),
        CheckConstraint('similarity IS NULL OR similarity BETWEEN -1 AND 1', name='ck_route_decision_similarity'),
        CheckConstraint("elapsed_ms >= 0 AND elapsed_ms < 'Infinity'::double precision", name='ck_route_decision_elapsed'),
        Index('ix_route_decisions_created_id', 'created_at', 'id'),
        Index('ix_route_decisions_virtual_created', 'virtual_model', 'created_at'),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(80), unique=True)
    # Historical IDs and snapshots intentionally survive config/group/sample deletion.
    config_id: Mapped[int] = mapped_column(Integer)
    virtual_model: Mapped[str] = mapped_column(String(100))
    embedding_request_id: Mapped[str | None] = mapped_column(String(80))
    top_k: Mapped[int] = mapped_column(Integer)
    similarity: Mapped[float | None] = mapped_column(Float)
    classification: Mapped[str | None] = mapped_column(String(20))
    selected_model_group: Mapped[int | None] = mapped_column(Integer)
    selected_group_name: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(80))
    evidence: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    elapsed_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
