import test from 'node:test'
import assert from 'node:assert/strict'
import {concurrencyLabel} from '../src/ui/groupLimits.ts'
test('inherited concurrency is bounded, not unlimited',()=>{
  assert.equal(concurrencyLabel(0,500,'网关'),'继承网关：500')
  assert.equal(concurrencyLabel(0,20,'用户组'),'继承用户组：20')
  assert.equal(concurrencyLabel(5,5,'用户组'),'配置 5 · 有效 5')
  assert.equal(concurrencyLabel(1000,500,'网关'),'配置 1000 · 有效 500')
  assert.equal(concurrencyLabel(0,undefined,'网关'),'继承网关：未知')
})
