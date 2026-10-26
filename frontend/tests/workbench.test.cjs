const { test } = require("node:test");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const esbuild = require("esbuild");
const path = require("node:path");

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(check) {
  for (let i = 0; i < 60; i++) {
    if (check()) return;
    await wait(25);
  }
  assert.ok(check(), "界面未在规定时间达到预期状态");
}

test("多目标地图、独立评估、TTL、回放与配置保存", async () => {
  const bundle = await esbuild.build({
    entryPoints: [path.join(__dirname, "../src/main.js")],
    bundle: true,
    write: false,
    format: "iife",
    platform: "browser",
    loader: { ".css": "empty" },
    define: {
      "import.meta.env": "{}",
      __VUE_OPTIONS_API__: "true",
      __VUE_PROD_DEVTOOLS__: "false",
      __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
      "process.env.NODE_ENV": '"production"',
    },
  });
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="app"></div></body></html>',
    {
      url: "http://localhost",
      runScripts: "outside-only",
      pretendToBeVisual: true,
    },
  );
  const win = dom.window,
    doc = win.document,
    errors = [];
  win.SVGSVGElement.prototype.createSVGRect = () => ({});
  win.AbortSignal.timeout = () => undefined;
  win.TextDecoder = TextDecoder;
  win.addEventListener("error", (e) =>
    errors.push(e.error?.stack || e.message),
  );
  const positions = [
    { id: "pos001", name: "一号阵地", lon: 116.4077, lat: 39.9045 },
    { id: "pos002", name: "二号阵地", lon: 116.412, lat: 39.9045 },
  ];
  const at = new Date(Date.now() - 10000).toISOString();
  let evaluations = [];
  const targets = Array.from({ length: 3 }, (_, i) => {
    const id = `drone00${i + 1}`;
    const assessments = positions.map((p, j) => ({
      id: "eval-" + String(i * 2 + j).padStart(24, "0"),
      target_id: id,
      target_name: `无人机00${i + 1}`,
      position_id: p.id,
      position_name: p.name,
      position_lon: p.lon,
      position_lat: p.lat,
      distance: 80 + i * 40 + j * 220,
      level: j ? "OutsideThreshold" : "HighAttention",
      level_label: j ? "阈值外" : "高关注",
      color: j ? "#5aab87" : "#e45555",
      reason: "距离80米≤100米",
      timestamp: at,
      observation_id: `obs-${i}`,
      source: "测试模拟器",
      data_mode: 'simulated',
      rule_version: "rule-test",
      thresholds: [100, 200, 300],
      stale_seconds: 5,
      observation: {
        lon: 116.408,
        lat: 39.9045,
        speed: 2,
        timestamp: at,
        source: "测试模拟器",
      },
    }));
    evaluations.push(...assessments);
    return {
      id,
      name: `无人机00${i + 1}`,
      lon: 116.408 + i * 0.001,
      lat: 39.9045,
      speed: 2,
      timestamp: at,
      source: "测试模拟器",
      stale: false,
      data_mode: 'simulated',
      assessments,
    };
  });
  const situation = {
    at,
    mode: "live",
    positions,
    targets,
    assessments: evaluations,
    thresholds: [100, 200, 300],
  };
  const history = {
    records: [
      { timestamp: at, lon: 116.408, lat: 39.9045 },
      {
        timestamp: new Date(Date.parse(at) + 1000).toISOString(),
        lon: 116.409,
        lat: 39.9045,
      },
    ],
  };
  const config = {
    version: "rule-test",
    config: {
      positions,
      high_threshold: 100,
      medium_threshold: 200,
      low_threshold: 300,
      stale_seconds: 5,
      history_limit: 300,
    },
  };
  let saved;
  const termURI = 'http://counteruav.org/counterUav#Observation';
  const termItem = {uri:termURI,id:'Observation',kind:'类',label:'观测记录',domain:[],range:[]};
  let learningSource = 'business';
  const queryCalls = [];
  let evidenceLoaded=false;
  const evidenceCalls=[];
  const evidenceData={devices:[{id:'radar',name:'模拟雷达',sensor_kind:'radar',data_mode:'simulated',reported_status:'normal',effective_status:'normal',effective_coverage:'unknown',status_fresh:true,reported_at:at,source:'模拟器',observation_note:'已有观测；身份未知'}],observations:[{id:'raw-positive',device_name:'模拟雷达',data_mode:'simulated',outcome:'detected',quality:'usable',fresh:true,usable_positive:true,mode_consistent:true,crs:'WGS84',lon:116.408,lat:39.9045,raw_evidence_ref:'urn:demo:positive',observed_at:at,received_at:at},{id:'raw-negative',device_name:'模拟红外',data_mode:'simulated',outcome:'not_detected',quality:'usable',fresh:true,usable_positive:false,mode_consistent:true,crs:'WGS84',lon:116.408,lat:39.9045,raw_evidence_ref:'urn:demo:negative',observed_at:at,received_at:at}],judgements:[{id:'j1',layer:'association',layer_label:'观测关联',current_status:'suspected',current_label:'疑似',status:'suspected',target_ref:'hypothesis',data_mode:'simulated',observation_ids:['raw-positive'],judgement_ids:[],method_name:'手工演示',method_version:'v1',source:'operator',conditions:'占位记录',uncertainty:'未验证',independence_note:'未知',gaps:['未实现融合算法']},{id:'j2',layer:'intrusion',layer_label:'异常闯入条件',current_status:'pending',current_label:'待核实',status:'pending',target_ref:'hypothesis',data_mode:'simulated',observation_ids:['raw-positive'],judgement_ids:[],region_id:'region1',authorization_status:'unknown',conditions:'待验证',uncertainty:'未知',gaps:['授权未知不能判为未授权']}],regions:[],authorizations:[]};

  const deviceData={positions,frame:{payload:{tick:6,sim_time_s:12}},topic:'counteruav/demo/telemetry',devices:[
    {id:'radar001',name:'雷达001',kind:'radar',kind_label:'雷达',deployed_at:'pos001',position:positions[0],parameters:{enabled:true},status_label:'当前帧已上报',in_latest_frame:true,stale:false,state_tick:'6',state:{transform:{longitude_deg:116.407,latitude_deg:39.904},faction:{side:1}}},
    {id:'jammer001',name:'干扰器001',kind:'jammer',kind_label:'干扰器',deployed_at:'pos001',position:positions[0],parameters:{enabled:true},status_label:'当前帧已上报',in_latest_frame:true,stale:false,state_tick:'6',state:{transform:{longitude_deg:116.406,latitude_deg:39.904},jammer:{enabled:true,emitting:false}}}
  ]};
  win.fetch = async (url, opts = {}) => {
    let json;
    if (url === '/api/devices') json=deviceData;
    else if(url.startsWith('/api/devices/deployments'))json={sparql:'SELECT ?device WHERE { ?device cu:deployedAt ?position }',rows:[{name:{value:'雷达001'},positionName:{value:'一号阵地'}}]};
    else if(url === '/api/devices/validate')json={conforms:true,focus_count:6,results:[]};
    else if (url === '/api/evidence') json=evidenceLoaded?evidenceData:{devices:[],observations:[],judgements:[],regions:[],authorizations:[]};
    else if(url === '/api/evidence/demo'){evidenceLoaded=true;json={status:'saved'};}
    else if(url === '/api/evidence/examples')json={devices:{id:'sample-radar',data_mode:'simulated'}};
    else if(url === '/api/evidence/devices'){evidenceCalls.push(opts);json={status:'saved'};}
    else if(url === '/api/evidence/validate')json={conforms:true,focus_count:12,result_count:0,results:[],report_ttl:'sh:ValidationReport'};
    else if (url === '/api/agent/questions') json = {items:[{id:'attention',label:'哪些无人机最需关注？'},{id:'nearest',label:'哪些无人机距离阵地最近？'}],llm_configured:false};
    else if (url === '/api/agent/ask') {
      const messages=[['snapshot',{position:positions[0],policy:{label:'距离关注排序策略 V1',description:'等级 → 时间 → 距离'},at,eligible:3,excluded:[],ttl:'cu:test a cu:SituationAnalysis .'}],
        ['candidate',{rank:1,target_id:'drone002',name:'无人机002',level_label:'高关注',distance:80,eta_seconds:0,reason:'距离80米',timestamp:at}],
        ['candidate',{rank:2,target_id:'drone003',name:'无人机003',level_label:'中关注',distance:120,eta_seconds:null,reason:'距离120米',timestamp:at}],
        ['explanation',{source:'rule',text:'这是规则说明，不是大模型回答。'}],['done',{}]];
      const bytes=new TextEncoder().encode(messages.map(([type,data])=>`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join(''));let i=0;
      return {ok:true,body:{getReader:()=>({read:async()=>i<bytes.length?{done:false,value:bytes.slice(i,i+=17)}:{done:true},cancel:async()=>{},releaseLock:()=>{}})}};
    }
    else if (url === '/api/learning/dictionary') json = {items:[termItem],source:learningSource,ttl:'cu:Observation a owl:Class .'};
    else if (url.startsWith('/api/learning/term?')) json = {...termItem,comment:'某时刻上报的位置',ttl:'cu:Observation a owl:Class .',relations:[],examples:[],count:0,scope:'当前最新事实'};
    else if (url === '/api/learning/model/preview') json = {items:[termItem],triple_count:2};
    else if (url === '/api/learning/model') { learningSource = opts.method === 'DELETE' ? 'business' : 'learning'; json = {status:'ok'}; }
    else if (url === '/api/learning/queries') json = {items:[{id:'current',title:'当前有哪些无人机？',concept:'SELECT 选择列',parameters:[],note:'当前状态图'},{id:'evidence',title:'评估依据是什么？',concept:'跨图关联',parameters:['target_id'],note:'最新评估依据'}]};
    else if (url === '/api/learning/query') {
      queryCalls.push(JSON.parse(opts.body));
      json = {sparql:'SELECT ?target WHERE { GRAPH <state> { ?target a cu:BlueDevice }} LIMIT 100',variables:['target'],rows:[{target:{type:'uri',value:'http://counteruav.org/counterUav#drone002'}}],executed_at:at};
    }
    else if (url === '/api/learning/validation/examples') json = {valid:'valid RDF sample',invalid:'invalid RDF sample',shapes:'sh:minCount 1'};
    else if (url.startsWith('/api/learning/validation')) {
      const bad = opts.body && JSON.parse(opts.body).ttl === 'invalid RDF sample';
      json = {conforms:!bad,result_count:bad?1:0,focus_count:5,triple_count:30,scope:'受检事实',note:'显式约束',report_ttl:'sh:ValidationReport',results:bad?[{focus:'cu:obs-test',path:'cu:timestamp',message:'观测必须有且仅有一个合法时间',shape:'cu:Observation_timestampShape'}]:[]};
    }
    else if (url === "/api/health")
      json = { fuseki: true, mqtt: { connected: true } };
    else if (url === "/api/ontology")
      json = { items: [{ kind: "类", id: "Assessment", label: "评估记录" }] };
    else if (url.startsWith("/api/assessments/"))
      json = evaluations.find((e) => url.endsWith(e.id));
    else if (url.startsWith("/api/history")) json = history;
    else if (url === "/api/config") {
      if (opts.method === "PUT") {
        saved = JSON.parse(opts.body);
        json = { ...saved, version: "rule-new" };
      } else json = config;
    } else
      json = { ...situation, mode: url.includes("?at=") ? "replay" : "live" };
    return {
      ok: true,
      json: async () => JSON.parse(JSON.stringify(json)),
      text: async () =>
        url === "/api/ontology/ttl"
          ? "cu:Assessment a owl:Class ."
          : "cu:drone001 cu:latestAssessment cu:eval-123 .",
    };
  };
  function button(text) {
    return [...doc.querySelectorAll("button")].find(
      (b) => b.textContent.trim() === text,
    );
  }
  try {
    win.eval(bundle.outputFiles[0].text);
    await until(() => doc.querySelectorAll(".drone-icon").length === 3);
    assert.ok([...doc.querySelectorAll('.drone-icon img')].every(img=>img.getAttribute('src')==='/icons/uav.png'));
    assert.equal(doc.querySelectorAll('.screen-objects .rail-target').length,3);
    assert.equal(doc.querySelectorAll('.screen-objects .rail-group').length,2);
    assert.equal(doc.querySelector('.rail-position-symbol img').getAttribute('src'),'/icons/position.png');
    assert.equal(doc.querySelector('.rail-aircraft img').getAttribute('src'),'/icons/uav.png');
    assert.ok(doc.querySelector('.screen-insights').textContent.includes('模拟 MQTT'));
    assert.ok(doc.querySelector('.screen-insights').textContent.includes('无人机不隶属于阵地'));
    assert.equal(doc.querySelector('.screen-objects .rail-group .rail-target'),null);
    assert.ok(doc.querySelector('.live-observation-line').textContent.includes('已观测'));
    doc.querySelectorAll('.screen-objects .rail-target')[1].click();
    await until(() => doc.querySelector('.focus-card h3')?.textContent === '无人机002');
    doc.querySelectorAll('.screen-objects .rail-target')[0].click();
    await until(() => doc.querySelector('.focus-card h3')?.textContent === '无人机001');
    assert.equal(doc.querySelectorAll(".position-icon").length, 2);
    assert.ok([...doc.querySelectorAll('.position-icon img')].every(img=>img.getAttribute('src')==='/icons/position.png'));
    assert.equal(doc.querySelectorAll(".ranking-panel tbody tr").length, 3);
    const selector = doc.querySelector('[aria-label="选择阵地"]');
    selector.value = "pos002";
    selector.dispatchEvent(new win.Event("change", { bubbles: true }));
    await until(() =>
      doc.querySelector(".ranking-panel h2").textContent.includes("二号阵地"),
    );
    button("查看评估").click();
    await until(() =>
      doc.querySelector(".trace-note").textContent.includes("已锁定"),
    );
    assert.ok(
      doc.querySelector(".explanation-panel").textContent.includes("rule-test"),
    );
    assert.equal(doc.querySelectorAll(".alarm-card").length, 3);
    assert.ok(doc.querySelector(".alarm-panel.urgent"));
    button("ABox · 实例与关系").click();
    await until(() => doc.querySelectorAll(".abox-grid article").length === 5);
    assert.equal(doc.querySelectorAll(".abox-table tbody tr").length, 6);
    assert.ok(doc.querySelector(".abox-view").textContent.includes("rule-test"));
    button("TBox · 类与属性定义").click();
    await until(() => doc.querySelector(".structure-grid"));
    assert.equal(doc.querySelector(".abox-view"), null);
    button("TBox 定义 TTL").click();
    await until(() =>
      doc.querySelector("pre")?.textContent.includes("owl:Class"),
    );
    button("选中实例 TTL").click();
    await until(() =>
      doc.querySelector("pre")?.textContent.includes("latestAssessment"),
    );
    button("加载选中目标历史").click();
    await until(() =>
      doc.querySelector(".mode-label").textContent.includes("历史快照"),
    );
    assert.ok(button("阵地与规则配置").disabled);
    button("播放回放").click();
    await wait(700);
    assert.ok(doc.querySelector(".frame-label").textContent.includes("2 / 2"));
    button("返回实时").click();
    await until(
      () => doc.querySelector(".mode-label").textContent === "实时态势",
    );
    button("阵地与规则配置").click();
    await until(() => doc.querySelector('[role="dialog"]'));
    assert.equal(doc.querySelectorAll(".config-position").length, 2);
    button("＋ 添加阵地（最多10处）").click();
    await until(() => doc.querySelectorAll(".config-position").length === 3);
    doc
      .querySelector("form")
      .dispatchEvent(
        new win.Event("submit", { bubbles: true, cancelable: true }),
      );
    await until(() => saved);
    assert.equal(saved.expected_version, "rule-test");
    assert.equal(saved.config.positions.length, 3);
    await until(() => doc.querySelector('.term-detail h3')?.textContent.includes('观测记录'));
    const search = doc.querySelector('[aria-label="搜索本体术语"]');
    search.value = '不存在'; search.dispatchEvent(new win.Event('input',{bubbles:true}));
    await until(() => doc.querySelector('.term-list').textContent.includes('没有匹配术语'));
    search.value = ''; search.dispatchEvent(new win.Event('input',{bubbles:true}));
    button('校验模型语法与术语').click();
    await until(() => !button('导入独立学习模型').disabled);
    button('导入独立学习模型').click();
    await until(() => doc.querySelector('.learning-note').textContent.includes('独立学习模型'));
    button('清除学习模型，恢复业务词典').click();
    await until(() => doc.querySelector('.learning-note').textContent.includes('业务模型'));
    button('② SPARQL 查询').click();
    await until(() => button('运行只读查询'));
    button('运行只读查询').click();
    await until(() => doc.querySelectorAll('.query-match').length === 1);
    assert.equal(doc.querySelector('.query-results tbody').textContent.trim(),'cu:drone002');
    assert.ok(doc.querySelector('.learning-body pre').textContent.includes('SELECT ?target'));
    button('cu:drone002').click();
    await until(() => doc.querySelector('[aria-label="选择无人机"]').value === 'drone002');
    const question = doc.querySelector('[aria-label="选择查询问题"]');
    question.value = 'evidence'; question.dispatchEvent(new win.Event('change',{bubbles:true}));
    await until(() => doc.querySelector('[aria-label="查询无人机"]'));
    button('运行只读查询').click();
    await until(() => queryCalls.length === 2);
    assert.equal(queryCalls[1].target_id,'drone001');
    button('③ SHACL 校验').click();
    await until(() => button('载入异常样例'));
    button('载入异常样例').click();
    await until(() => doc.querySelector('[aria-label="待校验 RDF 样例"]').value === 'invalid RDF sample');
    button('校验编辑器样例').click();
    await until(() => doc.querySelector('.validation-report.invalid'));
    assert.ok(doc.querySelector('.validation-report').textContent.includes('观测必须有且仅有一个合法时间'));
    button('报告 RDF / TTL').click();
    await until(() => doc.querySelector('.validation-report pre')?.textContent.includes('ValidationReport'));
    button('载入正常样例').click();
    await until(() => !doc.querySelector('.validation-report'));
    button('校验编辑器样例').click();
    await until(() => doc.querySelector('.validation-report h3')?.textContent.includes('校验通过'));
    button('态势大屏').click();
    await until(() => doc.querySelector('.workspace.screen'));
    assert.equal(doc.querySelector('.agent-dialog'),null);
    doc.querySelector('[aria-label="打开智能态势问答"]').click();
    await until(() => button('哪些无人机最需关注？ ↗'));
    button('哪些无人机最需关注？ ↗').click();
    await until(() => doc.querySelectorAll('.agent-candidate').length===2);
    await until(() => doc.querySelector('.agent-explanation')?.textContent.includes('确定性规则说明'));
    doc.querySelector('[aria-label="定位第1名 无人机002"]').click();
    await until(() => doc.querySelector('[aria-label="选择无人机"]').value==='drone002');
    doc.querySelector('[aria-label="定位第2名 无人机003"]').click();
    await until(() => doc.querySelector('[aria-label="选择无人机"]').value==='drone003');
    button('查看本次本体事实与排序策略').click();
    await until(() => doc.querySelector('.agent-evidence pre')?.textContent.includes('SituationAnalysis'));
    doc.querySelector('[aria-label="收起智能问答"]').click();
    await until(() => doc.querySelector('.agent-orb'));
    button('多源观测与证据').click();
    await until(()=>doc.querySelector('#evidence-panel')?.textContent.includes('尚无设备'));
    button('导入模拟示例').click();
    await until(()=>doc.querySelector('#evidence-panel')?.textContent.includes('raw-positive'));
    assert.equal([...doc.querySelectorAll('#evidence-panel button')].filter(b=>b.textContent==='定位原始观测').length,1,'未检出观测不能作为目标定位');
    button('定位原始观测').click();
    await until(()=>doc.querySelector('.leaflet-interactive'));
    button('③ 异常闯入条件').click();
    await until(()=>doc.querySelector('.evidence-card')?.textContent.includes('授权未知不能判为未授权'));
    assert.ok(!doc.querySelector('.evidence-card').textContent.includes('raw-negative'));
    button('SHACL 结构校验').click();
    await until(()=>doc.querySelector('.evidence-report')?.textContent.includes('12 个校验对象'));
    button('载入可编辑示例').click();
    await until(()=>doc.querySelector('[aria-label="证据 JSON 数据"]').value.includes('sample-radar'));
    button('登记当前记录').click();
    await until(()=>evidenceCalls.length===1);
    assert.equal(evidenceCalls[0].headers['Content-Type'],'application/json');
    assert.equal(JSON.parse(evidenceCalls[0].body).data_mode,'simulated');
    await until(()=>doc.querySelectorAll('.equipment-icon').length===2);
    assert.equal(doc.querySelector('.equipment-icon.radar img').getAttribute('src'),'/icons/radar.png');
    assert.equal(doc.querySelector('.equipment-icon.jammer img').getAttribute('src'),'/icons/jammer.png');
    button('设备与阵地关系').click();
    await until(()=>doc.querySelector('.device-detail')?.textContent.includes('雷达001'));
    assert.ok(doc.querySelector('.device-detail').textContent.includes('未提供。初始配置不能证明当前工作正常'));
    const deviceFilter=doc.querySelector('[aria-label="筛选设备类型"]');
    deviceFilter.value='jammer';deviceFilter.dispatchEvent(new win.Event('change',{bubbles:true}));
    await until(()=>doc.querySelector('.device-detail')?.textContent.includes('干扰器001'));
    assert.ok(doc.querySelector('.device-detail').textContent.includes('是 / 否'));
    button('本体字段映射').click();
    await until(()=>doc.querySelector('.device-detail').textContent.includes('cu:Jammer'));
    button('来源 MQTT JSON').click();
    await until(()=>doc.querySelector('.device-detail pre')?.textContent.includes('"emitting": false'));
    button('执行部署关系 SPARQL').click();
    await until(()=>doc.querySelector('.device-query').textContent.includes('查询到 1 条'));
    button('校验设备与关系').click();
    await until(()=>doc.querySelector('.device-validation')?.textContent.includes('结构通过'));
    doc.querySelector('.equipment-icon.radar').click();
    await until(()=>doc.querySelector('.device-detail')?.textContent.includes('雷达001'));
    assert.deepEqual(errors, []);
  } finally {
    dom.window.close();
  }
});
