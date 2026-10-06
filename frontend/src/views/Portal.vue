<script setup lang="ts">
import {onMounted,ref,computed,watch} from 'vue'
import {branding} from '../ui/branding'
import {api,message} from '../api/client'
import {copyText} from '../ui/clipboard'
import {category,squareModels,filterModels,pageModels,type CatalogModel,type CatalogGroup,type ModelCategory} from '../ui/modelSquare'
const apiBase=computed(()=>branding.public_api_base_url||window.location.origin+'/v1')
const groups=ref<CatalogGroup[]>([]),error=ref(''),loading=ref(false),q=ref(''),type=ref<ModelCategory>('all'),page=ref(1),pageSize=ref(20)
const documentation=ref(false),example=ref(''),exampleModel=ref('')
const categories=[{value:'all',label:'所有'},{value:'text',label:'文本'},{value:'image',label:'文生图'},{value:'vector',label:'向量'},{value:'rerank',label:'重排序'}] as const
const labels={text:'文本',image:'文生图',vector:'向量',rerank:'重排序'}
const models=computed(()=>squareModels(groups.value)),filtered=computed(()=>filterModels(models.value,type.value,q.value))
const paged=computed(()=>pageModels(filtered.value,page.value,pageSize.value))
watch([q,type,pageSize],()=>{page.value=1})
watch(filtered,()=>{page.value=pageModels(filtered.value,page.value,pageSize.value).page})
async function load(){loading.value=true;error.value='';try{groups.value=(await api.get('/portal/models')).data.data.groups}catch(e){error.value=message(e)}finally{loading.value=false}}
const endpoints=[
  {path:'/models',method:'GET',description:'查看已授权且可调用的模型'},
  {path:'/chat/completions',method:'POST',description:'OpenAI 聊天补全，支持流式输出'},
  {path:'/responses',method:'POST',description:'OpenAI Responses；需上游支持'},
  {path:'/messages',method:'POST',description:'Anthropic Messages；使用 x-api-key'},
  {path:'/embeddings',method:'POST',description:'文本向量'},
  {path:'/rerank',method:'POST',description:'文档重排；需上游支持'},
  {path:'/images/generations',method:'POST',description:'图片生成；需上游支持'}
]
function showExample(m:CatalogModel){
  let path='chat/completions',body:any={model:m.logical_model,messages:[{role:'user',content:'你好'}],max_tokens:32}
  if(m.model_type==='embedding'){path='embeddings';body={model:m.logical_model,input:'示例文本'}}
  else if(m.model_type==='rerank'){path='rerank';body={model:m.logical_model,query:'示例问题',documents:['示例文档']}}
  else if(m.model_type==='image'){path='images/generations';body={model:m.logical_model,prompt:'一座山'}}
  exampleModel.value=m.logical_model
  example.value='curl '+JSON.stringify(apiBase.value+'/'+path)+' \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '+"'"+JSON.stringify(body,null,2).replace(/'/g,"'\\''")+"'"
}
onMounted(load)
</script>
<template>
  <section class="panel square-page" aria-label="模型广场">
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="square-access"><div><span class="muted">接入地址</span><code>{{apiBase}}</code></div><div class="square-access-actions"><el-button @click="copyText(apiBase)">复制</el-button><el-button @click="documentation=true">接口说明</el-button></div></div>
    <div class="square-filters"><el-radio-group v-model="type" aria-label="模型分类"><el-radio-button v-for="c in categories" :key="c.value" :value="c.value">{{c.label}}</el-radio-button></el-radio-group><div class="square-search"><el-input v-model="q" placeholder="搜索模型名称" clearable aria-label="搜索模型名称"/><el-button :loading="loading" aria-label="刷新模型" @click="load"><UiIcon name="refresh"/></el-button></div></div>
    <div class="square-content" v-loading="loading">
      <div v-if="paged.items.length" class="square-cards"><article v-for="m in paged.items" :key="m.logical_model" class="square-card"><div class="square-card-title"><span class="square-symbol"><UiIcon :name="m.virtual?'route':category(m.model_type)==='vector'?'chart':category(m.model_type)==='image'?'image':'chat'"/></span><button class="square-model-name" @click="showExample(m)">{{m.logical_model}}</button><el-button text class="square-copy" :aria-label="'复制模型 '+m.logical_model" @click="copyText(m.logical_model)"><UiIcon name="copy"/></el-button></div><div class="square-tags"><el-tag size="small">{{labels[category(m.model_type)]}}</el-tag><el-tag v-if="m.virtual" size="small">智能路由</el-tag></div></article></div>
      <EmptyState v-else-if="!loading" :title="q?'没有匹配的模型':type==='all'?'暂无可调用模型':'当前分类暂无可调用模型'" description="调整筛选条件，或联系管理员确认模型权限及账号状态。"/>
    </div>
    <footer class="square-footer"><span class="muted">共 {{filtered.length}} 项数据</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20,50,100]" :total="filtered.length" layout="sizes, prev, pager, next"/></footer>
  </section>
  <el-dialog v-model="documentation" title="接口说明" width="740px"><el-descriptions :column="1" border><el-descriptions-item label="接入地址">{{apiBase}}</el-descriptions-item><el-descriptions-item label="认证方式">Authorization: Bearer &lt;API_KEY&gt;<br/>Messages 也支持 x-api-key；调用需使用已授权模型。</el-descriptions-item></el-descriptions><el-table :data="endpoints" style="margin-top:16px"><el-table-column prop="method" label="方法" width="80"/><el-table-column prop="path" label="接口" min-width="185"/><el-table-column prop="description" label="说明" min-width="230"/></el-table><template #footer><el-button @click="documentation=false">关闭</el-button><el-button type="primary" @click="documentation=false;$router.push('/portal/api-keys')">管理 API Keys</el-button></template></el-dialog>
  <el-dialog :model-value="!!example" :title="exampleModel+' · 调用示例'" width="640px" @close="example=''"><p class="muted">替换 YOUR_API_KEY 后调用。模型与上游须支持相应接口。</p><pre>{{example}}</pre><template #footer><el-button @click="example=''">关闭</el-button><el-button type="primary" @click="copyText(example)">复制示例</el-button></template></el-dialog>
</template>
<style scoped>
.square-page{margin:0;min-height:calc(100vh - 82px);display:flex;flex-direction:column;padding:16px}
.square-access{display:flex;align-items:center;justify-content:space-between;padding:20px;border:1px solid var(--line);border-radius:4px;gap:16px}.square-access code{display:block;margin-top:8px;font:600 13px ui-monospace,Consolas,monospace;overflow-wrap:anywhere}.square-access-actions{display:flex;flex-shrink:0}
.square-filters{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:18px 0}.square-search{display:flex;gap:8px;max-width:330px}.square-content{flex:1}.square-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.square-card{border:1px solid var(--line);border-radius:4px;padding:16px;min-height:120px;display:flex;flex-direction:column;justify-content:space-between;gap:22px}.square-card-title{display:flex;align-items:flex-start;gap:12px}.square-symbol{display:grid;place-items:center;flex-shrink:0;width:36px;height:36px;border-radius:4px;background:var(--el-color-primary-light-9);color:var(--el-color-primary)}.square-model-name{font-family:inherit;font-size:13px;font-weight:600;line-height:1.6;text-align:left;border:0;background:transparent;color:var(--text);overflow-wrap:anywhere;cursor:pointer;min-width:0;padding:4px 0;flex:1}.square-copy{padding:4px;height:28px;flex-shrink:0;color:var(--muted)}.square-copy .ui-icon{width:16px;height:16px}.square-tags{display:flex;gap:8px}.square-tags .el-tag{border:0;border-radius:2px}.square-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;border-top:1px solid var(--line);padding-top:16px;margin-top:60px}
.square-filters :deep(.el-radio-button__inner){border:0;border-radius:4px!important;background:var(--soft);box-shadow:none;padding:10px 16px}.square-filters :deep(.el-radio-button.is-active .el-radio-button__inner){background:var(--surface);color:var(--el-color-primary);box-shadow:0 2px 6px #00000014;font-weight:600}
@media(max-width:1250px){.square-cards{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:1000px){.square-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.square-cards{grid-template-columns:1fr}.square-access,.square-filters,.square-footer{align-items:flex-start;flex-direction:column}.square-search{max-width:100%;width:100%}.square-page{min-height:calc(100vh - 78px)}}
</style>
