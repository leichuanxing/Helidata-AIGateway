import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createApp} from 'vue'
import * as elementPlus from 'element-plus'

test('production component registration includes working radio group and radio buttons',()=>{
 const source=readFileSync(new URL('../src/main.ts',import.meta.url),'utf8')
 const registrations=source.match(/for\(const component of \[(.*?)\]\)app.use\(component\)/s)
 assert.ok(registrations,'production component registration list exists')
 const app=createApp({render:()=>null})
 for(const name of registrations[1].split(',').map(s=>s.trim())){
  assert.ok(elementPlus[name],name)
  app.use(elementPlus[name])
 }
 assert.ok(app.component('ElRadioGroup'),'route-mode radio group is registered, not emitted as an unknown HTML tag')
 assert.ok(app.component('ElRadioButton'),'route-mode radio button is registered')
})
