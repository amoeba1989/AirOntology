import { ref, computed, watch, onUnmounted } from 'vue/dist/vue.esm-bundler.js';

export default {
  props: ['request', 'active', 'locate', 'clearPoint'],
  setup(props) {
    const data=ref(null),error=ref(''),busy=ref(false),layer=ref('association'),ttl=ref(''),report=ref(null);
    const kind=ref('devices'),payload=ref(''),message=ref('');
    const kinds={devices:'设备状态',observations:'原始观测',regions:'区域引用',authorizations:'授权声明',judgements:'判断记录'};
    const layers={association:'① 观测关联',identification:'② 无人机识别',intrusion:'③ 异常闯入条件'};
    const labels={radar:'雷达',radio:'无线电',camera:'摄像头',infrared:'红外',normal:'正常',fault:'故障',unknown:'未知',insufficient:'证据不足',pending:'待核实',suspected:'疑似',conflict:'证据冲突',detected:'检出',not_detected:'未检出',usable:'可用声明',invalid:'无效',reported_available:'报告覆盖可用（未验证）',authorized:'有授权声明',unauthorized:'无授权声明',operator:'人工登记',external_algorithm:'外部算法声明',WGS84:'WGS84（世界大地坐标系）'};
    const text=value=>labels[value]||value||'—';
    const mode=value=>({simulated:'模拟数据',operational:'业务接入声明（未独立验证）',unverified:'来源待核实'})[value]||'来源待核实';
    const judgements=computed(()=>data.value?.judgements?.filter(j=>j.layer===layer.value)||[]);
    let reading=false,closed=false;
    async function refresh(){
      if(reading||closed)return; reading=true;
      try {const value=await props.request('/api/evidence');if(!closed){data.value=value;error.value='';}}
      catch(e){if(!closed)error.value=e.message;} finally{reading=false;}
    }
    async function act(fn){if(busy.value)return;busy.value=true;error.value='';message.value='';try{await fn();}catch(e){error.value=e.message;}finally{busy.value=false;}}
    const demo=()=>act(async()=>{await props.request('/api/evidence/demo',false,{method:'POST'});await refresh();message.value='已登记模拟示例；没有执行融合或识别算法。';});
    const example=()=>act(async()=>{const values=await props.request('/api/evidence/examples');payload.value=JSON.stringify(values[kind.value],null,2);});
    const submit=()=>act(async()=>{const body=JSON.parse(payload.value);await props.request('/api/evidence/'+kind.value,false,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});await refresh();ttl.value='';report.value=null;message.value='已保存；观测、判断、区域和授权不可覆盖，请用新编号登记后续记录。';});
    const showTTL=()=>act(async()=>{ttl.value=await props.request('/api/evidence/ttl',true);});
    const validate=()=>act(async()=>{report.value=await props.request('/api/evidence/validate',false,{method:'POST'});});
    watch(kind,()=>{payload.value='';});
    watch(()=>props.active,value=>{if(value)refresh();},{immediate:true});
    const timer=setInterval(()=>{if(props.active&&!busy.value)refresh();},5000);
    onUnmounted(()=>{closed=true;clearInterval(timer);});
    return {data,error,busy,layer,ttl,report,kind,payload,message,kinds,layers,judgements,text,mode,refresh,demo,example,submit,showTTL,validate};
  },
  template:`<section id="evidence-panel" class="panel evidence-panel">
    <div class="panel-heading"><div><span class="eyebrow">RDF / OWL / SHACL · 多源证据</span><h2>从设备观测到待核实判断</h2></div><button @click="refresh" :disabled="busy">刷新证据</button></div>
    <p class="evidence-boundary">本体保存概念、关系、约束和依据。融合、无人机识别、区域包含算法尚未选定或验证；大模型不能替代这些算法。未检出 ≠ 没有目标；授权未知 ≠ 未授权。</p>
    <p v-if="error" role="alert" class="error">{{error}}</p><p v-if="message" role="status">{{message}}</p>
    <div class="evidence-actions"><button :disabled="busy" @click="demo">导入模拟示例</button><button :disabled="busy" @click="showTTL">查看证据 ABox TTL</button><button :disabled="busy" @click="validate">SHACL 结构校验</button><button @click="clearPoint()">清除原始观测定位</button><span>学习环境有界保留；达到上限后拒绝新增，不自动删证据。</span></div>
    <template v-if="data">
      <h3>设备与覆盖状态（Device · 设备）</h3><div class="table-scroll"><table><thead><tr><th>来源设备 / 类型</th><th>数据声明</th><th>设备状态 / 覆盖</th><th>观测说明</th></tr></thead><tbody><tr v-for="d in data.devices" :key="d.id"><td>{{d.name}} · {{text(d.sensor_kind)}}<small>{{d.id}} · {{d.source}}</small></td><td>{{mode(d.data_mode)}}</td><td>{{text(d.effective_status)}} / {{text(d.effective_coverage)}}<small>{{d.reported_at}} {{d.status_fresh?'状态有效':'状态过期'}}</small></td><td>{{d.observation_note}}</td></tr><tr v-if="!data.devices.length"><td colspan="4">尚无设备；请登记来源或导入模拟示例。</td></tr></tbody></table></div>
      <h3>原始观测（Observation · 观测）</h3><p>观测保存原始声明，不因位置相近自动合并为同一目标。设备状态变更不会覆盖原观测。</p>
      <div class="table-scroll"><table><thead><tr><th>编号 / 来源</th><th>结果 / 有效性</th><th>位置与误差</th><th>时间与原始引用</th></tr></thead><tbody><tr v-for="o in data.observations" :key="o.id"><td><code>{{o.id}}</code><small>{{o.device_name}} · {{mode(o.data_mode)}}</small><small>接收时设备声明：{{text(o.device_state_at_receipt?.reported_status)}} / {{text(o.device_state_at_receipt?.coverage)}}</small><small>特征：{{o.features||'未提供'}} · 外部目标引用：{{o.reported_target_ref||'未知'}}</small></td><td>{{text(o.outcome)}} / {{text(o.quality)}}<small>{{o.fresh?'时间有效':'已过期'}} · {{o.usable_positive?'可作正向观测输入，身份未知':'当前不作有效正向输入'}}</small><small v-if="!o.mode_consistent">与设备的数据声明冲突</small></td><td>{{text(o.crs)}}<small>{{o.lon??'未知'}}, {{o.lat??'未知'}} · 水平误差 {{o.horizontal_error_m==null?'未知':o.horizontal_error_m+' 米（来源声明）'}}</small><button v-if="o.outcome==='detected'&&o.crs==='WGS84'&&o.lon!=null&&o.lat!=null" @click="locate(o)">定位原始观测</button></td><td><small>观测 {{o.observed_at}}</small><small>接收 {{o.received_at}}</small><code>{{o.raw_evidence_ref}}</code></td></tr><tr v-if="!data.observations.length"><td colspan="4">尚无观测。</td></tr></tbody></table></div>
      <h3>三个判断层（Judgement · 判断）</h3><div class="evidence-actions"><button v-for="(name,key) in layers" :key="key" :class="{active:layer===key}" @click="layer=key">{{name}}</button></div>
      <p>每层独立登记。当前状态是对输入可用性的保守提示，不能升级原登记结论；分数未校准，不代表概率；证据数量不代表独立可信度。</p>
      <div class="evidence-cards"><article v-for="j in judgements" :key="j.id" class="evidence-card"><b>{{j.current_label}} · {{j.layer_label}}</b><small>{{mode(j.data_mode)}} · 疑似目标 {{j.target_ref}}</small><p>原登记：{{text(j.status)}} → 当前提示：{{j.current_label}}</p><dl><div><dt>方法 / 版本</dt><dd>{{j.method_name}} / {{j.method_version}}（{{text(j.source)}}，未独立验证）</dd></div><div><dt>适用条件</dt><dd>{{j.conditions}}</dd></div><div><dt>不确定性</dt><dd>{{j.uncertainty}}</dd></div><div><dt>观测输入</dt><dd>{{j.observation_ids.join('、')||'无'}}</dd></div><div><dt>前置判断</dt><dd>{{j.judgement_ids.join('、')||'无'}}</dd></div><div><dt>证据独立性</dt><dd>{{j.independence_note}}</dd></div><div><dt>验证依据引用</dt><dd>{{j.validation_ref||'未提供'}}（引用本身不证明已验证）</dd></div><div v-if="j.score!=null"><dt>算法分数（非概率）</dt><dd>{{j.score}} · {{j.score_meaning}}</dd></div><div><dt>生成 / 接收</dt><dd>{{j.generated_at}} / {{j.received_at}}</dd></div><div v-if="j.region_id"><dt>区域 / 授权</dt><dd>{{j.region_id}} / {{j.authorization_id||'未提供'}} · {{text(j.authorization_status)}}</dd></div></dl><ul><li v-for="gap in j.gaps" :key="gap">{{gap}}</li></ul><code>{{j.id}}</code></article><p v-if="!judgements.length">本层尚无判断记录；不会借用其他层的结论。</p></div>
      <details><summary>区域引用与授权声明</summary><p>只登记空间引用和有效期；尚未计算进入、离开或包含关系。无授权声明也不能单独证明异常闯入。</p><article v-for="r in data.regions" :key="r.id"><b>{{r.name}} · {{mode(r.data_mode)}}</b><p>{{r.description}}</p><code>{{r.id}} · {{r.geometry_ref}}</code></article><article v-for="a in data.authorizations" :key="a.id"><b>{{text(a.effective_status)}} · {{mode(a.data_mode)}}</b><p>疑似目标 {{a.target_ref}} → 区域 {{a.region_id}} · {{a.authority}}</p><small>{{a.valid_from}} 至 {{a.valid_until}}；原登记 {{text(a.status)}}</small><code>{{a.id}} · {{a.evidence_ref}}</code></article><p v-if="!data.authorizations.length">无授权记录：状态为未知，不能当成未授权。</p></details>
    </template>
    <details class="evidence-editor"><summary>登记 JSON 数据 / 了解接入字段</summary><p>先登记设备和区域，再提交观测、授权、判断。模板仅供编辑，示例不会自动提交；使用新的记录编号。原始引用只保存文本，不抓取外部链接。</p><label>记录类型 <select v-model="kind"><option v-for="(name,key) in kinds" :value="key" :key="key">{{name}}</option></select></label><button :disabled="busy" @click="example">载入可编辑示例</button><textarea v-model="payload" aria-label="证据 JSON 数据" rows="14" spellcheck="false"></textarea><button :disabled="busy||!payload" @click="submit">登记当前记录</button><p>HTTP：POST /api/evidence/{{kind}}；MQTT 原始观测主题：counteruav/observation/raw（可配置）。</p></details>
    <details v-if="ttl" open><summary>证据 ABox（实例关系）Turtle</summary><pre>{{ttl}}</pre></details>
    <div v-if="report" class="evidence-report" role="status"><h3>SHACL：{{report.conforms?'结构通过':'存在结构错误'}}</h3><p>{{report.focus_count}} 个校验对象 · {{report.result_count}} 条问题。结构通过不证明算法、事实或授权真实性。</p><ul><li v-for="(r,i) in report.results" :key="i">{{r.focus}} · {{r.path}} · {{r.message}}</li></ul><details><summary>校验报告 TTL</summary><pre>{{report.report_ttl}}</pre></details></div>
  </section>`
};
