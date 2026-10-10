import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readAttachment,userContent,boundedMessages,byteLength,MAX_PAYLOAD_BYTES} from '../src/utils/chatAttachments.ts'
test('read images and PDF with matching signatures',async()=>{
 const png=await readAttachment(new File([new Uint8Array([137,80,78,71,13,10,26,10,1])],'a.png'),'1')
 assert.equal(png.kind,'image');assert.ok(png.data.startsWith('data:image/png;base64,'))
 const pdf=await readAttachment(new File(['%PDF-1.4 fixture'],'a.pdf'),'2')
 const parts=userContent('analyze',[png,pdf]);assert.equal(parts[1].type,'image_url');assert.equal(parts[2].file.filename,'a.pdf')
})
test('text files are UTF-8 content instead of binary files',async()=>{
 const item=await readAttachment(new File(['中文,测试\n1,2'],'a.csv'),'1')
 assert.equal(item.kind,'text');assert.equal(userContent('read',[item])[1].text,'附件：a.csv\n中文,测试\n1,2')
})
test('reject unsupported, disguised, oversized and invalid UTF-8 files',async()=>{
 for(const file of [new File(['svg'],'x.svg'),new File(['not png'],'x.png'),new File([new Uint8Array(1024*1024+1)],'large.pdf'),new File([new Uint8Array(64*1024+1)],'large.txt'),new File([new Uint8Array([255])],'bad.txt'),new File(['\u0000binary'],'bad.txt'),new File([''],'empty.txt')])await assert.rejects(readAttachment(file,'1'))
})
test('multimodal context preserves earlier attachments and trims oldest pairs by actual UTF-8 byte size',()=>{
 const image={id:'1',name:'a.png',size:100,kind:'image',data:'data:image/png;base64,'+'a'.repeat(900000)}
 const history=[{prompt:'old',answer:'old answer',attachments:[image]},{prompt:'recent',answer:'recent answer',attachments:[image]}]
 const result=boundedMessages('system',history,'now',[image],{model:'vision'})
 assert.equal(result.dropped,1);assert.equal(result.rounds,1);assert.ok(byteLength({model:'vision',messages:result.messages})<=MAX_PAYLOAD_BYTES)
 assert.equal(result.messages[1].content[0].text,'recent');assert.equal(result.messages[1].content[1].image_url.url,image.data)
})
test('too-large current message is rejected without silently discarding new files',()=>{
 assert.throws(()=>boundedMessages('',[],'hello',[{id:'1',name:'a.pdf',size:1,kind:'pdf',data:'x'.repeat(MAX_PAYLOAD_BYTES)}],{}),/超过/)
})
test('text conversation retains latest twenty successful rounds',()=>{
 const history=Array.from({length:21},(_,i)=>({prompt:String(i),answer:'a',attachments:[]}))
 const result=boundedMessages('',history,'new',[],{})
 assert.equal(result.dropped,1);assert.equal(result.messages[0].content,'1');assert.equal(result.messages.length,41)
})
