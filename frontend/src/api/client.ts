import axios from 'axios'
export const api=axios.create({baseURL:'/api',withCredentials:true})
export type User={id:number;username:string;name:string;email:string|null;phone:string|null;role:string;status:string;user_group_id:number|null;must_change_password:boolean;last_login_at:string|null;created_at:string;remark?:string;login_locked?:boolean|null;lock_remaining_seconds?:number|null}
let access=''
export function setAccess(value:string){access=value}
function csrf(){return document.cookie.split('; ').find(x=>x.startsWith('hd_csrf='))?.split('=').slice(1).join('=')||''}
api.interceptors.request.use(config=>{
  if(access)config.headers.Authorization='Bearer '+access
  const nonce=csrf();if(nonce)config.headers['X-CSRF-Token']=decodeURIComponent(nonce)
  return config
})
let refreshing:Promise<any>|null=null
export async function renew(){
  if(!refreshing) refreshing=api.post('/auth/refresh').then(r=>{setAccess(r.data.data.access_token);return r.data.data}).finally(()=>{refreshing=null})
  return refreshing
}
api.interceptors.response.use(r=>r,async error=>{
  const config=error.config
  if(error.response?.status===401 && config && !config._retried && !['/auth/login','/auth/refresh','/auth/logout'].includes(config.url)){
    config._retried=true
    try{await renew();return await api(config)}catch{setAccess('');window.location.assign('/login')}
  }
  return Promise.reject(error)
})
export function message(error:any){return error.response?.data?.error?.message||'请求失败，请稍后重试'}


// Fetch is required for incremental SSE; keep the same in-memory session lifecycle.
export async function sessionFetch(url:string,init:RequestInit){
 const send=()=>{const headers=new Headers(init.headers);if(access)headers.set('Authorization','Bearer '+access);return fetch(url,{...init,headers,credentials:'same-origin'})}
 let response=await send()
 if(response.status===401&&!init.signal?.aborted){await renew();response=await send()}
 return response
}
