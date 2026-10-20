export type GeneratedImage={src:string;remote:boolean}
export function imageTestPayload(model:string,prompt:string,n:number,size:string,consent:boolean){
 if(!consent)throw new Error('请先确认文生图调用及费用')
 if(!prompt.trim()||prompt.length>16000)throw new Error('请输入有效的画面描述，最多16000字符')
 if(!Number.isInteger(n)||n<1||n>4)throw new Error('图片数量须为1至4张')
 if(size&&!/^(auto|[1-9][0-9]{1,4}x[1-9][0-9]{1,4})$/.test(size))throw new Error('图片尺寸格式无效')
 return {model,prompt:prompt.trim(),n,...(size?{size}:{}),consent:true}
}
export function generatedImages(value:any):GeneratedImage[]{
 if(!Array.isArray(value?.data)||!value.data.length||value.data.length>4)throw new Error('上游未返回有效图片或图片数量超限')
 let bytes=0
 return value.data.map((row:any)=>{
  if(typeof row?.url==='string'&&row.url){
   if(row.url.length>16384)throw new Error('上游图片地址过长')
   let url:URL;try{url=new URL(row.url)}catch{throw new Error('上游图片地址无效')}
   if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error('上游图片地址协议不安全')
   return {src:url.href,remote:true}
  }
  const data=row?.b64_json
  if(typeof data!=='string'||data.length>24*1024*1024||data.length%4!==0||!/^[A-Za-z0-9+/]*={0,2}$/.test(data))throw new Error('上游图片编码无效或过大')
  bytes+=data.length/4*3
  if(bytes>32*1024*1024)throw new Error('上游图片总大小超限')
  const head=atob(data.slice(0,32)),mime=head.startsWith('\x89PNG\r\n\x1a\n')?'image/png':head.startsWith('\xff\xd8\xff')?'image/jpeg':head.startsWith('GIF87a')||head.startsWith('GIF89a')?'image/gif':head.startsWith('RIFF')&&head.slice(8,12)==='WEBP'?'image/webp':''
  if(!mime)throw new Error('上游返回了不支持的图片格式')
  return {src:`data:${mime};base64,${data}`,remote:false}
 })
}
