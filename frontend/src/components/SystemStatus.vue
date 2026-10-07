<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {api,message} from '../api/client'
import {formatDate} from '../ui/branding'
const props=defineProps<{active:boolean}>()
const snapshot=ref<any>(null),loading=ref(false),error=ref(''),auto=ref(true)
let timer:ReturnType<typeof setTimeout>|undefined,controller:AbortController|undefined
const labels:Record<string,string>={ok:'正常',error:'异常',unknown:'未知',warning:'告警',info:'配置状态'}
const types:Record<string,'success'|'danger'|'warning'|'info'>={ok:'success',error:'danger',unknown:'info',warning:'warning',info:'info'}
function bytes(n:number|null|undefined){if(n==null)return '无法读取';const units=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<4){n/=1024;i++}return n.toFixed(i?1:0)+' '+units[i]}
const uptime=computed(()=>{const seconds=snapshot.value?.uptime_seconds;if(seconds==null)return '—';return `${Math.floor(seconds/86400)} 天 ${Math.floor(seconds%86400/3600)} 小时 ${Math.floor(seconds%3600/60)} 分钟`})
function stop(){if(timer)clearTimeout(timer);timer=undefined;controller?.abort();controller=undefined;loading.value=false}
function schedule(){if(timer)clearTimeout(timer);if(props.active&&auto.value)timer=setTimeout(()=>{if(document.hidden)schedule();else void refresh()},15000)}
async function refresh(){if(loading.value||!props.active)return;if(timer)clearTimeout(timer);const request=new AbortController();controller=request;loading.value=true;error.value='';try{snapshot.value=(await api.get('/admin/settings/system-status',{signal:request.signal,timeout:20000})).data.data}catch(e){if(!request.signal.aborted)error.value=message(e)}finally{if(controller===request){controller=undefined;loading.value=false;schedule()}}}
watch(()=>props.active,active=>{if(active)void refresh();else stop()},{immediate:true})
watch(auto,schedule)
onBeforeUnmount(stop)
</script>
<template>
<div class="status-heading"><div><h2>系统状态</h2><p class="muted">查看当前资源占用和组件检查结果。</p></div><div class="status-actions"><el-checkbox v-model="auto">15 秒刷新</el-checkbox><el-button :loading="loading" @click="refresh">刷新状态</el-button></div></div>
<el-alert v-if="error" :title="error" :description="snapshot?'以下为上次成功采集的数据，请以采集时间为准。':''" type="error" :closable="false"/>
<div v-if="snapshot" v-loading="loading">
<p class="muted status-stamp">采集时间 {{formatDate(snapshot.checked_at)}} · API 进程运行 {{uptime}}</p>
<div class="resource-grid">
<el-card shadow="never"><h3>CPU 使用率</h3><strong class="resource-number">{{snapshot.cpu.percent==null?'—':snapshot.cpu.percent+'%'}}</strong><el-progress v-if="snapshot.cpu.percent!=null" :percentage="snapshot.cpu.percent" :show-text="false"/><p class="muted">宿主机 {{snapshot.cpu.cores??'—'}} 核 · 瞬时采样</p><p class="muted">1 / 5 / 15 分钟负载：{{snapshot.cpu.load?.join(' / ')??'无法读取'}}</p><p class="muted">容器 CPU 限额：{{snapshot.cpu.container_limit_cores==null?'未设置':snapshot.cpu.container_limit_cores+' 核'}}</p></el-card>
<el-card shadow="never"><h3>内存使用率</h3><strong class="resource-number">{{snapshot.memory.percent==null?'—':snapshot.memory.percent+'%'}}</strong><el-progress v-if="snapshot.memory.percent!=null" :percentage="snapshot.memory.percent" :show-text="false"/><p class="muted">宿主机 {{bytes(snapshot.memory.used_bytes)}} / {{bytes(snapshot.memory.total_bytes)}}</p><p class="muted">容器用量 {{bytes(snapshot.memory.container_used_bytes)}}</p><p class="muted">容器内存限额：{{snapshot.memory.container_limit_bytes==null?'未设置':bytes(snapshot.memory.container_limit_bytes)}}</p></el-card>
<el-card shadow="never"><h3>数据磁盘使用率</h3><strong class="resource-number">{{snapshot.disk.percent==null?'—':snapshot.disk.percent+'%'}}</strong><el-progress v-if="snapshot.disk.percent!=null" :percentage="snapshot.disk.percent" :show-text="false" :status="snapshot.disk.status==='low'?'exception':undefined"/><p class="muted">{{bytes(snapshot.disk.used_bytes)}} / {{bytes(snapshot.disk.total_bytes)}}</p><p class="muted">可用空间 {{bytes(snapshot.disk.free_bytes)}}</p><p class="muted">数据卷所在文件系统，包含其他文件占用。</p></el-card>
</div>
<h3 class="component-heading">组件运行状态</h3><el-table :data="snapshot.components"><el-table-column prop="name" label="组件" min-width="170"/><el-table-column label="检查结果" width="120"><template #default="s"><el-tag :type="types[s.row.status]||'info'">{{labels[s.row.status]||'未知'}}</el-tag></template></el-table-column><el-table-column label="进程状态" width="150"><template #default="s">{{s.row.process_state||'—'}}</template></el-table-column><el-table-column prop="detail" label="说明" min-width="280"/></el-table>
</div><el-skeleton v-else-if="loading" :rows="8" animated/><el-empty v-else description="暂时无法读取系统状态"><el-button @click="refresh">重新检查</el-button></el-empty>
</template>
<style scoped>
.status-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:20px 0}.status-heading h2{font-size:18px;margin:0 0 8px}.status-heading p{margin:0;font-size:13px}.status-actions{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.status-stamp{font-size:13px;margin:20px 0}.resource-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.resource-grid h3{font-size:15px;margin:0 0 16px}.resource-number{display:block;font-size:30px;margin-bottom:20px}.resource-grid p{font-size:13px;line-height:1.7;margin:12px 0 0;overflow-wrap:anywhere}.component-heading{font-size:16px;margin:28px 0 16px}@media(max-width:900px){.resource-grid{grid-template-columns:1fr}}@media(max-width:600px){.status-heading{align-items:flex-start;flex-direction:column}}
</style>
