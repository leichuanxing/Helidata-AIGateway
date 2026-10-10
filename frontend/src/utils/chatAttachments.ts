export type ContentPart = {type:'text';text:string}|{type:'image_url';image_url:{url:string}}|{type:'file';file:{filename:string;file_data:string}}
export type Attachment = {id:string;name:string;size:number;kind:'image'|'pdf'|'text';data:string}
export type ChatMessage = {role:'system'|'user'|'assistant';content:string|ContentPart[]}
export const MAX_ATTACHMENTS=4,MAX_ATTACHMENT_BYTES=1024*1024,MAX_PAYLOAD_BYTES=2*1024*1024
export const ACCEPT='.png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml,.xml,.html,.css,.js,.ts,.py,.sql'
const textExtensions=new Set(['txt','md','csv','json','log','yaml','yml','xml','html','css','js','ts','py','sql'])
export function formatBytes(bytes:number){return bytes<1024?bytes+' B':bytes<1024*1024?(bytes/1024).toFixed(1)+' KB':(bytes/1024/1024).toFixed(2)+' MB'}
export function byteLength(value:unknown){return new TextEncoder().encode(JSON.stringify(value)).length}
export async function readAttachment(file:File,id:string):Promise<Attachment>{
 if(!file.size)throw new Error('不能添加空文件')
 if(file.size>MAX_ATTACHMENT_BYTES)throw new Error('每个附件最大为 1 MB')
 if(file.name.length>200||/[\x00-\x1f\\/]/.test(file.name))throw new Error('文件名过长或包含无效字符')
 const extension=file.name.toLowerCase().split('.').pop()||''
 const bytes=new Uint8Array(await file.arrayBuffer())
 let mime='',kind:Attachment['kind']='image',data=''
 if(['jpg','jpeg'].includes(extension)&&bytes[0]===255&&bytes[1]===216&&bytes[2]===255)mime='image/jpeg'
 else if(extension==='png'&&[137,80,78,71,13,10,26,10].every((n,i)=>bytes[i]===n))mime='image/png'
 else if(extension==='gif'&&['GIF87a','GIF89a'].includes(new TextDecoder().decode(bytes.slice(0,6))))mime='image/gif'
 else if(extension==='webp'&&new TextDecoder().decode(bytes.slice(0,4))==='RIFF'&&new TextDecoder().decode(bytes.slice(8,12))==='WEBP')mime='image/webp'
 else if(extension==='pdf'&&new TextDecoder().decode(bytes.slice(0,5))==='%PDF-'){mime='application/pdf';kind='pdf'}
 else if(textExtensions.has(extension)){
  if(file.size>64*1024)throw new Error('文本文件最大为 64 KB')
  try{data=new TextDecoder('utf-8',{fatal:true}).decode(bytes)}catch{throw new Error('文本文件必须为 UTF-8 编码')}
  if(!data.trim()||data.length>64000||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(data))throw new Error('文本文件为空、过长或包含二进制内容')
  kind='text'
 }else throw new Error('文件类型或内容无效，请添加 PNG、JPEG、GIF、WebP、PDF 或文本文件')
 if(mime){let binary='';for(let offset=0;offset<bytes.length;offset+=8192)binary+=String.fromCharCode(...bytes.subarray(offset,offset+8192));data='data:'+mime+';base64,'+btoa(binary)}
 return {id,name:file.name,size:file.size,kind,data}
}
export function userContent(prompt:string,attachments:Attachment[]):string|ContentPart[]{
 if(!attachments.length)return prompt
 return [{type:'text',text:prompt},...attachments.map((a):ContentPart=>a.kind==='image'?{type:'image_url',image_url:{url:a.data}}:a.kind==='pdf'?{type:'file',file:{filename:a.name,file_data:a.data}}:{type:'text',text:'附件：'+a.name+'\n'+a.data})]
}
export function boundedMessages(system:string,history:{prompt:string;answer:string;attachments:Attachment[]}[],prompt:string,attachments:Attachment[],parameters:Record<string,unknown>){
 const previous=history.slice(-20).map(t=>[{role:'user',content:userContent(t.prompt,t.attachments)},{role:'assistant',content:t.answer}] as ChatMessage[])
 const prefix:ChatMessage[]=system.trim()?[{role:'system',content:system.trim()}]:[]
 const current:ChatMessage={role:'user',content:userContent(prompt,attachments)}
 let messages=[...prefix,...previous.flat(),current],dropped=history.length-previous.length
 while(byteLength({...parameters,messages})>MAX_PAYLOAD_BYTES&&previous.length){previous.shift();dropped++;messages=[...prefix,...previous.flat(),current]}
 if(byteLength({...parameters,messages})>MAX_PAYLOAD_BYTES)throw new Error('本次请求超过 2 MB，请减少附件或系统提示词')
 return {messages,dropped,rounds:previous.length}
}
