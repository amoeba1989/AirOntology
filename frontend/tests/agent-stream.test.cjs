const {test}=require('node:test');
const assert=require('node:assert/strict');
const esbuild=require('esbuild');
const vm=require('node:vm');
const path=require('node:path');

async function load() {
  const result=await esbuild.build({entryPoints:[path.join(__dirname,'../src/agent-stream.js')],bundle:true,write:false,format:'cjs'});
  const context={module:{exports:{}},TextDecoder,Uint8Array,Error,JSON};
  vm.runInNewContext(result.outputFiles[0].text,context);
  return context.module.exports.readAgentEvents;
}
function response(text) {
  const bytes=new TextEncoder().encode(text);let index=0;
  return {ok:true,body:{getReader:()=>({read:async()=>index<bytes.length?{value:bytes.slice(index,index+=1),done:false}:{done:true},cancel:async()=>{},releaseLock:()=>{}})}};
}
test('SSE中文跨字节、CRLF、分块结果卡片与完成标记',async()=>{
  const read=await load(),events=[];
  await read(response('event: candidate\r\ndata: {"name":"无人机一号","rank":1}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n'),(kind,data)=>events.push([kind,data]));
  assert.equal(events[0][1].name,'无人机一号');assert.equal(events[1][0],'done');
});
test('不完整流与HTTP错误可见，不伪装完整回答',async()=>{
  const read=await load();
  await assert.rejects(()=>read(response('event: candidate\ndata: {"rank":1}\n\n'),()=>{}),/提前结束/);
  await assert.rejects(()=>read({ok:false,status:429,json:async()=>({detail:'已有分析正在运行'})},()=>{}),/已有分析/);
});
