/** Display helpers preserve unknown values and distinguish no traffic from success. */
export function metric(value:unknown,digits=0){return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:digits}):'—'}
export function percentage(part:number|null|undefined,total:number|null|undefined){return part==null||total==null||total<=0?null:part/total*100}
export function rate(part:number|null|undefined,total:number|null|undefined){const value=percentage(part,total);return value==null?'—':metric(value,1)+'%'}
export function loadPercent(active:number|null,capacity:number){return percentage(active,capacity)}
export function rankMetric(row:{total_tokens:number|null,token_samples:number,requests:number}){
 const value=metric(row.total_tokens)
 return row.total_tokens==null?'未上报 Token':value+(row.token_samples<row.requests?'（部分上报）':'')
}
