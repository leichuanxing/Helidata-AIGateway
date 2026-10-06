from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.dependencies import active_user
from app.models.user import User
from app.schemas.auth import Profile, public_user
from app.services.sessions import audit

router=APIRouter(prefix='/api/portal',tags=['个人设置'])


@router.patch('/profile')
async def profile(body: Profile,request: Request,user: User=Depends(active_user),db: AsyncSession=Depends(get_session)):
    await db.refresh(user,with_for_update=True)
    for key,value in body.model_dump(exclude_unset=True).items():
        setattr(user,key,value)
    audit(db,user.id,'update_profile',user.id,request.client.host)
    await db.commit()
    return {'data':public_user(user)}
