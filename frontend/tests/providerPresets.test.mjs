import test from 'node:test'
import assert from 'node:assert/strict'
import {accountPreset,categoryProtocols,adaptMappingTypes,syncSharedUrls,validServiceUrl,validProxyUrl} from '../src/ui/providerPresets.ts'

test('changing the main address updates shared routes but preserves independent addresses',()=>{
  const urls={chat:'https://old.example/v1',responses:'https://independent.example/v1'}
  syncSharedUrls(urls,'https://old.example/v1','https://new.example/v1')
  assert.equal(urls.chat,'https://new.example/v1');assert.equal(urls.responses,'https://independent.example/v1')
})

test('plan endpoint and protocol URL override vendor defaults',()=>{
  const type={base_url:'https://example.com/v1',protocol_urls:{'anthropic-messages':'https://example.com/anthropic/v1'},account_types:{coding:{base_url:'https://example.com/coding/v1',protocol_urls:{'anthropic-messages':'https://example.com/coding/anthropic/v1'}}}}
  assert.equal(accountPreset(type,'coding').base_url,'https://example.com/coding/v1')
  assert.equal(accountPreset(type,'coding').protocol_urls['anthropic-messages'],'https://example.com/coding/anthropic/v1')
})
test('native Ollama remains selectable and vector selects embeddings',()=>{
  const type={supported_protocols:['ollama','openai-completions','openai-embeddings']}
  assert.deepEqual(categoryProtocols(type,'standard','text'),['openai-completions','ollama'])
  assert.deepEqual(categoryProtocols(type,'standard','vector'),['openai-embeddings'])
  assert.deepEqual(categoryProtocols(type,'standard','image'),[])
})
test('unsupported Responses is not offered by chat-only presets',()=>{
  assert.deepEqual(categoryProtocols({supported_protocols:['openai-completions']},'standard','text'),['openai-completions'])
})
test('category changes keep names and status while adapting every mapping type',()=>{
  const rows=[{logical_model:'a',upstream_model:'b',model_type:'text',status:'enabled'}]
  for(const [category,expected] of [['multimodal','multimodal'],['image','image'],['vector','embedding'],['text','text']]){
    adaptMappingTypes(rows,category);assert.equal(rows[0].model_type,expected);assert.equal(rows[0].logical_model,'a');assert.equal(rows[0].status,'enabled')
  }
})
test('complete API base URLs reject endpoints and unsafe input',()=>{
  for(const value of ['https://example.com/v1','http://127.0.0.1:11434','https://example.com/api/coding/paas/v4'])assert.equal(validServiceUrl(value),true)
  for(const value of ['','ftp://example.com','https://user:secret@example.com','https://example.com?key=secret','https://example.com/v1/messages','https://example.com/v1/chat/completions','https://example.com/v1/responses','https://example.com/api/tags','https://example.com/a b'])assert.equal(validServiceUrl(value),false,value)
  assert.equal(validProxyUrl(''),true);assert.equal(validProxyUrl('http://proxy.example:8080'),true);assert.equal(validProxyUrl('http://proxy.example/path'),false)
})
