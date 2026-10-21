import test from 'node:test'
import assert from 'node:assert/strict'
import {historyId,historyPayload} from '../src/utils/chatHistory.ts'
const turn={prompt:'hello',answer:'reply',reasoning:'thought',status:'done',error:'',requestId:'req_1',compliance:'pass',elapsed:10,rounds:0,finish:'stop',usage:{prompt_tokens:2,total_tokens:4,secret:'never'},attachments:[{id:'a',name:'private.txt',kind:'text',size:10,data:'sensitive bytes'}],images:[{src:'data:image/png;base64,xxx',remote:false},{src:'https://example.invalid/image.png',remote:true}]}
test('history snapshots strip binary files and unrecognized usage and keep ordinary text',()=>{
 const body=historyPayload('model','multimodal',{},[turn,{...turn,status:'pending'}]);assert.equal(body.turns.length,1)
 assert.deepEqual(body.turns[0].attachments,[{name:'private.txt',kind:'text',size:10}]);assert.deepEqual(body.turns[0].images,['https://example.invalid/image.png'])
 assert.doesNotMatch(JSON.stringify(body),/sensitive bytes|never|base64/);assert.equal(body.turns[0].answer,'reply');assert.equal(body.turns[0].usage.total_tokens,4)
})
test('history bounds completed rounds without mutating current conversation',()=>{
 const turns=Array.from({length:120},(_,i)=>({...turn,prompt:String(i)}));const body=historyPayload('m','text',{},turns)
 assert.equal(body.turns.length,100);assert.equal(body.turns[0].prompt,'20');assert.equal(turns.length,120)
 const large=historyPayload('m','text',{},Array.from({length:8},()=>({...turn,answer:'大'.repeat(400000)})))
 assert.ok(new TextEncoder().encode(JSON.stringify(large)).length<=4*1024*1024)
})
test('conversation IDs work on plain HTTP without crypto.randomUUID',()=>{assert.match(historyId(),/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);assert.notEqual(historyId(),historyId())})
