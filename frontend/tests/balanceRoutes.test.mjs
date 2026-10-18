import test from 'node:test'
import assert from 'node:assert/strict'
import {blankBalanceRoute,routePayload,matchesBalanceType,balanceStrategies} from '../src/ui/balanceRoutes.ts'
test('independent route supports five strategies and strips readonly metrics on save',()=>{
  assert.equal(Object.keys(balanceStrategies).length,5)
  const form={...blankBalanceRoute(),config_version:4,nodes:[{mapping_id:5,weight:3,priority:1,max_concurrency:2,status:'enabled',health_status:'healthy',current_concurrency:9,provider_name:'secret-metadata'}]}
  const body=routePayload(form,true)
  assert.equal(body.expected_config_version,4);assert.equal(body.config_version,undefined)
  assert.deepEqual(body.nodes,[{mapping_id:5,weight:3,priority:1,max_concurrency:2,status:'enabled'}])
  assert.equal(routePayload(form,false).expected_config_version,undefined)
})
test('multimodal, vector and image nodes cannot be silently mixed',()=>{
  assert.equal(matchesBalanceType('text','reasoning'),true)
  assert.equal(matchesBalanceType('multimodal','text'),false)
  assert.equal(matchesBalanceType('embedding','rerank'),false)
  assert.equal(matchesBalanceType('image','image'),true)
})
