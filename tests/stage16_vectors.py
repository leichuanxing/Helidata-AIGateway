"""Run inside an isolated Stage16 foundation container, never production."""
import asyncio
import hashlib
import math
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, DBAPIError
from app.core.database import session_factory, engine
from app.models.user import LogicalModel, ModelGroup
from app.models.routing import RouteConfig, RouteSample, RouteVector, RouteDecision
from app.services.route_vectors import encode_vector, nearest, classify, store_vector


from stage16_inputs import validate_inputs


async def main():
    validate_inputs()
    async with session_factory() as db:
        assert not await db.scalar(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user'))
        assert await db.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")) == '0.8.7'
        for model in (RouteConfig, RouteSample, RouteVector, RouteDecision):
            actual = dict((await db.execute(text('''SELECT column_name,is_nullable FROM information_schema.columns
                                                  WHERE table_schema='public' AND table_name=:table'''),
                                          dict(table=model.__tablename__))).all())
            assert actual == {column.name: 'YES' if column.nullable else 'NO' for column in model.__table__.columns}
        print('PASS: all four migration tables match ORM column names/nullability; application role remains non-superuser')
        db.add_all([LogicalModel(name='route-fixture-auto', model_type='text'),
                    LogicalModel(name='route-fixture-embed', model_type='embedding')])
        simple = ModelGroup(name='route-fixture-simple')
        complex_group = ModelGroup(name='route-fixture-complex')
        db.add_all([simple, complex_group]); await db.flush()
        config = RouteConfig(virtual_model='route-fixture-auto', embedding_model='route-fixture-embed',
                             simple_model_group=simple.id, complex_model_group=complex_group.id, top_k=5)
        db.add(config); await db.flush()
        async def sample(prompt, classification, embedding, status='ready', generation=1, revision=1, model=None):
            item = RouteSample(config_id=config.id, prompt=prompt,
                               prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
                               classification=classification, vector_status=status)
            db.add(item); await db.flush()
            encoded, dimensions = encode_vector(embedding)
            await db.execute(text('''INSERT INTO route_vectors
                (sample_id,embedding,dimensions,embedding_model,vector_generation,sample_revision)
                VALUES (:id,CAST(:embedding AS vector),:dimensions,:model,:generation,:revision)'''),
                dict(id=item.id, embedding=encoded, dimensions=dimensions, model=model or config.embedding_model,
                     generation=generation, revision=revision))
            return item.id
        simple_id = await sample('简单问候', 'simple', [1, 0])
        complex_id = await sample('复杂推理', 'complex', [0, 1])
        await sample('向量失败', 'complex', [1, 0], status='failed')
        await sample('尚未完成', 'complex', [1, 0], status='processing')
        await sample('旧版本', 'complex', [1, 0], generation=2)
        await sample('已改正文', 'complex', [1, 0], revision=2)
        await sample('不同Embedding', 'complex', [1, 0], model='different-model')
        await sample('不同维度', 'complex', [1, 0, 0])
        found = await nearest(db, config, [1, 0])
        assert [row['sample_id'] for row in found] == [simple_id, complex_id]
        assert math.isclose(found[0]['similarity'], 1) and math.isclose(found[1]['similarity'], 0)
        assert classify(found, .75, .1).classification == 'simple'
        found = await nearest(db, config, [0, 1])
        assert classify(found, .75, .1).classification == 'complex'
        assert classify(await nearest(db, config, [1, 1]), .75, .1).reason == 'ROUTE_LOW_SIMILARITY'
        assert classify(await nearest(db, config, [1, 1]), .5, 0).reason == 'ROUTE_AMBIGUOUS'
        assert classify([], .5, .1).reason == 'ROUTE_NO_SAMPLES'
        config.vector_generation = 3
        assert not await nearest(db, config, [1, 0])
        config.vector_generation = 1
        print('PASS: real pgvector cosine TopK; both classes; stale/failed/revised/wrong-model/dimension exclusion; threshold/gap/tie/empty checks')
        worker_sample = RouteSample(config_id=config.id, prompt='异步向量结果', prompt_hash=hashlib.sha256('异步向量结果'.encode()).hexdigest(),
                                    classification='simple', vector_status='processing')
        db.add(worker_sample); await db.flush()
        assert not await store_vector(db, config.id, worker_sample.id, 2, 1, config.embedding_model, [1, 0])
        assert not await store_vector(db, config.id, worker_sample.id, 1, 2, config.embedding_model, [1, 0])
        assert not await store_vector(db, config.id, worker_sample.id, 1, 1, 'different-model', [1, 0])
        assert await store_vector(db, config.id, worker_sample.id, 1, 1, config.embedding_model, [1, 0])
        assert worker_sample.vector_status == 'ready'
        assert not await store_vector(db, config.id, worker_sample.id, 1, 1, config.embedding_model, [0, 1])
        assert await db.scalar(text('SELECT embedding::text FROM route_vectors WHERE sample_id=:id'), dict(id=worker_sample.id)) == '[1,0]'
        print('PASS: worker compare-and-set rejects stale generation/revision/model and duplicate completion; vector+ready state updated together')
        for mutation in ({'top_k': 0}, {'top_k': 51}, {'similarity_threshold': float('nan')},
                         {'confidence_gap': 1.1}, {'fallback': 'silent'}, {'simple_model_group': complex_group.id}):
            try:
                async with db.begin_nested():
                    changes = ','.join(f'{key}=:{key}' for key in mutation)
                    await db.execute(text(f'UPDATE route_configs SET {changes} WHERE id=:id'), {**mutation, 'id': config.id})
            except IntegrityError:
                pass
            else:
                raise AssertionError('invalid config accepted')
        for vector, dimensions in (('[0,0]', 2), ('[1,0]', 3), ('[NaN,0]', 2), ('[Infinity,0]', 2)):
            try:
                async with db.begin_nested():
                    await db.execute(text('UPDATE route_vectors SET embedding=CAST(:vector AS vector), dimensions=:dimensions WHERE sample_id=:id'),
                                     dict(vector=vector, dimensions=dimensions, id=simple_id))
            except DBAPIError:
                pass
            else:
                raise AssertionError('invalid database vector accepted')
        try:
            async with db.begin_nested():
                db.add(RouteSample(config_id=config.id, prompt='重复提示词', prompt_hash=hashlib.sha256('简单问候'.encode()).hexdigest(), classification='simple'))
                await db.flush()
        except IntegrityError:
            pass
        else:
            raise AssertionError('duplicate sample accepted')
        print('PASS: database constraints protect config ranges, duplicate samples and invalid vector storage')
        db.add(RouteDecision(request_id='req_route_fixture', config_id=config.id, virtual_model=config.virtual_model,
                             top_k=5, similarity=1, classification='simple', selected_model_group=simple.id,
                             selected_group_name=simple.name, status='classified', elapsed_ms=4,
                             evidence=[dict(sample_id=simple_id, classification='simple', similarity=1)]))
        await db.flush()
        config_id = config.id
        await db.delete(config); await db.flush()
        assert not await db.scalar(select(RouteSample.id).where(RouteSample.config_id == config_id))
        assert await db.scalar(text('SELECT count(*) FROM route_vectors')) == 0
        await db.delete(simple); await db.flush()
        decision = await db.scalar(select(RouteDecision).where(RouteDecision.request_id == 'req_route_fixture'))
        assert decision.selected_group_name == 'route-fixture-simple' and decision.config_id == config_id
        columns = set((await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='route_decisions'"))).scalars())
        assert not {'prompt', 'input', 'messages', 'body', 'response'} & columns
        print('PASS: sample/vector cascade, immutable decision snapshots and no request Prompt columns')
        await db.rollback()
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
