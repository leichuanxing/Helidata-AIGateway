<script setup lang="ts">
import {formatDate} from '../ui/branding'
import {computed,ref,watch,onUnmounted} from 'vue'
import {ElMessage} from 'element-plus'
import {api,message} from '../api/client'
const props=defineProps<{mode?:'backups'|'audit';embedded?:boolean}>()
const backup=computed(()=>props.mode==='backups')
const rows=ref<any[]>([]),total=ref(0),page=ref(1),loading=ref(false),error=ref(''),creating=ref(false),downloading=ref(''),detail=ref<any>(null)
const action=ref(''),resource=ref(''),actorId=ref<number|undefined>(undefined),result=ref(''),days=ref(7)
const statuses:Record<string,string>={queued:'等待备份',running:'备份中',ready:'已完成',failed:'失败',success:'成功',failure:'失败'}
let generation=0,disposed=false
const requests=new Set<AbortController>()
async function load(){const mine=++generation,request=new AbortController();for(const pending of requests)if(pending!==request&&pending!==downloadRequest)pending.abort();requests.add(request);loading.value=true;error.value='';try{
 const params:any={page:page.value}
 if(!backup.value){Object.assign(params,{action:action.value||undefined,resource_type:resource.value||undefined,actor_id:actorId.value||undefined,result:result.value||undefined});const end=new Date();params.end=end.toISOString();params.start=new Date(end.getTime()-days.value*86400000).toISOString()}
 const d=(await api.get(backup.value?'/admin/backups':'/admin/audit-logs',{params,signal:request.signal})).data.data
 if(!disposed&&mine===generation){rows.value=d.items;total.value=d.total;if(backup.value&&detail.value)detail.value=d.items.find((r:any)=>r.id===detail.value.id)||detail.value;if(page.value>1&&!d.items.length){page.value=Math.max(1,Math.ceil(d.total/20));await load()}}
 }catch(e){if(!disposed&&!request.signal.aborted&&mine===generation)error.value=message(e)}finally{requests.delete(request);if(mine===generation)loading.value=false}}
async function create(){if(creating.value)return;creating.value=true;try{await api.post('/admin/backups');if(disposed)return;ElMessage.success('备份任务已创建');page.value=1;await load()}catch(e){if(!disposed)ElMessage.error(message(e))}finally{creating.value=false}}
let downloadRequest:AbortController|undefined
async function download(row:any){if(downloading.value)return;downloading.value=row.id;const request=new AbortController();downloadRequest=request;requests.add(request);try{const r=await api.get('/admin/backups/'+row.id+'/download',{responseType:'blob',signal:request.signal,timeout:300000});if(disposed||request.signal.aborted)return;const url=URL.createObjectURL(r.data);const link=document.createElement('a');link.href=url;link.download='helidata-'+row.id+'.tar.gz';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){if(!disposed&&!request.signal.aborted)ElMessage.error(message(e))}finally{requests.delete(request);downloadRequest=undefined;downloading.value=''}}
function reset(){action.value='';resource.value='';actorId.value=undefined;result.value='';days.value=7;page.value=1;load()}
function time(value:string){return value?formatDate(value):'—'}
watch(()=>props.mode,()=>{page.value=1;detail.value=null;load()},{immediate:true})
const timer=setInterval(()=>{if(!document.hidden&&!loading.value&&!creating.value&&backup.value&&rows.value.some(r=>['queued','running'].includes(r.status)))load()},3000)
onUnmounted(()=>{disposed=true;generation++;clearInterval(timer);for(const request of requests)request.abort()})
</script>
<template>
 <h2 v-if="!embedded">{{backup?'数据备份':'管理审计'}}</h2>
 <p class="muted">{{backup?'备份数据库、系统配置、Master Key及上传文件到 /data/backup/manual。备份文件含密钥，请妥善保管。':'记录登录及用户、模型供应商、模型组、API Key、合规与备份操作。保留操作时身份快照，审计记录不提供删除入口。'}}</p>
 <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
 <div class="toolbar">
  <template v-if="backup"><el-button type="primary" :loading="creating" @click="create">创建手动备份</el-button><span class="muted">一次仅执行一个任务；已有升级前SQL备份保留在原目录。</span></template>
  <template v-else>
   <el-input v-model="action" placeholder="动作，例如 update_provider" style="width:240px" clearable/>
   <el-input v-model="resource" placeholder="资源类型，例如 provider" style="width:210px" clearable/>
   <el-input-number v-model="actorId" :min="1" :precision="0" :controls="false" placeholder="操作者ID（可选）" style="width:160px"/>
   <el-select v-model="result" placeholder="全部结果" style="width:130px"><el-option label="全部结果" value=""/><el-option label="成功" value="success"/><el-option label="失败" value="failure"/></el-select>
   <el-select v-model="days" style="width:130px"><el-option v-for="d in [1,7,30]" :key="d" :label="'最近'+d+'天'" :value="d"/></el-select>
  </template>
  <el-button :loading="loading" @click="page=1;load()">{{backup?'刷新':'查询'}}</el-button><el-button v-if="!backup" @click="reset">重置</el-button>
 </div>
 <div :class="embedded?'operations-table':'panel'">
  <el-table :data="rows" v-loading="loading">
   <el-table-column label="创建时间" min-width="180"><template #default="s">{{time(s.row.created_at)}}</template></el-table-column>
   <template v-if="backup">
    <el-table-column prop="id" label="备份ID" min-width="190"/>
    <el-table-column label="状态" width="95"><template #default="s"><el-tag :type="s.row.status==='failed'?'danger':s.row.status==='ready'?'success':'info'">{{statuses[s.row.status]}}</el-tag></template></el-table-column>
    <el-table-column label="大小" width="100"><template #default="s">{{s.row.size_bytes==null?'—':(s.row.size_bytes/1024/1024).toFixed(2)+' MiB'}}</template></el-table-column>
    <el-table-column prop="error_code" label="失败原因" min-width="145"/>
    <el-table-column label="操作" width="140"><template #default="s"><el-button text @click="detail=s.row">详情</el-button><el-button text :disabled="s.row.status!=='ready'||!!downloading&&downloading!==s.row.id" :loading="downloading===s.row.id" @click="download(s.row)">下载</el-button></template></el-table-column>
   </template>
   <template v-else>
    <el-table-column label="操作者" min-width="155"><template #default="s">{{s.row.actor_username||'未知 / 已删除'}} <small>#{{s.row.actor_id||'—'}}</small></template></el-table-column>
    <el-table-column prop="action" label="动作" min-width="180"/>
    <el-table-column label="资源" min-width="140"><template #default="s">{{s.row.resource_type}} #{{s.row.resource_id||'—'}}</template></el-table-column>
    <el-table-column prop="client_ip" label="客户端IP" min-width="120"/>
    <el-table-column label="结果" width="75"><template #default="s">{{statuses[s.row.result]||s.row.result}}</template></el-table-column>
    <el-table-column label="详情" width="65"><template #default="s"><el-button text @click="detail=s.row">查看</el-button></template></el-table-column>
   </template>
  </el-table>
  <el-pagination class="operations-pagination" v-model:current-page="page" :page-size="20" :total="total" layout="prev,pager,next,total" @current-change="load"/>
 </div>
 <el-dialog :model-value="!!detail" :title="backup?'备份详情':'审计详情'" width="min(700px, 94vw)" @close="detail=null"><template v-if="detail"><el-descriptions :column="1" border><el-descriptions-item label="记录ID">{{detail.id}}</el-descriptions-item><el-descriptions-item label="创建时间">{{time(detail.created_at)}}</el-descriptions-item><el-descriptions-item label="状态 / 结果">{{statuses[detail.status||detail.result]||detail.status||detail.result}}</el-descriptions-item><template v-if="backup"><el-descriptions-item label="完成时间">{{time(detail.finished_at)}}</el-descriptions-item><el-descriptions-item label="SHA-256"><span class="operation-digest">{{detail.sha256||'尚未生成'}}</span></el-descriptions-item><el-descriptions-item v-if="detail.error_code" label="失败原因">{{detail.error_code}}</el-descriptions-item></template><template v-else><el-descriptions-item label="操作者">{{detail.actor_username||'未知 / 已删除'}} · #{{detail.actor_id??'—'}}</el-descriptions-item><el-descriptions-item label="动作">{{detail.action}}</el-descriptions-item><el-descriptions-item label="来源IP">{{detail.client_ip||'—'}}</el-descriptions-item><el-descriptions-item label="资源">{{detail.resource_type||'—'}} #{{detail.resource_id||'—'}}</el-descriptions-item></template></el-descriptions><details class="operation-raw"><summary>查看完整记录</summary><pre>{{JSON.stringify(detail,null,2)}}</pre></details><p v-if="backup" class="muted">恢复须在隔离环境验证，再停机恢复数据库与配套配置、Master Key和上传文件。当前页面不提供覆盖线上数据的恢复操作。</p></template></el-dialog>
</template>

<style scoped>.operations-pagination{margin-top:20px;justify-content:flex-end}.operation-digest,.operation-raw pre{overflow-wrap:anywhere}.operation-raw{margin-top:18px}.operation-raw summary{cursor:pointer;color:var(--el-color-primary)}.operation-raw pre{white-space:pre-wrap;max-height:300px;overflow:auto;font-size:12px;line-height:1.7}</style>
