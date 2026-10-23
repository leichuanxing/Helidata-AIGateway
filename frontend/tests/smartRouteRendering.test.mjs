import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import * as Vue from 'vue'
import ts from 'typescript'
const require=createRequire(import.meta.url)
const vueRequire=createRequire(require.resolve('vue/package.json'))
const {parse}=vueRequire('@vue/compiler-sfc')
const {compile}=vueRequire('@vue/compiler-dom')
const {renderToString}=vueRequire('@vue/server-renderer')
const source=readFileSync(new URL('../src/views/SmartRoute.vue',import.meta.url),'utf8')
const template=parse(source).descriptor.template.content
const generated=compile(template,{mode:'function',prefixIdentifiers:true,expressionPlugins:['typescript']}).code
const code=ts.transpileModule(generated,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
const render=new Function('Vue',code)(Vue)

const base={auth:{user:{role:'super_admin'}},tabs:{configs:'路由规则'},configs:[],loading:false,error:'',dialog:false,previewDialog:false,previewLoading:false,sampleDialog:false,importDialog:false,detail:null,editing:null,configId:4,status:'',sampleClass:'',sampleQuery:'',logQuery:'',logTarget:'',logSource:'',logKind:'',logClass:'',logStatus:'',logOperation:'',logModel:'',requestId:'',virtual:'',days:7,range:null,page:1,total:0,selected:[],building:false,summary:{},statsRange:null,distribution:'classification',distributionRows:[],labels:{simple:'简单任务',complex:'复杂任务'},sources:{model:'模型决策'},targetNames:[],groupName:id=>'组'+id,score:v=>v==null?'未记录':(v*100).toFixed(1)+'%',formatDate:value=>value||'—',distributionName:name=>name,vectorState:()=>({label:'已就绪',tone:'success',hint:'可用'})}
async function markup(values){
 const ctx={...base,...values}
 const app=Vue.createSSRApp({render:()=>render(ctx,[])})
 const block=Vue.defineComponent({props:['label','title'],setup:(props, {slots})=>()=>Vue.h('div',[props.label||props.title,slots.default?.()])})
 for(const name of [...generated.matchAll(/resolveComponent\("([^" ]+)"\)/g)].map(m=>m[1]).filter(n=>!['el-dialog','el-drawer','el-table'].includes(n)))app.component(name,block)
 const closed=Vue.defineComponent({setup:()=>()=>null})
 app.component('el-dialog',closed)
 app.component('el-drawer',Vue.defineComponent({props:['modelValue'],setup:(props,{slots})=>()=>props.modelValue?Vue.h('section',slots.default?.()):null}))
 const flatten=nodes=>(nodes||[]).flatMap(n=>n.type===Vue.Fragment?flatten(n.children):[n])
 app.component('el-table',Vue.defineComponent({props:['data'],setup:(props,{slots})=>()=>Vue.h('table',(props.data||[]).map(row=>Vue.h('tr',flatten(slots.default?.()).filter(c=>c.props).map(c=>Vue.h('td',c.children?.default?c.children.default({row}):String(row[c.props.prop]??''))))))}))
 app.directive('loading',{})
 const html=await renderToString(app)
 assert.doesNotMatch(html,/<template(?:\s|>)/,'plain native template hides the page content')
 return html
}
test('rules render real table cells, both modes and empty-vector warning',async()=>{
 const rows=[{id:3,virtual_model:'heli-model',route_mode:'model',decision_targets:[{name:'代码'}],status:'enabled'},{id:4,virtual_model:'heli_auto',route_mode:'vector',sample_summary:{total:2,ready:0},status:'enabled'}]
 const html=await markup({view:'configs',rows,configs:rows})
 assert.match(html,/新增路由规则/);assert.match(html,/<td>heli-model<\/td>/);assert.match(html,/<td>heli_auto<\/td>/)
 assert.match(html,/模型决策/);assert.match(html,/本地 \/ 向量/);assert.match(html,/无就绪样本/)
})
test('statistics preserve custom model-decision target names',async()=>{
 const html=await markup({view:'statistics',rows:[{classification:'代码分析',status:'classified',requests:1,usage_count:0}]})
 assert.match(html,/代码分析/)
})
test('samples and logs remain visible after merged page rendering',async()=>{
 const sample=await markup({view:'samples',currentConfig:{route_mode:'vector'},rows:[{id:1,prompt:'样本文本可见',classification:'simple',vector_status:'ready'}]})
 assert.match(sample,/样本文本可见/);assert.match(sample,/已就绪/)
 const log=await markup({view:'logs',rows:[{id:1,request_id:'request-visible',decision_target:'代码分析',source:'model',status:'classified',confidence:.9,elapsed_ms:10}]})
 assert.match(log,/request-visible/);assert.match(log,/代码分析/)
})

test('each route editor displays its own vector or decision configuration',async()=>{
 const form={virtual_model:'独立规则',route_mode:'vector',decision_provider:'aliyun',decision_service_url:'https://decision.example/systemone',decision_targets:[],decision_api_key:'',clear_decision_key:false}
 const props={view:'configs',rows:[],dialog:true,editing:3,models:[{name:'embedding'}],groups:[],sharedVector:'embedding',form,modelTesting:false,modelTestResult:null}
 const vector=await markup({...props,editorMode:'vector'})
 assert.match(vector,/路由模式/);assert.match(vector,/Embedding模型/);assert.doesNotMatch(vector,/决策 API Key/)
 const model=await markup({...props,form:{...form,route_mode:'model'},editorMode:'model'})
 assert.match(model,/路由模式/);assert.match(model,/决策 API Key/);assert.match(model,/服务地址/);assert.doesNotMatch(model,/Embedding模型/)
})
test('an auxiliary options failure does not hide the loaded rules',async()=>{
 const start=source.indexOf('async function load()'),end=source.indexOf('function open(',start)
 const js=ts.transpileModule(source.slice(start,end),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText
 const rules=[{id:3,virtual_model:'visible-despite-options-error'}]
 const scope={generation:0,view:{value:'configs'},error:{value:''},loading:{value:false},sharedVector:{value:''},configs:{value:[]},configId:{value:null},rows:{value:[]},models:{value:[]},groups:{value:[]},message:()=> '辅助接口失败',api:{get:async path=>{
  if(path==='/admin/smart-route/configs')return {data:{data:rules,meta:{}}}
  if(path==='/admin/logical-models')throw new Error('options unavailable')
  return {data:{data:[]}}
 }}}
 await new Function('scope','with(scope){'+js+';return load;}')(scope)()
 assert.deepEqual(scope.rows.value,rules);assert.equal(scope.error.value,'辅助接口失败');assert.equal(scope.loading.value,false)
})
