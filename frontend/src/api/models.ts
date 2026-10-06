export const modelTypes:Record<string,string>={text:'文本',reasoning:'推理',multimodal:'多模态',embedding:'Embedding',rerank:'Rerank',image:'图片生成'}
export type Mapping={id:number;provider_id:number;logical_model:string;upstream_model:string;model_type:string;status:string}
export type ModelGroup={created_at?:string;id:number;name:string;description:string;status:string;protocol_type?:'text'|'image'|'vector'|null;logical_models:string[]}
