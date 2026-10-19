export const balanceStrategies:Record<string,string>={round_robin:'轮询',weighted_round_robin:'加权轮询',least_concurrency:'最少并发',random:'随机',priority:'优先级路由'}
export const balanceStrategyHelp:Record<string,{description:string;hint:string}>={
  round_robin:{description:'在可用节点之间轮流分配请求，适合处理能力相近的节点。',hint:'权重和节点优先级不参与此策略的选择。'},
  weighted_round_robin:{description:'按节点权重分配请求。节点持续可用时，权重为 1 和 3 的节点，长期请求数约为 1:3。',hint:'权重在“模型节点”中设置；比例指请求数量，不代表 Token 用量或费用比例。'},
  least_concurrency:{description:'优先选择当前正在处理请求数最少的节点，适合请求耗时差异较大的场景。',hint:'比较当前请求数量，不按最大并发的占用比例排序；权重和节点优先级不参与选择。'},
  random:{description:'每次从可用节点中等概率随机选择一个，长期分布通常较均匀。',hint:'短时间内请求数可能不均衡；权重和节点优先级不参与选择。'},
  priority:{description:'优先选择优先级数值最小的可用节点；相同优先级选择当前并发较少的节点。',hint:'优先级在“模型节点”中设置。高优先级节点不可用或并发已满时，才会使用后续优先级节点。'},
}
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
