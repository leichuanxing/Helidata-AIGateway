<script setup lang="ts">
import {computed,ref,watch} from 'vue'
const props=defineProps<{code:string;name:string;icon?:string;compact?:boolean}>()
const failed=ref(false)
const source=computed(()=>props.icon||'/providers/'+props.code+'.svg')
watch(source,()=>{failed.value=false})
</script>
<template><span class="provider-identity" :class="{compact}"><span class="provider-mark"><img v-if="!failed" :src="source" alt="" @error="failed=true"/><span v-else>{{name.slice(0,2)}}</span></span><span v-if="!compact" class="provider-name">{{name}}</span></span></template>
<style scoped>
.provider-identity{display:inline-flex;align-items:center;gap:10px;vertical-align:middle;min-width:0;max-width:100%}.provider-mark{width:28px;height:28px;flex:none;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);background:#fff;border-radius:8px;padding:4px;box-sizing:border-box}.provider-mark img{width:100%;height:100%;object-fit:contain}.provider-mark>span{font-size:10px;color:#376dde;font-weight:700}.provider-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.compact .provider-mark{width:24px;height:24px}
</style>
