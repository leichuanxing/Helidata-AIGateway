<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {ElMessage} from 'element-plus'
import {api,message,sessionFetch} from '../api/client'
import {useRouter} from 'vue-router'
type Model={logical_model:string;model_type:string;configured:boolean;virtual:boolean;groups:string[]}
type Turn={prompt:string;answer:string;reasoning:string;status:'pending'|'done'|'error'|'cancelled';error:string;requestId:string;usage:any;elapsed:number}
const router=useRouter(),models=ref<Model[]>([]),model=ref(''),loading=ref(false),loadError=ref('')
const turns=ref<Turn[]>([]),prompt=ref(''),system=ref(''),temperature=ref(0.7),maxTokens=ref(512),stream=ref(true),busy=ref(false)
const viewport=ref<HTMLElement>(),selected=computed(()=>models.value.find(m=>m.logical_model===model.value))
let controller:AbortController|null=null,disposed=false
const canSend=computed(()=>!busy.value&&!!prompt.value.trim()&&selected.value?.configured&&Number.isInteger(maxTokens.value)&&maxTokens.value>=1&&maxTokens.value<=4096)
async function load(){loading.value=true;loadError.value='';try{models.value=(await api.get('/admin/chat-test/models')).data.data.models;if(!models.value.some(m=>m.logical_model===model.value))model.value=models.value.find(m=>m.configured)?.logical_model||''}catch(e){loadError.value=message(e)}finally{loading.value=false}}
watch(model,()=>{turns.value=[]})
async function scroll(){await nextTick();if(viewport.value)viewport.value.scrollTop=viewport.value.scrollHeight}
function stop(){controller?.abort()}
function clear(){if(!busy.value)turns.value=[]}
function keydown(event:KeyboardEvent){if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(canSend.value)void send()}}
async function copy(text:string){try{await navigator.clipboard.writeText(text);ElMessage.success('已复制')}catch{ElMessage.warning('当前浏览器不支持复制，请选择文本手动复制')}}
async function send(){
 if(!canSend.value)return
 const text=prompt.value.trim(),history=turns.value.filter(t=>t.status==='done'&&t.answer).slice(-20)
 const messages=[...(system.value.trim()?[{role:'system',content:system.value.trim()}]:[]),...history.flatMap(t=>[{role:'user',content:t.prompt},{role:'assistant',content:t.answer}]),{role:'user',content:text}]
 const turn=ref<Turn>({prompt:text,answer:'',reasoning:'',status:'pending',error:'',requestId:'',usage:null,elapsed:0})
 turns.value.push(turn.value);prompt.value='';busy.value=true;const started=performance.now();controller=new AbortController();const signal=controller.signal;void scroll()
 try{
  const response=await sessionFetch('/api/admin/chat-test/completions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:model.value,messages,temperature:temperature.value,max_tokens:maxTokens.value,stream:stream.value}),signal})
  turn.value.requestId=response.headers.get('X-Request-ID')||''
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error?.message||'请求失败（HTTP '+response.status+'）')}
  if(stream.value){
   if(!response.body||!response.headers.get('content-type')?.includes('text/event-stream'))throw new Error('服务器未返回有效的流式响应')
   const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',done=false
   function event(raw:string){
    const data=raw.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).replace(/^ /,'')).join('\n')
    if(!data)return
    if(data==='[DONE]'){done=true;return}
    const value=JSON.parse(data)
    if(value.error)throw new Error(value.error.message||value.error.code||'模型调用失败')
    if(value.usage)turn.value.usage=value.usage
    const delta=value.choices?.[0]?.delta
    if(typeof delta?.content==='string')turn.value.answer+=delta.content
    if(typeof delta?.refusal==='string')turn.value.answer+=delta.refusal
    const reasoning=delta?.reasoning_content||delta?.reasoning
    if(typeof reasoning==='string')turn.value.reasoning+=reasoning
   }
   try{while(!done){const chunk=await reader.read();buffer+=decoder.decode(chunk.value,{stream:!chunk.done});let separator:RegExpExecArray|null;while((separator=/\r?\n\r?\n/.exec(buffer))!==null){event(buffer.slice(0,separator.index));buffer=buffer.slice(separator.index+separator[0].length);if(done)break}void scroll();if(chunk.done)break}
    if(!done)throw new Error('流式连接中断，回复可能不完整')
   }finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
  }else{
   const value=await response.json();if(value.error)throw new Error(value.error.message||'模型调用失败')
   const result=value.choices?.[0]?.message;turn.value.answer=result?.content||result?.refusal||'';turn.value.reasoning=result?.reasoning_content||'';turn.value.usage=value.usage||null
  }
  turn.value.status='done'
 }catch(error:any){turn.value.status=signal.aborted?'cancelled':'error';turn.value.error=signal.aborted?'已停止生成，当前回复可能不完整':error.message||'请求失败，请重试'}
 finally{turn.value.elapsed=Math.round(performance.now()-started);busy.value=false;controller=null;if(!disposed)void scroll()}
}
onMounted(load)
onBeforeUnmount(()=>{disposed=true;stop()})
</script>
<template>
<div class="chat-test">
 <PageHeader title="对话测试"><el-button :loading="loading" :disabled="busy" @click="load">刷新模型</el-button></PageHeader>
 <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false"/>
 <div class="chat-grid">
  <aside class="panel chat-settings" v-loading="loading">
   <h2>模型与参数</h2>
   <el-form label-position="top">
    <el-form-item label="测试模型"><el-select v-model="model" filterable placeholder="选择已添加的对话模型" :disabled="busy" class="full"><el-option v-for="item in models" :key="item.logical_model" :value="item.logical_model" :label="item.logical_model" :disabled="!item.configured"><span>{{item.logical_model}}</span><span class="model-hint">{{!item.configured?'不可用':item.virtual?'智能路由':item.model_type==='multimodal'?'多模态':item.model_type==='reasoning'?'推理':'文本'}}</span></el-option></el-select></el-form-item>
    <p v-if="selected" class="muted model-groups">{{selected.groups.join(' · ')}}</p>
    <el-form-item label="系统提示词"><el-input v-model="system" type="textarea" :rows="4" maxlength="16000" placeholder="可选：指定模型的回答方式" :disabled="busy"/></el-form-item>
    <el-form-item label="温度"><el-slider v-model="temperature" :min="0" :max="2" :step="0.1" :disabled="busy" show-input/></el-form-item>
    <el-form-item label="最大输出 Token"><el-input-number v-model="maxTokens" :min="1" :max="4096" :step="128" :disabled="busy"/></el-form-item>
    <el-form-item label="流式回复"><el-switch v-model="stream" :disabled="busy"/></el-form-item>
   </el-form>
   <el-alert title="测试会真实调用模型，产生用量及可能的费用。" type="warning" :closable="false" show-icon/>
   <p class="muted settings-note">使用当前账号的模型权限、配额与内容合规配置。多模态模型可测试文本对话；向量、重排和文生图模型不在此列表。</p>
   <router-link to="/admin/providers">管理模型供应商 →</router-link>
  </aside>
  <section class="panel chat-conversation" aria-label="测试对话">
   <header class="conversation-toolbar"><div><strong>{{model||'选择模型开始测试'}}</strong><small>{{busy?'正在生成…':'当前会话包含最近 20 轮成功回复'}}</small></div><el-button :disabled="busy||!turns.length" @click="clear">清空对话</el-button></header>
   <div ref="viewport" class="conversation-scroll" aria-live="polite" :aria-busy="busy">
    <div v-if="!turns.length" class="chat-empty"><UiIcon name="chat"/><h3>{{models.length?'开始对话测试':'暂无可测试的对话模型'}}</h3><p>{{models.length?'输入问题，验证模型响应和实际网关配置。':'请先添加文本或多模态模型，并检查用户组授权。'}}</p></div>
    <article v-for="(turn,index) in turns" :key="index" class="chat-turn">
     <div class="user-message"><div class="message-label">你</div><div class="message-text">{{turn.prompt}}</div></div>
     <div class="assistant-message"><div class="message-label">模型回复 <span v-if="turn.status==='pending'" class="typing-dot"/></div>
      <details v-if="turn.reasoning" class="reasoning"><summary>思考过程</summary><div class="message-text">{{turn.reasoning}}</div></details>
      <div class="message-text">{{turn.answer||(turn.status==='pending'?'等待模型回复…':turn.status==='done'?'模型未返回文本内容。':'')}}</div>
      <el-alert v-if="turn.error" :title="turn.error" :type="turn.status==='cancelled'?'info':'error'" :closable="false"/>
      <footer v-if="turn.status!=='pending'" class="message-footer"><span>{{(turn.elapsed/1000).toFixed(2)}} 秒</span><span v-if="turn.usage">输入 {{turn.usage.prompt_tokens??'—'}} · 输出 {{turn.usage.completion_tokens??'—'}} · 总 Token {{turn.usage.total_tokens??'未上报'}}</span><el-button v-if="turn.answer" link @click="copy(turn.answer)">复制回复</el-button><el-button v-if="turn.requestId" link type="primary" @click="router.push('/admin/call-logs/'+turn.requestId)">调用日志</el-button></footer>
     </div>
    </article>
   </div>
   <div class="chat-composer"><el-input v-model="prompt" type="textarea" :rows="3" resize="none" maxlength="16000" show-word-limit placeholder="输入问题，Enter 发送，Shift+Enter 换行" @keydown="keydown"/><div class="composer-actions"><span class="muted">对话仅保留在当前页面，离开后清空。</span><el-button v-if="busy" type="danger" plain @click="stop">停止生成</el-button><el-button v-else type="primary" :disabled="!canSend" @click="send">发送</el-button></div></div>
  </section>
 </div>
</div>
</template>
<style scoped>
.chat-test>.el-alert{margin-bottom:16px}.chat-grid{display:grid;grid-template-columns:300px minmax(0,1fr);gap:20px;align-items:start}.chat-grid .panel{margin:0;min-width:0}.chat-settings h2{font-size:15px;margin:0 0 20px}.full{width:100%}.model-hint{float:right;color:var(--muted);font-size:12px;margin-left:12px}.model-groups{font-size:12px;margin:-8px 0 20px}.settings-note{font-size:12px;line-height:1.8;margin:16px 0}.chat-settings a{font-size:13px;color:var(--el-color-primary)}.chat-conversation{padding:0!important;display:flex;flex-direction:column;height:min(780px,calc(100dvh - 180px));min-height:520px;overflow:hidden}.conversation-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:18px 22px;border-bottom:1px solid var(--line)}.conversation-toolbar strong{display:block;overflow-wrap:anywhere}.conversation-toolbar small{display:block;color:var(--muted);font-size:12px;margin-top:6px}.conversation-scroll{flex:1;overflow:auto;padding:22px;scrollbar-gutter:stable}.chat-empty{text-align:center;color:var(--muted);padding:60px 12px}.chat-empty :deep(svg){width:40px;height:40px}.chat-empty h3{color:var(--text);font-size:17px}.chat-empty p{font-size:13px;line-height:1.8}.chat-turn{margin-bottom:24px}.user-message{margin-left:12%;padding:14px 18px;background:var(--el-color-primary-light-9);border-radius:14px 14px 4px 14px}.assistant-message{padding:18px 4px 0}.message-label{font-size:12px;color:var(--muted);margin-bottom:8px;display:flex;align-items:center;gap:8px}.message-text{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;font-size:14px}.assistant-message>.el-alert{margin-top:12px}.reasoning{background:var(--soft);padding:10px 14px;border-radius:8px;margin-bottom:12px}.reasoning summary{cursor:pointer;color:var(--muted);font-size:12px}.reasoning .message-text{color:var(--muted);font-size:13px;margin-top:8px}.message-footer{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:11px;margin-top:12px}.chat-composer{border-top:1px solid var(--line);padding:16px 22px}.composer-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px}.composer-actions>span{font-size:11px}.typing-dot{width:6px;height:6px;background:var(--el-color-primary);border-radius:50%;animation:pulse 1s ease-in-out infinite}@keyframes pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){.typing-dot{animation:none}}@media(max-width:1000px){.chat-grid{grid-template-columns:250px minmax(0,1fr)}}@media(max-width:760px){.chat-grid{grid-template-columns:1fr}.chat-conversation{height:640px;min-height:480px}.conversation-scroll{padding:16px}.chat-composer{padding:14px}.user-message{margin-left:5%}.composer-actions{flex-wrap:wrap}}
</style>
