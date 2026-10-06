<script setup lang="ts">
import {formatDate} from '../ui/branding'
import {computed,ref,watch,nextTick,onMounted,onBeforeUnmount,type ComponentPublicInstance} from 'vue'
import * as echarts from 'echarts'
import {dark,chartTheme} from '../ui/preferences'
import {useRouter} from 'vue-router'
import {api,message} from '../api/client'
const router=useRouter(),period=ref('24h'),data=ref<any>(null),loading=ref(false),error=ref(''),auto=ref(true)
const providerMetadata=ref<Record<number,any>>({})
function providerFailure(id:number){const row=data.value?.rankings.provider.find((r:any)=>r.provider_id===id&&!r.other);return row&&row.requests?((row.failure/row.requests)*100).toFixed(1)+'%':'—'}
let stopped=false,timer:ReturnType<typeof setInterval>|undefined
const charts:Record<string,echarts.ECharts>={},hosts:Record<string,HTMLElement>={}
const specs=[{id:'tokens',title:'Token 趋势'},{id:'requests',title:'请求趋势'},{id:'concurrency',title:'并发趋势 · 已采样峰值'},{id:'failures',title:'失败趋势'},{id:'provider',title:'供应商用量排行'},{id:'model',title:'模型用量排行'}]
const health:Record<string,string>={healthy:'健康',unhealthy:'异常',unknown:'未验证'},schedule:Record<string,string>={Available:'可用',Cooling:'冷却中',Unavailable:'不可用',Disabled:'禁用'}
function bindChart(key:string,node:Element|ComponentPublicInstance|null){if(node instanceof HTMLElement)hosts[key]=node}
function number(value:any){return value==null?'不可用':Number(value).toLocaleString()}
const cards=computed(()=>data.value?[
{label:'今日请求',value:data.value.today.requests,note:'北京时间 00:00 至今',tone:'blue'},
{label:'今日 Token',value:data.value.today.total_tokens,note:'仅统计上游已上报用量',tone:'purple'},
{label:'失败 / 取消',value:data.value.summary.failure,note:'所选时段 · 查看失败日志',tone:'orange',failed:true},
{label:'活跃用户',value:data.value.summary.active_users,note:'所选统计时段',tone:'green'}]:[])
const periodLabel=computed(()=>({'1h':'最近 1 小时','24h':'最近 24 小时','7d':'最近 7 天','30d':'最近 30 天'}[period.value]||''))
const utilization=computed(()=>data.value?.live.available&&data.value.live.max_concurrency>0?Math.min(100,Math.round(data.value.live.active/data.value.live.max_concurrency*100)):0)
function usage(query:Record<string,string>={}){return {path:'/admin/usage',query:{start:data.value.start,end:data.value.end,grain:data.value.grain,...query}}}
function failed(){return {path:'/admin/call-logs',query:{start:data.value.start,end:data.value.end,status:'failed'}}}
function dispose(){for(const chart of Object.values(charts))chart.dispose();for(const k of Object.keys(charts))delete charts[k]}
function resize(){for(const chart of Object.values(charts))chart.resize()}
async function load(){if(loading.value||stopped)return;loading.value=true;error.value='';const chosen=period.value;try{const result=(await api.get('/admin/dashboard',{params:{period:chosen}})).data.data;if(!stopped&&chosen===period.value){data.value=result;try{const p=(await api.get('/admin/providers',{params:{page_size:100}})).data.data.items;if(!stopped&&chosen===period.value)providerMetadata.value=Object.fromEntries(p.map((x:any)=>[x.id,x]))}catch{providerMetadata.value={}}}}catch(e){if(!stopped){error.value=message(e);data.value=null}}finally{loading.value=false;if(!stopped&&chosen!==period.value)void load()}}
async function render(){await nextTick();dispose();if(!data.value||stopped)return;const d=data.value,colors=['#2872dc','#19a891','#e7a53b','#d96363'];
for(const spec of specs){if(!hosts[spec.id])continue;const chart=echarts.init(hosts[spec.id]);charts[spec.id]=chart;
if(spec.id==='provider'||spec.id==='model'){const rows=d.rankings[spec.id];chart.setOption({color:colors,grid:{left:150,right:25,top:12,bottom:35},tooltip:{trigger:'axis'},xAxis:{type:'value'},yAxis:{type:'category',inverse:true,data:rows.map((r:any)=>r.label),axisLabel:{width:130,overflow:'truncate'}},series:[{type:'bar',data:rows.map((r:any)=>r.total_tokens),barMaxWidth:18,itemStyle:{borderRadius:[0,4,4,0]}}],graphic:rows.length?[]:[{type:'text',left:'center',top:'middle',style:{text:'暂无推理记录',fill:'#73849b'}}]});chart.on('click',(event:any)=>{const row=rows[event.dataIndex];if(event.componentType!=='series'||!row||row.other)return;if(spec.id==='provider'&&row.provider_id)void router.push('/admin/providers/'+row.provider_id);if(spec.id==='model'&&row.dimension)void router.push(usage({model:row.dimension}))});chart.setOption(chartTheme());continue}
const rows=spec.id==='concurrency'?d.concurrency_series:d.series;
const fields=spec.id==='tokens'?[['input_tokens','输入'],['output_tokens','输出'],['cached_tokens','缓存'],['total_tokens','总 Token']]:spec.id==='requests'?[['requests','全部请求'],['success','成功'],['failure','失败 / 取消']]:spec.id==='failures'?[['failure','失败 / 取消']]:[['active','执行'],['streaming','流式'],['queued','队列']];
chart.setOption({color:colors,grid:{left:54,right:24,top:45,bottom:40},legend:{top:5},tooltip:{trigger:'axis'},xAxis:{type:'category',data:rows.map((r:any)=>formatDate(r.bucket)),axisLabel:{hideOverlap:true}},yAxis:{type:'value',minInterval:spec.id==='tokens'?undefined:1},series:fields.map(([field,label])=>({name:label,type:'line',smooth:0.3,smoothMonotone:'x',connectNulls:false,showSymbol:rows.length<=2,symbol:'circle',symbolSize:5,lineStyle:{width:2.5,cap:'round',join:'round'},data:rows.map((r:any)=>r[field])})),graphic:(spec.id==='concurrency'?rows.some((r:any)=>r.samples>0):rows.length)?[]:[{type:'text',left:'center',top:'middle',style:{text:spec.id==='concurrency'?(d.history_available?'暂无历史采样':'采样状态不可用'):'暂无推理记录',fill:'#73849b'}}]});chart.setOption(chartTheme());chart.on('click',(event:any)=>{if(event.componentType!=='series'||spec.id==='concurrency')return;const row=rows[event.dataIndex];if(!row)return;const bucket=new Date(row.bucket).getTime(),size=d.grain==='hour'?3600000:86400000;const query={start:new Date(Math.max(bucket,new Date(d.start).getTime())).toISOString(),end:new Date(Math.min(bucket+size,new Date(d.end).getTime())).toISOString(),...(spec.id==='failures'||event.seriesName==='失败 / 取消'?{status:'failed'}:{})};void router.push({path:spec.id==='tokens'?'/admin/usage':'/admin/call-logs',query})})}}
watch(dark,render);watch(data,render);watch(period,load)
onMounted(()=>{void load();window.addEventListener('resize',resize);timer=setInterval(()=>{if(auto.value&&!document.hidden)void load()},15000)})
const observer=new ResizeObserver(resize)
watch(()=>data.value,async()=>{await nextTick();const main=document.querySelector('.workspace main');if(main)observer.observe(main)})
onBeforeUnmount(()=>{observer.disconnect();stopped=true;if(timer)clearInterval(timer);window.removeEventListener('resize',resize);dispose()})
</script>
<template>
<div class="dashboard" v-loading="loading">
  <div class="dash-toolbar">
    <div class="dash-status"><span class="status-dot" :class="{offline:!data?.live.available}"></span>{{data?.live.available?'实时负载正常':'实时负载待确认'}}<span class="toolbar-divider"></span><span class="muted">统计时段：{{periodLabel}}</span></div>
    <div class="dash-controls"><el-select v-model="period" aria-label="统计时段" style="width:140px"><el-option label="最近 1 小时" value="1h"/><el-option label="最近 24 小时" value="24h"/><el-option label="最近 7 天" value="7d"/><el-option label="最近 30 天" value="30d"/></el-select><el-checkbox v-model="auto">自动刷新</el-checkbox><el-button @click="load">刷新</el-button></div>
  </div>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <template v-if="data">
    <el-alert v-if="!data.live.available" title="实时负载不可用，当前并发与队列保持未知。" type="warning" :closable="false"/>
    <div class="dash-kpis">
      <component :is="card.failed?'router-link':'div'" v-for="card in cards" :key="card.label" :to="card.failed?failed():undefined" class="dash-kpi" :class="[card.tone,{clickable:card.failed}]">
        <span class="kpi-label">{{card.label}}</span><strong>{{number(card.value)}}</strong><small>{{card.note}}<span v-if="card.failed"> →</span></small>
      </component>
    </div>
    <section class="panel gateway-meter">
      <div class="load-overview"><h2>实时负载</h2><span class="muted">当前网关资源占用</span></div>
      <div class="load-stat"><span>执行请求</span><strong>{{number(data.live.active)}}<small> / {{number(data.live.max_concurrency)}}</small></strong></div>
      <div class="load-stat"><span>其中流式</span><strong>{{number(data.live.streaming)}}</strong></div>
      <div class="load-stat"><span>等待队列</span><strong>{{number(data.live.queued)}}<small> / {{number(data.live.queue_size)}}</small></strong></div>
      <div class="meter-bar"><div class="meter-label"><span>并发使用率</span><b>{{data.live.available?utilization+'%':'未知'}}</b></div><el-progress v-if="data.live.available" :percentage="utilization" :show-text="false" :stroke-width="8" :status="utilization>=80?'warning':undefined"/><span v-else class="muted">等待实时数据</span></div>
    </section>
    <div class="section-heading"><h2>运行趋势</h2><router-link :to="usage()" class="dash-link">查看完整用量 →</router-link></div>
    <div class="dash-charts">
      <section v-for="spec in specs" :key="spec.id" class="panel chart-panel"><div class="dash-heading"><h2>{{spec.title}}</h2><span class="chart-caption">{{spec.id==='provider'||spec.id==='model'?'已上报 Token · '+periodLabel:periodLabel}}</span></div><div :ref="el=>bindChart(spec.id,el)" class="dash-chart"></div></section>
    </div>
    <div class="section-heading"><h2>资源状态</h2><span class="muted">账号连接与用户组负载</span></div>
    <div class="dash-resources">
      <section class="panel"><div class="dash-heading"><h2>模型供应商 <span class="count-badge">{{data.provider_total}}</span></h2><router-link to="/admin/providers" class="dash-link">管理供应商 →</router-link></div>
        <el-table :data="data.providers" empty-text="暂无供应商">
          <el-table-column label="账号" min-width="140"><template #default="s"><router-link :to="'/admin/providers/'+s.row.id" class="dash-link">{{s.row.name}}</router-link></template></el-table-column>
          <el-table-column label="健康 / 调度" min-width="120"><template #default="s"><el-tag :type="s.row.health_status==='healthy'?'success':s.row.health_status==='unhealthy'?'danger':'info'">{{health[s.row.health_status]||s.row.health_status}}</el-tag><div class="muted schedule-label">{{schedule[s.row.scheduling_state]}}</div></template></el-table-column>
          <el-table-column label="并发 / 上限" min-width="110"><template #default="s">{{number(s.row.current_concurrency)}} / {{s.row.max_concurrency}}<el-progress v-if="s.row.current_concurrency!==null" :percentage="Math.min(100,s.row.current_concurrency/s.row.max_concurrency*100)" :show-text="false" :stroke-width="4"/></template></el-table-column>
          <el-table-column label="失败率" width="80"><template #default="s">{{providerFailure(s.row.id)}}</template></el-table-column>
          <el-table-column label="连接延迟" width="100"><template #default="s">{{providerMetadata[s.row.id]?.last_latency_ms==null?'—':providerMetadata[s.row.id].last_latency_ms+' ms'}}</template></el-table-column>
          <template #empty><EmptyState title="暂无模型供应商" description="配置上游模型服务后显示账号状态。"/></template>
        </el-table>
        <p class="resource-foot muted">显示 {{data.providers.length}} / {{data.provider_total}} 个账号；失败率取所选时段，延迟来自最近连接检查。</p>
      </section>
      <section class="panel"><div class="dash-heading"><h2>用户组 <span class="count-badge">{{data.group_total}}</span></h2><router-link to="/admin/user-groups" class="dash-link">管理用户组 →</router-link></div>
        <el-table :data="data.groups" empty-text="暂无用户组">
          <el-table-column label="用户组" min-width="130"><template #default="s"><router-link :to="usage({user_group_id:String(s.row.id)})" class="dash-link">{{s.row.name}}</router-link></template></el-table-column>
          <el-table-column label="状态" width="85"><template #default="s"><el-tag :type="s.row.status==='enabled'?'success':'info'">{{s.row.status==='enabled'?'启用':'禁用'}}</el-tag></template></el-table-column>
          <el-table-column label="并发 / 上限" min-width="110"><template #default="s">{{number(s.row.current_concurrency)}} / {{s.row.max_concurrency}}<el-progress v-if="s.row.current_concurrency!==null" :percentage="Math.min(100,s.row.current_concurrency/s.row.max_concurrency*100)" :show-text="false" :stroke-width="4"/></template></el-table-column>
          <template #empty><EmptyState title="暂无用户组" description="配置用户组后显示资源占用。"/></template>
        </el-table><p class="resource-foot muted">显示 {{data.groups.length}} / {{data.group_total}} 个用户组。</p>
      </section>
    </div>
    <details class="dash-notes"><summary>统计口径与采样说明</summary><p>今日指标从北京时间 00:00 起计；{{data.today.usage_unavailable}} 个今日请求的 Token 字段不完整，缺失字段不估算。{{data.concurrency_note}}账号健康状态未验证不代表连接正常。自动刷新间隔为 15 秒。</p></details>
  </template>
</div>
</template>
<style scoped>
.dashboard{padding:4px 0 12px}.dash-toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap}.dash-status{display:flex;align-items:center;gap:8px;font-size:13px}.status-dot{width:7px;height:7px;border-radius:50%;background:#32ad91}.status-dot.offline{background:var(--muted)}.toolbar-divider{height:14px;width:1px;background:var(--line);margin:0 4px}.dash-controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.dash-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:0 0 18px}.dash-kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:20px 22px;position:relative;overflow:hidden;min-width:0}.dash-kpi:before{content:'';position:absolute;left:0;top:22px;width:3px;height:22px;background:#1677ff;border-radius:0 3px 3px 0}.dash-kpi.purple:before{background:#8b6cdd}.dash-kpi.orange:before{background:#e9a23b}.dash-kpi.green:before{background:#32ad91}.kpi-label{color:var(--muted);font-size:13px}.dash-kpi strong{display:block;font-size:30px;font-weight:650;letter-spacing:-.7px;margin:12px 0 8px;line-height:1.15;overflow-wrap:anywhere}.dash-kpi small{color:var(--muted);font-size:12px}.clickable{transition:border-color .15s,box-shadow .15s}.clickable:hover{border-color:var(--el-color-primary);box-shadow:0 4px 16px #1677ff0d}.clickable:hover small{color:var(--el-color-primary)}.dashboard .panel{margin:0;border-radius:12px;padding:20px;min-width:0}.gateway-meter{display:grid;grid-template-columns:1.1fr 1fr .75fr 1fr 1.3fr;align-items:center;gap:24px}.load-overview h2{margin-bottom:6px}.load-stat>span,.meter-label{font-size:12px;color:var(--muted)}.load-stat strong{display:block;font-size:23px;font-weight:600;margin-top:8px}.load-stat small{font-size:12px;color:var(--muted);font-weight:400}.meter-label{display:flex;justify-content:space-between;margin-bottom:12px}.meter-label b{font-weight:500;color:var(--text)}.section-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:26px 0 14px}.section-heading h2{margin:0;font-size:15px}.dash-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}.dash-heading h2{margin:0;font-size:14px}.chart-caption{color:var(--muted);font-size:11px}.dash-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.dash-chart{height:260px;width:100%}.dash-resources{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);gap:18px;align-items:start}.dash-link{color:var(--el-color-primary);font-size:12px}.count-badge{font-size:11px;font-weight:400;padding:2px 7px;margin-left:4px;border-radius:10px;background:var(--soft);color:var(--muted)}.schedule-label{font-size:11px;margin-top:3px}.resource-foot{margin:12px 0 0;font-size:11px}.dash-notes{margin-top:18px;border-top:1px solid var(--line);padding-top:14px;color:var(--muted);font-size:12px}.dash-notes summary{cursor:pointer;width:fit-content}.dash-notes p{max-width:1000px;margin-bottom:0}.dashboard :deep(.el-alert){margin-bottom:16px}
@media(min-width:1700px){.dash-chart{height:290px}}
@media(max-width:1200px){.dash-resources{grid-template-columns:1fr}.gateway-meter{gap:16px;grid-template-columns:1fr 1fr .8fr 1fr}.meter-bar{grid-column:1/-1}}
@media(max-width:900px){.dash-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.dash-status .muted,.toolbar-divider{display:none}.dash-charts{grid-template-columns:1fr}}
@media(max-width:600px){.dash-kpi{padding:16px}.dash-kpi strong{font-size:25px}.dash-kpis{gap:10px}.gateway-meter{grid-template-columns:1fr 1fr}.load-overview{grid-column:1/-1}.dash-controls{gap:8px}.dashboard .panel{padding:16px}.dash-heading{gap:8px}.dash-chart{height:240px}}
</style>
