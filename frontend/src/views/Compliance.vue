<script setup lang="ts">
import {computed,reactive,ref,watch,onUnmounted} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ElMessage,ElMessageBox} from 'element-plus'
import {api,message} from '../api/client'
import {formatDate} from '../ui/branding'
const route=useRoute(),router=useRouter(),view=computed(()=>route.path.split('/').pop()||'words')
const tabs={words:'敏感词',samples:'审核样本',policies:'策略组',logs:'审核日志'}
const label:Record<string,string>={low:'低',medium:'中',high:'高',critical:'严重',enabled:'启用',disabled:'禁用',not_built:'未构建',pending:'排队中',processing:'构建中',ready:'已就绪',failed:'构建失败',audit:'仅审计',block:'拦截',pass:'通过',word:'关键词',sample:'样本语义',text:'文本',wildcard:'通配符',regex:'正则',chat:'OpenAI Completions',messages:'Anthropic Messages',responses:'OpenAI Responses',embeddings:'Embeddings',images:'Images',rerank:'Rerank'}
const rows=ref<any[]>([]),policies=ref<any[]>([]),words=ref<any[]>([]),samples=ref<any[]>([]),groups=ref<any[]>([]),models=ref<any[]>([])
const loading=ref(false),saving=ref(false),building=ref(false),error=ref(''),page=ref(1),total=ref(0),selected=ref<number[]>([]),remoteVectors=ref(false),dialog=ref(false),editing=ref<number|null>(null),detail=ref<any>(null),importing=ref(false),busy=reactive<Record<number,boolean>>({})
const filters=reactive({q:'',policy_id:undefined as number|undefined,status:'',vector_status:'',action:'',risk:'',source:'',request_id:String(route.query.request_id||'')})
const days=ref(7),range=ref<[Date,Date]|null>(null)
const blank=()=>({pattern:'',kind:'text',risk:'medium' as string|null,status:'enabled',remark:'',text:'',name:'',action:'audit',description:'',policy_id:undefined as number|undefined,word_ids:[] as number[],sample_ids:[] as number[],group_ids:[] as number[],models:[] as string[],threshold:.85})
const form=reactive(blank()),importForm=reactive({policy_id:undefined as number|undefined,lines:'',status:'enabled'})
let generation=0
async function load(){
 const mine=++generation;loading.value=true;error.value=''
 try{
  const params:any={page:page.value,q:filters.q||undefined}
  if(view.value==='words'||view.value==='samples'){params.page_size=20;params.policy_id=filters.policy_id;if(view.value==='samples'){params.enabled=filters.status||undefined;params.status=filters.vector_status||undefined}else params.status=filters.status||undefined}
  if(view.value==='policies')params.status=filters.status||undefined
  if(view.value==='logs'){
   Object.assign(params,{request_id:filters.request_id||undefined,action:filters.action||undefined,risk:filters.risk||undefined,source:filters.source||undefined,policy_id:filters.policy_id})
   const end=range.value?.[1]||new Date(),start=range.value?.[0]||new Date(end.getTime()-days.value*86400000);params.start=start.toISOString();params.end=end.toISOString()
  }
  const [result,options]=await Promise.all([api.get('/admin/compliance/'+view.value,{params}),api.get('/admin/compliance/policies')])
  if(mine!==generation)return
  const data=result.data.data;rows.value=data.items;total.value=data.total??data.items.length;policies.value=options.data.data.items;selected.value=[]
  if(view.value==='samples')remoteVectors.value=String(data.model_version||'').startsWith('upstream:')
 }catch(e){if(mine===generation)error.value=message(e)}finally{if(mine===generation)loading.value=false}
}
async function open(row?:any){
 editing.value=row?.id||null;Object.assign(form,blank(),row||{})
 form.word_ids=[...(row?.word_ids||[])];form.sample_ids=[...(row?.sample_ids||[])];form.group_ids=[...(row?.group_ids||[])];form.models=[...(row?.models||[])]
 form.policy_id=row?.policies?.length===1?row.policies[0].id:undefined
 if(view.value==='policies'){
  if(!row)form.status='enabled'
  try{
   const [w,s,g,m]=await Promise.all([api.get('/admin/compliance/words'),api.get('/admin/compliance/samples',{params:{page_size:500}}),api.get('/admin/user-group-options'),api.get('/admin/logical-models')])
   words.value=w.data.data.items;samples.value=s.data.data.items;groups.value=g.data.data.items||g.data.data;models.value=m.data.data.data||m.data.data
  }catch(e){ElMessage.error(message(e));return}
 }
 dialog.value=true
}
async function save(){
 if(view.value!=='policies'&&!form.policy_id&&!editing.value){ElMessage.warning('请选择所属策略组');return}
 if(!(view.value==='words'?form.pattern:view.value==='samples'?form.text:form.name).trim()){ElMessage.warning('请填写必填内容');return}
 saving.value=true
 try{
  let body:any
  if(view.value==='words')body={pattern:form.pattern,kind:form.kind,risk:form.risk||'medium',status:form.status,remark:form.remark}
  else if(view.value==='samples')body={text:form.text,risk:form.risk||'medium',status:form.status,remark:form.remark,build_vector:false}
  else body={name:form.name,action:form.action,risk:form.risk,description:form.description,status:form.status,word_ids:form.word_ids,sample_ids:form.sample_ids,group_ids:form.group_ids,models:form.models,threshold:form.threshold}
  if(view.value!=='policies'&&form.policy_id)body.policy_id=form.policy_id
  await api[editing.value?'put':'post']('/admin/compliance/'+view.value+(editing.value?'/'+editing.value:''),body)
  ElMessage.success(view.value==='samples'?'已保存；新增或修改文本后请构建向量':'已保存');dialog.value=false;await load()
 }catch(e){ElMessage.error(message(e))}finally{saving.value=false}
}
async function toggle(row:any,value:any){
 busy[row.id]=true
 try{await api.patch('/admin/compliance/'+view.value+'/'+row.id+'/status',{status:value?'enabled':'disabled'});row.status=value?'enabled':'disabled';ElMessage.success('状态已更新')}
 catch(e){ElMessage.error(message(e))}finally{busy[row.id]=false}
}
async function remove(row:any){
 try{
  await ElMessageBox.confirm('删除后该资源不再参与审核，历史日志保留。策略组仍有词或样本时无法删除。','确认删除',{type:'warning'})
  await api.delete('/admin/compliance/'+view.value+'/'+row.id);ElMessage.success('已删除');await load()
 }catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(message(e))}
}
async function build(all=false,ids=selected.value){
 if(!all&&!ids.length){ElMessage.warning('请先选择审核样本');return}
 building.value=true
 try{
  await ElMessageBox.confirm((all?'构建全部审核样本': '构建 '+ids.length+' 条审核样本')+'。'+(remoteVectors.value?'将调用共享向量服务，可能产生用量和费用。':'使用本地向量服务。'),'确认构建向量',{confirmButtonText:'构建',cancelButtonText:'取消'})
  const result=(await api.post('/admin/compliance/samples/build',{all,ids:all?[]:ids,consent:true})).data.data
  ElMessage.success('已排队 '+result.queued+' 条；正在构建的样本不会重复排队');await load()
 }catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(message(e))}finally{building.value=false}
}
async function importWords(){
 if(!importForm.policy_id||!importForm.lines.trim()){ElMessage.warning('请选择策略组并填写敏感词');return}
 saving.value=true
 try{const d=(await api.post('/admin/compliance/words/import',importForm)).data.data;ElMessage.success('导入 '+d.created+' 条，跳过 '+d.skipped+' 条重复词');importing.value=false;await load()}catch(e){ElMessage.error(message(e))}finally{saving.value=false}
}
function riskOf(row:any){const risks=(row.matches||[]).flatMap((m:any)=>m.risk?[m.risk]:(m.evidence||[]).map((e:any)=>e.risk));return ['critical','high','medium','low'].find(r=>risks.includes(r))||''}
function riskType(r:string){return ['high','critical'].includes(r)?'danger':r==='medium'?'warning':'success'}
function policyNames(row:any){return row.policies?.map((p:any)=>p.name).join('、')||'未分配（历史配置）'}
function sourceNames(row:any){return [...new Set((row.matches||[]).flatMap((m:any)=>(m.evidence||[]).map((e:any)=>label[e.source]||e.source)))].join('、')||'—'}
function groupNames(ids:number[]){return ids.map(i=>groups.value.find(g=>g.id===i)?.name||'#'+i).join('、')||'全部'}
function reset(reload=true){Object.assign(filters,{q:'',policy_id:undefined,status:'',vector_status:'',action:'',risk:'',source:'',request_id:''});range.value=null;days.value=7;page.value=1;if(reload)load()}
watch(()=>route.fullPath,()=>{rows.value=[];total.value=0;selected.value=[];dialog.value=false;detail.value=null;reset(false);filters.request_id=String(route.query.request_id||'');load()},{immediate:true})
const timer=window.setInterval(()=>{if(view.value==='samples'&&!dialog.value&&!loading.value&&!building.value&&!selected.value.length)load()},5000)
onUnmounted(()=>{clearInterval(timer);generation++})
</script>
<template>
 <div class="compliance-page">
  <PageHeader title="内容合规" description="维护敏感词、语义审核样本与策略组，查看请求审核结果及命中证据。"/>
  <el-alert v-if="error" :title="error" type="error" :closable="false" class="gap"/>
  <div class="panel">
   <el-tabs :model-value="view" @tab-change="(name:any)=>router.push('/admin/compliance/'+name)">
    <el-tab-pane v-for="(name,key) in tabs" :key="key" :name="key" :label="name"/>
   </el-tabs>
   <div class="toolbar">
    <el-select v-if="view!=='policies'" v-model="filters.policy_id" clearable filterable placeholder="全部策略组" class="filter"><el-option v-for="p in policies" :key="p.id" :label="p.name" :value="p.id"/></el-select>
    <el-select v-if="view!=='logs'" v-model="filters.status" clearable placeholder="全部状态" class="filter"><el-option label="启用" value="enabled"/><el-option label="禁用" value="disabled"/></el-select>
    <el-select v-if="view==='samples'" v-model="filters.vector_status" clearable placeholder="全部向量状态" class="filter"><el-option v-for="s in ['not_built','pending','processing','ready','failed']" :key="s" :label="label[s]" :value="s"/></el-select>
    <template v-if="view==='logs'">
     <el-select v-model="filters.action" clearable placeholder="全部动作" class="filter"><el-option v-for="a in ['block','audit','pass']" :key="a" :label="label[a]" :value="a"/></el-select>
     <el-select v-model="filters.risk" clearable placeholder="全部风险等级" class="filter"><el-option v-for="r in ['low','medium','high','critical']" :key="r" :label="label[r]" :value="r"/></el-select>
     <el-select v-model="filters.source" clearable placeholder="全部检测方式" class="filter"><el-option label="关键词" value="word"/><el-option label="样本语义" value="sample"/></el-select>
     <el-select v-model="days" class="filter" @change="range=null"><el-option v-for="d in [1,7,30]" :key="d" :label="'最近'+d+'天'" :value="d"/></el-select>
     <el-date-picker v-model="range" type="datetimerange" start-placeholder="开始时间" end-placeholder="结束时间"/>
    </template>
    <el-input v-model="filters.q" clearable :placeholder="view==='logs'?'搜索 Request ID、模型或证据':view==='words'?'搜索敏感词':view==='samples'?'搜索审核样本':'搜索策略组'" class="search" @keyup.enter="page=1;load()"/>
    <el-button @click="page=1;load()">查询</el-button><el-button @click="reset">重置</el-button>
   </div>
   <div v-if="view!=='logs'" class="toolbar actions">
    <el-button type="primary" @click="open()">添加{{tabs[view as keyof typeof tabs]}}</el-button>
    <el-button v-if="view==='words'" :disabled="!policies.length" @click="importForm.policy_id=undefined;importForm.lines='';importing=true">批量导入</el-button>
    <template v-if="view==='samples'"><el-button :loading="building" :disabled="!selected.length" @click="build(false)">构建选中向量</el-button><el-button :loading="building" :disabled="!total" @click="build(true)">构建全部向量</el-button></template>
    <span v-if="(view==='words'||view==='samples')&&!policies.length" class="muted">请先创建策略组，再添加{{tabs[view as keyof typeof tabs]}}。</span>
   </div>
   <el-alert v-if="view==='samples'" type="info" :closable="false" :title="(remoteVectors?'使用系统设置中的共享向量服务；构建向量可能产生费用。':'使用本地向量服务。')+'新增或修改文本后需构建向量；未就绪、禁用及版本过期的样本不参与语义检测。'" class="gap"/>
   <el-table :data="rows" v-loading="loading" @selection-change="(list:any[])=>selected=list.map(r=>r.id)" row-key="id" empty-text="暂无记录">
    <el-table-column v-if="view==='samples'" type="selection" width="44"/>
    <el-table-column v-if="view==='words'" prop="pattern" label="敏感词" min-width="220" show-overflow-tooltip/>
    <el-table-column v-if="view==='samples'" prop="text" label="样本文本" min-width="250" show-overflow-tooltip/>
    <template v-if="view==='words'||view==='samples'">
     <el-table-column label="策略组" min-width="160"><template #default="{row}">{{policyNames(row)}}</template></el-table-column>
     <el-table-column v-if="view==='words'" label="匹配方式" width="110"><template #default="{row}">{{label[row.kind]}}</template></el-table-column>
     <el-table-column v-if="view==='samples'" label="向量状态" width="120"><template #default="{row}"><el-tag :type="row.vector_status==='ready'?'success':row.vector_status==='failed'?'danger':'info'">{{label[row.vector_status]}}</el-tag></template></el-table-column>
     <el-table-column v-if="view==='samples'" prop="vector_error" label="构建错误" min-width="170" show-overflow-tooltip/>
     <el-table-column prop="remark" label="备注" min-width="150" show-overflow-tooltip/>
    </template>
    <template v-if="view==='policies'">
     <el-table-column prop="name" label="名称" min-width="160"/>
     <el-table-column label="动作" width="110"><template #default="{row}"><el-tag :type="row.action==='block'?'danger':'warning'">{{label[row.action]}}</el-tag></template></el-table-column>
     <el-table-column label="风险等级" width="120"><template #default="{row}"><el-tag v-if="row.risk" :type="riskType(row.risk)">{{label[row.risk]}}</el-tag><span v-else>按规则（历史）</span></template></el-table-column>
     <el-table-column label="敏感词 / 样本" width="140"><template #default="{row}">{{row.word_ids.length}} / {{row.sample_ids.length}}</template></el-table-column>
     <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip/>
    </template>
    <el-table-column v-if="view!=='logs'" label="状态" width="100"><template #default="{row}"><el-switch :model-value="row.status==='enabled'" :loading="busy[row.id]" @change="(value:any)=>toggle(row,value)" :aria-label="'启停 '+(row.name||row.pattern||row.text)"/></template></el-table-column>
    <template v-if="view==='logs'">
     <el-table-column label="Request ID" min-width="280"><template #default="{row}"><router-link class="link" :to="'/admin/call-logs/'+row.request_id">{{row.request_id}}</router-link></template></el-table-column>
     <el-table-column prop="model" label="请求模型" min-width="140"/>
     <el-table-column label="检测方式" min-width="120"><template #default="{row}">{{sourceNames(row)}}</template></el-table-column>
     <el-table-column label="策略组" min-width="150"><template #default="{row}">{{row.matches?.map((m:any)=>m.policy_name).join('、')||'—'}}</template></el-table-column>
     <el-table-column label="动作" width="100"><template #default="{row}"><el-tag :type="row.action==='block'?'danger':row.action==='audit'?'warning':'success'">{{label[row.action]}}</el-tag></template></el-table-column>
     <el-table-column label="风险等级" width="110"><template #default="{row}"><el-tag v-if="riskOf(row)" :type="riskType(riskOf(row))">{{label[riskOf(row)]}}</el-tag><span v-else>—</span></template></el-table-column>
     <el-table-column prop="elapsed_ms" label="耗时 ms" width="95"/>
     <el-table-column label="审核时间" min-width="170"><template #default="{row}">{{formatDate(row.created_at)}}</template></el-table-column>
    </template>
    <el-table-column label="操作" :width="view==='samples'?240:view==='logs'?90:160" fixed="right"><template #default="{row}">
     <el-button v-if="view==='logs'" link type="primary" @click="detail=row">查看</el-button>
     <template v-else><el-button link type="primary" @click="open(row)">编辑</el-button><el-button v-if="view==='samples'" link type="primary" :disabled="['pending','processing'].includes(row.vector_status)" @click="build(false,[row.id])">构建向量</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template>
    </template></el-table-column>
   </el-table>
   <el-pagination v-if="view!=='policies'" v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next" @current-change="load" class="pagination"/>
  </div>
  <el-drawer v-model="dialog" :title="(editing?'编辑':'添加')+tabs[view as keyof typeof tabs]" size="660px" destroy-on-close>
   <el-form label-position="top">
    <template v-if="view!=='policies'">
     <el-form-item label="策略组" :required="!editing"><el-select v-model="form.policy_id" filterable placeholder="选择所属策略组" style="width:100%"><el-option v-for="p in policies" :key="p.id" :value="p.id" :label="p.name+' · '+label[p.status]"/></el-select></el-form-item>
     <el-alert v-if="editing&&!form.policy_id" title="此历史资源可能被多个策略引用；留空保留已有引用，选择后转移到指定策略组。" type="info" :closable="false" class="gap"/>
     <el-form-item v-if="view==='words'" label="敏感词" required><el-input v-model="form.pattern" maxlength="256"/></el-form-item>
     <el-form-item v-else label="样本文本" required><el-input v-model="form.text" type="textarea" :rows="7" maxlength="2000" show-word-limit/></el-form-item>
     <el-form-item v-if="view==='words'" label="匹配方式"><el-select v-model="form.kind"><el-option v-for="k in ['text','wildcard','regex']" :key="k" :value="k" :label="label[k]"/></el-select><p class="muted">文本包含匹配忽略大小写；通配符支持 * 和 ?；正则执行有时限。</p></el-form-item>
     <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" maxlength="2000" show-word-limit/></el-form-item>
    </template>
    <template v-else>
     <el-form-item label="名称" required><el-input v-model="form.name" maxlength="80"/></el-form-item>
     <el-form-item label="动作" required><el-select v-model="form.action"><el-option label="仅审计" value="audit"/><el-option label="拦截" value="block"/></el-select></el-form-item>
     <el-alert v-if="form.action==='block'" title="命中后直接拦截，不向目标生成模型发送请求。语义检测可能调用向量服务。" type="warning" :closable="false" class="gap"/>
     <el-form-item label="风险等级" required><el-select v-model="form.risk"><el-option v-for="r in ['low','medium','high']" :key="r" :label="label[r]" :value="r"/><el-option v-if="editing&&form.risk===null" label="按规则风险（保留历史行为）" :value="null as any"/></el-select></el-form-item>
     <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000"/></el-form-item>
     <el-collapse><el-collapse-item title="规则与适用范围" name="scope">
      <el-form-item label="敏感词"><el-select v-model="form.word_ids" multiple filterable style="width:100%"><el-option v-for="w in words" :key="w.id" :value="w.id" :label="w.pattern+' · '+label[w.status]"/></el-select></el-form-item>
      <el-form-item label="审核样本"><el-select v-model="form.sample_ids" multiple filterable style="width:100%"><el-option v-for="s in samples" :key="s.id" :value="s.id" :label="s.text.slice(0,45)+' · '+label[s.vector_status]"/></el-select></el-form-item>
      <el-form-item label="语义阈值"><el-input-number v-model="form.threshold" :min="0" :max="1" :step=".01" :precision="2"/><p class="muted">系统配置全局阈值时，以全局值为准。</p></el-form-item>
      <el-form-item label="用户组"><el-select v-model="form.group_ids" multiple filterable placeholder="全部用户组" style="width:100%"><el-option v-for="g in groups" :key="g.id" :value="g.id" :label="g.name"/></el-select></el-form-item>
      <el-form-item label="模型"><el-select v-model="form.models" multiple filterable placeholder="全部模型" style="width:100%"><el-option v-for="m in models" :key="m.name" :value="m.name" :label="m.name"/></el-select></el-form-item>
     </el-collapse-item></el-collapse>
    </template>
    <el-form-item label="状态"><el-switch v-model="form.status" active-value="enabled" inactive-value="disabled" active-text="启用" inactive-text="禁用"/></el-form-item>
   </el-form>
   <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
  </el-drawer>
  <el-dialog v-model="importing" title="批量导入敏感词" width="620px">
   <el-form label-position="top"><el-form-item label="策略组" required><el-select v-model="importForm.policy_id" filterable style="width:100%"><el-option v-for="p in policies" :key="p.id" :value="p.id" :label="p.name"/></el-select></el-form-item><el-form-item label="敏感词" required><el-input v-model="importForm.lines" type="textarea" :rows="10" placeholder="每行一个敏感词，最多500条"/></el-form-item><p class="muted">按文本包含匹配导入；同一策略组的重复词会跳过，导入失败时不会部分保存。</p><el-form-item label="状态"><el-switch v-model="importForm.status" active-value="enabled" inactive-value="disabled"/></el-form-item></el-form>
   <template #footer><el-button @click="importing=false">取消</el-button><el-button type="primary" :loading="saving" @click="importWords">导入</el-button></template>
  </el-dialog>
  <el-drawer :model-value="!!detail" title="审核详情" size="860px" @close="detail=null">
   <template v-if="detail">
    <h3>审核信息</h3>
    <el-descriptions :column="2" border><el-descriptions-item label="Request ID" :span="2">{{detail.request_id}}</el-descriptions-item><el-descriptions-item label="审核时间">{{formatDate(detail.created_at)}}</el-descriptions-item><el-descriptions-item label="请求模型">{{detail.model||'—'}}</el-descriptions-item><el-descriptions-item label="客户端协议">{{label[detail.protocol]||detail.protocol||'历史未记录'}}</el-descriptions-item><el-descriptions-item label="动作">{{label[detail.action]}}</el-descriptions-item><el-descriptions-item label="风险等级">{{label[riskOf(detail)]||'—'}}</el-descriptions-item><el-descriptions-item label="审核状态码">{{detail.status_code??'历史未记录'}}</el-descriptions-item><el-descriptions-item label="审核耗时">{{detail.elapsed_ms}} ms</el-descriptions-item></el-descriptions>
    <h3>命中详情</h3><el-empty v-if="!detail.matches?.length" description="未命中违规依据"/>
    <div v-for="(m,i) in detail.matches" :key="i" class="evidence">
     <h4>{{m.policy_name}} · {{label[m.action]}}</h4>
     <el-table :data="m.evidence"><el-table-column label="检测方式" width="100"><template #default="{row}">{{label[row.source]}}</template></el-table-column><el-table-column label="证据" min-width="230"><template #default="{row}">{{row.text||'历史未保存原文 · #'+row.id}}</template></el-table-column><el-table-column label="置信度" width="100"><template #default="{row}">{{row.similarity===undefined?'—':Number(row.similarity).toFixed(6)}}</template></el-table-column><el-table-column label="风险" width="80"><template #default="{row}">{{label[row.risk]}}</template></el-table-column></el-table>
     <p class="muted">共 {{m.hit_count}} 条命中，最多显示20条。语义相似度不是概率。</p>
     <h4>策略详情</h4><el-descriptions :column="2" border><el-descriptions-item label="策略组">{{m.policy_name}}</el-descriptions-item><el-descriptions-item label="动作">{{label[m.action]}}</el-descriptions-item><el-descriptions-item label="风险等级">{{label[m.risk]||'按规则风险'}}</el-descriptions-item><el-descriptions-item label="语义阈值">{{m.threshold??'历史未记录'}}</el-descriptions-item><el-descriptions-item label="描述" :span="2">{{m.description||'—'}}</el-descriptions-item></el-descriptions>
    </div>
    <p class="muted">显示审核时保存的策略与规则证据快照；不保存客户端请求正文。审核状态码表示审核阶段结果，目标模型调用结果请查看调用日志。</p>
   </template>
  </el-drawer>
 </div>
</template>
<style scoped>
.filter{width:150px}.search{width:270px}.toolbar{flex-wrap:wrap}.gap{margin-bottom:16px}.actions{margin:16px 0}.pagination{margin-top:20px}.link{color:var(--el-color-primary)}.evidence{margin:24px 0}.muted{line-height:1.6}.compliance-page :deep(.el-form-item){margin-bottom:20px}.compliance-page :deep(.el-collapse){margin-bottom:20px}
</style>
