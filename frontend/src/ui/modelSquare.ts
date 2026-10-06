export type CatalogModel={logical_model:string;model_type:string;position:number;configured:boolean;virtual:boolean}
export type CatalogGroup={id:number;name:string;description:string;models:CatalogModel[]}
export type ModelCategory='all'|'text'|'image'|'vector'|'rerank'
export function category(type:string):Exclude<ModelCategory,'all'>{
  return type==='image'?'image':type==='rerank'?'rerank':type==='embedding'?'vector':'text'
}
export function squareModels(groups:CatalogGroup[]):CatalogModel[]{
  const models=new Map<string,CatalogModel>()
  for(const group of groups)for(const model of group.models){
    if(!model.configured)continue
    const previous=models.get(model.logical_model)
    models.set(model.logical_model,{...model,virtual:model.virtual||previous?.virtual||false})
  }
  return [...models.values()].sort((a,b)=>Number(b.virtual)-Number(a.virtual)||a.logical_model.localeCompare(b.logical_model,'zh-CN'))
}
export function filterModels(models:CatalogModel[],type:ModelCategory,query:string){
  const q=query.trim().toLocaleLowerCase()
  return models.filter(m=>(type==='all'||category(m.model_type)===type)&&m.logical_model.toLocaleLowerCase().includes(q))
}
export function pageModels(models:CatalogModel[],page:number,pageSize:number){
  const size=Math.max(1,Math.trunc(pageSize)||20)
  const current=Math.max(1,Math.min(Math.trunc(page)||1,Math.max(1,Math.ceil(models.length/size))))
  return {page:current,items:models.slice((current-1)*size,current*size)}
}
