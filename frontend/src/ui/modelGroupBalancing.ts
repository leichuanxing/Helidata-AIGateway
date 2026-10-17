export type WeightNode={provider_id:number;logical_model:string}

export function visibleWeightNodes<T extends WeightNode>(nodes:T[],models:string[]):T[]{
  const members=new Set(models),seen=new Set<number>()
  return nodes.filter(node=>{
    if(!members.has(node.logical_model)||seen.has(node.provider_id))return false
    seen.add(node.provider_id);return true
  })
}

export function weightsForSave(weights:Record<string,number>,nodes:WeightNode[],models:string[],loaded:boolean):Record<string,number>{
  if(!loaded)return {...weights}
  const ids=new Set(visibleWeightNodes(nodes,models).map(node=>String(node.provider_id)))
  return Object.fromEntries(Object.entries(weights).filter(([id])=>ids.has(id)))
}
