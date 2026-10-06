<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {ElMessage} from 'element-plus'
import {api,message} from '../api/client'
import type {Provider} from '../api/provider'
const visible=defineModel<boolean>({required:true}),props=defineProps<{provider:Provider|null;autoStart?:boolean}>(),emit=defineEmits<{finished:[]}>()
const selected=ref(''),consent=ref(false),imageConsent=ref(false),running=ref(false),results=ref<any[]>([])
const models=computed(()=>props.provider?.models?.filter(m=>m.status==='enabled')||[])
watch(visible,open=>{if(open){selected.value=props.provider?.default_test_model||models.value[0]?.logical_model||'';consent.value=!!props.autoStart;imageConsent.value=false;results.value=[];if(props.autoStart)void start()}})
async function start(all=false){
  const names=all?models.value.map(m=>m.logical_model):[selected.value]
  if(!props.provider||!consent.value||!names.length||!names[0])return
  if(models.value.some(m=>names.includes(m.logical_model)&&m.model_type==='image')&&!imageConsent.value){ElMessage.warning('请单独确认文生图测试费用');return}
  running.value=true;results.value=[]
  try{results.value=(await api.post('/admin/providers/'+props.provider.id+'/test-models',{models:names,consent:true,image_consent:imageConsent.value,expected_config_version:props.provider.config_version})).data.data.results;emit('finished')}
  catch(e){ElMessage.error(message(e))}finally{running.value=false}
}
</script>
<template><el-dialog v-model="visible" title="测试模型" width="760px" :close-on-click-modal="!running" :close-on-press-escape="!running" :show-close="!running">
<p>账号：{{provider?.name}}。使用已保存配置直接调用此账号，不切换其他供应商。</p>
<el-select v-model="selected" filterable placeholder="选择已启用模型" :disabled="running" style="width:100%"><el-option v-for="m in models" :key="m.logical_model" :value="m.logical_model" :label="m.logical_model+' → '+m.upstream_model"/></el-select>
<p class="muted">文本测试最多输出 8 Token；向量测试使用单条短文本；图片测试会生成一张图片。测试所有模型将逐个调用所有已启用映射，用量记录在调用日志中。</p>
<el-checkbox v-model="consent" :disabled="running">我确认发起真实调用，可能产生用量和费用</el-checkbox>
<el-checkbox v-if="models.some(m=>m.model_type==='image')" v-model="imageConsent" :disabled="running">我确认文生图测试将真实生成图片并可能产生费用</el-checkbox>
<el-table v-if="results.length" :data="results" style="margin-top:16px"><el-table-column prop="logical_model" label="模型"/><el-table-column label="结果"><template #default="s"><el-tag :type="s.row.success?'success':'danger'">{{s.row.success?'成功':'失败'}}</el-tag></template></el-table-column><el-table-column prop="latency_ms" label="耗时 ms"/><el-table-column label="Token"><template #default="s">{{s.row.total_tokens??'未上报'}}</template></el-table-column><el-table-column label="详情" min-width="210"><template #default="s"><span>{{s.row.error_code||s.row.operation}}</span> <router-link class="route-link" :to="'/admin/call-logs/'+s.row.request_id" @click="visible=false">调用日志</router-link></template></el-table-column></el-table>
<template #footer><el-button :disabled="running" @click="visible=false">关闭</el-button><el-button :disabled="!consent||!models.length||running" @click="start(true)">测试所有模型（{{models.length}}）</el-button><el-button type="primary" :disabled="!consent||!selected" :loading="running" @click="start()">开始</el-button></template>
</el-dialog></template>
