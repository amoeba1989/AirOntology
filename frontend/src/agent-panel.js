import { ref, computed, nextTick, onUnmounted } from 'vue/dist/vue.esm-bundler.js';
import { readAgentEvents } from './agent-stream.js';

export default {
  props: ['request', 'data', 'point', 'mode', 'locateCandidate', 'returnLive'],
  setup(props) {
    const open = ref(false), questions = ref([]), snapshot = ref(null), cards = ref([]);
    const busy = ref(false), error = ref(''), notice = ref(''), explanation = ref(''), explanationSource = ref('');
    const evidenceOpen = ref(false), configured = ref(false), selectedQuestion = ref('');
    const citationAudit = ref(null);
    const selectedEvidence = ref('');
    const loadingQuestions = ref(false);
    let controller, requestId = 0;
    async function toggle() {
      if (open.value) { open.value = false; return; }
      open.value = true;
      loadingQuestions.value = true;
      error.value = '';
      try {
        const value = await props.request('/api/agent/questions');
        questions.value = value.items; configured.value = value.llm_configured;
      } catch (e) { error.value = e.message; }
      finally { loadingQuestions.value = false; }
    }
    function stop() {
      requestId++; controller?.abort(); busy.value = false;
      notice.value = '已停止接收；已收到的结果仍对应当时快照。';
    }
    async function ask(question) {
      if (busy.value || !props.point) return;
      const token = ++requestId;
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 65000);
      snapshot.value = null; cards.value = []; explanation.value = ''; explanationSource.value = '';
      error.value = ''; notice.value = ''; evidenceOpen.value = false; citationAudit.value = null; selectedEvidence.value = '';
      selectedQuestion.value = question.label; busy.value = true;
      try {
        if (props.mode !== 'live') await props.returnLive();
        const response = await fetch('/api/agent/ask', {method:'POST',
          headers:{'Content-Type':'application/json'}, signal:controller.signal,
          body:JSON.stringify({question_id:question.id,position_id:props.point.id,limit:10})});
        await readAgentEvents(response, (type, value) => {
          if (token !== requestId) return;
          if (type === 'snapshot') snapshot.value = value;
          if (type === 'candidate') cards.value.push(value);
          if (type === 'notice') notice.value = value.message;
          if (type === 'explanation') { explanation.value += value.text; explanationSource.value = value.source; }
          if (type === 'explanation_audit') citationAudit.value = value;
          if (type === 'explanation_error') error.value = value.message;
        });
      } catch (e) {
        if (token === requestId) error.value = e.name === 'AbortError' ? '回答已停止或超时，请重新提问。' : e.message;
      } finally {
        clearTimeout(timeout);
        if (token === requestId) busy.value = false;
      }
    }
    onUnmounted(() => { requestId++; controller?.abort(); });
    const explanationParts = computed(() => explanation.value.split(/(\[E\d+\])/g).map(text => ({
      text, id: /^\[(E\d+)\]$/.exec(text)?.[1] || '',
    })));
    function hasEvidence(id) { return !!id && !!snapshot.value?.evidence?.some(row => row.id === id); }
    async function showEvidence(id) {
      evidenceOpen.value = true;
      selectedEvidence.value = id;
      await nextTick();
      document.getElementById('agent-evidence-' + id)?.scrollIntoView?.({block:'nearest'});
    }
    function compactTerm(value) {
      return value.replace(/^<http:\/\/counteruav\.org\/counterUav#([^>]+)>$/, 'cu:$1')
        .replace(/^<http:\/\/www\.w3\.org\/1999\/02\/22-rdf-syntax-ns#([^>]+)>$/, 'rdf:$1')
        .replace(/^<http:\/\/www\.w3\.org\/2000\/01\/rdf-schema#([^>]+)>$/, 'rdfs:$1')
        .replace(/\^\^<http:\/\/www\.w3\.org\/2001\/XMLSchema#([^>]+)>$/, '^^xsd:$1');
    }
    const format = value => value == null ? '未知' : value.toFixed(1);
    const time = value => value ? new Date(value).toLocaleTimeString('zh-CN',{hour12:false}) : '—';
    return {open,questions,snapshot,cards,busy,error,notice,explanation,explanationSource,evidenceOpen,configured,selectedQuestion,loadingQuestions,citationAudit,explanationParts,selectedEvidence,hasEvidence,showEvidence,compactTerm,toggle,stop,ask,format,time};
  },
  template: `
  <button v-if="!open" class="agent-orb" aria-label="打开智能态势问答" @click="toggle"><b>AI</b><span>态势问答</span></button>
  <section v-else class="agent-dialog" role="dialog" aria-label="智能态势问答" @keydown.esc="open=false">
    <div class="agent-title"><div class="agent-title-copy"><span class="agent-kicker"><i aria-hidden="true"></i> SITUATION INTELLIGENCE</span><b>智能态势问答</b><small>本体事实 · 策略排序 · 地图联动</small></div><button aria-label="收起智能问答" @click="open=false">收起 ×</button></div>
    <div class="agent-content">
      <div class="agent-context"><span>所选阵地：{{point?.name || '等待阵地'}}</span><span>{{configured?'DeepSeek 解读已配置':'规则演示模式'}}</span></div>
      <p class="agent-boundary">根据所选阵地的观测、评估与本体规则生成结果，DeepSeek 结合相关三元组解释并引用证据编号。</p>
      <p v-if="mode!=='live'" class="agent-notice">点击问题会先返回实时态势，再使用当前观测生成回答。</p>
      <div class="agent-questions"><button v-for="q in questions" :key="q.id" @click="ask(q)" :disabled="busy||!point">{{q.label}} ↗</button></div>
      <p v-if="loadingQuestions" class="agent-notice">正在加载预设问题…</p>
      <p v-else-if="!questions.length&&!error" class="agent-notice">暂时没有可用的预设问题。</p>
      <p v-if="!data?.targets.some(t=>!t.stale)" class="agent-notice">当前没有新观测，仍可提问；结果会列出未参与排序的对象与原因。</p>
      <div v-if="selectedQuestion" class="agent-question">{{selectedQuestion}}</div>
      <div v-if="snapshot" class="agent-snapshot"><b>{{snapshot.position.name}} · {{snapshot.policy.label}}</b><span>{{time(snapshot.at)}} 固定快照 · {{snapshot.eligible}} 架匹配 · {{snapshot.excluded.length}} 架无有效评估{{snapshot.filtered_out?' · '+snapshot.filtered_out+' 架不符合筛选':''}}</span><span>依据：{{snapshot.policy.description}}</span><button @click="evidenceOpen=!evidenceOpen">{{evidenceOpen?'收起本体证据':'查看模型使用的本体证据'}}</button></div>
      <div class="agent-candidates"><button v-for="c in cards" :key="c.target_id" class="agent-candidate" :aria-label="'定位第'+c.rank+'名 '+c.name" @click="locateCandidate(c,snapshot)"><span class="candidate-rank">{{c.rank}}</span><div><b>第 {{c.rank}} 名 · {{c.name}}</b><span :style="{color:c.color}">{{snapshot?.question_id==='nearest'?'距离 '+format(c.distance)+' 米':c.level_label+' · '+format(c.distance)+' 米'}}</span><small v-if="snapshot?.question_id==='attention'">观测起算进入高关注圈：{{c.eta_seconds===0?'该次观测已在圈内':c.eta_seconds==null?'未知':format(c.eta_seconds)+' 秒（估计）'}}</small><small>{{({simulated:"模拟数据",operational:"业务接入声明（未验证）"})[c.data_mode]||"来源待核实"}} · {{snapshot?.question_id==='nearest'?'按距离升序排列':c.reason}}</small><small>观测 {{time(c.timestamp)}}<template v-if="snapshot?.question_id==='attention'"> · {{c.trend_note}}</template></small><span class="candidate-link">定位地图 · 查看对象 ↗</span></div></button></div>
      <details v-if="snapshot?.excluded.length" class="agent-excluded"><summary>哪些对象未参与排序？</summary><p v-for="e in snapshot.excluded">{{e.target_id}}：{{e.reason}}</p></details>
      <div v-if="explanation" class="agent-explanation"><b>{{explanationSource==='deepseek'?'DeepSeek 本体证据解读':'确定性规则说明'}}</b><p><template v-for="(part,index) in explanationParts" :key="index"><button v-if="hasEvidence(part.id)" class="agent-reference" :aria-label="'查看证据 '+part.id" @click="showEvidence(part.id)">{{part.text}}</button><template v-else>{{part.text}}</template></template></p><small v-if="explanationSource==='deepseek'">名次和数值以结果卡片为准。<template v-if="citationAudit"> {{!citationAudit.has_citations?'回答未引用证据编号。':citationAudit.unknown.length?'存在未知引用：'+citationAudit.unknown.join('、'):'点击引用编号查看三元组。'}} 编号检查不验证文字含义。</template></small></div>
      <p v-if="notice" class="agent-notice">{{notice}}</p><p v-if="error" class="agent-error" role="alert">{{error}}</p>
      <p v-if="busy" class="agent-progress">正在接收分析结果… <button @click="stop">停止</button></p>
      <div v-if="evidenceOpen&&snapshot" class="agent-evidence"><h3>本次相关三元组 · {{snapshot.evidence?.length || 0}} 条</h3><p>{{configured&&snapshot.eligible?'模型请求使用下列三元组及本次计算结果。':'以下三元组是本次证据；没有进行模型解读。'}} 显示时缩写常用命名空间。</p><ol class="agent-triples"><li v-for="e in snapshot.evidence" :id="'agent-evidence-'+e.id" :key="e.id" :class="{selected:e.id===selectedEvidence}"><b>[{{e.id}}] {{e.origin}}</b><code>{{compactTerm(e.subject)}} {{compactTerm(e.predicate)}} {{compactTerm(e.object)}} .</code></li></ol><details><summary>查看完整 RDF 快照（Turtle）</summary><pre><code>{{snapshot.ttl}}</code></pre></details></div>
      <p class="agent-footnote">结果按提问时刻固定；点击卡片定位该对象当前可用位置。新观测到达后，可再次提问刷新结果。</p>
    </div>
  </section>`
};
