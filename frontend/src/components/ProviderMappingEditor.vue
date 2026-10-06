<script setup lang="ts">
import {ref} from 'vue'
import {ElMessage} from 'element-plus'
import {modelTypes} from '../api/models'
import type {ProviderDraftMapping} from '../api/provider'
const rows=defineModel<ProviderDraftMapping[]>({required:true})
const props=defineProps<{models:string[];discovering:boolean}>()
const emit=defineEmits<{discover:[]}>(),selected=ref<string[]>([])
function add(){if(rows.value.length>=100){ElMessage.warning('最多100个模型映射');return}rows.value.push({logical_model:'',upstream_model:'',model_type:'text',status:'enabled'})}
function appendSelected(){
  const names=selected.value.filter(name=>!rows.value.some(m=>m.logical_model===name))
  if(rows.value.length+names.length>100){ElMessage.warning('最多100个模型映射，请减少选择');return}
  rows.value.push(...names.map(name=>({logical_model:name,upstream_model:name,model_type:'text',status:'enabled'})))
  selected.value=[]
}
</script>
<template><section class="mapping-editor"><div class="mapping-toolbar"><h3>模型映射</h3><el-button :loading="discovering" @click="emit('discover')">发现模型</el-button><el-button :disabled="rows.length>=100" @click="add">添加映射</el-button></div><p class="muted">请求模型名称对应上游模型名称；保留1至100条，同一账号内请求模型名不能重复。</p><div v-if="props.models.length" class="mapping-toolbar"><el-select v-model="selected" multiple filterable placeholder="选择发现的模型" style="flex:1"><el-option v-for="name in props.models" :key="name" :value="name" :label="name" :disabled="rows.some(m=>m.logical_model===name)"/></el-select><el-button :disabled="!selected.length" @click="appendSelected">添加选中</el-button></div><div v-for="(m,i) in rows" :key="i" class="mapping-row"><el-input v-model="m.logical_model" placeholder="请求模型名称" :aria-label="'请求模型名称 '+(i+1)" maxlength="100"/><span>→</span><el-input v-model="m.upstream_model" placeholder="上游模型名称" :aria-label="'上游模型名称 '+(i+1)" maxlength="200"/><el-select v-model="m.model_type" style="width:120px" :aria-label="'模型类型 '+(i+1)"><el-option v-for="(label,value) in modelTypes" :key="value" :value="value" :label="label"/></el-select><el-switch v-model="m.status" active-value="enabled" inactive-value="disabled" :aria-label="'启用模型映射 '+(i+1)"/><el-button text type="danger" :disabled="rows.length===1" :aria-label="'删除映射 '+(i+1)" @click="rows.splice(i,1)">删除</el-button></div></section></template>
<style scoped>.mapping-editor{border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:20px 0;padding:16px 0}.mapping-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:12px}.mapping-toolbar h3{margin:0;flex:1}.mapping-row{display:flex;align-items:center;gap:8px;margin:10px 0}.mapping-row>.el-input{flex:1;min-width:0}@media(max-width:700px){.mapping-row{flex-wrap:wrap}.mapping-row>.el-input{flex-basis:40%}}</style>
