<script setup lang="ts">
defineProps<{value:string;items:Record<string,string>}>()
const emit=defineEmits<{change:[name:string]}>()
</script>
<template><el-tabs class="management-tabs" :model-value="value" @tab-change="(name:string|number)=>emit('change',String(name))"><el-tab-pane v-for="(label,key) in items" :key="key" :name="key" :label="label"/></el-tabs></template>
