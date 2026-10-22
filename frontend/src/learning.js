import { ref, computed, onMounted, watch } from 'vue/dist/vue.esm-bundler.js';

export default {
  props: ['request', 'data', 'mode', 'highlight', 'focusRow'],
  setup(props) {
    const page = ref('dictionary'), busy = ref(false), error = ref('');
    const terms = ref([]), search = ref(''), term = ref(null), termLoading = ref(false);
    const source = ref('business'), modelTTL = ref(''), preview = ref(null), previewText = ref('');
    const catalog = ref([]), queryId = ref('current'), queryTarget = ref(''), queryPosition = ref(''), result = ref(null);
    const examples = ref(null), sample = ref(''), report = ref(null), reportTab = ref('errors');
    let termToken = 0;
    const filtered = computed(() => terms.value.filter(t => `${t.label} ${t.id} ${t.kind}`.toLowerCase().includes(search.value.toLowerCase())));
    const querySpec = computed(() => catalog.value.find(q => q.id === queryId.value));
    const name = uri => terms.value.find(t => t.uri === uri)?.label || ({double:'双精度数值',string:'文本',dateTime:'日期时间'})[uri.split('#').pop()] || uri.split('#').pop();
    const short = value => value?.startsWith('http://counteruav.org/counterUav#') ? `cu:${value.split('#')[1]}` : value;
    watch(modelTTL, () => { preview.value = null; });
    watch(queryId, () => { result.value = null; props.highlight([]); });
    async function action(fn) {
      if (busy.value) return;
      busy.value = true; error.value = '';
      try { await fn(); } catch (e) { error.value = e.message; }
      finally { busy.value = false; }
    }
    async function selectTerm(uri) {
      const token = ++termToken;
      termLoading.value = true; error.value = '';
      try {
        const detail = await props.request(`/api/learning/term?uri=${encodeURIComponent(uri)}`);
        if (token === termToken) term.value = detail;
      } catch (e) { if (token === termToken) error.value = e.message; }
      finally { if (token === termToken) termLoading.value = false; }
    }
    async function loadDictionary() {
      const value = await props.request('/api/learning/dictionary');
      terms.value = value.items; source.value = value.source; modelTTL.value = value.ttl;
      search.value = ''; term.value = null;
      if (value.items.length) await selectTerm(value.items[0].uri);
    }
    const previewModel = () => action(async () => {
      preview.value = await props.request('/api/learning/model/preview', false, json(modelTTL.value));
      previewText.value = modelTTL.value;
    });
    const importModel = () => action(async () => {
      if (!preview.value || previewText.value !== modelTTL.value) throw new Error('请先校验当前模型文本');
      await props.request('/api/learning/model', false, { ...json(modelTTL.value), method: 'PUT' });
      await loadDictionary();
    });
    const resetModel = () => action(async () => {
      await props.request('/api/learning/model', false, { method: 'DELETE' });
      await loadDictionary();
    });
    function json(ttl) { return {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ttl})}; }
    async function readFile(event) {
      const file = event.target.files?.[0];
      if (!file) return;
      error.value = '';
      if (file.size > 32768) { error.value = '模型文件最多 32KB'; return; }
      modelTTL.value = await file.text();
    }
    function download(text, filename) {
      const url = URL.createObjectURL(new Blob([text], {type:'text/turtle;charset=utf-8'}));
      const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    const runQuery = () => action(async () => {
      result.value = null; props.highlight([]);
      result.value = await props.request('/api/learning/query', false, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({query_id:queryId.value, target_id:queryTarget.value || null, position_id:queryPosition.value || null}),
      });
      props.highlight(result.value.rows);
    });
    const validateSample = () => action(async () => {
      report.value = null;
      report.value = await props.request('/api/learning/validation', false, json(sample.value));
    });
    const validateCurrent = () => action(async () => {
      report.value = null;
      report.value = await props.request('/api/learning/validation/current', false, {method:'POST'});
    });
    function useExample(kind) { sample.value = examples.value[kind]; report.value = null; }
    watch(sample, () => { report.value = null; });
    watch(() => props.data, d => {
      if (!d?.targets.some(t => t.id === queryTarget.value)) queryTarget.value = d?.targets[0]?.id || '';
      if (!d?.positions.some(p => p.id === queryPosition.value)) queryPosition.value = d?.positions[0]?.id || '';
    }, { immediate:true });
    const initialize = () => action(async () => {
      const outcomes = await Promise.allSettled([
        loadDictionary(),
        props.request('/api/learning/queries').then(v => { catalog.value = v.items; }),
        props.request('/api/learning/validation/examples').then(v => { examples.value = v; sample.value = v.valid; }),
      ]);
      const failed = outcomes.find(r => r.status === 'rejected');
      if (failed) throw failed.reason;
    });
    onMounted(initialize);
    return {page,busy,error,terms,filtered,search,term,termLoading,source,modelTTL,preview,catalog,queryId,queryTarget,queryPosition,querySpec,result,examples,sample,report,reportTab,name,short,selectTerm,previewModel,importModel,resetModel,readFile,download,runQuery,validateSample,validateCurrent,useExample,initialize};
  },
  template: `
  <section id="learning-panel" class="panel learning-panel" aria-labelledby="learning-title">
    <div class="panel-heading learning-heading"><h2 id="learning-title"><span class="section-index">06</span>本体学习工作台</h2><div class="tabs" role="tablist" aria-label="本体学习功能"><button role="tab" :aria-selected="page==='dictionary'" :class="{active:page==='dictionary'}" @click="page='dictionary'">① 本体词典</button><button role="tab" :aria-selected="page==='query'" :class="{active:page==='query'}" @click="page='query'">② SPARQL 查询</button><button role="tab" :aria-selected="page==='validation'" :class="{active:page==='validation'}" @click="page='validation'">③ SHACL 校验</button></div></div>
    <div class="learning-intro">TBox（模型定义）规定术语，ABox（实例事实）记录业务；SPARQL 查询事实，SHACL 检查数据约束。距离由 Python 计算，未启用推理。</div>
    <p v-if="error" class="alert" role="alert">{{error}} <button @click="initialize" :disabled="busy">重新加载学习工作台</button></p>
    <div v-if="page==='dictionary'" class="learning-body">
      <p class="learning-note">当前词典：<b>{{source==='learning'?'独立学习模型':'业务模型'}}</b>。URI（资源标识）是对象的完整名字；cu: 是业务命名空间的缩写。</p>
      <div class="dictionary-layout"><aside class="term-list"><label>搜索中文名称或英文标识<input aria-label="搜索本体术语" v-model="search" placeholder="例如：阵地、Observation"></label><button v-for="t in filtered" :key="t.uri" :class="{active:term?.uri===t.uri}" @click="selectTerm(t.uri)"><b>{{t.label}}</b><span>{{t.kind}} · {{t.id}}</span></button><p v-if="!filtered.length">没有匹配术语</p></aside>
      <article class="term-detail" :aria-busy="termLoading"><p v-if="termLoading">正在读取术语与实例…</p><template v-else-if="term"><span class="tag">{{term.kind}}</span><h3>{{term.label}} <small>{{term.id}}</small></h3><code class="full-uri">{{term.uri}}</code><p>{{term.comment || '此术语尚未补充中文说明。'}}</p><dl><div><dt>定义域 domain（属性从哪类对象出发）</dt><dd><button v-for="uri in term.domain" @click="selectTerm(uri)">{{name(uri)}}</button><span v-if="!term.domain.length">未声明</span></dd></div><div><dt>值域 range（指向哪类对象或数据类型）</dt><dd><span v-for="uri in term.range">{{name(uri)}} · {{short(uri)}} </span><span v-if="!term.range.length">未声明</span></dd></div></dl>
      <p class="learning-note">OWL 定义域和值域用于表达语义；“必须填写几个值”等数据完整性要求请看 SHACL 校验。</p>
      <div v-if="term.relations.length"><h4>模型中的关联</h4><p v-for="r in term.relations"><span>{{r.direction}}：</span><button @click="selectTerm(r.uri)">{{r.label}}</button> → {{r.other.join('、') || '未声明'}}</p></div>
      <h4>对应 TTL（Turtle 文本）</h4><pre><code>{{term.ttl}}</code></pre><p class="learning-note">a 表示“属于某类”；rdfs:label 是名称，@zh 表示中文；分号连接同一主语的属性，句号结束一组描述。</p>
      <h4>对应 ABox 实例 · {{term.count}} 条匹配，最多显示 20 条</h4><p class="learning-note">{{term.scope}}</p><div class="table-scroll"><table><thead><tr><th>主语（哪个对象）</th><th>谓语（什么关系）</th><th>宾语（对象或值）</th></tr></thead><tbody><tr v-for="e in term.examples"><td><button @click="focusRow({target:{value:e.subject}})">{{short(e.subject)}}</button></td><td>{{short(e.predicate)}}</td><td>{{short(e.object)}}</td></tr></tbody></table></div><p v-if="!term.examples.length">当前范围暂无实例；新增的学习类也需要实例事实才会产生结果。</p></template></article></div>
      <details class="learning-editor"><summary>用 Protégé 练习：导出、编辑、校验并导入学习模型</summary><p>下载模型后可在 Protégé（本体编辑工具）中编辑，另存为 Turtle，再选择文件并校验。导入只替换独立学习模型，不改业务 TBox 或距离规则；模型保存在 Fuseki，重启后仍保留。</p><div class="learning-actions"><button @click="download(modelTTL,'airontology-learning-model.ttl')">下载当前模型 TTL</button><label>选择 TTL 文件<input type="file" accept=".ttl,text/turtle" @change="readFile"></label></div><textarea aria-label="学习模型 TTL" v-model="modelTTL" maxlength="32768" rows="10" spellcheck="false"></textarea><div class="learning-actions"><button @click="previewModel" :disabled="busy">校验模型语法与术语</button><button @click="importModel" :disabled="busy||!preview">导入独立学习模型</button><button @click="resetModel" :disabled="busy||source!=='learning'">清除学习模型，恢复业务词典</button><span v-if="preview">校验通过：{{preview.items.length}} 个术语，{{preview.triple_count}} 条三元组</span></div><p class="learning-note">此处是 Turtle 语法和术语基本检查，不等同于 OWL 逻辑一致性验证。最多 32KB / 3000 条三元组，不加载外部 imports。</p></details>
    </div>
    <div v-else-if="page==='query'" class="learning-body">
      <p class="learning-note"><b>查询实时业务图，不随历史回放切换。</b>地图高亮使用页面当前显示的对象；历史查询坐标仅显示在表格，不将历史位置画成当前位置。</p><div class="learning-actions"><label>中文问题<select aria-label="选择查询问题" v-model="queryId"><option v-for="q in catalog" :value="q.id">{{q.title}}</option></select></label><label v-if="querySpec?.parameters.includes('target_id')">无人机<select aria-label="查询无人机" v-model="queryTarget"><option v-for="t in data?.targets" :value="t.id">{{t.name}}</option></select></label><label v-if="querySpec?.parameters.includes('position_id')">阵地<select aria-label="查询阵地" v-model="queryPosition"><option v-for="p in data?.positions" :value="p.id">{{p.name}}</option></select></label><button @click="runQuery" :disabled="busy||!catalog.length">{{busy?'正在查询…':'运行只读查询'}}</button><button @click="highlight([])">清除地图高亮</button></div><p>{{querySpec?.concept}}</p><p class="learning-note">{{querySpec?.note}}</p>
      <template v-if="result"><h3>实际执行的 SPARQL</h3><pre><code>{{result.sparql}}</code></pre><p>{{result.rows.length}} 行 · {{result.executed_at}} · 点击结果行定位页面中的对象，蓝色外框表示查询命中。</p><div class="table-scroll query-results"><table><thead><tr><th v-for="v in result.variables">{{({target:'无人机',position:'阵地',assessment:'评估',observation:'观测',rule:'规则',time:'时间',lon:'经度',lat:'纬度',distance:'距离 / 米',graph:'命名图',triples:'三元组数',name:'名称'})[v] || v}} <code>?{{v}}</code></th></tr></thead><tbody><tr v-for="(row,i) in result.rows" :key="i" @click="focusRow(row)"><td v-for="v in result.variables"><button class="query-cell" :title="row[v]?.value || ''" @click.stop="focusRow(row)">{{short(row[v]?.value) || '—'}}</button></td></tr></tbody></table></div><p v-if="!result.rows.length">没有符合条件的事实；检查是否有观测、数据是否过期，以及所选阵地与阈值。</p></template>
    </div>
    <div v-else class="learning-body">
      <p>Pydantic（接口输入校验）检查进入 API 的数据；SHACL（形状约束语言）检查 RDF 图中的对象、属性和数量约束。这里使用固定约束，不启用推理。</p><div class="learning-actions"><button @click="validateCurrent" :disabled="busy">校验当前实时 RDF</button><button @click="useExample('valid')" :disabled="!examples||busy">载入正常样例</button><button @click="useExample('invalid')" :disabled="!examples||busy">载入异常样例</button></div><p class="learning-note">实时校验：最多 100 架无人机的最新观测与评估，加上规则和当前阵地。样例校验不会写入业务库。</p><label>可编辑 RDF 样例（Turtle）<textarea aria-label="待校验 RDF 样例" v-model="sample" maxlength="32768" rows="9" spellcheck="false"></textarea></label><div class="learning-actions"><button @click="validateSample" :disabled="busy||!sample">{{busy?'正在处理…':'校验编辑器样例'}}</button><span>异常样例：缺时间、经度非数值、评估关联两个阵地。</span></div>
      <div v-if="report" class="validation-report" :class="{invalid:!report.conforms}" role="status"><h3>{{report.conforms?'校验通过':'发现数据约束问题'}} · {{report.result_count}} 条问题</h3><p>{{report.scope}} · {{report.triple_count}} 条三元组 · {{report.focus_count}} 个受检对象</p><p>{{report.note}}</p><div class="learning-actions"><button @click="reportTab='errors'">中文校验报告</button><button @click="reportTab='ttl'">报告 RDF / TTL</button><button @click="download(report.report_ttl,'shacl-report.ttl')">下载校验报告</button></div><pre v-if="reportTab==='ttl'"><code>{{report.report_ttl}}</code></pre><div v-else class="table-scroll"><table><thead><tr><th>对象 URI</th><th>属性</th><th>中文问题</th><th>约束位置</th></tr></thead><tbody><tr v-for="(r,i) in report.results" :key="i"><td>{{short(r.focus)}}</td><td>{{short(r.path)}}</td><td>{{r.message}}</td><td :title="r.constraint">{{short(r.shape)}}</td></tr></tbody></table><p v-if="!report.result_count">本次检查未发现违反已定义约束的数据。</p></div></div>
      <details v-if="examples" class="learning-editor"><summary>查看 SHACL 约束 TTL</summary><p>sh:targetClass 指定受检类；sh:path 指定属性；sh:minCount / maxCount 规定数量；sh:datatype 规定类型；sh:message 提供中文说明。</p><pre><code>{{examples.shapes}}</code></pre></details>
    </div>
  </section>`
};
