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
  win.fetch = async (url, opts = {}) => {
    let json;
    if (url === '/api/learning/dictionary') json = {items:[termItem],source:learningSource,ttl:'cu:Observation a owl:Class .'};
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
    assert.equal(doc.querySelectorAll(".position-icon").length, 2);
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
    assert.deepEqual(errors, []);
  } finally {
    dom.window.close();
  }
});
