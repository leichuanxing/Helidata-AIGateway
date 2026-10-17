import test from 'node:test'
import assert from 'node:assert/strict'
import {visibleWeightNodes,weightsForSave} from '../src/ui/modelGroupBalancing.ts'

test('remaining mapping still exposes shared supplier weight after first member is removed',()=>{
  const nodes=[{provider_id:1,logical_model:'a'},{provider_id:1,logical_model:'b'},{provider_id:2,logical_model:'b'}]
  assert.deepEqual(visibleWeightNodes(nodes,['b']),[nodes[1],nodes[2]])
  assert.deepEqual(weightsForSave({'1':4,'2':2,'3':9},nodes,['b'],true),{'1':4,'2':2})
})

test('failed or unfinished monitoring load never erases saved node weights',()=>{
  const weights={'1':4,'2':2}
  assert.deepEqual(weightsForSave(weights,[],['b'],false),weights)
  assert.deepEqual(weightsForSave(weights,[],['b'],true),{})
  assert.notEqual(weightsForSave(weights,[],['b'],false),weights)
})
