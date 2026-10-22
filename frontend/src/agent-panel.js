import { ref, onUnmounted } from 'vue/dist/vue.esm-bundler.js';
import { readAgentEvents } from './agent-stream.js';

export default {
  props: ['request', 'data', 'point', 'mode', 'locateCandidate'],
  setup(props) {
    const open = ref(false), questions = ref([]), snapshot = ref(null), cards = ref([]);
    const busy = ref(false), error = ref(''), notice = ref(''), explanation = ref(''), explanationSource = ref('');
    const evidenceOpen = ref(false), configured = ref(false), selectedQuestion = ref('');
    let controller, requestId = 0;
    async function toggle() {
      if (open.value) { open.value = false; return; }
      open.value = true;
      try {
        const value = await props.request('/api/agent/questions');
        questions.value = value.items; configured.value = value.llm_configured;
      } catch (e) { error.value = e.message; }
    }
    function stop() {
      requestId++; controller?.abort(); busy.value = false;
      notice.value = '已停止接收；已收到的结果仍对应当时快照。';
    }
    async function ask(question) {
      if (busy.value || props.mode !== 'live' || !props.point) return;
      const token = ++requestId;
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 65000);
      snapshot.value = null; cards.value = []; explanation.value = ''; explanationSource.value = '';
      error.value = ''; notice.value = ''; evidenceOpen.value = false;
      selectedQuestion.value = question.label; busy.value = true;
      try {
        const response = await fetch('/api/agent/ask', {method:'POST',
          headers:{'Content-Type':'application/json'}, signal:controller.signal,
          body:JSON.stringify({question_id:question.id,position_id:props.point.id,limit:10})});
        await readAgentEvents(response, (type, value) => {
          if (token !== requestId) return;
          if (type === 'snapshot') snapshot.value = value;
          if (type === 'candidate') cards.value.push(value);
          if (type === 'notice') notice.value = value.message;
          if (type === 'explanation') { explanation.value += value.text; explanationSource.value = value.source; }
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
    const format = value => value == null ? '未知' : value.toFixed(1);
    const time = value => value ? new Date(value).toLocaleTimeString('zh-CN',{hour12:false}) : '—';
    return {open,questions,snapshot,cards,busy,error,notice,explanation,explanationSource,evidenceOpen,configured,selectedQuestion,toggle,stop,ask,format,time};
  },
  template: `
  <button v-if="!open" class="agent-orb" aria-label="打开智能态势问答" @click="toggle"><b>AI</b><span>态势问答</span></button>
  <section v-else class="agent-dialog" role="dialog" aria-label="智能态势问答" @keydown.esc="open=false">
    <div class="agent-title"><div><b>智能态势问答</b><small>本体事实 · 策略排序 · 地图联动</small></div><button aria-label="收起智能问答" @click="open=false">收起 ×</button></div>
    <div class="agent-content">
      <div class="agent-context"><span>所选阵地：{{point?.name || '等待阵地'}}</span><span>{{configured?'DeepSeek 解读已配置':'规则演示模式'}}</span></div>
      <p class="agent-boundary">Python 按本体策略计算与排序；大模型只解释。当前依据是距离与可用趋势，不等同于综合威胁。</p>
      <p v-if="mode!=='live'" class="agent-notice">请返回实时态势后提问，避免把回放数据当成当前结果。</p>
      <div class="agent-questions"><button v-for="q in questions" :key="q.id" @click="ask(q)" :disabled="busy||mode!=='live'||!point||!data?.targets.some(t=>!t.stale)">{{q.label}} ↗</button></div>
      <p v-if="!data?.targets.length" class="agent-notice">等待有效无人机观测后再提问。</p>
      <div v-if="selectedQuestion" class="agent-question">{{selectedQuestion}}</div>
      <div v-if="snapshot" class="agent-snapshot"><b>{{snapshot.position.name}} · {{snapshot.policy.label}}</b><span>{{time(snapshot.at)}} 固定快照 · {{snapshot.eligible}} 架可用 · {{snapshot.excluded.length}} 架排除</span><span>排序：{{snapshot.policy.description}}</span><button @click="evidenceOpen=!evidenceOpen">{{evidenceOpen?'收起 RDF 证据':'查看本次本体事实与排序策略'}}</button></div>
      <div class="agent-candidates"><button v-for="c in cards" :key="c.target_id" class="agent-candidate" :aria-label="'定位第'+c.rank+'名 '+c.name" @click="locateCandidate(c,snapshot)"><span class="candidate-rank">{{c.rank}}</span><div><b>第 {{c.rank}} 名 · {{c.name}}</b><span :style="{color:c.color}">{{c.level_label}} · {{format(c.distance)}} 米</span><small>观测起算进入高关注圈：{{c.eta_seconds===0?'该次观测已在圈内':c.eta_seconds==null?'未知':format(c.eta_seconds)+' 秒（估计）'}}</small><small>{{c.reason}}</small><small>观测 {{time(c.timestamp)}} · {{c.trend_note}}</small><span class="candidate-link">定位地图 · 查看对象 ↗</span></div></button></div>
      <details v-if="snapshot?.excluded.length" class="agent-excluded"><summary>哪些对象未参与排序？</summary><p v-for="e in snapshot.excluded">{{e.target_id}}：{{e.reason}}</p></details>
      <div v-if="explanation" class="agent-explanation"><b>{{explanationSource==='deepseek'?'DeepSeek 流式解读':'确定性规则说明'}}</b><p>{{explanation}}</p><small v-if="explanationSource==='deepseek'">生成文字仅用于解读；名次和数值以服务器结果卡片为准。</small></div>
      <p v-if="notice" class="agent-notice">{{notice}}</p><p v-if="error" class="agent-error" role="alert">{{error}}</p>
      <p v-if="busy" class="agent-progress">正在接收分析结果… <button @click="stop">停止</button></p>
      <div v-if="evidenceOpen&&snapshot" class="agent-evidence"><h3>本次 RDF 快照（Turtle）</h3><p>包含排序策略、排序候选、观测、评估与规则。此处固定为本次回答依据。</p><pre><code>{{snapshot.ttl}}</code></pre></div>
      <p class="agent-footnote">结果按提问时刻固定；点击卡片定位该对象当前可用位置。新观测到达后，可再次提问刷新结果。</p>
    </div>
  </section>`
};
