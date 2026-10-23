<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {onBeforeRouteLeave} from 'vue-router'
import {api,message} from '../api/client'
import {useAuth} from '../stores/auth'
const props=defineProps<{field:'smart_route_enabled'|'compliance_enabled';title:string;description:string;embedded?:boolean}>()
const emit=defineEmits<{changed:[]}>()
const auth=useAuth(),allowed=computed(()=>auth.user?.role==='super_admin')
const enabled=ref(false),ready=ref(false),busy=ref(false),error=ref(''),revision=ref(0)
const threshold=ref<number|null|undefined>(null),savedThreshold=ref<number|null>(null)
const thresholdDirty=computed(()=>(threshold.value??null)!==savedThreshold.value)
let disposed=false
const request=new AbortController()
async function load(){
 if(!allowed.value)return
 ready.value=false;error.value=''
 try{const d=(await api.get('/admin/settings',{params:{include_assets:false},signal:request.signal})).data.data;if(disposed)return;enabled.value=d.governance[props.field];threshold.value=savedThreshold.value=d.governance.semantic_threshold??null;revision.value=d.revision;ready.value=true}
 catch(e){if(!disposed)error.value=message(e)}
}
async function persist(fields:Record<string,unknown>,success:string){
 if(busy.value||!ready.value)return
 busy.value=true;error.value=''
 try{const d=(await api.patch('/admin/settings',{revision:revision.value,governance:fields},{params:{include_assets:false}})).data.data;if(disposed)return;enabled.value=d.governance[props.field];revision.value=d.revision;if('semantic_threshold' in fields)threshold.value=savedThreshold.value=d.governance.semantic_threshold??null;ElMessage.success(success);emit('changed')}
 catch(e){if(!disposed){error.value=message(e);ready.value=false;emit('changed')}}
 finally{busy.value=false}
}
function toggle(value:boolean|string|number){return persist({[props.field]:value},props.title+(value?'已开启':'已关闭'))}
function saveThreshold(){const value=threshold.value??null;if(value!==null&&(!Number.isFinite(value)||value<0||value>1)){error.value='语义阈值须在 0 至 1 之间';return}return persist({semantic_threshold:value},'全局语义阈值已保存')}
async function reload(){if(thresholdDirty.value){try{await ElMessageBox.confirm('重新加载将放弃未保存的语义阈值。','未保存更改',{type:'warning'})}catch{return}}await load()}
function beforeUnload(e:BeforeUnloadEvent){if(thresholdDirty.value){e.preventDefault();e.returnValue=''}}
onBeforeRouteLeave(async()=>{if(busy.value)return false;if(!thresholdDirty.value)return true;try{await ElMessageBox.confirm('离开将放弃未保存的语义阈值。','未保存更改',{type:'warning'});return true}catch{return false}})
onMounted(()=>{window.addEventListener('beforeunload',beforeUnload);void load()})
onUnmounted(()=>{disposed=true;request.abort();window.removeEventListener('beforeunload',beforeUnload)})
</script>
<template><section v-if="allowed" :class="['governance-control',{panel:!embedded}]" :aria-label="title"><div class="governance-row"><div><strong>{{title}}</strong><p>{{description}}</p><small>切换后立即保存并生效</small></div><el-switch :model-value="enabled" :aria-label="title" :loading="busy" :disabled="!ready||busy" @change="toggle"/></div><el-form v-if="field==='compliance_enabled'&&ready" label-position="top" class="threshold-form"><el-form-item label="全局语义阈值"><el-input-number v-model="threshold" :min="0" :max="1" :step=".01" :precision="2" :disabled="busy" aria-label="全局语义阈值"/><span class="threshold-help">留空沿用各策略阈值；填写后统一覆盖。数值越高，语义越接近才命中。</span></el-form-item><el-button type="primary" :loading="busy" :disabled="!thresholdDirty||busy" @click="saveThreshold">保存语义阈值</el-button><el-button :disabled="!thresholdDirty||busy" @click="threshold=savedThreshold">撤销更改</el-button></el-form><el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/><el-button v-if="!ready&&!busy" text @click="reload">重新加载</el-button></section></template>
<style scoped>.governance-control{margin-bottom:16px}.governance-row{display:flex;align-items:center;justify-content:space-between;gap:24px}.governance-row p{margin:6px 0;color:var(--el-text-color-regular);line-height:1.6}.governance-row small{color:var(--el-text-color-secondary)}.governance-row .el-switch{flex-shrink:0}.el-alert{margin-top:12px}.threshold-form{margin-top:20px;padding-top:20px;border-top:1px solid var(--el-border-color-lighter)}.threshold-help{margin-left:16px;color:var(--el-text-color-secondary);font-size:12px;line-height:1.6}</style>
