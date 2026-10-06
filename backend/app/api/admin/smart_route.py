"""Administrator-only routing configuration and durable sample operations."""
import hashlib
from time import monotonic
from datetime import datetime,timedelta,timezone
from fastapi import APIRouter,Depends,Query,Request
from pydantic import BaseModel,Field,ConfigDict,model_validator,StrictInt
from sqlalchemy import select,delete,update,func,case,or_
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.user import LogicalModel,ModelGroup,ModelGroupModel
from app.models.routing import RouteConfig,RouteSample,RouteVector,RouteDecision
from app.models.call_log import CallLog
from app.schemas.routing import RouteConfigInput,RouteSamplesInput,RouteSampleInput,parse_samples_csv
from app.api.admin.model_mappings import config_lock
from app.services.model_catalog import candidates
from app.services.sessions import audit
from app.providers.operations import compatible

router=APIRouter(prefix='/api/admin/smart-route',tags=['智能路由'])


def public(row):
    return {column.name:getattr(row,column.name) for column in row.__table__.columns}


async def config(db,ident,lock=False):
    query=select(RouteConfig).where(RouteConfig.id==ident)
    row=await db.scalar(query.with_for_update() if lock else query)
    if not row:raise APIError(404,'ROUTE_NOT_FOUND','路由规则不存在')
    return row


async def real_members(db,group_id,operation=None):
    group=await db.get(ModelGroup,group_id)
    if not group or group.status!='enabled':raise APIError(400,'ROUTE_GROUP_INVALID','路由目标模型组必须启用')
    members=(await db.execute(select(ModelGroupModel,LogicalModel).join(LogicalModel,LogicalModel.name==ModelGroupModel.logical_model)
        .where(ModelGroupModel.model_group_id==group_id).order_by(ModelGroupModel.position))).all()
    virtual=set((await db.scalars(select(RouteConfig.virtual_model))).all())
    if any(model.name in virtual for member,model in members):
        raise APIError(400,'ROUTE_RECURSION','路由目标组不能包含虚拟模型')
    usable=[]
    for member,model in members:
        if model.model_type in ('text','reasoning','multimodal'):
            if any(compatible(op,provider) for mapping,provider in await candidates(db,model.name) for op in ((operation,) if operation and operation!='preflight' else ('chat','messages','responses'))):
                usable.append(model.name)
    if not usable:raise APIError(400,'ROUTE_GROUP_EMPTY','目标模型组需要可用的文本模型映射')
    return group,usable


@router.get('/configs')
async def listing(actor=Depends(administrator),db=Depends(get_session)):
    return {'data':[public(row) for row in (await db.scalars(select(RouteConfig).order_by(RouteConfig.id))).all()]}


async def save(body,request,actor,db,row=None):
    await config_lock(db)
    if row:
        row=await config(db,row.id,True)
        if body.virtual_model!=row.virtual_model:raise APIError(409,'ROUTE_NAME_IMMUTABLE','虚拟模型名称不可修改，请新建规则')
    elif await db.get(LogicalModel,body.virtual_model):
        raise APIError(409,'ROUTE_NAME_CONFLICT','虚拟模型名称已被逻辑模型或路由占用')
    from app.services.operations_settings import vector
    if vector['model'] and body.embedding_model!=vector['model']:raise APIError(400,'VECTOR_MODEL_MISMATCH','路由规则需使用系统配置中的共享向量模型')
    embedding=await db.get(LogicalModel,body.embedding_model)
    from app.services.vector_service import pin
    if not embedding or embedding.model_type!='embedding' or not any(compatible('embeddings',p) for m,p in pin(await candidates(db,body.embedding_model),body.embedding_model)):
        raise APIError(400,'ROUTE_EMBEDDING_UNAVAILABLE','请选择有可用OpenAI兼容映射的Embedding逻辑模型')
    for ident in (body.simple_model_group,body.complex_model_group):await real_members(db,ident)
    if not row:
        if await db.scalar(select(func.count()).select_from(RouteConfig))>=100:
            raise APIError(400,'ROUTE_CONFIG_LIMIT','最多配置100条路由规则')
        db.add(LogicalModel(name=body.virtual_model,model_type='text'));await db.flush()
        row=RouteConfig(**body.model_dump());db.add(row);action='create_route'
    else:
        changed=row.embedding_model!=body.embedding_model
        for name,value in body.model_dump().items():setattr(row,name,value)
        if changed:
            row.vector_generation+=1
            await db.execute(update(RouteSample).where(RouteSample.config_id==row.id).values(vector_status='stale',vector_requested=False,vector_error=None,
                revision=RouteSample.revision+1,requested_by=actor.id,job_started_at=None,vector_request_id=None))
        action='update_route'
    await db.flush();await db.refresh(row);audit(db,actor.id,action,row.id,request.client.host,resource_type='route_config')
    result=public(row);await db.commit();return {'data':result}


@router.post('/configs',status_code=201)
async def create(body:RouteConfigInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    return await save(body,request,actor,db)


class PreviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    prompt:str=Field(min_length=1,max_length=16000)

    @model_validator(mode='after')
    def valid_prompt(self):
        RouteSampleInput(prompt=self.prompt,classification='simple',build_vector=False)
        if len(self.prompt.encode())>64000:raise ValueError('预览文本不得超过64KB')
        return self


@router.post('/configs/{ident}/preview')
async def preview(ident:int,body:PreviewInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    from app.services.admin_embedding import embedding
    from app.services.route_vectors import nearest,classify,exact_match,normalize_prompt
    from app.core.database import session_factory
    from app.gateway.request_id import generate
    import anyio
    cfg=await config(db,ident);started=monotonic()
    fields=('embedding_model','vector_generation','simple_model_group','complex_model_group','top_k','similarity_threshold','confidence_gap','fallback','status')
    snapshot={key:getattr(cfg,key) for key in fields};virtual_model=cfg.virtual_model
    text=normalize_prompt(body.prompt);source='vector';embedding_id=None;evidence=[];choice=None
    classification=None;status='failed';reason=None;group_id=None;group_name=None;models=[]
    try:
        evidence=await exact_match(db,cfg,text)
        if evidence:source='local_rule'
        else:
            try:
                await db.commit();embedding_id=generate()
                vector,_=await embedding(actor.id,snapshot['embedding_model'],text,request.client.host,request_id=embedding_id)
                cfg=await db.scalar(select(RouteConfig).where(RouteConfig.id==ident).execution_options(populate_existing=True))
                if not cfg or any(getattr(cfg,key)!=value for key,value in snapshot.items()):
                    raise APIError(409,'ROUTE_CHANGED','预览期间模型选择配置已变化，请重试')
                evidence=await nearest(db,cfg,vector)
            except APIError as error:
                if error.status_code in (400,401,403,409,429,499) or snapshot['fallback']=='error':raise
                classification=snapshot['fallback'];reason=error.detail['code'];source='fallback';status='fallback'
        if classification is None:
            choice=classify(evidence,cfg.similarity_threshold,cfg.confidence_gap)
            classification=choice.classification;reason=choice.reason;status='classified' if classification else 'failed'
            if classification is None:classification='simple';status='fallback'
        if classification:
            group_id=cfg.simple_model_group if classification=='simple' else cfg.complex_model_group
            group,models=await real_members(db,group_id);group_name=group.name
        return {'data':{'status':status,'classification':classification,'similarity':choice.similarity if choice else None,'confidence':choice.confidence if choice else None,
            'reason':reason,'source':source,'normalized_text':text,'request_kind':'preview',
            'selected_model_group':group_id,'selected_group_name':group_name,'selected_model':models[0] if models else None,
            'candidate_models':models,'evidence':evidence,'top_k':cfg.top_k,'elapsed_ms':round((monotonic()-started)*1000,2),
            'embedding_request_id':embedding_id,'virtual_model':virtual_model,'preview':True,'request_id':request.state.request_id}}
    except BaseException as error:
        status='failed';reason=error.detail['code'] if isinstance(error,APIError) else 'ROUTE_PREVIEW_INTERRUPTED'
        raise
    finally:
        if db.in_transaction():db.expunge_all();await db.rollback()
        with anyio.CancelScope(shield=True):
            async with session_factory.begin() as history:
                history.add(RouteDecision(request_id=request.state.request_id,config_id=ident,virtual_model=virtual_model,
                    embedding_request_id=embedding_id,top_k=snapshot['top_k'],source=source,request_kind='preview',normalized_text=text,
                    classification=classification,similarity=choice.similarity if choice else None,confidence=choice.confidence if choice else None,
                    selected_model_group=group_id,selected_group_name=group_name,selected_model=models[0] if models else None,
                    status=status,reason=reason,evidence=evidence,elapsed_ms=round((monotonic()-started)*1000,2)))


@router.put('/configs/{ident}')
async def edit(ident:int,body:RouteConfigInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    return await save(body,request,actor,db,await config(db,ident))


@router.delete('/configs/{ident}')
async def remove(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    await config_lock(db);row=await config(db,ident,True)
    if await db.scalar(select(ModelGroupModel.logical_model).where(ModelGroupModel.logical_model==row.virtual_model).limit(1)):
        raise APIError(409,'ROUTE_IN_USE','请先移除模型组中的虚拟模型成员')
    name=row.virtual_model
    await db.delete(row);await db.flush();await db.execute(delete(LogicalModel).where(LogicalModel.name==name))
    audit(db,actor.id,'delete_route',ident,request.client.host,resource_type='route_config');await db.commit()
    return {'data':{'message':'规则及样本已删除，历史决策保留'}}


@router.get('/samples')
async def samples(config_id:int,actor=Depends(administrator),db=Depends(get_session),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),
                  vector_status:str|None=Query(None,pattern='^(not_built|pending|processing|ready|failed|stale)$'),
                  classification:str|None=Query(None,pattern='^(simple|complex)$'),q:str=Query('',max_length=200)):
    cfg=await config(db,config_id)
    query=select(RouteSample).where(RouteSample.config_id==config_id)
    if classification:query=query.where(RouteSample.classification==classification)
    if q:query=query.where(or_(RouteSample.prompt.icontains(q,autoescape=True),RouteSample.remark.icontains(q,autoescape=True)))
    if vector_status=='not_built':query=query.where(RouteSample.vector_status=='pending',RouteSample.vector_requested.is_(False))
    elif vector_status:
        query=query.where(RouteSample.vector_status==vector_status)
        if vector_status=='pending':query=query.where(RouteSample.vector_requested.is_(True))
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(RouteSample.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':[{**public(row),'model_group_id':cfg.simple_model_group if row.classification=='simple' else cfg.complex_model_group} for row in rows],'total':total}}


async def add_samples(ident,items,request,actor,db,build_vector=None):
    await config_lock(db);await config(db,ident,True)
    hashes=[hashlib.sha256(item.prompt.encode()).hexdigest() for item in items]
    if len(hashes)!=len(set(hashes)) or await db.scalar(select(RouteSample.id).where(RouteSample.config_id==ident,RouteSample.prompt_hash.in_(hashes)).limit(1)):
        raise APIError(409,'ROUTE_SAMPLE_DUPLICATE','样本Prompt重复，本批次未导入')
    count=await db.scalar(select(func.count()).select_from(RouteSample).where(RouteSample.config_id==ident))
    if count+len(items)>10000:raise APIError(400,'ROUTE_SAMPLE_LIMIT','每条规则最多10000条样本')
    rows=[RouteSample(config_id=ident,prompt=item.prompt,prompt_hash=digest,classification=item.classification,
        similarity_threshold=item.similarity_threshold,remark=item.remark,vector_requested=item.build_vector if build_vector is None else build_vector,requested_by=actor.id) for item,digest in zip(items,hashes)]
    db.add_all(rows);await db.flush()
    audit(db,actor.id,'add_route_samples',ident,request.client.host,resource_type='route_config')
    ids=[row.id for row in rows];queued=sum(row.vector_requested for row in rows)
    await db.commit();return {'data':{'ids':ids,'vector_status':'pending','queued':queued}}


@router.post('/samples',status_code=201)
async def add(body:RouteSamplesInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    return await add_samples(body.config_id,body.samples,request,actor,db)


class CSVInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    config_id:int=Field(gt=0,strict=True)
    content:str=Field(max_length=2*1024*1024)
    build_vector: bool=True


@router.post('/samples/import',status_code=201)
async def csv_import(body:CSVInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    return await add_samples(body.config_id,parse_samples_csv(body.content.encode('utf-8')),request,actor,db,body.build_vector)


class BuildSamplesInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    config_id:int=Field(gt=0,strict=True)
    sample_ids:list[StrictInt]=Field(default_factory=list,max_length=500)
    all_samples:bool=False

    @model_validator(mode='after')
    def selection(self):
        if self.all_samples==bool(self.sample_ids):raise ValueError('请选择样本或构建全部')
        if len(set(self.sample_ids))!=len(self.sample_ids) or any(isinstance(i,bool) or i<=0 for i in self.sample_ids):raise ValueError('Invalid sample selection')
        return self


@router.post('/samples/vectorize')
async def build_samples(body:BuildSamplesInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    await config_lock(db);await config(db,body.config_id,True)
    query=select(RouteSample).where(RouteSample.config_id==body.config_id)
    if not body.all_samples:query=query.where(RouteSample.id.in_(body.sample_ids))
    rows=(await db.scalars(query.with_for_update())).all()
    if not body.all_samples and len(rows)!=len(body.sample_ids):
        raise APIError(400,'ROUTE_SAMPLE_SELECTION_INVALID','选中的样本不存在或不属于当前规则')
    for row in rows:retry_sample(row,actor)
    audit(db,actor.id,'build_route_vectors',body.config_id,request.client.host,resource_type='route_config')
    await db.commit();return {'data':{'queued':len(rows)}}


async def locked_sample(db,ident):
    row=await db.get(RouteSample,ident)
    if not row:raise APIError(404,'ROUTE_SAMPLE_NOT_FOUND','样本不存在')
    await config_lock(db);await config(db,row.config_id,True)
    row=await db.scalar(select(RouteSample).where(RouteSample.id==ident).with_for_update().execution_options(populate_existing=True))
    if not row:raise APIError(404,'ROUTE_SAMPLE_NOT_FOUND','样本不存在')
    return row


def retry_sample(row,actor):
    row.revision+=1;row.vector_status='pending';row.vector_error=None
    row.vector_requested=True
    row.job_started_at=None;row.vector_request_id=None;row.requested_by=actor.id


@router.put('/samples/{ident}')
async def sample_edit(ident:int,body:RouteSampleInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    row=await locked_sample(db,ident);digest=hashlib.sha256(body.prompt.encode()).hexdigest()
    if await db.scalar(select(RouteSample.id).where(RouteSample.config_id==row.config_id,RouteSample.prompt_hash==digest,RouteSample.id!=ident)):
        raise APIError(409,'ROUTE_SAMPLE_DUPLICATE','相同Prompt的样本已存在')
    row.prompt=body.prompt;row.prompt_hash=digest;row.classification=body.classification;retry_sample(row,actor)
    row.similarity_threshold=body.similarity_threshold;row.remark=body.remark;row.vector_requested=body.build_vector
    await db.flush();await db.refresh(row);result=public(row)
    audit(db,actor.id,'update_route_sample',ident,request.client.host,resource_type='route_sample');await db.commit()
    return {'data':result}


@router.post('/samples/{ident}/vectorize')
async def sample_retry(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    row=await locked_sample(db,ident);retry_sample(row,actor)
    await db.flush();await db.refresh(row);result=public(row)
    audit(db,actor.id,'retry_route_sample',ident,request.client.host,resource_type='route_sample');await db.commit()
    return {'data':result}


@router.delete('/samples/{ident}')
async def sample_delete(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    row=await locked_sample(db,ident);await db.delete(row)
    audit(db,actor.id,'delete_route_sample',ident,request.client.host,resource_type='route_sample');await db.commit()
    return {'data':{'message':'样本及向量已删除'}}


def period(start,end):
    end=end or datetime.now(timezone.utc);start=start or end-timedelta(days=7)
    if not start.tzinfo or not end.tzinfo or start>=end or end-start>timedelta(days=31):
        raise APIError(422,'ROUTE_TIME_INVALID','请提供带时区且不超过31天的时间范围')
    return start,end


def decision_query():
    return select(RouteDecision,CallLog.operation,CallLog.logical_model.label('actual_model'),CallLog.upstream_model,
        CallLog.total_tokens,CallLog.status.label('call_status')).outerjoin(CallLog,CallLog.request_id==RouteDecision.request_id)


def decision_row(row,detail=False):
    value=public(row[0])
    if not detail:
        value.pop('evidence',None);text=value.pop('normalized_text',None);value['text_excerpt']=text[:200] if text else None
    value.update(operation=row.operation,selected_model=row.actual_model or row[0].selected_model,
        upstream_model=row.upstream_model,total_tokens=row.total_tokens,call_status=row.call_status)
    return value


@router.get('/logs')
async def logs(actor=Depends(administrator),db=Depends(get_session),request_id:str|None=Query(None,max_length=80),
               virtual_model:str|None=Query(None,max_length=100),start:datetime|None=None,end:datetime|None=None,
               classification:str|None=Query(None,pattern='^(simple|complex|unclassified)$'),
               status:str|None=Query(None,pattern='^(classified|fallback|failed)$'),
               operation:str|None=Query(None,max_length=20),selected_model:str|None=Query(None,max_length=100),
               source:str|None=Query(None,pattern='^(vector|local_rule|fallback|error|legacy)$'),
               request_kind:str|None=Query(None,pattern='^(real|preview)$'),q:str=Query('',max_length=200),
               page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    query=decision_query()
    if request_id:query=query.where(RouteDecision.request_id==request_id)
    else:
        start,end=period(start,end);query=query.where(RouteDecision.created_at>=start,RouteDecision.created_at<end)
    if virtual_model:query=query.where(RouteDecision.virtual_model==virtual_model)
    if classification=='unclassified':query=query.where(RouteDecision.classification.is_(None))
    elif classification:query=query.where(RouteDecision.classification==classification)
    if status:query=query.where(RouteDecision.status==status)
    if operation:query=query.where(CallLog.operation==operation)
    if source:query=query.where(RouteDecision.source==source)
    if request_kind:query=query.where(RouteDecision.request_kind==request_kind)
    selected=func.coalesce(CallLog.logical_model,RouteDecision.selected_model)
    if selected_model:query=query.where(selected==selected_model)
    if q:query=query.where(or_(RouteDecision.request_id.icontains(q,autoescape=True),RouteDecision.virtual_model.icontains(q,autoescape=True),
        selected.icontains(q,autoescape=True),RouteDecision.normalized_text.icontains(q,autoescape=True)))
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.execute(query.order_by(RouteDecision.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':[decision_row(row) for row in rows],'total':total}}


@router.get('/logs/{ident}')
async def log_detail(ident:int,actor=Depends(administrator),db=Depends(get_session)):
    row=(await db.execute(decision_query().where(RouteDecision.id==ident))).first()
    if not row:raise APIError(404,'ROUTE_DECISION_NOT_FOUND','模型选择决策不存在')
    return {'data':decision_row(row,True)}


@router.get('/statistics')
async def statistics(actor=Depends(administrator),db=Depends(get_session),start:datetime|None=None,end:datetime|None=None,virtual_model:str|None=Query(None,max_length=100)):
    start,end=period(start,end)
    filters=[RouteDecision.created_at>=start,RouteDecision.created_at<end]
    if virtual_model:filters.append(RouteDecision.virtual_model==virtual_model)
    def joined(statement):
        return statement.select_from(RouteDecision).outerjoin(CallLog,CallLog.request_id==RouteDecision.request_id).where(*filters)
    failed=or_(RouteDecision.status=='failed',CallLog.status=='failure')
    def metrics():return [func.count().label('decisions'),func.count().filter(RouteDecision.request_kind=='real').label('real_requests'),
        func.count().filter(RouteDecision.request_kind=='preview').label('previews'),func.count().filter(failed).label('failures'),
        func.count(CallLog.total_tokens).label('usage_count'),func.sum(CallLog.total_tokens).label('total_tokens'),
        func.avg(CallLog.total_tokens).label('average_tokens'),func.sum(RouteDecision.elapsed_ms).label('elapsed_ms')]
    overview=(await db.execute(joined(select(*metrics())))).mappings().one()
    dimensions=(RouteDecision.classification,RouteDecision.status,RouteDecision.selected_model_group,RouteDecision.selected_group_name)
    rows=(await db.execute(joined(select(*dimensions,func.count().label('requests'),func.avg(RouteDecision.elapsed_ms).label('elapsed_ms'),
        func.avg(RouteDecision.similarity).label('similarity'),func.sum(CallLog.total_tokens).label('total_tokens'),func.count(CallLog.total_tokens).label('usage_count')))
        .group_by(*dimensions))).mappings().all()
    async def distribution(dimension):
        statement=joined(select(dimension.label('name'),*metrics())).group_by(dimension).order_by(func.count().desc(),dimension)
        return [dict(row) for row in (await db.execute(statement)).mappings().all()]
    token_band=case((CallLog.total_tokens.is_(None),'unknown'),(CallLog.total_tokens<1000,'0-999'),
        (CallLog.total_tokens<10000,'1000-9999'),else_='10000+')
    distributions={'classification':await distribution(RouteDecision.classification),'source':await distribution(RouteDecision.source),
        'model':await distribution(func.coalesce(CallLog.logical_model,RouteDecision.selected_model)),'tokens':await distribution(token_band)}
    return {'data':{'start':start,'end':end,'items':[dict(row) for row in rows],'summary':dict(overview),
        'distributions':distributions,'token_scope':'仅父推理请求；Embedding子调用在独立用量中统计',
        'metric_scope':'真实请求与预览分别计数；失败包含决策失败或实际调用失败（不重复）；Token仅统计父推理已上报用量；累计耗时为决策耗时'}}
