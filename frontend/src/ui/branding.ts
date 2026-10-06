import {reactive} from 'vue'
export const branding=reactive({system_name:'合力数据AI网关',logo:'',icon:'',system_url:'',public_api_base_url:'',language:'zh-CN',timezone:'Asia/Shanghai'})
export async function loadBranding(){try{const r=await fetch('/api/public/settings');if(!r.ok)return;Object.assign(branding,(await r.json()).data);document.title=branding.system_name;let icon=document.querySelector<HTMLLinkElement>('link[rel="icon"]');if(branding.icon){if(!icon){icon=document.createElement('link');icon.rel='icon';document.head.appendChild(icon)}icon.href=branding.icon}else icon?.remove()}catch{}}
export function formatDate(value:string|number|Date){return value?new Date(value).toLocaleString(branding.language,{timeZone:branding.timezone}):'—'}
