<script setup lang="ts">
import {formatDate} from '../ui/branding'
import {onMounted,onBeforeUnmount,ref} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {copyText} from '../ui/clipboard'
import {api,message} from '../api/client'
type Key={id:number,name:string,prefix:string,suffix:string,status:string,last_used_at:string|null,created_at:string}
const rows=ref<Key[]>([]),total=ref(0),page=ref(1),loading=ref(false),saving=ref(false),error=ref(''),dialog=ref(false),editing=ref<number|null>(null),name=ref(''),secret=ref('')
async function load(){loading.value=true;error.value='';try{const d=(await api.get('/portal/api-keys',{params:{page:page.value}})).data.data;rows.value=d.items;total.value=d.total}catch(e){error.value=message(e)}finally{loading.value=false}}
function open(k?:Key){editing.value=k?.id??null;name.value=k?.name||'';dialog.value=true}
async function save(){if(saving.value)return;if(!name.value.trim()){ElMessage.error('请填写名称');return}name.value=name.value.trim();saving.value=true;try{if(editing.value)await api.patch('/portal/api-keys/'+editing.value,{name:name.value});else secret.value=(await api.post('/portal/api-keys',{name:name.value})).data.data.secret;dialog.value=false;await load()}catch(e){ElMessage.error(message(e))}finally{saving.value=false}}
const toggling=ref<number[]>([])
async function toggle(k:Key,enabled:boolean){if(toggling.value.includes(k.id))return;toggling.value.push(k.id);try{await api.patch('/portal/api-keys/'+k.id,{status:enabled?'enabled':'disabled'});ElMessage.success(enabled?'API Key 已启用':'API Key 已禁用');await load()}catch(e){ElMessage.error(message(e))}finally{toggling.value=toggling.value.filter(id=>id!==k.id)}}
async function remove(k:Key){try{await ElMessageBox.confirm('删除后，该 Key 立即失效且无法恢复。','删除 '+k.name,{type:'warning',confirmButtonText:'删除',cancelButtonText:'取消'});await api.delete('/portal/api-keys/'+k.id);await load()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(message(e))}}
onMounted(load);onBeforeUnmount(()=>{secret.value=''})
</script>
<template>
  <section class="panel key-page">
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="toolbar"><el-button type="primary" @click="open()">创建 API Key</el-button><el-button :loading="loading" aria-label="刷新 API Keys" @click="load">刷新</el-button></div>
    <el-table :data="rows" v-loading="loading" empty-text="暂无 API Key">
      <el-table-column prop="name" label="名称" min-width="160"/>
      <el-table-column label="API Key" min-width="220"><template #default="s"><code>{{s.row.prefix.slice(0,4)}}••••••{{s.row.suffix}}</code></template></el-table-column>
      <el-table-column label="创建时间" min-width="175"><template #default="s">{{formatDate(s.row.created_at)}}</template></el-table-column>
      <el-table-column label="最新使用日期" min-width="175"><template #default="s">{{s.row.last_used_at?formatDate(s.row.last_used_at):'-'}}</template></el-table-column>
      <el-table-column label="操作" width="190" fixed="right"><template #default="s"><el-switch :model-value="s.row.status==='enabled'" :loading="toggling.includes(s.row.id)" :disabled="loading||toggling.includes(s.row.id)" :aria-label="'启用 API Key '+s.row.name" @change="toggle(s.row,Boolean($event))"/><el-button link type="primary" @click="open(s.row)">编辑</el-button><el-button link type="danger" @click="remove(s.row)">删除</el-button></template></el-table-column>
      <template #empty><EmptyState title="暂无 API Key" description="点击“创建 API Key”创建第一个 API Key。"/></template>
    </el-table>
    <el-pagination v-if="total>0" v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next" @current-change="load"/>
  </section>
  <el-drawer v-model="dialog" :title="editing?'编辑 API Key':'创建 API Key'" size="440px" class="key-drawer">
    <el-form label-position="top" @submit.prevent="save"><el-form-item label="名称" required><el-input v-model="name" placeholder="请输入名称" maxlength="80" @keyup.enter="save"/></el-form-item></el-form>
    <template #footer><el-button :disabled="saving" @click="dialog=false">取消</el-button><el-button type="primary" :disabled="!name.trim()" :loading="saving" @click="save">{{editing?'保存':'创建'}}</el-button></template>
  </el-drawer>
  <el-dialog :model-value="!!secret" title="保存 API Key" width="580px" :close-on-click-modal="false" @close="secret=''">
    <el-alert title="API Key 仅显示一次，请立即保存。" type="warning" :closable="false"/><div class="credential" style="margin-top:20px;user-select:all">{{secret}}</div>
    <template #footer><el-button @click="copyText(secret)">复制 API Key</el-button><el-button type="primary" @click="secret=''">已保存，关闭</el-button></template>
  </el-dialog>
</template>
<style scoped>.key-page{min-height:calc(100vh - 82px);margin:0}.toolbar{justify-content:space-between}.el-switch{margin-right:14px}.el-pagination{margin-top:20px}</style>
