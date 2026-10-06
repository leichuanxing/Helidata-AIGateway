"""Recover only an owned failed test fixture identified by its captured Request ID."""
import asyncio,sys
from sqlalchemy import select,delete,text
import stage12_nonstream_regression as seed
from app.models.call_log import CallLog

async def main():
    async with seed.session_factory.begin() as db:
        row=await db.scalar(select(CallLog).where(CallLog.request_id==sys.argv[1]));assert row and row.username_snapshot.startswith('stage12_')
        user=await db.get(seed.User,row.user_id);assert user and user.username==row.username_snapshot
        prefix=user.username;name=row.request_model;assert name==prefix+'-chat'
        group=await db.get(seed.UserGroup,row.user_group_id);assert group.name==prefix
        provider=await db.get(seed.Provider,row.provider_id);assert provider.name==prefix
        await db.execute(delete(seed.User).where(seed.User.id==user.id))
        await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==group.id))
        await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.name==prefix))
        await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id==provider.id))
        await db.execute(delete(seed.Provider).where(seed.Provider.id==provider.id))
        await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([name,prefix+'-embed'])))
        await db.execute(delete(CallLog).where(CallLog.request_model.in_([name,prefix+'-embed'])))
        for table in ('usage_hourly','usage_daily'):
            await db.execute(text(f'DELETE FROM {table} WHERE request_model IN (:name,:embed)'),{'name':name,'embed':prefix+'-embed'})
        key_id=row.api_key_id
    from app.core.redis import redis_client
    keys=[k async for k in redis_client.scan_iter(match=f'sticky:{key_id}:*')]
    if keys:await redis_client.delete(*keys)
    await redis_client.aclose();await seed.engine.dispose()
    print('PASS: failed fixture recovered by captured Request ID, matching username/model/group/Provider; only its owned data removed')

if __name__=='__main__':asyncio.run(main())
