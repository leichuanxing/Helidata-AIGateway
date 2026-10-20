type Row={bucket:string,requests:number,failure:number,usage_unavailable?:number,total_tokens:number|null,[key:string]:any}
type Field=readonly [string,string]
function escape(value:unknown){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!))}
export function missingTokenRows(rows:Row[]){return rows.filter(row=>row.requests>0&&row.total_tokens==null)}
export function usageGapNote(rows:Row[]){
  const missing=missingTokenRows(rows)
  if(!missing.length)return ''
  const requests=missing.reduce((sum,row)=>sum+row.requests,0),failures=missing.reduce((sum,row)=>sum+row.failure,0)
  return `${missing.length} 个时段未上报 Token：${requests} 次请求，失败 / 取消 ${failures} 次。橙色虚线标记未知用量，不能按 0 计算；无请求时段显示 0。`
}
export function timelineTooltip(row:Row,fields:readonly Field[],date:(value:string)=>string,format:(key:string,value:any)=>string=(_key,value)=>Number(value).toLocaleString('zh-CN')){
  const lines=[escape(date(row.bucket)),...fields.map(([key,label])=>`${escape(label)}：${row[key]==null?'未上报（未知）':escape(format(key,row[key]))}`)]
  lines.push(`请求 ${row.requests} 次 · 失败 / 取消 ${row.failure} 次`)
  if(row.requests>0&&row.total_tokens==null)lines.push('该时段未收到 Token 用量，不代表 0；请查看调用日志。')
  else if(row.usage_unavailable)lines.push(`${row.usage_unavailable} 次请求用量字段不完整，Token 仅累计已上报部分。`)
  else if(!row.requests)lines.push('该时段没有推理请求。')
  return lines.join('<br/>')
}
export function unknownTokenMarkers(rows:Row[],fields:readonly Field[],date:(value:string)=>string){
  return {silent:false,symbol:'none',lineStyle:{color:'#e7a53b',type:'dashed',width:1.5},label:{show:false},
    data:missingTokenRows(rows).map(row=>({name:'Token 未上报',xAxis:date(row.bucket),tooltip:{formatter:()=>timelineTooltip(row,fields,date)}}))}
}
