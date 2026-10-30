const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const esbuild=require('esbuild');
const path=require('node:path');
const wait=()=>new Promise(r=>setTimeout(r,20));
async function until(fn){for(let i=0;i<80;i++){if(fn())return;await wait()}assert.ok(fn(),'界面未达到预期状态')}
test('独立本体页面切换模型、实例、类型对照，查询定位与错误反馈',async()=>{
  const bundle=await esbuild.build({entryPoints:[path.join(__dirname,'../src/main.js')],bundle:true,write:false,format:'iife',platform:'browser',loader:{'.css':'empty'},define:{'import.meta.env':'{}',__VUE_OPTIONS_API__:'true',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false','process.env.NODE_ENV':'"production"'}});
  const dom=new JSDOM('<div id="app"></div>',{url:'http://localhost/back',runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,d=w.document,errors=[];w.addEventListener('error',e=>errors.push(e.message));
  const cls='urn:test#BlueDevice',instance='urn:test#drone001';let fail=false;
  const fixture={terms:[{uri:cls,label:'无人机',kind:'class',domain:[],range:[],count:1,constraints:[]}],individuals:[{uri:instance,label:'一号无人机',kind:'individual',types:[cls]}],schema_edges:[],edges:[{source:instance,target:cls,kind:'type',label:'类型'}],triples:[],at:new Date().toISOString(),scope:'测试快照',schema_ttl:''};
  w.fetch=async(url)=>({ok:!fail,status:fail?503:200,json:async()=>url==='/api/ontology/topology'?fixture:url==='/api/learning/queries'?{items:[{id:'current',title:'当前目标'}]}:{variables:['target'],rows:[{target:{type:'uri',value:instance}}],sparql:'SELECT ?target WHERE {}'}});
  const button=text=>[...d.querySelectorAll('button')].find(x=>x.textContent.includes(text));
  try{
    w.eval(bundle.outputFiles[0].text);
    await until(()=>d.querySelectorAll('.ow-node').length===1);
    assert.match(d.querySelector('.ow-node').textContent,/OWL 类/);
    button('ABox 实例事实').click();await until(()=>d.querySelector('.ow-node').textContent.includes('一号无人机'));
    assert.equal(d.querySelectorAll('.ow-edge').length,0);
    button('模型 · 实例对照').click();await until(()=>d.querySelectorAll('.ow-node').length===2);
    assert.equal(d.querySelectorAll('.ow-edge.type').length,1);
    button('运行只读查询').click();await until(()=>button('定位对象'));button('定位对象').click();
    await until(()=>d.querySelector('.ow-details h2').textContent==='一号无人机');
    assert.match(d.querySelector('.ow-toolbar').textContent,/邻居视图/);
    fail=true;button('刷新事实').click();await until(()=>d.querySelector('[role="alert"]'));
    assert.match(d.querySelector('[role="alert"]').textContent,/503/);
    assert.deepEqual(errors,[]);
  }finally{w.close()}
});
