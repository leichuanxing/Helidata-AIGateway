export function concurrencyLabel(configured:number,effective:number|undefined,source:string){
  if(!Number.isInteger(effective)||!effective||effective<1)return configured?`配置 ${configured} · 有效未知`:`继承${source}：未知`
  if(!configured)return `继承${source}：${effective}`
  return `配置 ${configured} · 有效 ${effective}`
}
