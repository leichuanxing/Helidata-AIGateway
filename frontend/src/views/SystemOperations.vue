<script setup lang="ts">
import {formatDate} from '../ui/branding'
import {computed,ref,watch,onUnmounted} from 'vue'
import {useRoute} from 'vue-router'
import {ElMessage} from 'element-plus'
import {api,message} from '../api/client'
const route=useRoute(),backup=computed(()=>route.path==='/admin/backups')
const rows=ref<any[]>([]),total=ref(0),page=ref(1),loading=ref(false),error=ref(''),creating=ref(false),downloading=ref(''),detail=ref<any>(null)
const action=ref(''),resource=ref(''),actor=ref(''),result=ref(''),days=ref(7)
const statuses:Record<string,string>={queued:'等待备份',running:'备份中',ready:'已完成',failed:'失败',success:'成功',failure:'失败'}
let generation=0
async function load(){const mine=++generation;loading.value=true;error.value='';try{
 const params:any={page:page.value}
 if(!backup.value){Object.assign(params,{action:action.value||undefined,resource_type:resource.value||undefined,actor_id:actor.value?Number(actor.value):undefined,result:result.value||undefined});const end=new Date();params.end=end.toISOString();params.start=new Date(end.getTime()-days.value*86400000).toISOString()}
 const d=(await api.get(backup.value?'/admin/backups':'/admin/audit-logs',{params})).data.data
 if(mine===generation){rows.value=d.items;total.value=d.total}
 }catch(e){if(mine===generation)error.value=message(e)}finally{if(mine===generation)loading.value=false}}
async function create(){creating.value=true;try{await api.post('/admin/backups');ElMessage.success('备份任务已创建');page.value=1;await load()}catch(e){ElMessage.error(message(e))}finally{creating.value=false}}
async function download(row:any){downloading.value=row.id;try{const r=await api.get('/admin/backups/'+row.id+'/download',{responseType:'blob'});const url=URL.createObjectURL(r.data);const link=document.createElement('a');link.href=url;link.download='helidata-'+row.id+'.tar.gz';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){ElMessage.error(message(e))}finally{downloading.value=''}}
function time(value:string){return value?formatDate(value):'—'}
watch(()=>route.path,()=>{page.value=1;detail.value=null;load()},{immediate:true})
const timer=setInterval(()=>{if(backup.value&&rows.value.some(r=>['queued','running'].includes(r.status)))load()},3000)
onUnmounted(()=>{generation++;clearInterval(timer)})
</script>
<template>
 <h1>{{backup?'数据备份':'管理审计'}}</h1>
 <p class="muted">{{backup?'备份数据库、系统配置、Master Key及上传文件到 /data/backup/manual。备份文件含密钥，请妥善保管。':'记录登录及用户、账号池、模型组、API Key、合规与备份操作。保留操作时身份快照，审计记录不提供删除入口。'}}</p>
 <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
 <div class="toolbar">
  <template v-if="backup"><el-button type="primary" :loading="creating" @click="create">创建手动备份</el-button><span class="muted">一次仅执行一个任务；已有升级前SQL备份保留在原目录。</span></template>
  <template v-else>
   <el-input v-model="action" placeholder="动作，例如 update_provider" style="width:240px" clearable/>
   <el-input v-model="resource" placeholder="资源类型，例如 provider" style="width:210px" clearable/>
   <el-input v-model="actor" placeholder="操作者ID（可选）" inputmode="numeric" style="width:160px" clearable/>
   <el-select v-model="result" placeholder="全部结果" style="width:130px"><el-option label="全部结果" value=""/><el-option label="成功" value="success"/><el-option label="失败" value="failure"/></el-select>
   <el-select v-model="days" style="width:130px"><el-option v-for="d in [1,7,30]" :key="d" :label="'最近'+d+'天'" :value="d"/></el-select>
  </template>
  <el-button :loading="loading" @click="page=1;load()">刷新查询</el-button>
 </div>
 <div class="panel">
  <el-table :data="rows" v-loading="loading">
   <el-table-column label="创建时间" min-width="180"><template #default="s">{{time(s.row.created_at)}}</template></el-table-column>
   <template v-if="backup">
    <el-table-column prop="id" label="备份ID" min-width="190"/>
    <el-table-column label="状态" width="95"><template #default="s"><el-tag :type="s.row.status==='failed'?'danger':s.row.status==='ready'?'success':'info'">{{statuses[s.row.status]}}</el-tag></template></el-table-column>
    <el-table-column label="大小" width="100"><template #default="s">{{s.row.size_bytes==null?'—':(s.row.size_bytes/1024/1024).toFixed(2)+' MB'}}</template></el-table-column>
    <el-table-column prop="error_code" label="失败原因" min-width="145"/>
    <el-table-column label="操作" width="140"><template #default="s"><el-button text @click="detail=s.row">详情</el-button><el-button text :disabled="s.row.status!=='ready'" :loading="downloading===s.row.id" @click="download(s.row)">下载</el-button></template></el-table-column>
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
  <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev,pager,next,total" @current-change="load"/>
 </div>
 <el-dialog :model-value="!!detail" :title="backup?'备份详情':'审计详情'" width="700px" @close="detail=null"><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{JSON.stringify(detail,null,2)}}</pre><p v-if="backup" class="muted">恢复须在隔离环境验证，再停机恢复数据库与配套配置、Master Key和上传文件。当前页面不提供覆盖线上数据的恢复操作。</p></el-dialog>
</template>
