import test from 'node:test'
import assert from 'node:assert/strict'
import {imageTestPayload,generatedImages} from '../src/utils/imagePlayground.ts'
test('image requests contain no chat parameters and require per-request consent',()=>{
 assert.deepEqual(imageTestPayload('image',' blue sky ',1,'',true),{model:'image',prompt:'blue sky',n:1,consent:true})
 for(const args of [['m','p',1,'',false],['m',' ',1,'',true],['m','p',0,'',true],['m','p',1,'javascript:',true]])assert.throws(()=>imageTestPayload(...args))
})
test('image results support safe remote URLs and raster Base64',()=>{
 assert.equal(generatedImages({data:[{url:'https://images.example/a.png?expires=1'}]})[0].remote,true)
 const image=generatedImages({data:[{b64_json:Buffer.from('\x89PNG\r\n\x1a\n','latin1').toString('base64')}]})[0]
 assert.ok(image.src.startsWith('data:image/png;base64,'));assert.equal(image.remote,false)
})
test('untrusted image results cannot inject scripts or SVG',()=>{
 for(const row of [{url:'javascript:alert(1)'},{url:'data:image/svg+xml,<svg/>'},{url:'https://u:p@example.com/a'},{b64_json:Buffer.from('<svg/>').toString('base64')},{b64_json:'***'}])assert.throws(()=>generatedImages({data:[row]}))
 assert.throws(()=>generatedImages({data:[]}));assert.throws(()=>generatedImages({data:Array(5).fill({url:'https://example.com/a'})}))
})
