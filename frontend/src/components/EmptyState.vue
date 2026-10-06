<script setup lang="ts">
withDefaults(defineProps<{title?:string;description?:string}>(),{title:'暂无数据',description:'调整筛选条件或刷新页面后重试。'})
</script>
<template><div class="empty-state"><svg width="44" height="44" viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M12 6h18l8 8v28H12z M30 6v10h8 M18 24h14 M18 30h10" stroke="currentColor" stroke-width="2"/></svg><strong>{{title}}</strong><p>{{description}}</p><slot/></div></template>
