<script setup lang="ts">
import { onMounted, ref } from 'vue'
import axios from 'axios'
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
    <header><div class="brand">HD</div><strong>合力数据AI网关</strong><span>HeliData AI Gateway</span></header>
    <main>
      <div class="eyebrow">运行环境 · 阶段 {{health?.phase ?? '—'}}</div>
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
      <section><h2>部署信息</h2><p>Nginx · FastAPI · PostgreSQL · Redis · Supervisor</p><p>所有持久化数据保存在 /data。已开放 Chat Completions、SSE、账号调度与故障转移；四级并发、等待队列与配额已接入；调用日志已持久化并支持 Request ID 查询；Token、流式 TTFT、Tokens/s 及小时 / 日用量汇总已接入；Dashboard 展示真实运行状态、趋势与排行。Responses、Messages、Embeddings、Rerank 和图片生成接口已接入；Chat 与 Messages 支持协议转换。</p></section>
    </main>
  </div>
</template>
<style scoped>
.page{min-height:100vh;background:var(--page-bg);color:var(--text)}header{display:flex;align-items:center;gap:16px;padding:22px 5%;background:var(--surface);border-bottom:1px solid var(--line)}header span{color:#738299;font-size:13px}.brand{background:#1865da;color:white;border-radius:12px;padding:10px;font-weight:800}main{max-width:1100px;margin:60px auto;padding:0 24px}.eyebrow{color:#2867bb;font-size:14px}h1{font-size:32px;margin-bottom:12px}p{color:var(--muted);line-height:1.8}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin:32px 0}.label{font-size:16px;margin-bottom:22px}section{margin-top:44px;padding:24px;background:var(--surface);border:1px solid var(--line);border-radius:8px}h2{font-size:18px}@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}header span{display:none}}
</style>
