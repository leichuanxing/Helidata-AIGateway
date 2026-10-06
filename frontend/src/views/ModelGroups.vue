<script setup lang="ts">
import {computed,onMounted,reactive,ref} from 'vue'
import {ElMessage,ElMessageBox} from 'element-plus'
import {api,message} from '../api/client'
import {formatDate} from '../ui/branding'
import {type ModelGroup} from '../api/models'
const rows=ref<ModelGroup[]>([]),options=ref<{name:string;model_type:string}[]>([]),page=ref(1),total=ref(0),q=ref(''),loading=ref(false),saving=ref(false),dialog=ref(false),editing=ref<number|null>(null),error=ref(''),dragging=ref<number|null>(null)
const dragTarget=ref<number|null>(null)
const protocol=ref(''),categoryLabels:Record<string,string>={text:'文本',image:'文生图',vector:'向量'}
const category=(type:string)=>type==='image'?'image':['embedding','rerank'].includes(type)?'vector':'text'
const visibleOptions=computed(()=>options.value.filter(o=>!form.protocol_type||category(o.model_type)===form.protocol_type))
const blank=()=>({name:'',description:'',status:'enabled',protocol_type:'text' as string|null,logical_models:[] as string[]})
const form=reactive(blank())
async function load(){loading.value=true;error.value='';try{const d=(await api.get('/admin/model-groups',{params:{page:page.value,q:q.value,protocol_type:protocol.value}})).data.data;rows.value=d.items;total.value=d.total;options.value=(await api.get('/admin/logical-models')).data.data}catch(e){error.value=message(e)}finally{loading.value=false}}
function open(g?:ModelGroup){editing.value=g?.id??null;Object.assign(form,blank(),g?{name:g.name,description:g.description,status:g.status,protocol_type:g.protocol_type??null,logical_models:[...g.logical_models]}:{});dialog.value=true}
function move(from:number,to:number){if(to<0||to>=form.logical_models.length||from===to)return;const m=form.logical_models.splice(from,1)[0];if(m!==undefined)form.logical_models.splice(to,0,m)}
function startDrag(i:number,e:DragEvent){dragging.value=i;e.dataTransfer?.setData('text/plain',String(i))}
function drop(i:number){if(dragging.value!==null)move(dragging.value,i);dragging.value=null;dragTarget.value=null}
async function save(){if(saving.value)return;if(!form.name.trim()){ElMessage.error('请填写名称');return}form.name=form.name.trim();saving.value=true;try{if(editing.value)await api.put('/admin/model-groups/'+editing.value,form);else await api.post('/admin/model-groups',form);dialog.value=false;await load();ElMessage.success('模型组及顺序已保存')}catch(e){ElMessage.error(message(e))}finally{saving.value=false}}
async function remove(g:ModelGroup){try{await ElMessageBox.confirm('已授权给用户组的模型组不能删除，请先取消关联。','删除 '+g.name,{type:'warning',confirmButtonText:'删除',cancelButtonText:'取消'});await api.delete('/admin/model-groups/'+g.id);await load()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(message(e))}}
onMounted(load)
</script>
<template>
  <section class="panel group-page">
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="toolbar"><el-button type="primary" @click="open()">添加分组</el-button><el-select v-model="protocol" placeholder="全部类型" clearable style="width:160px" @change="page=1;load()"><el-option v-for="(label,value) in categoryLabels" :key="value" :label="label" :value="value"/></el-select><el-input v-model="q" clearable placeholder="搜索名称" style="width:240px" @keyup.enter="page=1;load()"/><el-button :loading="loading" @click="page=1;load()">刷新</el-button></div>
    <el-table :data="rows" v-loading="loading" empty-text="暂无模型组">
      <el-table-column prop="name" label="名称" min-width="180"/>
      <el-table-column label="协议类型" width="120"><template #default="s">{{categoryLabels[s.row.protocol_type]??'历史混合类型'}}</template></el-table-column>
      <el-table-column label="模型" min-width="300"><template #default="s"><div class="model-tags"><el-tag v-for="m in s.row.logical_models" :key="m" size="small">{{m}}</el-tag><span v-if="!s.row.logical_models.length" class="muted">-</span></div></template></el-table-column>
      <el-table-column prop="description" label="备注" min-width="180"/>
      <el-table-column label="创建时间" min-width="175"><template #default="s">{{s.row.created_at?formatDate(s.row.created_at):'-'}}</template></el-table-column>
      <el-table-column label="操作" width="130" fixed="right"><template #default="s"><el-button link type="primary" @click="open(s.row)">编辑</el-button><el-button link type="danger" @click="remove(s.row)">删除</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next" @current-change="load"/>
  </section>
  <el-drawer v-model="dialog" :title="editing?'编辑分组':'添加分组'" size="440px" class="model-group-drawer">
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="名称" required><el-input v-model="form.name" maxlength="80"/></el-form-item>
      <el-form-item label="协议类型" required><el-select v-model="form.protocol_type" style="width:100%"><el-option v-if="form.protocol_type===null" :value="null" label="历史混合类型"/><el-option v-for="(label,value) in categoryLabels" :key="value" :label="label" :value="value"/></el-select></el-form-item>
      <el-form-item label="模型"><el-select v-model="form.logical_models" multiple filterable allow-create default-first-option style="width:100%" placeholder="选择候选模型或输入新模型名"><el-option v-for="o in visibleOptions" :key="o.name" :value="o.name" :label="o.name"/></el-select></el-form-item>
      <ol v-if="form.logical_models.length" class="model-order"><li v-for="(m,i) in form.logical_models" :key="m" draggable="true" :class="{'drag-target':dragTarget===i,dragging:dragging===i}" @dragenter.prevent="dragTarget=i" @dragstart="startDrag(i,$event)" @dragover.prevent @drop.prevent="drop(i)" @dragend="dragging=null;dragTarget=null"><span class="order-handle" aria-hidden="true">⋮⋮</span><span class="order-name">{{m}}</span><div><el-button text size="small" :aria-label="'上移 '+m" :disabled="i===0" @click="move(i,i-1)">上移</el-button><el-button text size="small" :aria-label="'下移 '+m" :disabled="i===form.logical_models.length-1" @click="move(i,i+1)">下移</el-button></div></li></ol>
      <el-form-item label="备注"><el-input v-model="form.description" maxlength="2000"/></el-form-item>
      <el-form-item v-if="editing&&form.status!=='enabled'" label="历史状态"><el-select v-model="form.status"><el-option label="启用" value="enabled"/><el-option label="禁用" value="disabled"/></el-select></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="dialog=false">取消</el-button><el-button type="primary" :disabled="!form.name.trim()" :loading="saving" @click="save">保存</el-button></template>
  </el-drawer>
</template>
<style scoped>
.group-page{min-height:calc(100vh - 82px);margin:0}.toolbar{gap:12px}.model-tags{display:flex;flex-wrap:wrap;gap:6px}.el-pagination{margin-top:20px}.model-order{padding:0;margin:0 0 18px;list-style:none}.model-order li{display:flex;gap:10px;align-items:center;padding:10px;margin:6px 0;border:1px solid var(--line);border-radius:4px}.model-order li>div{margin-left:auto;flex-shrink:0}.order-name{overflow-wrap:anywhere;min-width:0}.order-handle{cursor:grab;color:var(--muted)}.model-order .drag-target{border-color:var(--el-color-primary);background:var(--el-color-primary-light-9)}.model-order .dragging{opacity:.5}
</style>
