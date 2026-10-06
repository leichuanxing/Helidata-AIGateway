import uuid
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import super_administrator
from app.core.exceptions import APIError
from app.models.backup import Backup
from app.services.backups import DIRECTORY
from app.services.sessions import audit

router = APIRouter(prefix='/api/admin/backups', tags=['手动备份'])


def public(row):
    return {c.name: getattr(row, c.name) for c in Backup.__table__.columns}


@router.get('')
async def listing(actor=Depends(super_administrator), db=Depends(get_session),
                  page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100)):
    total = await db.scalar(select(func.count()).select_from(Backup))
    rows = (await db.scalars(select(Backup).order_by(Backup.created_at.desc())
                            .offset((page-1)*page_size).limit(page_size))).all()
    return {'data': {'items': [public(r) for r in rows], 'total': total}}


@router.post('', status_code=202)
async def create(request: Request, actor=Depends(super_administrator), db=Depends(get_session)):
    row = Backup(id=str(uuid.uuid4()), actor_id=actor.id, status='queued')
    db.add(row)
    try:
        await db.flush()
        audit(db, actor.id, 'create_backup', row.id, request.client.host, resource_type='backup')
        await db.commit(); await db.refresh(row)
    except IntegrityError:
        await db.rollback()
        raise APIError(409, 'BACKUP_BUSY', '已有备份任务，请等待完成') from None
    return {'data': public(row)}


@router.get('/{ident}/download')
async def download(ident: uuid.UUID, request: Request, actor=Depends(super_administrator), db=Depends(get_session)):
    row = await db.get(Backup, str(ident))
    if not row: raise APIError(404, 'BACKUP_NOT_FOUND', '备份不存在')
    if row.status != 'ready': raise APIError(409, 'BACKUP_NOT_READY', '备份尚未完成')
    path = DIRECTORY / (str(ident) + '.tar.gz')
    if path.is_symlink() or not path.is_file():
        raise APIError(404, 'BACKUP_FILE_MISSING', '备份文件不可用')
    audit(db, actor.id, 'download_backup', row.id, request.client.host, resource_type='backup')
    await db.commit()
    return FileResponse(path, media_type='application/gzip', filename='helidata-' + str(ident) + '.tar.gz',
                        headers={'Cache-Control': 'no-store'})
