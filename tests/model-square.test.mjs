import assert from 'node:assert/strict'
import {category,squareModels,filterModels,pageModels} from '../frontend/src/ui/modelSquare.ts'
const m=(name,type='text',configured=true,virtual=false)=>({logical_model:name,model_type:type,configured,virtual,position:0})
const groups=[{id:1,name:'研发',description:'',models:[m('shared', 'text', false),m('B-model'),m('auto','text',true,true)]},
  {id:2,name:'运营',description:'',models:[m('shared'),m('B-model'),m('hidden','text',false),m('中文向量','embedding'),m('picture','image')]}]
const models=squareModels(groups)
assert.equal(models.length,5)
assert.equal(models[0].logical_model,'auto')
assert.equal(models.filter(x=>x.logical_model==='shared').length,1)
assert.ok(!models.some(x=>x.logical_model==='hidden'))
assert.deepEqual(filterModels(models,'vector','中文').map(x=>x.logical_model),['中文向量'])
assert.deepEqual(filterModels(models,'all',' b-MODEL ').map(x=>x.logical_model),['B-model'])
assert.equal(filterModels(models,'image','B-model').length,0)
assert.equal(category('reasoning'),'text');assert.equal(category('rerank'),'rerank')
const ranked=[m('rank-model','rerank'),m('embedding-model','embedding')]
assert.deepEqual(filterModels(ranked,'rerank','').map(x=>x.logical_model),['rank-model'])
assert.deepEqual(filterModels(ranked,'vector','').map(x=>x.logical_model),['embedding-model'])
assert.equal(pageModels(models,99,2).page,3)
assert.equal(pageModels(models,99,2).items.length,1)
assert.deepEqual(pageModels([],99,20),{page:1,items:[]})
assert.equal(pageModels(models,-1,0).page,1)
assert.equal(groups[0].models.length,3)
console.log('Model square: availability, cross-group deduplication, categories, combined search and pagination passed.')
