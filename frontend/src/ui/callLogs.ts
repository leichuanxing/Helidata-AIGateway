export const logOperations:Record<string,string>={chat:'对话',responses:'Responses',messages:'Messages',embeddings:'向量',rerank:'重排',images:'图像生成',preflight:'预检',models:'模型目录'}
export function logNumber(value:unknown,digits=0){return value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits})}
export function logDuration(value:unknown){return value==null?'—':`${logNumber(value,1)} ms`}
export function logStatus(row:any){return row.status==='success'?'成功':row.status==='client_cancelled'?'客户端取消':row.error_code==='CONTENT_BLOCKED'?'合规拦截':row.error_code==='UPSTREAM_TIMEOUT'?'上游超时':'失败'}
