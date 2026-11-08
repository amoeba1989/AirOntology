const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const esbuild=require('esbuild');
const path=require('node:path');
const wait=()=>new Promise(r=>setTimeout(r,20));
async function until(fn){for(let i=0;i<80;i++){if(fn())return;await wait()}assert.ok(fn(),'未达到预期界面状态')}
test('规则草稿试运行、发布冲突、版本、迁移的对象配置',async()=>{
 const bundle=await esbuild.build({entryPoints:[path.join(__dirname,'../src/main.js')],bundle:true,write:false,format:'iife',platform:'browser',loader:{'.css':'empty'},define:{'import.meta.env':'{}',__VUE_OPTIONS_API__:'true',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false','process.env.NODE_ENV':'"production"'}});
 const dom=new JSDOM('<div id="app"></div>',{url:'http://localhost/rules',runScripts:'outside-only',pretendToBeVisual:true});const w=dom.window,d=w.document;w.structuredClone=structuredClone;
 const errors=[];w.addEventListener('error',e=>errors.push(e.message));
 let published,trial,saved,conflict=false;
 const data={revision:0,rules:[],versions:[],events:[],results:[],engine_enabled:true,config:{version:'old',config:{positions:[{id:'pos001',name:'甲阵地',lon:116.4,lat:39.9}],high_threshold:100,medium_threshold:200,low_threshold:300,stale_seconds:30,history_limit:300}}};
 w.fetch=async(url,options={})=>{let result=data,status=200;const body=options.body&&JSON.parse(options.body);
  if(url==='/api/health')result={version:'2.5.0'};
  else if(url==='/api/rules/trial'){trial=body;result={at:new Date().toISOString(),results:[{rule_name:'观测过期',entity_id:'u1',status:'matched',reason:'距最后上报40秒'}]};}
  else if(url==='/api/rules'&&options.method==='PUT'){published=body;if(conflict){status=409;result={detail:'规则已被更新'};}else{data.revision++;data.rules=body.rules;result={...data};}}
  else if(url==='/api/config'){saved=body;result={version:'new',config:body.config};}
  return {ok:status===200,status,json:async()=>structuredClone(result)};
 };
 const button=text=>[...d.querySelectorAll('button')].find(b=>b.textContent.includes(text));
 function input(el,value){el.value=value;el.dispatchEvent(new w.Event('input',{bubbles:true}));}
 try{
  w.eval(bundle.outputFiles[0].text);await until(()=>button('＋ 观测过期'));
  assert.match(d.querySelector('.app-version').textContent,/v2.5.0/);
  button('＋ 观测过期').click();await until(()=>d.querySelector('.rules-check input'));
  assert.equal(d.querySelector('.rules-check input').checked,false);
  d.querySelector('.rules-check input').click();button('试运行草稿').click();await until(()=>trial);
  assert.equal(trial.rules[0].enabled,true);assert.equal(published,undefined);
  await until(()=>d.querySelector('.rules-trial')?.textContent.includes('距最后上报40秒'));
  input(d.querySelector('input[placeholder="例如：增加雷达上报中断提醒"]'),'首次发布');await wait();button('发布全部草稿').click();await until(()=>published);
  assert.equal(published.expected_revision,0);await until(()=>d.querySelector('.rules-runtime').textContent.includes('发布版本 1'));
  conflict=true;input(d.querySelector('input[placeholder="例如：增加雷达上报中断提醒"]'),'第二次');await wait();button('发布全部草稿').click();await until(()=>d.querySelector('[role="alert"]'));
  assert.match(d.querySelector('[role="alert"]').textContent,/规则已被更新/);assert.equal(d.querySelector('.rules-editor input').value,'观测过期');
  button('对象与距离配置').click();await until(()=>d.querySelector('.rules-position'));
  button('＋ 添加阵地').click();await until(()=>d.querySelectorAll('.rules-position').length===2);
  d.querySelector('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await until(()=>saved);
  assert.equal(saved.expected_version,'old');assert.equal(saved.config.positions.length,2);
  assert.deepEqual(errors,[]);
 } finally {dom.window.close()}
});
