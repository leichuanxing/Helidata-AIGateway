import test from 'node:test'
import assert from 'node:assert/strict'
import {missingTokenRows,usageGapNote,timelineTooltip,unknownTokenMarkers} from '../src/ui/usageTimeline.ts'
const fields=[['total_tokens','总 Token'],['input_tokens','输入']]
const date=x=>x
const rows=[
  {bucket:'2026-10-19T23:00:00+08:00',requests:46,failure:26,total_tokens:727,input_tokens:536,usage_unavailable:26},
  {bucket:'2026-10-20T00:00:00+08:00',requests:2,failure:2,total_tokens:null,input_tokens:null,usage_unavailable:2},
  {bucket:'2026-10-20T01:00:00+08:00',requests:0,failure:0,total_tokens:0,input_tokens:0},
  {bucket:'2026-10-20T02:00:00+08:00',requests:1,failure:0,total_tokens:0,input_tokens:0}
]
test('cross-midnight unknown usage is marked without changing null or genuine zero',()=>{
  assert.deepEqual(missingTokenRows(rows),[rows[1]])
  assert.match(usageGapNote(rows),/1 个时段.*2 次请求.*取消 2 次/)
  const markers=unknownTokenMarkers(rows,fields,date)
  assert.equal(markers.data.length,1);assert.equal(markers.data[0].xAxis,rows[1].bucket)
  assert.match(markers.data[0].tooltip.formatter(),/未上报（未知）/)
  assert.equal(rows[1].total_tokens,null);assert.equal(rows[3].total_tokens,0)
})
test('tooltips distinguish partial reporting, unknown, no requests and reported zero',()=>{
  assert.match(timelineTooltip(rows[0],fields,date),/仅累计已上报部分/)
  assert.match(timelineTooltip(rows[1],fields,date),/不代表 0/)
  assert.match(timelineTooltip(rows[2],fields,date),/没有推理请求/)
  assert.match(timelineTooltip(rows[3],fields,date),/总 Token：0/)
  assert.equal(usageGapNote([rows[2],rows[3]]),'')
})
test('tooltip escapes text from display values',()=>{
  assert.doesNotMatch(timelineTooltip(rows[0],[['total_tokens','<img>']],()=>'<script>'),/<script>|<img>/)
})
