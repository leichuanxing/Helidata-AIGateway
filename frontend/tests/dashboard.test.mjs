import test from 'node:test'
import assert from 'node:assert/strict'
import {metric,rate,loadPercent,rankMetric} from '../src/ui/dashboard.ts'
import {timelineTooltip,unknownTokenMarkers} from '../src/ui/usageTimeline.ts'
test('dashboard metrics distinguish unknown, zero and no requests',()=>{
 assert.equal(metric(null),'—');assert.equal(metric(Number.NaN),'—');assert.equal(metric(0),'0')
 assert.equal(rate(0,0),'—');assert.equal(rate(0,10),'0%');assert.equal(rate(9,10),'90%')
 assert.equal(loadPercent(null,100),null);assert.equal(loadPercent(125,100),125)
})
test('rank labels preserve unknown and partially reported token usage',()=>{
 assert.equal(rankMetric({total_tokens:null,token_samples:0,requests:2}),'未上报 Token')
 assert.equal(rankMetric({total_tokens:0,token_samples:1,requests:1}),'0')
 assert.match(rankMetric({total_tokens:10,token_samples:1,requests:2}),/部分上报/)
})
test('dashboard rich text tooltips use real newlines for series and unknown markers',()=>{
 const row={bucket:'2026-10-22T00:00:00Z',requests:1,failure:1,total_tokens:null}
 const fields=[['total_tokens','总 Token']]
 const tip=timelineTooltip(row,fields,v=>v,undefined,'richText')
 assert.match(tip,/\n总 Token：未上报/);assert.doesNotMatch(tip,/<br/)
 const marker=unknownTokenMarkers([row],fields,v=>v,'richText')
 assert.equal(marker.data[0].tooltip.formatter(),tip)
})
