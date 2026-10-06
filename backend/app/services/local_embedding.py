"""Pinned multilingual E5 ONNX CPU inference. No downloads or Provider calls."""
import asyncio,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from app.core.exceptions import APIError
VERSION='e5-small-int8:761b726dd34fb83930e26aab4e9ac3899aa1fa78'
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='compliance-embedding')
CAPACITY=threading.BoundedSemaphore(2)
_model=None
_tokenizer=None
def inference(text):
 global _model,_tokenizer
 if _model is None:
  import onnxruntime as ort
  from tokenizers import Tokenizer
  opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
  _model=ort.InferenceSession('/app/compliance-model/model.onnx',sess_options=opts,providers=['CPUExecutionProvider'])
  _tokenizer=Tokenizer.from_file('/app/compliance-model/tokenizer.json')
  _tokenizer.enable_truncation(max_length=512);_tokenizer.enable_padding()
 chunks=[text[i:i+256] for i in range(0,len(text),224)] or ['']
 vectors=[]
 for chunk in chunks:
  item=_tokenizer.encode('query: '+chunk)
  feed={'input_ids':np.array([item.ids],dtype=np.int64),'attention_mask':np.array([item.attention_mask],dtype=np.int64)}
  for inp in _model.get_inputs():
   if inp.name=='token_type_ids':feed[inp.name]=np.zeros_like(feed['input_ids'])
  raw=_model.run(None,feed)[0]
  if raw.ndim==3:
   mask=feed['attention_mask'][...,None];v=(raw*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)
  else:v=raw
  v=v[0].astype(np.float64);norm=np.linalg.norm(v)
  if not np.isfinite(v).all() or norm==0:raise ValueError('invalid local vector')
  vectors.append((v/norm).tolist())
 return vectors
async def embed(text):
 if not CAPACITY.acquire(blocking=False):raise APIError(503,'COMPLIANCE_BUSY','本地审核繁忙，请重试')
 future=POOL.submit(inference,text)
 future.add_done_callback(lambda _:CAPACITY.release())
 try:return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)),15)
 except asyncio.CancelledError:raise
 except Exception:raise APIError(503,'COMPLIANCE_EMBEDDING_UNAVAILABLE','本地语义审核不可用，请重试') from None
