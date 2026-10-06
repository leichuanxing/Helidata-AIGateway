from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from app.core.database import get_session
from app.gateway.pipeline import GatewayPipeline
from app.schemas.chat import ChatInput

router = APIRouter(tags=['Gateway Core'])
pipeline = GatewayPipeline()


class PreflightInput(BaseModel):
    model: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')


@router.get('/v1/models')
async def models(request: Request, db=Depends(get_session)):
    return await pipeline.run(request, db, 'models')


@router.post('/api/gateway/preflight')
async def preflight(body: PreflightInput, request: Request, db=Depends(get_session)):
    return {'data': await pipeline.run(request, db, 'preflight', body.model)}


@router.post('/v1/chat/completions')
async def chat(body: ChatInput, request: Request, db=Depends(get_session)):
    return await pipeline.run(request, db, 'chat', body.model, body.model_dump(exclude_unset=True))


from app.schemas.inference import ResponsesInput,MessagesInput,EmbeddingsInput,RerankInput,ImagesInput

@router.post('/v1/responses')
async def responses(body:ResponsesInput,request:Request,db=Depends(get_session)):
    return await pipeline.run(request,db,'responses',body.model,body.model_dump(exclude_unset=True))

@router.post('/v1/messages')
async def messages(body:MessagesInput,request:Request,db=Depends(get_session)):
    return await pipeline.run(request,db,'messages',body.model,body.model_dump(exclude_unset=True))

@router.post('/v1/embeddings')
async def embeddings(body:EmbeddingsInput,request:Request,db=Depends(get_session)):
    return await pipeline.run(request,db,'embeddings',body.model,body.model_dump(exclude_unset=True))

@router.post('/v1/rerank')
async def rerank(body:RerankInput,request:Request,db=Depends(get_session)):
    return await pipeline.run(request,db,'rerank',body.model,body.model_dump(exclude_unset=True))

@router.post('/v1/images/generations')
async def images(body:ImagesInput,request:Request,db=Depends(get_session)):
    return await pipeline.run(request,db,'images',body.model,body.model_dump(exclude_unset=True))
