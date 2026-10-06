<script setup lang="ts">
defineProps<{title:string;description?:string}>()
</script>
<template><div class="page-heading"><div><h1>{{title}}</h1><p v-if="description" class="muted">{{description}}</p></div><div class="page-actions"><slot/></div></div></template>
