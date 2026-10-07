export const settingsTabs:Record<string,string>={brand:'基础与品牌',basic:'基础设置',performance:'性能设置',vector:'向量服务',smart:'智能路由',compliance:'内容合规',elasticsearch:'Elasticsearch'}
export const copy=<T>(value:T):T=>value===undefined?value:JSON.parse(JSON.stringify(value))
export const equal=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
export function settingsPayload(form:any,rules:string,tab:string):Record<string,any>{
  switch(tab){
    case 'brand':return {basic:Object.fromEntries(['system_name','logo','icon','system_url','language','timezone'].map(key=>[key,form.basic[key]]))}
    case 'basic':return {basic:{public_api_base_url:form.basic.public_api_base_url},logging:{...form.logging,redaction_rules:rules.split('\n').map(x=>x.trim()).filter(Boolean)},gateway:{protocol_conversion:form.gateway.protocol_conversion}}
    case 'performance':return {gateway:Object.fromEntries(Object.entries(form.gateway).filter(([key])=>key!=='protocol_conversion'))}
    case 'vector':return {vector:{...form.vector}}
    case 'smart':return {governance:{smart_route_enabled:form.governance.smart_route_enabled}}
    case 'compliance':return {governance:{compliance_enabled:form.governance.compliance_enabled,semantic_threshold:form.governance.semantic_threshold??null}}
    case 'elasticsearch':{const {secret_configured,...es}=form.elasticsearch;return {elasticsearch:es}}
    default:return {}
  }
}
// Update only the submitted fields, preserving edits made during the request.
export function acceptSaved(form:any,baseline:any,sent:Record<string,any>,saved:any){
  form.revision=baseline.revision=saved.revision
  for(const [section,fields] of Object.entries(sent)){
    for(const key of Object.keys(fields)){
      if(equal(form[section][key],fields[key]))form[section][key]=copy(saved[section][key])
      baseline[section][key]=copy(saved[section][key])
    }
    if(section==='elasticsearch')form.elasticsearch.secret_configured=baseline.elasticsearch.secret_configured=saved.elasticsearch.secret_configured
  }
}
