<script setup lang="ts">
import {ref,computed,watch} from 'vue'
import {ElMessage} from 'element-plus'
import {modelTypes} from '../api/models'
import type {ProviderDraftMapping} from '../api/provider'
const rows=defineModel<ProviderDraftMapping[]>({required:true})
const props=defineProps<{models:string[];discovering:boolean;category?:string|null}>()
const emit=defineEmits<{discover:[]}>(),selected=ref<string[]>([])
const query=ref(''),defaultType=computed(()=>props.category==='multimodal'?'multimodal':props.category==='vector'?'embedding':props.category==='image'?'image':'text')
const allowed=computed(()=>Object.entries(modelTypes).filter(([value])=>!props.category||(props.category==='multimodal'?value==='multimodal':props.category==='text'?['text','reasoning','multimodal'].includes(value):props.category==='image'?value==='image':['embedding','rerank'].includes(value))))
const filtered=computed(()=>rows.value.map((m,i)=>({m,i})).filter(({m})=>!query.value||m.logical_model.toLowerCase().includes(query.value.toLowerCase())||m.upstream_model.toLowerCase().includes(query.value.toLowerCase())))
watch(()=>props.models,()=>{selected.value=[]})
function add(){if(rows.value.length>=100){ElMessage.warning('最多100个模型映射');return}query.value='';rows.value.push({logical_model:'',upstream_model:'',model_type:defaultType.value,status:'enabled'})}
function appendSelected(){
  const names=selected.value.filter(name=>!rows.value.some(m=>m.logical_model===name))
  const existing=rows.value.filter(m=>m.logical_model.trim()||m.upstream_model.trim())
  if(existing.length+names.length>100){ElMessage.warning('最多100个模型映射，请减少选择');return}
  if(names.some(name=>! /^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,99}$/.test(name))){ElMessage.warning('部分模型名称不能直接用作请求模型名，请手工添加映射');return}
  rows.value=[...existing,...names.map(name=>({logical_model:name,upstream_model:name,model_type:defaultType.value,status:'enabled'}))]
  query.value=''
  selected.value=[]
}
</script>
<template><section class="mapping-editor"><div class="mapping-toolbar"><h3>模型映射</h3><span class="muted">已添加 {{rows.filter(m=>m.logical_model.trim()).length}} / 100</span><el-button :loading="discovering" @click="emit('discover')">发现模型</el-button><el-button :disabled="rows.length>=100" @click="add">添加映射</el-button></div><p class="muted">请求模型名称对应上游模型名称；保留1至100条，同一账号内请求模型名不能重复。</p><el-input v-model="query" clearable placeholder="搜索请求模型或上游模型"/><div v-if="props.models.length" class="mapping-toolbar" style="margin-top:12px"><el-select v-model="selected" multiple filterable placeholder="选择发现的模型（已配置模型不可重复添加）" style="flex:1"><el-option v-for="name in props.models" :key="name" :value="name" :label="name" :disabled="rows.some(m=>m.logical_model===name)"/></el-select><el-button :disabled="!selected.length" @click="appendSelected">添加选中</el-button></div><div v-for="{m,i} in filtered" :key="i" class="mapping-row"><el-input v-model="m.logical_model" placeholder="请求模型名称" :aria-label="'请求模型名称 '+(i+1)" maxlength="100"/><span>→</span><el-input v-model="m.upstream_model" placeholder="上游模型名称" :aria-label="'上游模型名称 '+(i+1)" maxlength="200"/><el-select v-model="m.model_type" style="width:120px" :aria-label="'模型类型 '+(i+1)"><el-option v-for="[value,label] in allowed" :key="value" :value="value" :label="label"/></el-select><el-switch v-model="m.status" active-value="enabled" inactive-value="disabled" :aria-label="'启用模型映射 '+(i+1)"/><el-button text type="danger" :disabled="rows.length===1" :aria-label="'删除映射 '+(i+1)" @click="rows.splice(i,1)">删除</el-button></div><p v-if="!filtered.length" class="muted">没有匹配的模型映射</p></section></template>
<style scoped>.mapping-editor{border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:20px 0;padding:16px 0}.mapping-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:12px}.mapping-toolbar h3{margin:0;flex:1}.mapping-row{display:flex;align-items:center;gap:8px;margin:10px 0}.mapping-row>.el-input{flex:1;min-width:0}@media(max-width:700px){.mapping-row{flex-wrap:wrap}.mapping-row>.el-input{flex-basis:40%}}</style>
