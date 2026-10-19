import test from 'node:test'
import assert from 'node:assert/strict'
import {mappingType,mappingAllowed,accountPreset,categoryProtocols,providerCategoryOptions,categoryBaseUrl,automaticConnection,adaptMappingTypes,syncSharedUrls,validServiceUrl,validProxyUrl} from '../src/ui/providerPresets.ts'

test('normal providers automatically select all supported category protocols and dedicated URLs',()=>{
  const type={base_url:'https://api.example/v1',supported_protocols:['openai-completions','openai-responses','anthropic-messages','openai-embeddings'],protocol_urls:{'openai-responses':'https://api.example','anthropic-messages':'https://api.example/anthropic/v1'}}
  const auto=automaticConnection(type,'standard','multimodal',type.base_url)
  assert.deepEqual(auto.selected,['openai-completions','openai-responses','anthropic-messages'])
  assert.equal(auto.urls['openai-responses'],'https://api.example');assert.equal(auto.separate,true)
  assert.equal(auto.routes['anthropic-messages'].auth_type,'x-api-key')
  assert.equal(automaticConnection(type,'standard','text',type.base_url+'/').urls['openai-responses'],'https://api.example')
  assert.deepEqual(automaticConnection(type,'standard','vector',type.base_url).selected,['openai-embeddings'])
})
test('plan constraints override automatic wire protocols',()=>{
  const type={base_url:'https://api.example/v1',supported_protocols:['openai-completions','openai-responses'],account_types:{plan:{base_url:'https://api.example/plan',supported_protocols:['openai-completions']}}}
  assert.deepEqual(automaticConnection(type,'plan','text','https://api.example/plan').selected,['openai-completions'])
})
test('customized server addresses never send traffic to official protocol addresses',()=>{
  const type={base_url:'https://official.example/v1',supported_protocols:['openai-completions','anthropic-messages'],protocol_urls:{'anthropic-messages':'https://official.example/anthropic/v1'}}
  const auto=automaticConnection(type,'standard','text','http://private.example/v1')
  assert.equal(auto.separate,false);assert.deepEqual(Object.values(auto.urls),['http://private.example/v1','http://private.example/v1'])
})

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

test('image category remains visible with accurate provider and plan support',()=>{
  const labels={text:'文本',image:'文生图',rerank:'重排序',mixed:'历史混合'}
  const vendor={supported_protocols:['openai-completions','openai-images'],account_types:{coding:{supported_protocols:['openai-completions']}}}
  assert.equal(providerCategoryOptions(vendor,'standard',labels).find(o=>o.value==='image').disabled,false)
  assert.equal(providerCategoryOptions(vendor,'coding',labels).find(o=>o.value==='image').disabled,true)
  assert.equal(providerCategoryOptions(vendor,'standard',labels).some(o=>o.value==='mixed'),false)
  assert.equal(providerCategoryOptions(undefined,'standard',labels).every(o=>o.disabled),true)
  assert.deepEqual(automaticConnection(vendor,'standard','image','https://example.com/v1').selected,['openai-images'])
  const rows=[{logical_model:'draw',upstream_model:'image-model',model_type:'text',status:'enabled'}]
  adaptMappingTypes(rows,'image');assert.equal(rows[0].model_type,'image')
})
test('category changes keep names and status while adapting every mapping type',()=>{
  const rows=[{logical_model:'a',upstream_model:'b',model_type:'text',status:'enabled'}]
  for(const [category,expected] of [['multimodal','multimodal'],['image','image'],['vector','embedding'],['text','text']]){
    adaptMappingTypes(rows,category);assert.equal(rows[0].model_type,expected);assert.equal(rows[0].logical_model,'a');assert.equal(rows[0].status,'enabled')
  }
})

test('reranking has a dedicated wire protocol and mapping type',()=>{
  const type={supported_protocols:['openai-completions','openai-embeddings','openai-rerank']}
  assert.deepEqual(categoryProtocols(type,'standard','rerank'),['openai-rerank'])
  assert.deepEqual(categoryProtocols({supported_protocols:['openai-completions']},'standard','rerank'),[])
  const rows=[{logical_model:'rank',upstream_model:'rank-upstream',model_type:'embedding',status:'enabled'}]
  adaptMappingTypes(rows,'rerank');assert.equal(rows[0].model_type,'rerank')
  adaptMappingTypes(rows,'vector');assert.equal(rows[0].model_type,'rerank') // Existing vector accounts remain compatible.
})

test('vendor category address and capability explanations follow the selected plan',()=>{
  const vendor={base_url:'https://vendor.example/compatible-mode/v1',supported_protocols:['openai-images','openai-rerank'],protocol_urls:{'openai-rerank':'https://vendor.example/api/v1'},category_notes:{image:'image models only',rerank:'native conversion'},account_types:{coding:{supported_protocols:['openai-completions'],category_notes:{image:'plan restricted'}}}}
  assert.equal(categoryBaseUrl(vendor,'standard','rerank'),'https://vendor.example/api/v1')
  assert.equal(categoryBaseUrl(vendor,'standard','image'),vendor.base_url)
  assert.equal(providerCategoryOptions(vendor,'coding',{image:'文生图'})[0].reason,'plan restricted')
  assert.equal(providerCategoryOptions(vendor,'standard',{image:'文生图'})[0].disabled,false)
  assert.equal(providerCategoryOptions(vendor,'coding',{image:'文生图'})[0].disabled,true)
})
test('complete API base URLs reject endpoints and unsafe input',()=>{
  for(const value of ['https://example.com/v1','http://127.0.0.1:11434','https://example.com/api/coding/paas/v4'])assert.equal(validServiceUrl(value),true)
  for(const value of ['','ftp://example.com','https://user:secret@example.com','https://example.com?key=secret','https://example.com/v1/messages','https://example.com/v1/chat/completions','https://example.com/v1/responses','https://example.com/api/tags','https://example.com/a b'])assert.equal(validServiceUrl(value),false,value)
  assert.equal(validProxyUrl(''),true);assert.equal(validProxyUrl('http://proxy.example:8080'),true);assert.equal(validProxyUrl('http://proxy.example/path'),false)
})

test('account editor and detail mapping editor agree on rerank and other categories',()=>{
  const kinds=['text','reasoning','multimodal','embedding','rerank','image']
  for(const [category,expected,defaultKind] of [['rerank',['rerank'],'rerank'],['multimodal',['multimodal'],'multimodal'],['image',['image'],'image'],['vector',['embedding','rerank'],'embedding'],['text',['text','reasoning','multimodal'],'text']]){
    assert.deepEqual(kinds.filter(kind=>mappingAllowed(category,kind)),expected)
    assert.equal(mappingType(category),defaultKind)
  }
  assert.deepEqual(kinds.filter(kind=>mappingAllowed(null,kind)),kinds)
})