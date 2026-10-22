import test from 'node:test'
import assert from 'node:assert/strict'
import {settingsPayload,acceptSaved,copy} from '../src/ui/settingsDraft.ts'
const initial=()=>({revision:1,basic:{system_name:'gateway',logo:'/api/public/settings/assets/logo?v=1',icon:'',system_url:'',public_api_base_url:'/v1',language:'zh-CN',timezone:'UTC'},gateway:{max_concurrency:10,protocol_conversion:true},logging:{redaction_rules:['old'],retention_days:30},vector:{provider_id:1,model:'embed'},governance:{smart_route_enabled:true,compliance_enabled:true,semantic_threshold:null},elasticsearch:{enabled:false,secret:'',secret_configured:true}})
test('settings pages only submit current fields and retain asset references',()=>{
 const form=initial()
 assert.equal(settingsPayload(form,'old','brand').basic.logo,undefined)
 assert.equal(settingsPayload(form,'old','brand').basic.icon,'')
 assert.deepEqual(settingsPayload(form,'old','performance'),{gateway:{max_concurrency:10}})
 assert.deepEqual(settingsPayload(form,'old','smart'),{governance:{smart_route_enabled:true}})
 assert.deepEqual(settingsPayload(form,'old','audit'),{})
})
test('settings save preserves later edits and other tab drafts',()=>{
 const form=initial(),baseline=copy(form);form.gateway.max_concurrency=20
 const sent=settingsPayload(form,'old','performance');form.gateway.max_concurrency=30;form.basic.system_name='later name'
 const saved=initial();saved.revision=2;saved.gateway.max_concurrency=20
 acceptSaved(form,baseline,sent,saved)
 assert.equal(form.gateway.max_concurrency,30);assert.equal(baseline.gateway.max_concurrency,20)
 assert.equal(form.basic.system_name,'later name');assert.equal(form.revision,2)
})
test('Elasticsearch save clears submitted secret but preserves a newer secret draft',()=>{
 for(const later of [false,true]){
  const form=initial(),baseline=copy(form);form.elasticsearch.secret='sent-fixture'
  const sent=settingsPayload(form,'old','elasticsearch')
  if(later)form.elasticsearch.secret='newer-fixture'
  const saved=initial();saved.revision=2
  acceptSaved(form,baseline,sent,saved)
  assert.equal(form.elasticsearch.secret,later?'newer-fixture':'')
  assert.equal(form.elasticsearch.secret_configured,true)
 }
})
