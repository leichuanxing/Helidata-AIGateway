export const balanceStrategies:Record<string,string>={round_robin:'轮询',weighted_round_robin:'加权轮询',least_concurrency:'最少并发',random:'随机',priority:'优先级路由'}
export const balanceTypes:Record<string,string>={text:'文本',reasoning:'推理',multimodal:'多模态',embedding:'向量',rerank:'重排',image:'文生图'}
export type BalanceNode={id?:number;mapping_id:number;weight:number;priority:number;max_concurrency:number;status:string;[key:string]:any}
export const blankBalanceRoute=()=>({name:'',model_name:'',model_type:'text',strategy:'round_robin',status:'enabled',description:'',max_concurrency:100,max_retries:2,timeout_seconds:60,retry_uncertain:false,health_interval:30,cooldown_seconds:30,failure_threshold:3,config_version:0,nodes:[] as BalanceNode[]})
export function routePayload(value:ReturnType<typeof blankBalanceRoute>,editing:boolean){
  const {config_version,nodes,...fields}=value
  // Read-only node health, statistics and provider metadata never enter a save.
  return {...Object.fromEntries(Object.keys(blankBalanceRoute()).filter(k=>!['nodes','config_version'].includes(k)).map(k=>[k,(fields as Record<string,unknown>)[k]])),
    ...(editing?{expected_config_version:config_version}:{}),nodes:nodes.map(n=>({mapping_id:n.mapping_id,weight:n.weight,priority:n.priority,max_concurrency:n.max_concurrency,status:n.status}))}
}
export function matchesBalanceType(wanted:string,actual:string){return wanted===actual||['text','reasoning'].includes(wanted)&&['text','reasoning'].includes(actual)}
