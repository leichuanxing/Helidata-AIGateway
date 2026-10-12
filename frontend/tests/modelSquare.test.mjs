import test from 'node:test'
import assert from 'node:assert/strict'
import {category,filterModels,squareModels} from '../src/ui/modelSquare.ts'
test('model square preserves multimodal type and filters independently from text',()=>{
 const models=squareModels([{id:0,name:'all',description:'',models:[{logical_model:'vision',model_type:'multimodal',position:0,configured:true,virtual:false},{logical_model:'chat',model_type:'text',position:1,configured:true,virtual:false},{logical_model:'vector',model_type:'embedding',position:2,configured:true,virtual:false}]}])
 assert.equal(category('multimodal'),'multimodal')
 assert.deepEqual(filterModels(models,'multimodal','').map(m=>m.logical_model),['vision'])
 assert.deepEqual(filterModels(models,'text','').map(m=>m.logical_model),['chat'])
 assert.equal(filterModels(models,'all','').length,3)
 assert.deepEqual(filterModels(models,'multimodal','VISION').map(m=>m.logical_model),['vision'])
})
