"""Semantic routing; separate metered Embedding subrequests precede admission."""
from time import monotonic
from datetime import datetime,timezone
from starlette.requests import Request
from sqlalchemy import select
from app.core.database import session_factory
from app.core.exceptions import APIError
from app.models.routing import RouteConfig,RouteDecision
from app.models.user import ModelGroupModel
from app.services.model_catalog import allowed_groups
from app.services.route_vectors import nearest,classify,exact_match,normalize_prompt
from app.services.route_jobs import embedding_value
from app.gateway.request_id import generate


async def authorize(db,ctx,cfg):
    groups=await allowed_groups(db,ctx.group.id);ids={group.id for group in groups}
    if not {cfg.simple_model_group,cfg.complex_model_group}.issubset(ids):
        raise APIError(403,'ROUTE_GROUP_FORBIDDEN','用户组需同时授权简单和复杂目标模型组')
    if ctx.group.model_access=='all':return
    names=set((await db.scalars(select(ModelGroupModel.logical_model).where(ModelGroupModel.model_group_id.in_(ids)))).all())
    if cfg.embedding_model not in names or cfg.virtual_model not in names:
        raise APIError(403,'ROUTE_MODEL_FORBIDDEN','用户组需授权虚拟模型和Embedding模型')


def prompt(ctx):
    body=ctx.payload or {};items=body.get('input') if ctx.operation=='responses' else body.get('messages')
    if isinstance(items,str):result=items
    else:
        texts=[]
        for item in items or []:
            if not isinstance(item,dict):raise APIError(400,'ROUTE_PROMPT_UNSUPPORTED','智能路由需要文本用户输入')
            if item.get('role') not in ('user',None):continue
            content=item.get('content')
            if isinstance(content,str):texts.append(content)
            elif isinstance(content,list):
                for block in content:
                    if not isinstance(block,dict) or block.get('type') not in ('text','input_text'):
                        raise APIError(400,'ROUTE_PROMPT_UNSUPPORTED','图像或非文本输入请使用明确的逻辑模型')
                    texts.append(block.get('text',''))
            elif item.get('type') in ('text','input_text'):texts.append(item.get('text',''))
            else:raise APIError(400,'ROUTE_PROMPT_UNSUPPORTED','智能路由需要文本用户输入')
        if any(not isinstance(t,str) for t in texts):raise APIError(400,'ROUTE_PROMPT_UNSUPPORTED','模型选择需要有效文本输入')
        result='\n'.join(texts)
    if not result.strip() or len(result)>16000 or len(result.encode())>64000:
        raise APIError(400,'ROUTE_PROMPT_UNSUPPORTED','智能路由文本输入须为1至16000字符且不超过64KB')
    if any(ord(c)<32 and c not in '\n\r\t' or ord(c)==127 for c in result):
        raise APIError(400,'ROUTE_PROMPT_UNSUPPORTED','模型选择文本包含不支持的控制字符')
    return normalize_prompt(result)


async def route(db,ctx):
    cfg=await db.scalar(select(RouteConfig).where(RouteConfig.virtual_model==ctx.logical_model))
    from app.services.operations_settings import governance
    if cfg and not governance['smart_route_enabled']:raise APIError(503,'ROUTE_DISABLED','智能路由总开关未启用')
    if not cfg:
        ctx.deferred['smart_routing']='not_applicable';return ctx.logical_model
    started=monotonic();ctx.original_model=ctx.logical_model;ctx.route_config_id=cfg.id
    snapshot={name:getattr(cfg,name) for name in ('id','virtual_model','embedding_model','vector_generation','simple_model_group','complex_model_group','top_k','similarity_threshold','confidence_gap','fallback','status')}
    evidence=[];classification=None;similarity=None;confidence=None;source='error';text=None;status='failed';reason=None;embedding_id=None;selected=None;group_name=None;selected_model=None
    try:
        if cfg.status!='enabled':raise APIError(503,'ROUTE_DISABLED','虚拟模型路由已禁用')
        if ctx.operation not in ('chat','messages','responses','preflight'):
            raise APIError(400,'MODEL_TYPE_UNSUPPORTED','虚拟模型仅支持文本生成接口')
        await authorize(db,ctx,cfg)
        if ctx.operation=='preflight':
            classification='complex';status='fallback';reason='ROUTE_PREFLIGHT_NO_INFERENCE'
        else:
            try:
                text=prompt(ctx)
                evidence=await exact_match(db,cfg,text)
                if evidence:
                    source='local_rule'
                    choice=classify(evidence,cfg.similarity_threshold,cfg.confidence_gap)
                    classification,similarity,confidence,reason=choice.classification,choice.similarity,choice.confidence,choice.reason
                    status='classified'
                else:
                    source='vector'
                    evidence,embedding_id,cfg=await vector_decision(db,ctx,cfg,snapshot,text)
                    choice=classify(evidence,cfg.similarity_threshold,cfg.confidence_gap)
                    classification,similarity,confidence,reason=choice.classification,choice.similarity,choice.confidence,choice.reason
                    if classification is None:classification='simple';status='fallback'
                    else:status='classified'
            except APIError as error:
                embedding_id=embedding_id or ctx.deferred.get('_selection_embedding_id')
                reason=error.detail['code']
                if error.status_code in (400,401,403,409,429,499) or snapshot['fallback']=='error':raise
                classification=snapshot['fallback'];status='fallback';source='fallback'
        selected=cfg.simple_model_group if classification=='simple' else cfg.complex_model_group
        from app.api.admin.smart_route import real_members
        group,members=await real_members(db,selected,ctx.operation);group_name=group.name
        ctx.route_group_id=selected;ctx.logical_model=selected_model=members[0]
        ctx.deferred['smart_routing']={'status':status,'classification':classification,'selected_model_group':selected,
                                       'request_id':ctx.request_id,'embedding_request_id':embedding_id,'reason':reason,'source':source,'confidence':confidence}
        return ctx.logical_model
    except BaseException as error:
        embedding_id=embedding_id or ctx.deferred.get('_selection_embedding_id')
        status='failed';reason=error.detail['code'] if isinstance(error,APIError) else 'ROUTE_INTERRUPTED'
        ctx.deferred['smart_routing']={'status':status,'request_id':ctx.request_id,'reason':reason,'embedding_request_id':embedding_id}
        raise
    finally:
        ctx.deferred.pop('_selection_embedding_id',None)
        if db.in_transaction():db.expunge_all();await db.rollback()
        if ctx.operation!='preflight':
            import anyio
            with anyio.CancelScope(shield=True):
                async with session_factory.begin() as history:
                    history.add(RouteDecision(request_id=ctx.request_id,config_id=snapshot['id'],virtual_model=snapshot['virtual_model'],
                        embedding_request_id=embedding_id,top_k=snapshot['top_k'],similarity=similarity,classification=classification,
                        source=source,request_kind='real',normalized_text=text,confidence=confidence,selected_model=selected_model,
                        selected_model_group=selected,selected_group_name=group_name,status=status,reason=reason,evidence=evidence,
                        elapsed_ms=round((monotonic()-started)*1000,2)))


async def vector_decision(db,ctx,cfg,snapshot,text):
    await db.commit()
    from app.gateway.pipeline import GatewayPipeline
    scope={**ctx.request.scope,'state':{**ctx.request.scope.get('state',{}),'request_id':generate(),'parent_request_id':ctx.request_id,
                                        'started':monotonic(),'received_at':datetime.now(timezone.utc)}}
    scope['state'].pop('gateway_context',None)
    child=Request(scope,receive=ctx.request.receive)
    # Keep the child ID even if its request fails, so diagnostics link to its call log.
    ctx.deferred['_selection_embedding_id']=child.state.request_id
    async with session_factory() as child_db:
        result=await GatewayPipeline().run(child,child_db,'embeddings',snapshot['embedding_model'],
            {'model':snapshot['embedding_model'],'input':text,'encoding_format':'float'})
    cfg=await db.scalar(select(RouteConfig).where(RouteConfig.id==snapshot['id']).execution_options(populate_existing=True))
    if not cfg or any(getattr(cfg,name)!=value for name,value in snapshot.items()):
        raise APIError(409,'ROUTE_CHANGED','向量请求期间模型选择配置已变化，请重新请求')
    await authorize(db,ctx,cfg)
    return await nearest(db,cfg,embedding_value(result)),child.state.request_id,cfg
