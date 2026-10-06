"""UI fixtures only. Requires a marker in a fresh, isolated /data mount."""
import asyncio
from pathlib import Path
from sqlalchemy import func,select
from app.core.database import engine,session_factory
from app.core.security import hash_password
from app.models.user import (Provider,User,UserGroup,Role,LogicalModel,ProviderModelMapping,
    ModelGroup,ModelGroupModel,UserGroupModelGroup)

async def main():
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    async with session_factory.begin() as db:
        assert await db.scalar(select(func.count()).select_from(Provider))==0
        assert await db.scalar(select(func.count()).select_from(User))==1
        groups=[UserGroup(name='fixture-team-a'),UserGroup(name='fixture-team-b'),UserGroup(name='unavailable-team')]
        model_groups=[ModelGroup(name='fixture-models-a'),ModelGroup(name='fixture-models-b',protocol_type='text'),ModelGroup(name='unavailable-models',protocol_type='text')]
        provider=Provider(name='fixture-only-no-inference',provider_type='custom_openai',protocol='openai',base_url='http://127.0.0.1:9/v1')
        db.add_all([*groups,*model_groups,provider]);await db.flush()
        roles=dict((code,ident) for ident,code in (await db.execute(select(Role.id,Role.code))).all())
        # Public test-only password; never used for production identities.
        for username,role in [('replica-viewer','user'),('replica-manager','super_admin')]:
            db.add(User(username=username,role=role,role_id=roles[role],user_group_id=groups[0].id,
                password_hash=await hash_password('Reproduction!Fixture2026'),must_change_password=False))
        for i in (0,1):db.add(UserGroupModelGroup(user_group_id=groups[0].id,model_group_id=model_groups[i].id))
        db.add(UserGroupModelGroup(user_group_id=groups[2].id,model_group_id=model_groups[2].id))
        entries=[('deepseek-flash','text'),('semantic-vector','embedding'),('picture-model','image')]
        entries += [(f'fixture-text-{i:02d}','text') for i in range(25)]
        entries += [('unconfigured-model','text'),('not-authorized-model','text')]
        for pos,(name,kind) in enumerate(entries):
            db.add(LogicalModel(name=name,model_type=kind));await db.flush()
            if name!='unconfigured-model':db.add(ProviderModelMapping(provider_id=provider.id,logical_model=name,model_type=kind,upstream_model=name))
            group=model_groups[2] if name=='not-authorized-model' else model_groups[0]
            db.add(ModelGroupModel(model_group_id=group.id,logical_model=name,position=pos))
        db.add(ModelGroupModel(model_group_id=model_groups[1].id,logical_model='deepseek-flash',position=0))
    await engine.dispose()
    print('PASS: isolated UI fixtures ready; 28 available unique authorized models; no inference calls.')

asyncio.run(main())
