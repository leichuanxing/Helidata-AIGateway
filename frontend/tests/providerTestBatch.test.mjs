import test from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {once} from 'node:events'
import {runProviderTests} from '../src/ui/providerTestBatch.ts'

test('aborting an in-flight real HTTP batch never calls later models',async()=>{
  const calls=[];let seen
  const started=new Promise(resolve=>seen=resolve)
  const server=createServer((request,response)=>{calls.push(request.url);seen()})
  server.listen(0,'127.0.0.1');await once(server,'listening')
  try{
    const controller=new AbortController()
    const pending=runProviderTests(['first','second'],controller.signal,async(name,signal)=>{
      const response=await fetch(`http://127.0.0.1:${server.address().port}/${name}`,{signal});return response.json()
    },()=>assert.fail('aborted result must not be published'))
    const rejected=assert.rejects(pending,error=>error.name==='AbortError')
    await started;controller.abort();await rejected
    assert.deepEqual(calls,['/first'])
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
})

test('stop between results and stale configuration prevent additional HTTP calls',async()=>{
  const calls=[];let code=null
  const server=createServer((request,response)=>{calls.push(request.url);response.end(JSON.stringify([{error_code:code}]))})
  server.listen(0,'127.0.0.1');await once(server,'listening')
  try{
    const request=async(name,signal)=>(await fetch(`http://127.0.0.1:${server.address().port}/${name}`,{signal})).json()
    let controller=new AbortController();const results=[]
    await runProviderTests(['one','two'],controller.signal,request,rows=>{results.push(...rows);controller.abort()})
    assert.equal(results.length,1);assert.deepEqual(calls,['/one'])
    for(code of ['PROVIDER_CHANGED','ADMIN_TEST_FORBIDDEN']){
      calls.length=0;controller=new AbortController()
      await runProviderTests(['one','two'],controller.signal,request,()=>{})
      assert.deepEqual(calls,['/one'])
    }
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
})
