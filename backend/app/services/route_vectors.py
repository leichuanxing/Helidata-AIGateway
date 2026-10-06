"""Version-aware exact pgvector retrieval and deterministic confidence checks.

No request Prompt is persisted by this module. Network embedding calls and
sample management will use these primitives in the Stage16 application layer.
"""
import json
import math
from dataclasses import dataclass
from sqlalchemy import select, text
from app.core.exceptions import APIError
from app.models.routing import RouteConfig, RouteSample


def encode_vector(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 4096:
        raise APIError(502, 'ROUTE_INVALID_VECTOR', 'Embedding维度必须在1至4096之间')
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value):
        raise APIError(502, 'ROUTE_INVALID_VECTOR', 'Embedding包含非数值')
    try:
        numbers = [float(x) for x in value]
    except (OverflowError, ValueError):
        raise APIError(502, 'ROUTE_INVALID_VECTOR', 'Embedding包含无效数值') from None
    # pgvector uses float32. Reject overflow before passing values to PostgreSQL.
    if any(not math.isfinite(x) or abs(x) > 3.4028234663852886e38 for x in numbers):
        raise APIError(502, 'ROUTE_INVALID_VECTOR', 'Embedding包含非有限数值')
    if not any(abs(x) >= 1.401298464324817e-45 for x in numbers):
        raise APIError(502, 'ROUTE_INVALID_VECTOR', 'Embedding不能为零向量')
    # Cosine distance is scale invariant. Unit vectors avoid float32 dot-product
    # overflow/underflow for otherwise finite, nonzero supplier embeddings.
    norm = math.hypot(*numbers)
    numbers = [x / norm for x in numbers]
    return json.dumps(numbers, separators=(',', ':'), allow_nan=False), len(numbers)


async def nearest(db, config, vector):
    encoded, dimensions = encode_vector(vector)
    rows = (await db.execute(text('''
        SELECT s.id AS sample_id, s.classification, s.similarity_threshold,
               CASE WHEN v.dimensions=:dimensions THEN
                   1 - (v.embedding <=> CAST(:embedding AS vector))
               END AS similarity
        FROM route_vectors v JOIN route_samples s ON s.id=v.sample_id
        WHERE s.config_id=:config_id AND s.vector_status='ready'
          AND s.revision=v.sample_revision
          AND v.vector_generation=:generation
          AND v.embedding_model=:model AND v.dimensions=:dimensions
        ORDER BY similarity DESC, s.id ASC
        LIMIT :top_k
    '''), {'embedding': encoded, 'dimensions': dimensions, 'config_id': config.id,
           'generation': config.vector_generation, 'model': config.embedding_model,
           'top_k': config.top_k})).mappings().all()
    if any(row['similarity'] is None or not math.isfinite(row['similarity']) for row in rows):
        raise APIError(502, 'ROUTE_INVALID_VECTOR', '样本向量无法计算有效相似度，请重新向量化')
    return [{'sample_id': row['sample_id'], 'classification': row['classification'],
             'similarity': max(-1.0, min(1.0, row['similarity'])),
             **({'similarity_threshold':row['similarity_threshold']} if row['similarity_threshold'] is not None else {})} for row in rows]


async def store_vector(db, config_id, sample_id, generation, revision, embedding_model, vector):
    """Commit a completed worker result only if its captured versions still match.

The caller owns the short DB transaction. Never hold these locks during an
Embedding network call. Configuration then sample is the fixed lock order.
"""
    encoded, dimensions = encode_vector(vector)
    config = await db.scalar(select(RouteConfig).where(RouteConfig.id == config_id).with_for_update().execution_options(populate_existing=True))
    if not config or config.vector_generation != generation or config.embedding_model != embedding_model:
        return False
    sample = await db.scalar(select(RouteSample).where(RouteSample.id == sample_id, RouteSample.config_id == config_id)
                             .with_for_update().execution_options(populate_existing=True))
    if not sample or sample.revision != revision or sample.vector_status != 'processing':
        return False
    await db.execute(text('''INSERT INTO route_vectors
        (sample_id,embedding,dimensions,embedding_model,vector_generation,sample_revision)
        VALUES (:id,CAST(:embedding AS vector),:dimensions,:model,:generation,:revision)
        ON CONFLICT (sample_id) DO UPDATE SET
            embedding=EXCLUDED.embedding, dimensions=EXCLUDED.dimensions,
            embedding_model=EXCLUDED.embedding_model, vector_generation=EXCLUDED.vector_generation,
            sample_revision=EXCLUDED.sample_revision, created_at=now()
    '''), dict(id=sample_id, embedding=encoded, dimensions=dimensions,
               model=embedding_model, generation=generation, revision=revision))
    sample.vector_status = 'ready'
    sample.vector_error = None
    await db.flush()
    return True


@dataclass(frozen=True)
class Classification:
    classification: str | None
    similarity: float | None
    confidence: float | None
    reason: str | None


def classify(evidence, threshold, gap):
    """Compare the best similarity per class, using zero for an absent class.

TopK must be sorted descending. An exact cross-class tie remains ambiguous
even when an administrator chooses confidence_gap=0.
"""
    if not evidence:
        return Classification(None, None, None, 'ROUTE_NO_SAMPLES')
    eligible=[item for item in evidence if item.get('similarity_threshold') is None or item['similarity']>=item['similarity_threshold']]
    if not eligible:return Classification(None,evidence[0]['similarity'],None,'ROUTE_LOW_SIMILARITY')
    evidence=eligible
    best = evidence[0]
    opposite = max((item['similarity'] for item in evidence
                    if item['classification'] != best['classification']), default=0.0)
    confidence = best['similarity'] - opposite
    if best['similarity'] < (best.get('similarity_threshold') if best.get('similarity_threshold') is not None else threshold):
        return Classification(None, best['similarity'], confidence, 'ROUTE_LOW_SIMILARITY')
    if confidence <= 1e-7 or confidence < gap:
        return Classification(None, best['similarity'], confidence, 'ROUTE_AMBIGUOUS')
    return Classification(best['classification'], best['similarity'], confidence, None)
