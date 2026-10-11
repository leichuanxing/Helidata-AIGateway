export const securityTabs:Record<string,string>={global_access:'IP访问控制',admin_access:'管理后台访问控制',api_access:'API访问控制',rate:'请求频率限制',login:'登录安全',bans:'IP封禁',proxies:'可信代理',logs:'安全日志'}
const fields:Record<string,string[]>={global_access:['global_access'],admin_access:['admin_access'],api_access:['api_access','key_bindings'],rate:['ip_rpm','key_rpm'],login:['login_max_attempts','login_lock_seconds'],bans:['bans'],proxies:['trusted_proxies']}
export const clone=<T>(value:T):T=>JSON.parse(JSON.stringify(value))
export const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
export function securityValues(policy:any,tab:string):Record<string,any>{return Object.fromEntries((Object.prototype.hasOwnProperty.call(fields,tab)?fields[tab]:[]).map(key=>[key,clone(policy[key])]))}
export function acceptSecuritySave(draft:any,baseline:any,sent:Record<string,any>,saved:any){
  const edits=Object.fromEntries(Object.keys(fields).flatMap(tab=>Object.keys(securityValues(draft,tab))).filter(key=>!same(draft[key],baseline[key])).map(key=>[key,clone(draft[key])]))
  for(const key of Object.keys(sent))if(same(draft[key],sent[key]))delete edits[key]
  Object.assign(baseline,clone(saved));Object.assign(draft,clone(saved),edits)
}
