<script setup lang="ts">
import {formatDate} from '../ui/branding'
import {logNumber,logDuration,logStatus,logOperations} from '../ui/callLogs'
import {computed,onBeforeUnmount,reactive,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api,message} from '../api/client'
const route=useRoute(),router=useRouter(),rows=ref<any[]>([]),total=ref(0),loading=ref(false),error=ref(''),page=ref(1),pageSize=ref(20)
const fields=['request_id','user_id','user_group_id','api_key_id','provider_id','model','model_scope','request_model','logical_model','status','http_status','error_code','operation','protocol','stream','min_latency_ms'] as const
const form=reactive<Record<string,string>>(Object.fromEntries(fields.map(k=>[k,''])))
const names:Record<string,string>={request_id:'Request ID',user_id:'用户',user_group_id:'用户组',api_key_id:'API Key',provider_id:'供应商账号',model:'模型',model_scope:'模型范围',request_model:'请求模型',logical_model:'实际模型',status:'状态',http_status:'HTTP 状态',error_code:'错误码',operation:'操作',protocol:'协议',stream:'请求模式',min_latency_ms:'最小耗时'}
const labels:Record<string,string>={success:'成功',failure:'失败',client_cancelled:'客户端取消',failed:'失败与取消',either:'请求或实际',request:'仅请求',actual:'仅实际',true:'流式 SSE',false:'非流式'}
const advanced=ref(false),range=ref<[Date,Date]|null>(null),allTime=ref(false),options=ref<Record<string,{value:string;label:string}[]>>({}),optionsError=ref(''),resolvedRange=ref('')
let generation=0,controller:AbortController|undefined
let appliedWindow:Record<string,string>={}
watch(()=>form.request_id,value=>{if(!value.trim())allTime.value=false})
const chips=computed(()=>fields.filter(k=>typeof route.query[k]==='string'&&route.query[k]).map(k=>({key:k,label:`${names[k]}：${options.value[k]?.find(o=>o.value===route.query[k])?.label||labels[String(route.query[k])]||logOperations[String(route.query[k])]||route.query[k]}${k==='min_latency_ms'?' ms':''}`})))
async function loadOptions(){try{options.value=(await api.get('/admin/call-logs/options',{timeout:15000})).data.data;optionsError.value=''}catch{optionsError.value='筛选选项加载失败，可输入名称或 ID 查询。'}}
async function load(){
  controller?.abort();controller=new AbortController();const mine=++generation;loading.value=true;error.value=''
  for(const key of fields)form[key]=typeof route.query[key]==='string'?String(route.query[key]):''
  page.value=Number(route.query.page)||1;pageSize.value=Number(route.query.page_size)||20
  if(fields.slice(1).filter(k=>!['model','status'].includes(k)).some(k=>route.query[k]))advanced.value=true
  const start=typeof route.query.start==='string'?new Date(route.query.start):null,end=typeof route.query.end==='string'?new Date(route.query.end):null
  range.value=start&&end&&!isNaN(start.getTime())&&!isNaN(end.getTime())?[start,end]:null
  allTime.value=!!form.request_id&&!route.query.start&&!route.query.end
  try{const d=(await api.get('/admin/call-logs',{params:route.query,signal:controller.signal,timeout:20000})).data.data;if(mine===generation){rows.value=d.items;total.value=d.total;appliedWindow=d.start&&d.end?{start:d.start,end:d.end}:{};resolvedRange.value=d.start&&d.end?`${formatDate(d.start)} 至 ${formatDate(d.end)}`:'按 Request ID 查询全部历史';if(!range.value&&d.start&&d.end)range.value=[new Date(d.start),new Date(d.end)]}}
  catch(e:any){if(mine===generation&&e.code!=='ERR_CANCELED')error.value=message(e)}finally{if(mine===generation)loading.value=false}
}
async function apply(query:Record<string,any>){const target=router.resolve({path:'/admin/call-logs',query});if(target.fullPath===route.fullPath)await load();else await router.replace(target)}
function search(){
  if(allTime.value&&!form.request_id.trim()){error.value='查询全部历史需填写精确 Request ID';return}
  if(!allTime.value&&range.value&&(range.value[1]<=range.value[0]||range.value[1].getTime()-range.value[0].getTime()>31*86400000)){error.value='请选择大于 0 且不超过 31 天的时间范围';return}
  for(const key of ['user_id','user_group_id','api_key_id','provider_id'])if(form[key]&&!/^[1-9]\d*$/.test(form[key])){error.value=`${names[key]}需选择选项或输入正整数 ID`;return}
  if(form.http_status&&(!/^\d{3}$/.test(form.http_status)||Number(form.http_status)<100||Number(form.http_status)>599)){error.value='HTTP 状态需介于 100 和 599';return}
  const query:Record<string,string>={page:'1',page_size:String(pageSize.value)};for(const k of fields)if(form[k].trim())query[k]=form[k].trim()
  if(!allTime.value&&range.value){query.start=range.value[0].toISOString();query.end=range.value[1].toISOString()}return apply(query)
}
function paginate(nextPage:number){return apply({...appliedWindow,...route.query,page:String(nextPage)})}
function resize(size:number){pageSize.value=size;return apply({...appliedWindow,...route.query,page:'1',page_size:String(size)})}
function reset(){return apply({})}
function quick(days:number){const end=new Date();range.value=[new Date(end.getTime()-days*86400000),end];allTime.value=false;return search()}
function remove(key:string){const query:Record<string,any>={...route.query,page:'1'};delete query[key];return apply(query)}
function detail(row:any){return {path:'/admin/call-logs/'+row.request_id,query:{return_to:route.fullPath}}}
watch(()=>route.fullPath,load,{immediate:true});void loadOptions();onBeforeUnmount(()=>{generation++;controller?.abort()})
</script>
<template><div><PageHeader title="调用日志"/>
<el-alert v-if="error" :title="error" type="error" :closable="false" class="log-alert"/>
<div class="panel"><div class="log-filters">
<el-input v-model="form.request_id" placeholder="Request ID（精确匹配）" clearable aria-label="Request ID" @keyup.enter="search()"/>
<el-select v-model="form.model" filterable allow-create default-first-option clearable placeholder="请求或实际模型" aria-label="模型"><el-option v-for="o in options.model" :key="o.value" v-bind="o"/></el-select>
<el-select v-model="form.status" placeholder="全部状态" clearable aria-label="状态"><el-option v-for="s in ['success','failure','client_cancelled','failed']" :key="s" :value="s" :label="labels[s]"/></el-select>
<el-select v-model="form.stream" clearable placeholder="全部请求模式" aria-label="请求模式"><el-option label="流式 SSE" value="true"/><el-option label="非流式" value="false"/></el-select>
<template v-if="advanced">
<el-select v-for="key in ['provider_id','user_id','user_group_id','api_key_id','protocol','error_code']" :key="key" v-model="form[key]" filterable allow-create default-first-option clearable :placeholder="names[key]" :aria-label="names[key]"><el-option v-for="o in options[key]" :key="o.value" v-bind="o"/></el-select>
<el-select v-model="form.model_scope" clearable placeholder="模型匹配范围" aria-label="模型匹配范围"><el-option v-for="s in ['either','request','actual']" :key="s" :value="s" :label="labels[s]"/></el-select>
<el-select v-model="form.operation" clearable placeholder="全部操作" aria-label="操作"><el-option v-for="(name,key) in logOperations" :key="key" :label="name" :value="key"/></el-select>
<el-input v-model="form.request_model" placeholder="请求模型（精确匹配）" clearable aria-label="请求模型"/>
<el-input v-model="form.logical_model" placeholder="实际模型（精确匹配）" clearable aria-label="实际模型"/>
<el-input v-model="form.http_status" placeholder="HTTP 状态，如 429" clearable aria-label="HTTP 状态"/>
<el-select v-model="form.min_latency_ms" clearable placeholder="最小总耗时" aria-label="最小总耗时"><el-option label="至少 1 秒" value="1000"/><el-option label="至少 5 秒" value="5000"/><el-option label="至少 10 秒" value="10000"/><el-option label="至少 30 秒" value="30000"/></el-select>
</template></div>
<div class="toolbar log-toolbar"><el-date-picker v-model="range" :disabled="allTime" type="datetimerange" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间"/><el-button type="primary" :loading="loading" @click="search">查询</el-button><el-button @click="reset">重置</el-button><el-button @click="advanced=!advanced">{{advanced?'收起筛选':'更多筛选'}}</el-button><el-button :loading="loading" @click="load">刷新</el-button></div>
<div class="log-shortcuts"><el-button size="small" @click="quick(1)">最近 24 小时</el-button><el-button size="small" @click="quick(7)">最近 7 天</el-button><el-button size="small" @click="quick(30)">最近 30 天</el-button><el-button size="small" @click="form.status='failed';search()">失败与取消</el-button><el-checkbox v-model="allTime" :disabled="!form.request_id.trim()">按 Request ID 查询全部历史</el-checkbox></div>
<p v-if="optionsError" class="muted">{{optionsError}} <el-button link type="primary" @click="loadOptions">重试</el-button></p>
<div class="applied-filters"><el-tag v-for="chip in chips" :key="chip.key" closable @close="remove(chip.key)">{{chip.label}}</el-tag></div>
<div class="log-caption muted">{{resolvedRange}} · {{logNumber(total)}} 条已完成请求<span v-if="error&&rows.length"> · 查询失败，以下保留上次结果</span></div>
<el-table :data="rows" v-loading="loading" empty-text="暂无符合条件的已完成请求">
<el-table-column label="请求 / 时间" min-width="255"><template #default="s"><router-link class="log-link request-id" :title="s.row.request_id" :to="detail(s.row)">{{s.row.request_id}}</router-link><div class="muted">{{formatDate(s.row.created_at)}}</div><div class="muted">{{logOperations[s.row.operation]||s.row.operation}} · {{s.row.stream?'流式 SSE':'非流式'}} · {{s.row.protocol||'—'}}</div></template></el-table-column>
<el-table-column label="用户 / API Key" min-width="165"><template #default="s">{{s.row.username_snapshot||(s.row.user_id?'用户 #'+s.row.user_id:'未认证')}}<div class="muted">{{s.row.group_name_snapshot||'—'}}</div><div class="muted">{{s.row.key_name_snapshot||'—'}}{{s.row.api_key_id?' · #'+s.row.api_key_id:''}}</div></template></el-table-column>
<el-table-column label="模型 / 供应商账号" min-width="215"><template #default="s"><div>{{s.row.request_model||'—'}}</div><div v-if="s.row.logical_model&&s.row.logical_model!==s.row.request_model" class="actual-model">→ {{s.row.logical_model}}</div><div class="muted" :title="s.row.upstream_model">上游：{{s.row.upstream_model||'未调用'}}</div><div class="muted">{{s.row.provider_name_snapshot||(s.row.provider_id?'账号 #'+s.row.provider_id:'未选择账号')}}</div></template></el-table-column>
<el-table-column label="终态 / HTTP" width="130"><template #default="s"><el-tag :type="s.row.status==='success'?'success':s.row.status==='client_cancelled'?'info':'danger'">{{logStatus(s.row)}}</el-tag><div class="muted">HTTP {{s.row.http_status}}</div><div v-if="s.row.stream&&s.row.status!=='success'&&s.row.http_status===200" class="muted">流开始后未成功</div></template></el-table-column>
<el-table-column label="Token 用量" min-width="180" align="right"><template #default="s"><strong>{{['models','preflight'].includes(s.row.operation)?'—':logNumber(s.row.total_tokens)}}</strong><div class="muted">输入 {{logNumber(s.row.input_tokens)}} / 输出 {{logNumber(s.row.output_tokens)}}</div><div class="muted">缓存 {{logNumber(s.row.cached_tokens)}}</div></template></el-table-column>
<el-table-column label="耗时 / 性能" min-width="175" align="right"><template #default="s"><strong>{{logDuration(s.row.gateway_latency_ms)}}</strong><div class="muted">上游 {{logDuration(s.row.upstream_latency_ms)}}</div><div class="muted">TTFT {{logDuration(s.row.ttft_ms)}}</div><div class="muted">{{logNumber(s.row.tokens_per_second,1)}} Tokens/s</div></template></el-table-column>
<el-table-column label="错误信息" min-width="210"><template #default="s"><div class="error-code">{{s.row.error_code||'—'}}</div><el-tooltip v-if="s.row.error_message" :content="s.row.error_message" placement="top"><div class="error-preview muted">{{s.row.error_message}}</div></el-tooltip></template></el-table-column>
<el-table-column label="操作" width="75" fixed="right"><template #default="s"><router-link class="log-link" :to="detail(s.row)">详情</router-link></template></el-table-column>
<template #empty><EmptyState title="暂无符合条件的已完成请求" description="尝试调整时间范围或清除筛选条件。"/></template></el-table>
<div class="log-footer"><span class="muted">— 表示未上报或不适用；HTTP 200 不代表流式请求最终成功。</span><el-pagination background layout="total, sizes, prev, pager, next" :total="total" :page-sizes="[20,50,100]" :page-size="pageSize" :current-page="page" @current-change="paginate" @size-change="resize"/></div>
</div></div></template>
<style scoped>.log-alert{margin-bottom:16px}.log-filters{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:12px}.log-toolbar :deep(.el-date-editor){flex:1;min-width:280px}.log-shortcuts,.applied-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}.log-shortcuts .el-button+.el-button{margin-left:0}.log-caption{margin:16px 0;font-size:12px}.log-link{color:var(--el-color-primary)}.request-id{display:block;font-family:monospace;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.actual-model{color:var(--el-color-primary)}.error-code{overflow-wrap:anywhere}.error-preview{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}.log-footer{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-top:20px}.log-footer>span{font-size:12px}@media(max-width:1100px){.log-filters{grid-template-columns:repeat(2,minmax(150px,1fr))}}@media(max-width:600px){.log-filters{grid-template-columns:1fr}.log-toolbar :deep(.el-date-editor){min-width:0;width:100%}.log-footer :deep(.el-pagination){flex-wrap:wrap;gap:8px}}
</style>
