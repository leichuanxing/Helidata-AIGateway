<script setup lang="ts">
import {formatDate} from '../ui/branding'
import {reactive,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api,message} from '../api/client'
const route=useRoute(),router=useRouter(),rows=ref<any[]>([]),total=ref(0),loading=ref(false),error=ref(''),page=ref(1)
const fields=['request_id','user_id','user_group_id','api_key_id','provider_id','model','model_scope','request_model','logical_model','status','http_status','error_code','operation','protocol'] as const
const form=reactive<Record<string,string>>(Object.fromEntries(fields.map(k=>[k,''])))
const advanced=ref(false)
const range=ref<[Date,Date]|null>(null)
const labels:Record<string,string>={success:'成功',failure:'失败',client_cancelled:'客户端取消'}
const operations:Record<string,string>={chat:'Chat',responses:'Responses',messages:'Messages',embeddings:'Embeddings',rerank:'Rerank',images:'Images',preflight:'预检',models:'模型目录'}
let generation=0
async function load(){
  const mine=++generation;loading.value=true;error.value=''
  for(const key of fields)form[key]=typeof route.query[key]==='string'?String(route.query[key]):''
  page.value=Number(route.query.page)||1
  if(['request_model','logical_model','protocol','operation','user_id','user_group_id','api_key_id','provider_id','http_status','error_code'].some(k=>route.query[k]))advanced.value=true
  const start=typeof route.query.start==='string'?new Date(route.query.start):null,end=typeof route.query.end==='string'?new Date(route.query.end):null
  range.value=start&&end&&!isNaN(start.getTime())&&!isNaN(end.getTime())?[start,end]:null
  try{const d=(await api.get('/admin/call-logs',{params:route.query})).data.data;if(mine===generation){rows.value=d.items;total.value=d.total}}
  catch(e){if(mine===generation){rows.value=[];total.value=0;error.value=message(e)}}finally{if(mine===generation)loading.value=false}
}
function search(nextPage=1){const query:Record<string,string>={page:String(nextPage)};for(const k of fields)if(form[k])query[k]=form[k];if(range.value){query.start=range.value[0].toISOString();query.end=range.value[1].toISOString()}return router.replace({path:'/admin/call-logs',query})}
function reset(){for(const k of fields)form[k]='';range.value=null;return search()}
function failed(){form.status='failed';return search()}
watch(()=>route.fullPath,load,{immediate:true})
</script>
<template><div><PageHeader title="调用日志"/>
<el-alert v-if="error" :title="error" type="error" :closable="false"/>
<div class="panel"><div class="log-filters">
<el-input v-model="form.request_id" placeholder="Request ID（精确匹配）" clearable aria-label="Request ID" @keyup.enter="search()"/>
<el-input v-if="advanced" v-model="form.protocol" placeholder="协议" clearable aria-label="协议"/><el-input v-model="form.model" placeholder="请求或最终逻辑模型" clearable aria-label="模型"/>
<el-input v-if="advanced" v-model="form.request_model" placeholder="请求模型（精确匹配）" clearable aria-label="请求模型"/><el-input v-if="advanced" v-model="form.logical_model" placeholder="实际模型（精确匹配）" clearable aria-label="实际模型"/><el-select v-if="advanced||form.model_scope" v-model="form.model_scope" placeholder="请求或实际模型" clearable aria-label="模型匹配范围"><el-option label="请求或实际模型" value="either"/><el-option label="仅请求模型" value="request"/><el-option label="仅实际模型" value="actual"/></el-select><el-select v-model="form.status" placeholder="全部状态" clearable aria-label="状态"><el-option label="成功" value="success"/><el-option label="失败" value="failure"/><el-option label="客户端取消" value="client_cancelled"/><el-option label="失败与取消" value="failed"/></el-select>
<el-select v-if="advanced" v-model="form.operation" placeholder="全部操作" clearable aria-label="操作"><el-option v-for="op in ['chat','responses','messages','embeddings','rerank','images']" :key="op" :label="operations[op]" :value="op"/><el-option label="模型目录" value="models"/><el-option label="预检" value="preflight"/></el-select>
<el-input v-if="advanced" v-model="form.user_id" placeholder="用户 ID" clearable aria-label="用户 ID"/><el-input v-if="advanced" v-model="form.user_group_id" placeholder="用户组 ID" clearable aria-label="用户组 ID"/><el-input v-if="advanced" v-model="form.api_key_id" placeholder="API Key ID" clearable aria-label="API Key ID"/><el-input v-if="advanced" v-model="form.provider_id" placeholder="Provider ID" clearable aria-label="Provider ID"/>
<el-input v-if="advanced" v-model="form.http_status" placeholder="HTTP 状态，如 429" clearable aria-label="HTTP 状态"/><el-input v-if="advanced" v-model="form.error_code" placeholder="错误码（精确匹配）" clearable aria-label="错误码"/>
</div><div class="toolbar"><el-date-picker v-model="range" type="datetimerange" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间"/><el-button type="primary" @click="search()">查询</el-button><el-button @click="reset">重置</el-button><el-button @click="advanced=!advanced">{{advanced?'收起筛选':'更多筛选'}}</el-button><el-button @click="failed">仅失败与取消</el-button><el-button :loading="loading" @click="load">刷新</el-button></div>
<el-table :data="rows" v-loading="loading" empty-text="暂无符合条件的已完成请求"><el-table-column label="Request ID / 时间" min-width="310"><template #default="s"><router-link class="log-link" :to="'/admin/call-logs/'+s.row.request_id">{{s.row.request_id}}</router-link><div class="muted">{{formatDate(s.row.created_at)}}</div></template></el-table-column>
<el-table-column label="用户 / Key" min-width="160"><template #default="s">{{s.row.username_snapshot||'未认证'}}<div class="muted">{{s.row.key_name_snapshot||'—'}} · #{{s.row.api_key_id??'—'}}</div></template></el-table-column>
<el-table-column label="模型 / 账号" min-width="170"><template #default="s">{{s.row.request_model||s.row.operation}}<div class="muted">{{s.row.provider_name_snapshot||'未选择账号'}}</div></template></el-table-column>
<el-table-column label="状态 / HTTP" width="130"><template #default="s"><el-tag :type="s.row.error_code==='UPSTREAM_TIMEOUT'?'warning':s.row.status==='success'?'success':s.row.status==='failure'?'danger':'info'">{{s.row.error_code==='CONTENT_BLOCKED'?'Block 拦截':s.row.error_code==='UPSTREAM_TIMEOUT'?'超时':labels[s.row.status]||s.row.status}}</el-tag><div class="muted">HTTP {{s.row.http_status}} · {{s.row.stream?'SSE':operations[s.row.operation]||'JSON'}}</div></template></el-table-column>
<el-table-column label="输入 / 输出 Token" width="145"><template #default="s">{{s.row.input_tokens??'—'}} / {{s.row.output_tokens??'—'}}</template></el-table-column><el-table-column label="TTFT" width="110"><template #default="s">{{s.row.ttft_ms==null?'—':s.row.ttft_ms.toFixed(1)+' ms'}}</template></el-table-column><el-table-column label="实际 Token" width="100"><template #default="s">{{!['models','preflight'].includes(s.row.operation)?(s.row.total_tokens??'未上报'):'—'}}</template></el-table-column><el-table-column label="总耗时" width="105"><template #default="s">{{s.row.gateway_latency_ms.toFixed(1)}} ms</template></el-table-column><el-table-column prop="error_code" label="错误码" min-width="190"/><el-table-column label="操作" width="75" fixed="right"><template #default="s"><router-link class="log-link" :to="'/admin/call-logs/'+s.row.request_id">详情</router-link></template></el-table-column>
<template #empty><EmptyState title="暂无符合条件的已完成请求" description="检查筛选条件、时间范围或相关配置后重试。"/></template></el-table><el-pagination class="toolbar" background layout="total, prev, pager, next" :total="total" :page-size="20" :current-page="page" @current-change="search"/></div></div></template>
<style scoped>.log-filters{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:12px}.log-link{color:var(--el-color-primary);font-family:monospace;overflow-wrap:anywhere}@media(max-width:1100px){.log-filters{grid-template-columns:repeat(2,minmax(150px,1fr))}}</style>
