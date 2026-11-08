import { ref, computed, onMounted, onUnmounted } from 'vue/dist/vue.esm-bundler.js';
import './rules-workbench.css';
export default {
  setup() {
    const data=ref(null), draft=ref([]), revision=ref(0), selected=ref(''), tab=ref('rules'), error=ref(''), message=ref(''), busy=ref(false), trial=ref(null), trialAt=ref(''), note=ref(''), config=ref(null), configVersion=ref(''), loaded=ref(false);
    const labels={observation_stale:'观测过期',device_stale:'雷达上报中断',zone:'圆形区域进出'};
    const statuses={matched:'命中',clear:'未命中',unknown:'无法判断'};
    const active=computed(()=>draft.value.find(r=>r.id===selected.value));
    const events=computed(()=>[...(data.value?.events||[])].reverse());
    const statusCounts=computed(()=>['matched','clear','unknown'].map(s=>({name:statuses[s],count:(data.value?.results||[]).filter(r=>r.status===s).length})));
    let timer, polling=false, closed=false;
    const format=t=>t?new Date(t).toLocaleString('zh-CN',{hour12:false}):'尚未执行';
    async function request(path,body,method='POST') {
      const r=await fetch(path,{signal:AbortSignal.timeout(20000),...(body?{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
      const value=await r.json();
      if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail||value));
      return value;
    }
    async function refresh(reset=false) {
      if(polling)return;polling=true;
      try {const value=await request('/api/rules');if(closed)return;data.value=value;
        if(reset||!loaded.value){draft.value=structuredClone(value.rules);revision.value=value.revision;config.value=structuredClone(value.config.config);configVersion.value=value.config.version;selected.value=draft.value[0]?.id||'';loaded.value=true;trial.value=null;}
      }catch(e){error.value=e.message}finally{polling=false}
    }
    async function action(fn){busy.value=true;error.value='';message.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false}}
    function add(kind){if(draft.value.length>=40)return;const rule={id:'r-'+Date.now()+'-'+Math.random().toString(16).slice(2,6),name:labels[kind],kind,enabled:false,source:'演示规则；参数需按现场要求确认',position_id:kind==='zone'?config.value?.positions[0]?.id||null:null,seconds:30,radius:300};draft.value.push(rule);selected.value=rule.id;trial.value=null;}
    function remove(){draft.value=draft.value.filter(r=>r.id!==selected.value);selected.value=draft.value[0]?.id||'';trial.value=null;}
    function restore(v){draft.value=structuredClone(v.rules);revision.value=data.value.revision;selected.value=draft.value[0]?.id||'';note.value='恢复版本 '+v.revision+' 的规则内容';trial.value=null;tab.value='rules';message.value='已载入历史草稿；试运行并发布后才生效。'}
    function runTrial(){return action(async()=>{trial.value=await request('/api/rules/trial',{rules:draft.value,at:trialAt.value?new Date(trialAt.value).toISOString():null});message.value='已完成只读快照试运行；结果对应此次试运行时的草稿。'});}
    function publish(){return action(async()=>{const value=await request('/api/rules',{expected_revision:revision.value,rules:draft.value,note:note.value},'PUT');revision.value=value.revision;data.value={...data.value,...value};trial.value=null;note.value='';message.value='已发布版本 '+value.revision+'；后台将在下一周期执行（约5秒）。';});}
    function saveConfig(){return action(async()=>{const value=await request('/api/config',{expected_version:configVersion.value,config:config.value},'PUT');configVersion.value=value.version;message.value='对象与距离配置已保存；区域规则会重新建立基线，地图等级从新观测生效。';await refresh();});}
    onMounted(async()=>{await refresh(true);timer=setInterval(()=>refresh(),5000)});
    onUnmounted(()=>{closed=true;clearInterval(timer)});
    return {data,draft,revision,selected,tab,error,message,busy,trial,trialAt,note,config,configVersion,loaded,labels,statuses,active,events,statusCounts,format,refresh,add,remove,restore,runTrial,publish,saveConfig};
  },
  template:`<div class="rules-page">
    <header class="rules-header"><a href="/" class="rules-brand"><span>AO</span><div>AirOntology<small>观测 · 规则 · 证据</small></div></a><nav aria-label="工作台视图"><a href="/">态势地图</a><a href="/back">本体拓扑</a><a href="/rules" aria-current="page">规则引擎</a><a href="/back#query-tools">查询与校验</a><a href="/back?legacy=1">本体学习</a></nav></header>
    <main class="rules-main"><div class="rules-title"><div><small>业务决策中心</small><h1>规则引擎</h1><p>把观测转化为可解释的事件，让每一次提醒都有依据。</p></div><div class="rules-runtime"><b>发布版本 {{data?.revision??'—'}}</b><span>最近执行 {{format(data?.evaluated_at)}}</span><span>每 5 秒评估 · {{data?.engine_enabled?'后台已启用':'后台未启用'}}</span></div></div>
    <div v-if="error" class="rules-error" role="alert">{{error}} <button @click="error=''">关闭提示</button></div><div v-if="message" class="rules-message" role="status">{{message}}</div>
    <div v-if="data?.engine_error" class="rules-error">{{data.engine_error}}</div><div v-if="data?.evaluated_at && Date.now()-Date.parse(data.evaluated_at)>20000" class="rules-error">执行结果已超过20秒未更新，请勿作为实时状态。</div>
    <div class="rules-metrics"><div><b>{{data?.rules.filter(r=>r.enabled).length||0}}</b><span>启用规则</span></div><div v-for="s in statusCounts"><b>{{s.count}}</b><span>{{s.name}}</span></div><p>距离分级保持现有地图口径。新增规则输出独立事件，不自动认定违法或控制设备。</p></div>
    <nav class="rules-tabs"><button v-for="t in [['rules','规则库与编辑'],['results','运行与证据'],['config','对象与距离配置'],['versions','发布版本']]" :class="{active:tab===t[0]}" @click="tab=t[0]">{{t[1]}}</button></nav>
    <p v-if="!loaded">正在读取规则与配置…</p>
    <template v-if="loaded"><section v-if="tab==='rules'" class="rules-editor-layout">
      <aside class="rules-panel rules-library"><h2>规则库 <small>{{draft.length}} / 40</small></h2><p>草稿可自由编辑，发布后才生效。</p><button class="rules-builtin" @click="tab='config'"><b>距离关注分级</b><small>内置 · 与地图共用 · 编辑配置 →</small></button>
        <button v-for="r in draft" :key="r.id" :class="['rules-list-item',{selected:selected===r.id}]" @click="selected=r.id"><span>{{r.name}}</span><small>{{labels[r.kind]}} · {{r.enabled?'启用':'停用'}}</small></button>
        <div class="rules-add"><span>从模板添加</span><button v-for="(label,kind) in labels" @click="add(kind)" :disabled="busy||draft.length>=40">＋ {{label}}</button></div>
      </aside>
      <div class="rules-panel rules-editor"><template v-if="active"><div class="rules-section-title"><div><small>{{labels[active.kind]}}</small><h2>{{active.name}}</h2></div><button @click="remove" :disabled="busy">从草稿移除</button></div>
        <label>规则名称<input v-model="active.name" maxlength="80" :disabled="busy"></label>
        <label>依据与来源<textarea v-model="active.source" maxlength="500" :disabled="busy" placeholder="填写管理要求、设备说明或演示假设"></textarea></label>
        <div class="rules-fields"><label v-if="active.kind!=='observation_stale'">适用阵地<select v-model="active.position_id" :disabled="busy"><option v-if="active.kind==='device_stale'" :value="null">全部已登记雷达</option><option v-for="p in config.positions" :value="p.id">{{p.name}}</option></select></label><label>{{active.kind==='zone'?'位置有效期 / 秒':'中断或过期阈值 / 秒'}}<input type="number" min="2" max="3600" v-model.number="active.seconds" :disabled="busy"></label><label v-if="active.kind==='zone'">圆形区域半径 / 米<input type="number" min="0.1" max="100000" v-model.number="active.radius" :disabled="busy"></label></div>
        <label class="rules-check"><input type="checkbox" v-model="active.enabled" :disabled="busy">发布后启用这条规则</label>
        <div class="rules-explanation"><b>执行含义</b><p v-if="active.kind==='zone'">使用所选阵地中心计算 WGS84 水平距离。初次位于区域内记录“首次确认”，后续有效状态变化记录进入或离开；位置过期显示“无法判断”。第一版不支持多边形、高度或持续停留。</p><p v-else-if="active.kind==='device_stale'">根据已登记雷达的最后状态时间判断上报中断，可按部署阵地筛选。仅说明数据链路状态，不证明雷达故障或没有目标。</p><p v-else>检查无人机最后一次观测距今的时长。即使没有新消息，后台定时检查仍会运行；恢复上报后记录恢复事件。</p></div>
      </template><div v-else class="rules-empty"><h2>从一个业务问题开始</h2><p>左侧选择模板，配置条件和依据，再试运行。新规则默认停用，不影响现有距离分级。</p></div>
      <div class="rules-publish"><h3>试运行与发布</h3><label>历史快照时间（可选，留空使用当前数据）<input type="datetime-local" v-model="trialAt" :disabled="busy"></label><p>试运行不改变线上规则；历史数据受保留范围限制，不支持雷达历史和连续事件回放。停用的规则不参与试运行。</p><div class="rules-actions"><button @click="runTrial" :disabled="busy">{{busy?'处理中…':'试运行草稿'}}</button><button @click="refresh(true)" :disabled="busy">放弃草稿并加载已发布内容</button></div><label>发布说明<input v-model="note" maxlength="200" placeholder="例如：增加雷达上报中断提醒" :disabled="busy"></label><button class="rules-primary" @click="publish" :disabled="busy||!note.trim()">发布全部草稿 · 基于版本 {{revision}}</button><p v-if="data.revision!==revision" class="rules-error">线上已有新版本，请保留草稿后重新加载对比。</p></div>
      <section v-if="trial" class="rules-trial"><h3>试运行结果 · {{format(trial.at)}}</h3><p>{{trial.note}}</p><p v-if="!trial.results.length">没有启用的规则。请勾选“发布后启用”再试运行。</p><div v-for="(r,i) in trial.results" :key="i" class="rules-result"><span :class="['rules-status',r.status]">{{statuses[r.status]}}</span><b>{{r.rule_name}} · {{r.entity_id}}</b><p>{{r.reason}}</p></div></section>
      </div></section>
    <section v-if="tab==='results'" class="rules-panel"><h2>最新执行结果</h2><p>每个对象单独判定；命中只表示满足本条条件。详情包含输入和规则参数。</p><div class="rules-table"><table><thead><tr><th>规则 / 对象</th><th>结果</th><th>依据</th></tr></thead><tbody><tr v-for="(r,i) in data.results" :key="i"><td>{{r.rule_name}}<small>{{r.entity_id}} · {{r.data_mode==='simulated'?'模拟数据':'来源待核实'}}</small></td><td><span :class="['rules-status',r.status]">{{statuses[r.status]}}</span></td><td>{{r.reason}}<details><summary>查看执行证据</summary><pre>{{JSON.stringify(r,null,2)}}</pre></details></td></tr></tbody></table></div><p v-if="!data.results.length">暂无结果，请添加并发布启用的规则，等待下一执行周期。</p><h2>事件记录 <small>最近 {{events.length}} / 300 条</small></h2><p>仅记录状态变化，不重复生成相同提醒。发布新版本、配置变化或数据中断后重新建立基线。</p><div v-for="e in events" :key="e.id" class="rules-event"><span>{{format(e.evaluated_at)}}</span><b>{{e.event}} · {{e.entity_id}}</b><p>{{e.rule_name}} · 发布版本 {{e.revision}} · {{e.reason}}</p><details><summary>原始依据与参数快照</summary><pre>{{JSON.stringify(e,null,2)}}</pre></details></div><p v-if="!events.length">还没有状态变化事件。</p></section>
    <section v-if="tab==='config'" class="rules-panel"><h2>阵地对象与内置距离分级</h2><p>该配置与现有态势地图共用。规则通过阵地编号引用对象；修改位置会使区域规则重新建立基线。坐标使用 WGS84。</p><form @submit.prevent="saveConfig"><fieldset :disabled="busy"><div class="rules-position" v-for="(p,i) in config.positions" :key="i"><label>阵地名称<input required v-model="p.name" maxlength="80"></label><label>编号<input required v-model="p.id" pattern="[A-Za-z0-9_-]{1,100}"></label><label>经度<input required type="number" step="any" min="-180" max="180" v-model.number="p.lon"></label><label>纬度<input required type="number" step="any" min="-90" max="90" v-model.number="p.lat"></label><button type="button" :disabled="config.positions.length===1" @click="config.positions.splice(i,1)">移除</button></div><button type="button" :disabled="config.positions.length>=10" @click="config.positions.push({id:'pos'+Date.now(),name:'新阵地',lon:116.4,lat:39.9})">＋ 添加阵地</button><h3>距离分级 · 全部阵地共用</h3><div class="rules-fields"><label>高关注 / 米<input required type="number" step="any" min="0.001" v-model.number="config.high_threshold"></label><label>中关注 / 米<input required type="number" step="any" min="0.001" v-model.number="config.medium_threshold"></label><label>低关注 / 米<input required type="number" step="any" min="0.001" max="100000" v-model.number="config.low_threshold"></label><label>地图观测有效期 / 秒<input required type="number" min="2" max="3600" step="any" v-model.number="config.stale_seconds"></label><label>每目标保留历史条数<input required type="number" min="10" max="1000" v-model.number="config.history_limit"></label></div><p>高关注 ＜ 中关注 ＜ 低关注。缩小历史数量会清理旧观测；历史评估保留当时的规则。新增规则的有效期由各自模板单独设置。</p><button class="rules-primary" type="submit">保存对象与距离配置</button></fieldset></form></section>
    <section v-if="tab==='versions'" class="rules-panel"><h2>发布历史</h2><p>保留最近20个规则集版本；恢复内容先载入草稿，重新发布才生效。对象与距离配置不包含在此规则集版本中。</p><div class="rules-event" v-for="v in [...data.versions].reverse()" :key="v.revision"><b>版本 {{v.revision}} · {{v.note}}</b><p>{{format(v.at)}} · {{v.rules.length}} 条规则</p><button @click="restore(v)" :disabled="busy">载入为恢复草稿</button></div><p v-if="!data.versions.length">尚未发布规则集。</p></section></template>
    </main></div>`
};
