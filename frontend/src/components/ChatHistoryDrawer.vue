<script setup lang="ts">
import {ref,watch} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {api,message} from '../api/client'
import {formatDate} from '../ui/branding'
import {generatedImages} from '../utils/imagePlayground'
const visible=defineModel<boolean>({default:false})
const items=ref<any[]>([]),total=ref(0),page=ref(1),q=ref(''),loading=ref(false),detail=ref<any>(null),error=ref(''),preview=ref('')
let sequence=0
async function load(){const seq=++sequence;loading.value=true;error.value='';try{const data=(await api.get('/admin/chat-test/history',{params:{page:page.value,page_size:15,q:q.value}})).data.data;if(seq===sequence){items.value=data.items;total.value=data.total}}catch(e){if(seq===sequence)error.value=message(e)}finally{if(seq===sequence)loading.value=false}}
async function open(id:string){const seq=++sequence;loading.value=true;error.value='';try{const data=(await api.get('/admin/chat-test/history/'+id)).data.data;for(const t of data.turns)t.pictures=t.images.length?generatedImages({data:t.images.map((url:string)=>({url}))}):[];if(seq===sequence)detail.value=data}catch(e){if(seq===sequence)error.value=message(e)}finally{if(seq===sequence)loading.value=false}}
async function remove(item:any){try{await ElMessageBox.confirm('删除后无法恢复，是否删除这段测试对话？','删除对话历史',{type:'warning'});await api.delete('/admin/chat-test/history/'+item.id);if(detail.value?.id===item.id)detail.value=null;ElMessage.success('已删除');if(items.value.length===1&&page.value>1)page.value--;await load()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(message(e))}}
function date(value:string){return formatDate(value)}
watch(visible,value=>{if(value){detail.value=null;page.value=1;void load()}else{sequence++;loading.value=false;preview.value=''}})
</script>
<template>
<el-drawer v-model="visible" title="对话历史" size="min(900px, 96vw)" destroy-on-close>
 <p class="history-note">仅显示当前管理员的测试对话，保留最近50段，每段最多100轮。附件仅记录名称和大小，Base64生成图片不保存；供应商图片链接可能过期。上线前的对话无法补录。</p>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <div v-loading="loading">
 <template v-if="!detail"><div class="history-search"><el-input v-model="q" clearable placeholder="搜索对话或模型" @keyup.enter="page=1;load()"/><el-button @click="page=1;load()">查询</el-button></div>
 <el-empty v-if="!items.length&&!loading" description="暂无对话历史"/>
 <div v-for="item in items" :key="item.id" class="history-row"><button class="history-open" @click="open(item.id)"><strong>{{item.title}}</strong><span>{{item.model}} · {{date(item.updated_at)}}</span></button><el-button link type="danger" @click="remove(item)">删除</el-button></div>
 <el-pagination v-if="total" layout="total, prev, pager, next" :total="total" :page-size="15" v-model:current-page="page" @current-change="load"/>
 </template>
 <template v-else><div class="history-heading"><el-button @click="detail=null;load()">返回列表</el-button><el-button type="danger" plain @click="remove(detail)">删除</el-button></div><h3>{{detail.title}}</h3><p class="history-note">{{detail.model}} · {{date(detail.updated_at)}}</p>
 <details class="history-parameters"><summary>最近一次测试参数</summary><p v-if="detail.parameters.system" class="history-text">系统提示词：{{detail.parameters.system}}</p><p>{{detail.model_type==='image'?'图片数量 '+detail.parameters.image_count+' · 尺寸 '+(detail.parameters.image_size||'上游默认'):'温度 '+detail.parameters.temperature+' · 输出上限 '+detail.parameters.max_tokens+' Token · '+(detail.parameters.stream?'流式':'非流式')}}</p></details>
 <article v-for="(turn,index) in detail.turns" :key="index" class="history-turn"><h4>第 {{index+1}} 轮 · 你</h4><div class="history-text">{{turn.prompt}}</div><p v-for="(file,i) in turn.attachments" :key="i" class="history-note">附件：{{file.name}} · {{(file.size/1024).toFixed(1)}} KB（原文件未保存）</p><h4>模型回复</h4><details v-if="turn.reasoning"><summary>思考过程</summary><div class="history-text">{{turn.reasoning}}</div></details><div class="history-text">{{turn.answer}}</div><div class="history-images"><button v-for="(image,i) in turn.pictures" :key="i" @click="preview=image.src"><img :src="image.src" referrerpolicy="no-referrer" loading="lazy" alt="历史生成图片（链接可能已过期）"/></button></div><p v-if="turn.kind==='image'&&!turn.pictures.length" class="history-note">生成图片未持久化或未生成，请查看调用日志。</p><el-alert v-if="turn.error" :title="turn.error" type="warning" :closable="false"/><footer><span v-if="turn.usage">{{turn.kind==='image'?'图片 '+(turn.usage.image_count??'—'):'Token '+(turn.usage.total_tokens??'未上报')}}</span><span>{{({done:'完成',error:'失败',cancelled:'已停止'} as Record<string,string>)[turn.status]}} · {{(turn.elapsed/1000).toFixed(2)}} 秒</span><router-link v-if="turn.requestId" :to="'/admin/call-logs/'+encodeURIComponent(turn.requestId)">调用日志</router-link></footer></article>
 </template></div>
</el-drawer>
<el-dialog :model-value="!!preview" title="历史生成图片" width="min(960px, 94vw)" @close="preview=''"><img v-if="preview" :src="preview" referrerpolicy="no-referrer" class="history-preview" alt="历史生成图片"/></el-dialog>
</template>
<style scoped>
.history-note{font-size:12px;color:var(--muted);line-height:1.8}.history-search,.history-heading{display:flex;gap:12px;margin:16px 0}.history-heading{justify-content:space-between}.history-row{display:flex;align-items:center;gap:16px;border-bottom:1px solid var(--line);padding:16px 0}.history-open{flex:1;min-width:0;display:flex;flex-direction:column;gap:8px;text-align:left;background:none;border:0;color:var(--text);cursor:pointer;font:inherit}.history-open strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}.history-open span{font-size:12px;color:var(--muted)}.history-turn{border-top:1px solid var(--line);margin-top:20px;padding-top:12px}.history-text{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;font-size:14px}.history-turn footer{display:flex;gap:16px;color:var(--muted);font-size:12px;margin:14px 0}.history-images{display:flex;flex-wrap:wrap;gap:12px}.history-images button{border:1px solid var(--line);background:var(--soft);border-radius:8px;cursor:zoom-in;padding:4px}.history-images img{width:180px;height:180px;object-fit:contain}.history-preview{display:block;max-width:100%;max-height:65vh;margin:auto;object-fit:contain}.history-parameters{padding:12px;background:var(--soft);border-radius:8px;margin:16px 0}.el-pagination{margin-top:18px}
</style>
