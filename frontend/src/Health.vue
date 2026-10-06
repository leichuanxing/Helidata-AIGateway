<script setup lang="ts">
import { onMounted, ref } from 'vue'
import axios from 'axios'
import {branding} from './ui/branding'
type Health = { status: string; checks: Record<string, string>; phase: number }
const health = ref<Health | null>(null)
const loading = ref(false)
const error = ref('')
const labels: Record<string, string> = {fastapi: 'API 服务', postgresql: 'PostgreSQL', redis: 'Redis', disk: '数据磁盘'}
async function refresh() {
  loading.value = true
  error.value = ''
  try { health.value = (await axios.get<Health>('/api/health/detail')).data }
  catch (e) {
    health.value = axios.isAxiosError(e) ? e.response?.data ?? null : null
    error.value = '服务检查未通过，请检查容器日志。'
  } finally { loading.value = false }
}
onMounted(refresh)
</script>
<template>
  <div class="page health-page">
    <header><img v-if="branding.logo" :src="branding.logo" alt="Logo" class="health-logo"/><div v-else class="brand">HD</div><strong>{{branding.system_name}}</strong><span>服务状态</span></header>
    <main>
      <div class="eyebrow">运行环境 · 实时检查</div>
      <h1>服务运行状态</h1>
      <p>检查网关基础服务的实际可用性。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <div class="cards" v-if="health">
        <el-card v-for="(value, key) in health.checks" :key="key" shadow="never">
          <div class="label">{{ labels[key] || key }}</div>
          <el-tag :type="value === 'ok' ? 'success' : 'danger'">{{ value === 'ok' ? '正常' : value }}</el-tag>
        </el-card>
      </div>
      <el-empty v-else-if="!loading" description="暂时无法读取服务状态" />
      <el-button type="primary" :loading="loading" @click="refresh">刷新检查</el-button>
      <router-link to="/admin/dashboard" class="health-return">返回工作台 →</router-link>
      <section><h2>检查说明</h2><p>状态反映本次检查时 API 服务、数据库、缓存和数据磁盘的可用性。点击刷新可重新检查。</p><p>上游模型的连接状态和调度情况，请在管理后台的模型供应商页面查看。</p></section>
    </main>
  </div>
</template>
<style scoped>
.page{min-height:100vh;background:var(--page-bg);color:var(--text)}header{display:flex;align-items:center;gap:16px;padding:22px 5%;background:var(--surface);border-bottom:1px solid var(--line)}header span{color:#738299;font-size:13px}.brand{background:#1865da;color:white;border-radius:12px;padding:10px;font-weight:800}main{max-width:1100px;margin:60px auto;padding:0 24px}.eyebrow{color:#2867bb;font-size:14px}h1{font-size:32px;margin-bottom:12px}p{color:var(--muted);line-height:1.8}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin:32px 0}.label{font-size:16px;margin-bottom:22px}section{margin-top:44px;padding:24px;background:var(--surface);border:1px solid var(--line);border-radius:8px}h2{font-size:18px}@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}header span{display:none}}
</style>
