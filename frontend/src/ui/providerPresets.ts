import type {ProviderType,ProviderDraftMapping} from '../api/provider'

export function accountPreset(type:ProviderType|undefined,plan:string){
  const selected=type?.account_types?.[plan]
  return {...type,...selected,protocol_urls:{...type?.protocol_urls,...selected?.protocol_urls}}
}

export function categoryProtocols(type:ProviderType|undefined,plan:string,category:string|null){
  const supported=accountPreset(type,plan).supported_protocols||['openai-completions','openai-responses','anthropic-messages','openai-embeddings','openai-images','openai-rerank','ollama']
  const options=category==='rerank'?['openai-rerank']:category==='image'?['openai-images']:category==='vector'?['openai-embeddings','openai-rerank']:['openai-completions','openai-responses','anthropic-messages','ollama']
  return options.filter(p=>supported.includes(p))
}

export function providerCategoryOptions(type:ProviderType|undefined,plan:string,labels:Record<string,string>){
  return Object.entries(labels).filter(([value])=>value!=='mixed').map(([value,label])=>({
    value,label,disabled:!type||categoryProtocols(type,plan,value).length===0,
  }))
}

export function automaticConnection(type:ProviderType|undefined,plan:string,category:string|null,baseUrl:string){
  baseUrl=baseUrl.trim().replace(/\/+$/,'')
  const preset=accountPreset(type,plan),selected=categoryProtocols(type,plan,category)
  const urls=Object.fromEntries(selected.map(name=>[name,baseUrl===preset.base_url?preset.protocol_urls[name]||baseUrl:baseUrl]))
  const separate=selected.some(name=>urls[name]!==baseUrl)
  const routes=Object.fromEntries(selected.map(name=>[name,{path_prefix:'',auth_type:name==='anthropic-messages'?'x-api-key' as const:'bearer' as const}]))
  return {selected,urls,routes,separate}
}

export function mappingType(category:string|null){return category==='rerank'?'rerank':category==='multimodal'?'multimodal':category==='image'?'image':category==='vector'?'embedding':'text'}
export function syncSharedUrls(urls:Record<string,string>,previous:string,value:string){
  for(const protocol of Object.keys(urls))if(urls[protocol]===previous)urls[protocol]=value
}
export function adaptMappingTypes(rows:ProviderDraftMapping[],category:string|null){
  if(!category)return
  for(const m of rows){
    if(category==='text'&&['text','reasoning'].includes(m.model_type))continue
    if(category==='vector'&&['embedding','rerank'].includes(m.model_type))continue
    m.model_type=mappingType(category)
  }
}

export function validServiceUrl(value:string){
  try{
    const text=value.trim(),url=new URL(text)
    return ['http:','https:'].includes(url.protocol)&&!!url.hostname&&!url.username&&!url.password&&!url.search&&!url.hash&&!/[\s\\]/.test(text)&&!/(?:\/chat\/completions|\/responses|\/messages|\/embeddings|\/images\/generations|\/rerank|\/api\/chat|\/api\/tags)\/?$/.test(url.pathname)
  }catch{return false}
}

export function validProxyUrl(value:string){
  if(!value.trim())return true
  if(!validServiceUrl(value))return false
  return ['', '/'].includes(new URL(value.trim()).pathname)
}
