"""Smart route configuration, samples, pgvector storage and decision history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from app.models.routing import Vector

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def timestamp(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade():
    # Bootstrap enables the extension as postgres; the application role stays non-superuser.
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector') THEN RAISE EXCEPTION 'pgvector must be provisioned before migration 0012'; END IF; END $$")
    op.create_table('route_configs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('virtual_model', sa.String(100), sa.ForeignKey('logical_models.name', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('embedding_model', sa.String(100), sa.ForeignKey('logical_models.name', ondelete='RESTRICT'), nullable=False),
        sa.Column('simple_model_group', sa.Integer(), sa.ForeignKey('model_groups.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('complex_model_group', sa.Integer(), sa.ForeignKey('model_groups.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('similarity_threshold', sa.Float(), nullable=False, server_default='0.75'),
        sa.Column('confidence_gap', sa.Float(), nullable=False, server_default='0.1'),
        sa.Column('fallback', sa.String(20), nullable=False, server_default='error'),
        sa.Column('status', sa.String(20), nullable=False, server_default='disabled'),
        sa.Column('vector_generation', sa.Integer(), nullable=False, server_default='1'),
        timestamp('created_at'), timestamp('updated_at'),
        sa.CheckConstraint("status IN ('enabled','disabled')", name='ck_route_config_status'),
        sa.CheckConstraint('top_k BETWEEN 1 AND 50', name='ck_route_config_top_k'),
        sa.CheckConstraint('similarity_threshold BETWEEN 0 AND 1', name='ck_route_config_threshold'),
        sa.CheckConstraint('confidence_gap BETWEEN 0 AND 1', name='ck_route_config_gap'),
        sa.CheckConstraint('vector_generation > 0', name='ck_route_config_generation'),
        sa.CheckConstraint('simple_model_group <> complex_model_group', name='ck_route_config_distinct_groups'),
        sa.CheckConstraint('virtual_model <> embedding_model', name='ck_route_config_embedding'),
        sa.CheckConstraint("fallback IN ('error','simple','complex')", name='ck_route_config_fallback'),
    )
    op.create_table('route_samples',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('config_id', sa.Integer(), sa.ForeignKey('route_configs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('prompt_hash', sa.String(64), nullable=False),
        sa.Column('classification', sa.String(20), nullable=False),
        sa.Column('vector_status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('vector_error', sa.String(80)),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        timestamp('created_at'), timestamp('updated_at'),
        sa.UniqueConstraint('config_id', 'prompt_hash', name='uq_route_sample_prompt'),
        sa.CheckConstraint("classification IN ('simple','complex')", name='ck_route_sample_class'),
        sa.CheckConstraint("vector_status IN ('pending','processing','ready','failed','stale')", name='ck_route_sample_status'),
        sa.CheckConstraint('revision > 0', name='ck_route_sample_revision'),
        sa.CheckConstraint('length(prompt) BETWEEN 1 AND 16000', name='ck_route_sample_prompt'),
    )
    op.create_index('ix_route_samples_config_status', 'route_samples', ['config_id', 'vector_status'])
    op.create_table('route_vectors',
        sa.Column('sample_id', sa.BigInteger(), sa.ForeignKey('route_samples.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('embedding', Vector(), nullable=False),
        sa.Column('dimensions', sa.Integer(), nullable=False),
        sa.Column('embedding_model', sa.String(100), nullable=False),
        sa.Column('vector_generation', sa.Integer(), nullable=False),
        sa.Column('sample_revision', sa.Integer(), nullable=False),
        timestamp('created_at'),
        sa.CheckConstraint('dimensions BETWEEN 1 AND 4096 AND vector_dims(embedding) = dimensions', name='ck_route_vector_dimensions'),
        sa.CheckConstraint('vector_generation > 0 AND sample_revision > 0', name='ck_route_vector_revision'),
        sa.CheckConstraint('vector_norm(embedding) > 0', name='ck_route_vector_nonzero'),
    )
    op.create_table('route_decisions',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('request_id', sa.String(80), nullable=False, unique=True),
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('virtual_model', sa.String(100), nullable=False),
        sa.Column('embedding_request_id', sa.String(80)),
        sa.Column('top_k', sa.Integer(), nullable=False),
        sa.Column('similarity', sa.Float()),
        sa.Column('classification', sa.String(20)),
        sa.Column('selected_model_group', sa.Integer()),
        sa.Column('selected_group_name', sa.String(80)),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('reason', sa.String(80)),
        sa.Column('evidence', JSONB(), nullable=False, server_default='[]'),
        sa.Column('elapsed_ms', sa.Float(), nullable=False),
        timestamp('created_at'),
        sa.CheckConstraint("status IN ('classified','fallback','failed')", name='ck_route_decision_status'),
        sa.CheckConstraint("classification IS NULL OR classification IN ('simple','complex')", name='ck_route_decision_class'),
        sa.CheckConstraint('top_k BETWEEN 1 AND 50', name='ck_route_decision_top_k'),
        sa.CheckConstraint('similarity IS NULL OR similarity BETWEEN -1 AND 1', name='ck_route_decision_similarity'),
        sa.CheckConstraint("elapsed_ms >= 0 AND elapsed_ms < 'Infinity'::double precision", name='ck_route_decision_elapsed'),
    )
    op.create_index('ix_route_decisions_created_id', 'route_decisions', ['created_at', 'id'])
    op.create_index('ix_route_decisions_virtual_created', 'route_decisions', ['virtual_model', 'created_at'])


def downgrade():
    for table in ('route_vectors', 'route_samples', 'route_configs', 'route_decisions'):
        op.drop_table(table)
    # Do not drop a shared database extension, logical models, call logs or usage.
