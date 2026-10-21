export type HistoryTurn={kind?:'chat'|'image';prompt:string;answer:string;reasoning:string;status:string;usage?:any;error:string;requestId:string;compliance:string;elapsed:number;rounds:number;finish:string;attachments:{name:string;size:number;kind:string}[];images?:{src:string;remote:boolean}[]}
export function historyId(){const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]!&15)|64;bytes[8]=(bytes[8]!&63)|128;const hex=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`}
export function historyPayload(model:string,modelType:string,parameters:unknown,turns:HistoryTurn[]){
 const saved=turns.filter(t=>t.status!=='pending').slice(-100).map(t=>({usage:t.usage?{input_tokens:t.usage.prompt_tokens??null,output_tokens:t.usage.completion_tokens??null,total_tokens:t.usage.total_tokens??null,image_count:t.kind==='image'?(t.usage.output_image_count??t.usage.image_count??null):null}:null,kind:t.kind||'chat',prompt:t.prompt,answer:t.answer,reasoning:t.reasoning,status:t.status,error:t.error.slice(0,4000),requestId:t.requestId,compliance:t.compliance,elapsed:t.elapsed,rounds:t.rounds,finish:t.finish,attachments:t.attachments.map(a=>({name:a.name,size:a.size,kind:a.kind})),images:(t.images||[]).filter(i=>i.remote).map(i=>i.src)}))
 const result={model,model_type:modelType,parameters,turns:saved}
 while(result.turns.length>1&&new TextEncoder().encode(JSON.stringify(result)).length>4*1024*1024)result.turns.shift()
 return result
}
