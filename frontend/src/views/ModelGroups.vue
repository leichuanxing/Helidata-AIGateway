<script setup lang="ts">
import {computed,onMounted,reactive,ref} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {api,message} from '../api/client'
import {formatDate} from '../ui/branding'
import {type ModelGroup} from '../api/models'
import {visibleWeightNodes,weightsForSave} from '../ui/modelGroupBalancing'
const rows=ref<ModelGroup[]>([]),options=ref<{name:string;model_type:string}[]>([]),page=ref(1),total=ref(0),q=ref(''),loading=ref(false),saving=ref(false),dialog=ref(false),editing=ref<number|null>(null),error=ref(''),dragging=ref<number|null>(null)
const dragTarget=ref<number|null>(null)
const protocol=ref(''),categoryLabels:Record<string,string>={text:'文本',multimodal:'多模态',image:'文生图',vector:'向量'}
const category=(type:string)=>type==='multimodal'?'multimodal':type==='image'?'image':['embedding','rerank'].includes(type)?'vector':'text'
const visibleOptions=computed(()=>options.value.filter(o=>!form.protocol_type||category(o.model_type)===form.protocol_type))
const strategies:Record<string,string>={legacy:'原有粘性调度',round_robin:'轮询',weighted_round_robin:'加权轮询',least_concurrency:'最少并发'}
type Node={mapping_id:number;provider_id:number;provider_name:string;logical_model:string;upstream_model:string;status:string;mapping_status:string;health:string;weight:number;priority:number;max_concurrency:number;current_concurrency:number;requests:number;success_rate:number|null;average_latency_ms:number|null;last_error_code:string|null;cooldown_until:string|null}
const nodeRows=ref<Node[]>([]),nodeLoading=ref(false),monitor=ref(false),monitorGroup=ref<ModelGroup|null>(null),hours=ref(24)
const healthLabels:Record<string,string>={Available:'可用',Cooling:'冷却中',Unavailable:'不可用',Disabled:'已禁用'}
const blank=()=>({name:'',description:'',status:'enabled',protocol_type:'text' as string|null,logical_models:[] as string[],balancing_strategy:'least_concurrency',max_retries:2,attempt_timeout:120,retry_uncertain:false,node_weights:{} as Record<string,number>})
const form=reactive(blank())
const weightNodes=computed(()=>visibleWeightNodes(nodeRows.value,form.logical_models))
const nodesLoaded=ref(false)
async function load(){loading.value=true;error.value='';try{const d=(await api.get('/admin/model-groups',{params:{page:page.value,q:q.value,protocol_type:protocol.value}})).data.data;rows.value=d.items;total.value=d.total;options.value=(await api.get('/admin/logical-models')).data.data}catch(e){error.value=message(e)}finally{loading.value=false}}
function open(g?:ModelGroup){nodeGeneration++;nodesLoaded.value=false;editing.value=g?.id??null;Object.assign(form,blank(),g?{name:g.name,description:g.description,status:g.status,protocol_type:g.protocol_type??null,logical_models:[...g.logical_models],balancing_strategy:g.balancing_strategy,max_retries:g.max_retries,attempt_timeout:g.attempt_timeout,retry_uncertain:g.retry_uncertain,node_weights:{...g.node_weights}}:{});dialog.value=true;nodeRows.value=[];if(g)void loadNodes(g.id);else nodeLoading.value=false}
let nodeGeneration=0
async function loadNodes(id:number){const generation=++nodeGeneration;nodeLoading.value=true;nodesLoaded.value=false;try{const data=(await api.get('/admin/model-groups/'+id+'/nodes',{params:{hours:hours.value}})).data.data;if(generation===nodeGeneration){nodeRows.value=data.items;nodesLoaded.value=true}}catch(e){if(generation===nodeGeneration)ElMessage.error(message(e))}finally{if(generation===nodeGeneration)nodeLoading.value=false}}
function showMonitor(g:ModelGroup){monitorGroup.value=g;monitor.value=true;nodeRows.value=[];void loadNodes(g.id)}
async function toggleNode(n:Node){try{await ElMessageBox.confirm('此操作修改供应商状态，将影响引用该账号的所有模型组。','确认'+(n.status==='enabled'?'停用':'启用'),{type:'warning'});await api.patch('/admin/providers/'+n.provider_id,{status:n.status==='enabled'?'disabled':'enabled'});if(monitorGroup.value)await loadNodes(monitorGroup.value.id)}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(message(e))}}
function move(from:number,to:number){if(to<0||to>=form.logical_models.length||from===to)return;const m=form.logical_models.splice(from,1)[0];if(m!==undefined)form.logical_models.splice(to,0,m)}
function startDrag(i:number,e:DragEvent){dragging.value=i;e.dataTransfer?.setData('text/plain',String(i))}
function drop(i:number){if(dragging.value!==null)move(dragging.value,i);dragging.value=null;dragTarget.value=null}
async function save(){if(saving.value)return;if(editing.value&&nodeLoading.value){ElMessage.warning('请等待节点配置加载完成');return}if(!form.name.trim()){ElMessage.error('请填写名称');return}form.name=form.name.trim();saving.value=true;try{if(editing.value)await api.put('/admin/model-groups/'+editing.value,{...form,node_weights:weightsForSave(form.node_weights,nodeRows.value,form.logical_models,nodesLoaded.value)});else await api.post('/admin/model-groups',form);dialog.value=false;await load();ElMessage.success('模型组及顺序已保存')}catch(e){ElMessage.error(message(e))}finally{saving.value=false}}
async function remove(g:ModelGroup){try{await ElMessageBox.confirm('已授权给用户组的模型组不能删除，请先取消关联。','删除 '+g.name,{type:'warning',confirmButtonText:'删除',cancelButtonText:'取消'});await api.delete('/admin/model-groups/'+g.id);await load()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(message(e))}}
onMounted(load)
</script>
<template>
  <section class="panel group-page">
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="toolbar"><el-button type="primary" @click="open()">添加分组</el-button><el-select v-model="protocol" placeholder="全部类型" clearable style="width:160px" @change="page=1;load()"><el-option v-for="(label,value) in categoryLabels" :key="value" :label="label" :value="value"/></el-select><el-input v-model="q" clearable placeholder="搜索名称" style="width:240px" @keyup.enter="page=1;load()"/><el-button :loading="loading" @click="page=1;load()">刷新</el-button></div>
    <el-table :data="rows" v-loading="loading" empty-text="暂无模型组">
      <el-table-column prop="name" label="名称" min-width="180"/>
      <el-table-column label="协议类型" width="120"><template #default="s">{{categoryLabels[s.row.protocol_type]??'历史混合类型'}}</template></el-table-column>
      <el-table-column label="模型" min-width="300"><template #default="s"><div class="model-tags"><el-tag v-for="m in s.row.logical_models" :key="m" size="small">{{m}}</el-tag><span v-if="!s.row.logical_models.length" class="muted">-</span></div></template></el-table-column>
      <el-table-column label="调度策略" min-width="150"><template #default="s">{{strategies[s.row.balancing_strategy]||'原有粘性调度'}}</template></el-table-column>
      <el-table-column prop="description" label="备注" min-width="180"/>
      <el-table-column label="创建时间" min-width="175"><template #default="s">{{s.row.created_at?formatDate(s.row.created_at):'-'}}</template></el-table-column>
      <el-table-column label="操作" width="190" fixed="right"><template #default="s"><el-button link type="primary" @click="open(s.row)">编辑</el-button><el-button link type="primary" @click="showMonitor(s.row)">负载监控</el-button><el-button link type="danger" @click="remove(s.row)">删除</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next" @current-change="load"/>
  </section>
  <el-drawer v-model="dialog" :title="editing?'编辑分组':'添加分组'" size="440px" class="model-group-drawer">
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="名称" required><el-input v-model="form.name" maxlength="80"/></el-form-item>
      <el-form-item label="协议类型" required><el-select v-model="form.protocol_type" style="width:100%"><el-option v-if="form.protocol_type===null" :value="null" label="历史混合类型"/><el-option v-for="(label,value) in categoryLabels" :key="value" :label="label" :value="value"/></el-select></el-form-item>
      <el-form-item label="模型"><el-select v-model="form.logical_models" multiple filterable allow-create default-first-option style="width:100%" placeholder="选择候选模型或输入新模型名"><el-option v-for="o in visibleOptions" :key="o.name" :value="o.name" :label="o.name"/></el-select></el-form-item>
      <ol v-if="form.logical_models.length" class="model-order"><li v-for="(m,i) in form.logical_models" :key="m" draggable="true" :class="{'drag-target':dragTarget===i,dragging:dragging===i}" @dragenter.prevent="dragTarget=i" @dragstart="startDrag(i,$event)" @dragover.prevent @drop.prevent="drop(i)" @dragend="dragging=null;dragTarget=null"><span class="order-handle" aria-hidden="true">⋮⋮</span><span class="order-name">{{m}}</span><div><el-button text size="small" :aria-label="'上移 '+m" :disabled="i===0" @click="move(i,i-1)">上移</el-button><el-button text size="small" :aria-label="'下移 '+m" :disabled="i===form.logical_models.length-1" @click="move(i,i+1)">下移</el-button></div></li></ol>
      <el-form-item label="备注"><el-input v-model="form.description" maxlength="2000"/></el-form-item>
      <el-divider content-position="left">负载均衡</el-divider>
      <el-form-item label="调度策略"><el-select v-model="form.balancing_strategy" style="width:100%"><el-option v-for="(label,value) in strategies" :key="value" :value="value" :label="label"/></el-select></el-form-item>
      <p class="muted">先按模型顺序、原生协议与供应商优先级分层，同层节点执行算法。多个授权组包含同一模型时使用 ID 最小的组；智能路由使用选中的目标组。</p>
      <el-form-item label="最大重试次数"><el-input-number v-model="form.max_retries" :min="0" :max="7"/><span class="muted">　次（不含首次）</span></el-form-item>
      <el-form-item label="单次尝试超时"><el-input-number v-model="form.attempt_timeout" :min="1" :max="3600"/><span class="muted">　秒</span></el-form-item><p class="muted">普通响应及 SSE 建连使用此期限；总耗时仍受系统非流式超时限制，SSE 建连后使用系统空闲超时。</p><el-form-item label="允许结果不确定时重试"><el-switch v-model="form.retry_uncertain"/></el-form-item>
      <el-alert :closable="false" type="warning" title="默认只重试明确的连接失败、鉴权拒绝和限流。启用后将重试读超时及上游异常，可能重复计费；流式响应开始后始终不重试。"/>
      <template v-if="editing"><h3>节点权重</h3><p class="muted">权重按供应商在当前组内保存。优先级和最大并发复用供应商配置，对所有引用组生效。</p><div v-loading="nodeLoading"><div v-for="n in weightNodes" :key="n.provider_id" class="node-weight"><router-link :to="'/admin/providers/'+n.provider_id">{{n.provider_name}}</router-link><el-input-number :model-value="form.node_weights[String(n.provider_id)]??1" :min="1" :max="100" @update:model-value="(v:number|undefined)=>form.node_weights[String(n.provider_id)]=v??1"/><span class="muted">优先级 {{n.priority}} · 最大并发 {{n.max_concurrency}}</span></div></div></template>
      <el-form-item v-if="editing&&form.status!=='enabled'" label="历史状态"><el-select v-model="form.status"><el-option label="启用" value="enabled"/><el-option label="禁用" value="disabled"/></el-select></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="dialog=false">取消</el-button><el-button type="primary" :disabled="!form.name.trim()" :loading="saving" @click="save">保存</el-button></template>
  </el-drawer>
  <el-drawer v-model="monitor" :title="(monitorGroup?.name||'')+' · 负载监控'" size="min(1100px, 96vw)">
    <div class="toolbar"><el-select v-model="hours" style="width:160px" @change="monitorGroup&&loadNodes(monitorGroup.id)"><el-option label="最近 1 小时" :value="1"/><el-option label="最近 24 小时" :value="24"/><el-option label="最近 7 天" :value="168"/></el-select><el-button :loading="nodeLoading" @click="monitorGroup&&loadNodes(monitorGroup.id)">刷新</el-button></div>
    <p class="muted">并发为供应商实时总占用；统计为当前组成员模型的已落库上游尝试，包含故障节点与客户端取消。历史无耗时记录不统计。</p>
    <el-table :data="nodeRows" v-loading="nodeLoading"><el-table-column label="节点 / 模型" min-width="200"><template #default="s"><router-link :to="'/admin/providers/'+s.row.provider_id">{{s.row.provider_name}}</router-link><div>{{s.row.logical_model}} → {{s.row.upstream_model}}</div><small class="muted">映射{{s.row.mapping_status==='enabled'?'启用':'禁用'}} · 优先级 {{s.row.priority}} · 权重 {{s.row.weight}}</small></template></el-table-column><el-table-column label="并发" width="95"><template #default="s">{{s.row.current_concurrency}} / {{s.row.max_concurrency}}</template></el-table-column><el-table-column prop="requests" label="请求数" width="85"/><el-table-column label="成功率" width="95"><template #default="s">{{s.row.success_rate===null?'—':s.row.success_rate+'%'}}</template></el-table-column><el-table-column label="平均响应" width="115"><template #default="s">{{s.row.average_latency_ms===null?'—':s.row.average_latency_ms+' ms'}}</template></el-table-column><el-table-column label="健康状态" min-width="175"><template #default="s"><el-tag :type="s.row.health==='Available'?'success':'warning'">{{healthLabels[s.row.health]||s.row.health}}</el-tag><div class="muted">{{s.row.last_error_code||'—'}}</div><small v-if="s.row.cooldown_until">冷却至 {{formatDate(s.row.cooldown_until)}}</small></template></el-table-column><el-table-column label="操作" width="90"><template #default="s"><el-button link :type="s.row.status==='enabled'?'danger':'primary'" @click="toggleNode(s.row)">{{s.row.status==='enabled'?'停用':'启用'}}</el-button></template></el-table-column></el-table>
  </el-drawer>
</template>
<style scoped>
.node-weight{display:grid;grid-template-columns:1fr 130px;gap:10px;padding:12px 0;border-bottom:1px solid var(--line)}.node-weight .muted{grid-column:1/-1;font-size:12px}.node-weight a{overflow-wrap:anywhere;color:var(--el-color-primary)}
.group-page{min-height:calc(100vh - 82px);margin:0}.toolbar{gap:12px}.model-tags{display:flex;flex-wrap:wrap;gap:6px}.el-pagination{margin-top:20px}.model-order{padding:0;margin:0 0 18px;list-style:none}.model-order li{display:flex;gap:10px;align-items:center;padding:10px;margin:6px 0;border:1px solid var(--line);border-radius:4px}.model-order li>div{margin-left:auto;flex-shrink:0}.order-name{overflow-wrap:anywhere;min-width:0}.order-handle{cursor:grab;color:var(--muted)}.model-order .drag-target{border-color:var(--el-color-primary);background:var(--el-color-primary-light-9)}.model-order .dragging{opacity:.5}
</style>
