<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {ElMessage} from 'element-plus'
import {api,message,sessionFetch} from '../api/client'
import {useRouter} from 'vue-router'
import {ACCEPT,MAX_ATTACHMENTS,MAX_ATTACHMENT_BYTES,formatBytes,readAttachment,boundedMessages} from '../utils/chatAttachments'
import type {Attachment} from '../utils/chatAttachments'
type Model={logical_model:string;model_type:string;configured:boolean;virtual:boolean;groups:string[]}
type Turn={prompt:string;attachments:Attachment[];answer:string;reasoning:string;status:'pending'|'done'|'error'|'cancelled';error:string;requestId:string;usage:any;elapsed:number;rounds:number;finish:string}
const router=useRouter(),models=ref<Model[]>([]),model=ref(''),loading=ref(false),loadError=ref('')
const turns=ref<Turn[]>([]),prompt=ref(''),system=ref(''),temperature=ref(0.7),maxTokens=ref(512),stream=ref(true),busy=ref(false)
const attachments=ref<Attachment[]>([]),reading=ref(false),settingsOpen=ref(true),preview=ref<Attachment|null>(null)
const fileInput=ref<HTMLInputElement>(),viewport=ref<HTMLElement>(),selected=computed(()=>models.value.find(m=>m.logical_model===model.value))
const multimodal=computed(()=>selected.value?.model_type==='multimodal')
const modelLabel=computed(()=>selected.value?.virtual?'智能路由':multimodal.value?'多模态':selected.value?.model_type==='reasoning'?'推理':'文本')
const attachmentBytes=computed(()=>attachments.value.reduce((sum,a)=>sum+a.size,0))
let controller:AbortController|null=null,disposed=false,sequence=0
const canSend=computed(()=>!busy.value&&!reading.value&&(!!prompt.value.trim()||attachments.value.length>0)&&selected.value?.configured&&Number.isInteger(maxTokens.value)&&maxTokens.value>=1&&maxTokens.value<=4096)
async function load(){
 loading.value=true;loadError.value=''
 try{models.value=(await api.get('/admin/chat-test/models')).data.data.models;if(!models.value.some(m=>m.logical_model===model.value))model.value=models.value.find(m=>m.configured)?.logical_model||''}
 catch(e){loadError.value=message(e)}finally{loading.value=false}
}
watch(model,()=>{turns.value=[];attachments.value=[];preview.value=null})
watch(multimodal,(value,previous)=>{if(previous&&!value){attachments.value=[];turns.value=[];preview.value=null}})
async function scroll(force=false){const nearBottom=!viewport.value||viewport.value.scrollHeight-viewport.value.scrollTop-viewport.value.clientHeight<120;await nextTick();if(viewport.value&&(force||nearBottom))viewport.value.scrollTop=viewport.value.scrollHeight}
function stop(){controller?.abort()}
function clear(){if(!busy.value&&!reading.value){turns.value=[];attachments.value=[];prompt.value='';preview.value=null}}
function keydown(event:KeyboardEvent){if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(canSend.value)void send()}}
async function copy(text:string){try{await navigator.clipboard.writeText(text);ElMessage.success('已复制')}catch{ElMessage.warning('当前浏览器不支持复制，请选择文本手动复制')}}
async function addFiles(files:File[]){
 if(!multimodal.value||busy.value||reading.value)return
 reading.value=true
 try{for(const file of files){
  if(disposed)break
  if(attachments.value.length>=MAX_ATTACHMENTS){ElMessage.warning('每次最多添加 4 个附件');break}
  if(attachmentBytes.value+file.size>MAX_ATTACHMENT_BYTES){ElMessage.warning('附件总大小不能超过 1 MB');continue}
  try{const item=await readAttachment(file,String(++sequence));if(!disposed)attachments.value.push(item)}catch(e:any){ElMessage.warning(file.name+'：'+e.message)}
 }}finally{reading.value=false;if(fileInput.value)fileInput.value.value=''}
}
function chooseFiles(event:Event){void addFiles(Array.from((event.target as HTMLInputElement).files||[]))}
function paste(event:ClipboardEvent){const files=Array.from(event.clipboardData?.files||[]);if(multimodal.value&&files.length){event.preventDefault();void addFiles(files)}}
function remove(id:string){attachments.value=attachments.value.filter(a=>a.id!==id)}
async function send(){
 if(!canSend.value)return
 const text=prompt.value.trim()||'请分析所附图片或文件。',sent=attachments.value.slice()
 const history=turns.value.filter(t=>t.status==='done'&&t.answer)
 const parameters={model:model.value,temperature:temperature.value,max_tokens:maxTokens.value,stream:stream.value}
 let context:ReturnType<typeof boundedMessages>
 try{context=boundedMessages(system.value,history,text,sent,parameters)}catch(e:any){ElMessage.warning(e.message);return}
 if(context.dropped)ElMessage.info('请求大小受限，本次已省略 '+context.dropped+' 轮较早的上下文')
 const turn=ref<Turn>({prompt:text,attachments:sent,answer:'',reasoning:'',status:'pending',error:'',requestId:'',usage:null,elapsed:0,rounds:context.rounds,finish:''})
 turns.value.push(turn.value);prompt.value='';attachments.value=[];busy.value=true
 const started=performance.now();controller=new AbortController();const signal=controller.signal;void scroll(true)
 try{
  const response=await sessionFetch('/api/admin/chat-test/completions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...parameters,messages:context.messages}),signal})
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
    const choice=value.choices?.[0],delta=choice?.delta
    if(choice?.finish_reason)turn.value.finish=choice.finish_reason
    if(typeof delta?.content==='string')turn.value.answer+=delta.content
    if(typeof delta?.refusal==='string')turn.value.answer+=delta.refusal
    const reasoning=delta?.reasoning_content||delta?.reasoning
    if(typeof reasoning==='string')turn.value.reasoning+=reasoning
   }
   try{while(!done){const chunk=await reader.read();buffer+=decoder.decode(chunk.value,{stream:!chunk.done});let separator:RegExpExecArray|null
     while((separator=/\r?\n\r?\n/.exec(buffer))!==null){event(buffer.slice(0,separator.index));buffer=buffer.slice(separator.index+separator[0].length);if(done)break}
     void scroll();if(chunk.done)break
    }
    if(!done)throw new Error('流式连接中断，回复可能不完整')
   }finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
  }else{
   const value=await response.json();if(value.error)throw new Error(value.error.message||'模型调用失败')
   const choice=value.choices?.[0],result=choice?.message
   turn.value.answer=result?.content||result?.refusal||'';turn.value.reasoning=result?.reasoning_content||'';turn.value.usage=value.usage||null;turn.value.finish=choice?.finish_reason||''
  }
  turn.value.status='done'
 }catch(error:any){turn.value.status=signal.aborted?'cancelled':'error';turn.value.error=signal.aborted?'已停止生成，当前回复可能不完整':error.response?message(error):error.message||'请求失败，请重试'}
 finally{turn.value.elapsed=Math.round(performance.now()-started);busy.value=false;controller=null;if(!disposed)void scroll()}
}
onMounted(()=>{if(window.matchMedia('(max-width:800px)').matches)settingsOpen.value=false;void load()})
onBeforeUnmount(()=>{disposed=true;stop()})
</script>
<template>
<div class="chat-test">
 <PageHeader title="对话测试"><el-button :loading="loading" :disabled="busy||reading" @click="load">刷新模型</el-button><el-button :aria-expanded="settingsOpen" @click="settingsOpen=!settingsOpen">{{settingsOpen?'收起参数':'参数设置'}}</el-button></PageHeader>
 <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false"/>
 <div class="chat-grid" :class="{'settings-hidden':!settingsOpen}">
  <section class="panel chat-conversation" aria-label="测试对话">
   <header class="conversation-toolbar">
    <div class="model-picker"><el-select v-model="model" filterable placeholder="选择模型开始对话" :disabled="busy||reading" class="full"><el-option v-for="item in models" :key="item.logical_model" :value="item.logical_model" :label="item.logical_model" :disabled="!item.configured"><span>{{item.logical_model}}</span><span class="model-hint">{{!item.configured?'不可用':item.virtual?'智能路由':item.model_type==='multimodal'?'多模态':item.model_type==='reasoning'?'推理':'文本'}}</span></el-option></el-select><el-tag v-if="selected" size="small" effect="plain">{{modelLabel}}</el-tag></div>
    <el-button :disabled="busy||reading||(!turns.length&&!attachments.length&&!prompt)" @click="clear">新对话</el-button>
   </header>
   <div ref="viewport" class="conversation-scroll" aria-live="polite" :aria-busy="busy">
    <div v-if="!turns.length" class="chat-empty"><div class="empty-icon"><UiIcon name="chat"/></div><h3>{{models.length?'开始一段新的对话':'暂无可测试的对话模型'}}</h3><p>{{multimodal?'上传图片、PDF 或文本文件，测试模型的理解能力。':models.length?'选择已配置的模型，输入问题并查看实时回复。':'请先添加模型，并检查用户组授权。'}}</p><div class="capability-tags"><el-tag effect="plain">多轮对话</el-tag><el-tag effect="plain">流式回复</el-tag><el-tag v-if="multimodal" effect="plain">图片与文件</el-tag></div></div>
    <article v-for="(turn,index) in turns" :key="index" class="chat-turn">
     <div class="user-message"><div class="message-label">你</div><div class="message-text">{{turn.prompt}}</div>
      <div v-if="turn.attachments.length" class="sent-attachments"><button v-for="file in turn.attachments" :key="file.id" class="sent-file" @click="preview=file"><img v-if="file.kind==='image'" :src="file.data" :alt="file.name"/><span v-else class="file-kind">{{file.kind==='pdf'?'PDF':'TXT'}}</span><span class="file-name">{{file.name}}<small>{{formatBytes(file.size)}}</small></span></button></div>
     </div>
     <div class="assistant-message"><div class="assistant-avatar"><UiIcon name="chat"/></div><div class="assistant-body"><div class="message-label">模型回复 <span v-if="turn.status==='pending'" class="typing-dot"/></div>
      <details v-if="turn.reasoning" class="reasoning"><summary>思考过程</summary><div class="message-text">{{turn.reasoning}}</div></details>
      <div class="message-text">{{turn.answer||(turn.status==='pending'?'等待模型回复…':turn.status==='done'?'模型未返回文本内容。':'')}}</div>
      <el-alert v-if="turn.error" :title="turn.error" :type="turn.status==='cancelled'?'info':'error'" :closable="false"/>
      <p v-if="turn.finish==='length'" class="limit-note">已达到输出 Token 上限，可调整参数后重试。</p>
      <footer v-if="turn.status!=='pending'" class="message-footer"><span>{{(turn.elapsed/1000).toFixed(2)}} 秒</span><span v-if="turn.usage">输入 {{turn.usage.prompt_tokens??'—'}} · 输出 {{turn.usage.completion_tokens??'—'}} · 总 Token {{turn.usage.total_tokens??'未上报'}}</span><span>上下文 {{turn.rounds}} 轮</span><el-button v-if="turn.answer" link @click="copy(turn.answer)">复制</el-button><el-button v-if="turn.requestId" link type="primary" @click="router.push('/admin/call-logs/'+turn.requestId)">调用日志</el-button></footer>
     </div></div>
    </article>
   </div>
   <div class="chat-composer" @paste="paste">
    <div v-if="attachments.length" class="attachment-list"><div v-for="file in attachments" :key="file.id" class="attachment-card"><button class="attachment-preview" @click="preview=file"><img v-if="file.kind==='image'" :src="file.data" :alt="file.name"/><span v-else class="file-kind">{{file.kind==='pdf'?'PDF':'TXT'}}</span><span class="file-name">{{file.name}}<small>{{formatBytes(file.size)}}</small></span></button><el-button link :aria-label="'移除 '+file.name" :disabled="busy" @click="remove(file.id)">×</el-button></div></div>
    <el-input v-model="prompt" type="textarea" :rows="3" resize="none" maxlength="16000" show-word-limit :placeholder="multimodal?'输入问题，或上传图片、文件后发送…':'输入问题，Enter 发送，Shift+Enter 换行'" @keydown="keydown"/>
    <div class="composer-actions"><div class="composer-tools"><input ref="fileInput" class="file-input" type="file" multiple :accept="ACCEPT" aria-label="选择图片或文件" @change="chooseFiles"/><el-button v-if="multimodal" :loading="reading" :disabled="busy||attachments.length>=4" @click="fileInput?.click()">＋ 图片 / 文件</el-button><span class="muted">{{multimodal?attachments.length+' / 4 · '+formatBytes(attachmentBytes)+' / 1 MB':'Enter 发送 · Shift+Enter 换行'}}</span></div><el-button v-if="busy" type="danger" plain @click="stop">停止生成</el-button><el-button v-else type="primary" :disabled="!canSend" @click="send">发送</el-button></div>
    <p class="composer-note">{{multimodal?'支持 PNG、JPEG、GIF、WebP、PDF 及 UTF-8 文本文件（文本文件 ≤ 64 KB）。':'仅多模态模型支持附件。'}} 附件随发送提交给所选供应商。</p>
   </div>
  </section>
  <aside v-if="settingsOpen" class="panel chat-settings">
   <div class="settings-title"><h2>对话参数</h2><el-tag size="small" type="info">当前会话</el-tag></div>
   <p v-if="selected?.groups.length" class="muted model-groups">{{selected.groups.join(' · ')}}</p>
   <el-form label-position="top">
    <el-form-item label="系统提示词"><el-input v-model="system" type="textarea" :rows="5" maxlength="16000" placeholder="可选：指定模型的角色与回答方式" :disabled="busy"/></el-form-item>
    <el-form-item label="温度"><el-slider v-model="temperature" :min="0" :max="2" :step="0.1" :disabled="busy" show-input/></el-form-item>
    <el-form-item label="最大输出 Token"><el-input-number v-model="maxTokens" :min="1" :max="4096" :step="128" :disabled="busy" class="full"/></el-form-item>
    <el-form-item label="流式回复"><el-switch v-model="stream" :disabled="busy"/><span class="switch-hint">实时显示生成内容</span></el-form-item>
   </el-form>
   <div class="session-note"><strong>会话说明</strong><p>最多携带最近 20 轮成功回复；请求较大时自动减少较早的上下文。对话及附件仅保留在当前页面，离开后清空。</p><p>使用当前账号的模型权限、配额与内容合规配置。附件支持取决于上游模型；仅支持文本的审核策略会拒绝图片和 PDF。</p></div>
   <el-alert title="测试会产生实际用量及可能的费用。" type="warning" :closable="false" show-icon/>
   <router-link to="/admin/providers" class="provider-link">管理模型供应商 →</router-link>
  </aside>
 </div>
 <el-dialog :model-value="!!preview" :title="preview?.name||'附件预览'" width="min(720px,92vw)" append-to-body @close="preview=null"><template v-if="preview"><img v-if="preview.kind==='image'" :src="preview.data" :alt="preview.name" class="large-preview"/><pre v-else-if="preview.kind==='text'" class="text-preview">{{preview.data}}</pre><div v-else class="pdf-preview"><span class="file-kind">PDF</span><p>{{preview.name}}</p><p class="muted">{{formatBytes(preview.size)}} · 原始 PDF 随对话发送，由所选模型读取。</p></div></template></el-dialog>
</div>
</template>
<style scoped>
.chat-test>.el-alert{margin-bottom:16px}.chat-grid{display:grid;grid-template-columns:minmax(0,1fr) 288px;gap:20px;align-items:start}.chat-grid.settings-hidden{grid-template-columns:minmax(0,1fr)}.chat-grid .panel{margin:0;min-width:0}.full{width:100%}.model-hint{float:right;color:var(--muted);font-size:12px;margin-left:12px}.chat-conversation{padding:0!important;display:flex;flex-direction:column;height:calc(100dvh - 175px);min-height:430px;max-height:1050px;overflow:hidden}.conversation-toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 22px;border-bottom:1px solid var(--line)}.model-picker{display:flex;align-items:center;gap:10px;min-width:0;width:min(480px,75%)}.conversation-scroll{flex:1;min-height:150px;overflow:auto;padding:26px;scrollbar-gutter:stable}.chat-empty{text-align:center;color:var(--muted);padding:32px 12px}.empty-icon{display:inline-flex;padding:18px;border-radius:20px;background:var(--el-color-primary-light-9);color:var(--el-color-primary)}.empty-icon :deep(svg){width:34px;height:34px}.chat-empty h3{color:var(--text);font-size:20px;margin:20px 0 10px}.chat-empty p{font-size:13px;line-height:1.8}.capability-tags{display:flex;justify-content:center;gap:8px;margin-top:20px}.chat-turn{margin-bottom:26px}.user-message{margin-left:16%;padding:14px 18px;background:var(--el-color-primary-light-9);border:1px solid var(--el-color-primary-light-8);border-radius:16px 16px 4px 16px}.assistant-message{display:flex;gap:12px;padding-top:22px}.assistant-avatar{display:flex;align-items:center;justify-content:center;width:30px;height:30px;flex-shrink:0;border-radius:9px;background:var(--soft);color:var(--el-color-primary)}.assistant-avatar :deep(svg){width:18px;height:18px}.assistant-body{min-width:0;flex:1}.message-label{font-size:12px;color:var(--muted);margin-bottom:8px;display:flex;align-items:center;gap:8px}.message-text{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.85;font-size:14px}.assistant-body>.el-alert{margin-top:12px}.reasoning{background:var(--soft);padding:10px 14px;border-radius:8px;margin-bottom:12px}.reasoning summary{cursor:pointer;color:var(--muted);font-size:12px}.reasoning .message-text{color:var(--muted);font-size:13px;margin-top:8px}.message-footer{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:11px;margin-top:12px}.chat-composer{border-top:1px solid var(--line);padding:16px 22px;background:var(--surface)}.composer-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px}.composer-tools{display:flex;gap:12px;align-items:center;min-width:0}.composer-tools>span,.composer-note{font-size:11px;color:var(--muted)}.composer-note{margin:10px 0 0;line-height:1.7}.file-input{display:none}.attachment-list,.sent-attachments{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}.sent-attachments{margin:12px 0 0}.attachment-card{display:flex;align-items:center;gap:8px;padding:8px;border:1px solid var(--line);border-radius:10px;background:var(--soft);max-width:240px}.attachment-preview,.sent-file{display:flex;align-items:center;gap:10px;border:0;background:none;color:var(--text);cursor:pointer;padding:0;min-width:0;text-align:left;font:inherit}.sent-file{background:var(--surface);padding:8px;border:1px solid var(--line);border-radius:10px;max-width:240px}.attachment-preview img,.sent-file img{width:42px;height:42px;object-fit:cover;border-radius:6px;flex-shrink:0}.file-kind{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;flex-shrink:0;border-radius:7px;background:var(--el-color-primary-light-9);color:var(--el-color-primary);font-size:11px;font-weight:600}.file-name{font-size:12px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file-name small{display:block;font-size:10px;color:var(--muted);margin-top:5px}.large-preview{display:block;max-width:100%;max-height:65vh;object-fit:contain;margin:auto}.text-preview{white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh;overflow:auto;font-size:13px;line-height:1.7}.pdf-preview{text-align:center;padding:30px 0}.chat-settings{max-height:calc(100dvh - 175px);overflow:auto}.settings-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.settings-title h2{font-size:15px;margin:0}.model-groups{font-size:12px;line-height:1.7;margin:0 0 18px;overflow-wrap:anywhere}.switch-hint{font-size:12px;color:var(--muted);margin-left:10px}.session-note{border-top:1px solid var(--line);padding-top:18px;margin-bottom:16px;font-size:12px;line-height:1.8;color:var(--muted)}.session-note strong{color:var(--text)}.provider-link{display:block;font-size:12px;margin-top:18px;color:var(--el-color-primary)}.limit-note{font-size:12px;color:var(--el-color-warning)}.typing-dot{width:6px;height:6px;background:var(--el-color-primary);border-radius:50%;animation:pulse 1s ease-in-out infinite}@keyframes pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){.typing-dot{animation:none}}@media(max-width:1100px){.chat-grid{grid-template-columns:minmax(0,1fr) 250px}.conversation-scroll{padding:20px}}@media(max-width:800px){.chat-grid{grid-template-columns:1fr}.chat-settings{grid-row:1;max-height:none;overflow:visible}.chat-conversation{height:720px;min-height:600px}.conversation-scroll{padding:16px}.conversation-toolbar,.chat-composer{padding:14px}.user-message{margin-left:6%}.composer-tools{flex-wrap:wrap;gap:6px}.model-picker{width:72%}.conversation-toolbar{gap:8px}.conversation-toolbar>.el-button{padding:8px}.assistant-message{gap:8px}}
</style>
