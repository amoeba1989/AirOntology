import {ref,computed,watch} from 'vue/dist/vue.esm-bundler.js';

export default {
  props:['request','data','selectedId','locate','replay'],
  setup(props){
    const filter=ref('all'),selected=ref(''),tab=ref('state'),ttl=ref(''),query=ref(null),report=ref(null),error=ref(''),busy=ref(false),position=ref('');
    const devices=computed(()=>props.data?.devices||[]);
    const filtered=computed(()=>devices.value.filter(d=>filter.value==='all'||d.kind===filter.value));
    const chosen=computed(()=>devices.value.find(d=>d.id===selected.value)||filtered.value[0]);
    const bool=value=>value==null?'未提供':value?'是':'否';
    const mode=value=>['待命','巡航','遥控失联','导航失锁/下坠','返航','已摧毁','沿航路飞行'][value]||'未提供';
    const faction=value=>['中立','红方','蓝方'][value]||'未提供';
    const pretty=value=>JSON.stringify(value,null,2);
    watch(()=>props.selectedId,value=>{if(value){filter.value='all';selected.value=value;tab.value='state';}},{immediate:true});
    watch(filter,()=>{selected.value='';},{flush:'sync'});
    function choose(d){selected.value=d.id;tab.value='state';}
    async function act(fn){if(busy.value)return;busy.value=true;error.value='';try{await fn();}catch(e){error.value=e.message;}finally{busy.value=false;}}
    const loadTTL=()=>act(async()=>{ttl.value=await props.request('/api/devices/ttl',true);tab.value='ttl';});
    const runQuery=()=>act(async()=>{query.value=await props.request('/api/devices/deployments'+(position.value?'?position_id='+encodeURIComponent(position.value):''));});
    const validate=()=>act(async()=>{report.value=await props.request('/api/devices/validate',false,{method:'POST'});});
    return {filter,selected,tab,ttl,query,report,error,busy,position,devices,filtered,chosen,bool,mode,faction,pretty,choose,loadTTL,runQuery,validate};
  },
  template:`<section id="devices-panel" class="panel devices-panel">
    <div class="panel-heading"><div><span class="eyebrow">MQTT → RDF · 模拟设备</span><h2>无人机、阵地、雷达与干扰器</h2></div><span class="tag">全部模拟数据</span></div>
    <p>类型与部署关系来自明确登记的设备配置；状态来自 MQTT。配置开启不代表当前正常，设备邻近不自动产生归属、探测或干扰关系。</p>
    <p v-if="replay" class="alert">下方为设备最新状态，地图正在回放无人机历史。定位设备会返回实时视图。</p>
    <p v-if="error" role="alert" class="error">{{error}}</p>
    <div class="devices-sites"><article v-for="p in data?.positions||[]" :key="p.id"><b>⚑ {{p.name}} · 阵地</b><code>{{p.id}}</code><span>显式部署：{{devices.filter(d=>d.deployed_at===p.id).map(d=>d.name).join('、')||'尚无登记设备'}}</span></article></div>
    <p v-if="!devices.length" class="empty">等待设备登记 MQTT；启动 demo 模拟器后将登记无人机、雷达和干扰器。</p>
    <div class="devices-toolbar"><label>设备类型 <select v-model="filter" aria-label="筛选设备类型"><option value="all">全部设备</option><option value="uav">无人机</option><option value="radar">雷达</option><option value="jammer">干扰器</option></select></label><span>{{devices.length}} 台设备 · 最新源帧 {{data?.frame?.payload?.tick??'—'}} · 仿真时间 {{data?.frame?.payload?.sim_time_s??'—'}} 秒</span><button @click="loadTTL" :disabled="busy">查看设备 RDF / TTL</button><button @click="validate" :disabled="busy">校验设备与关系</button></div>
    <div class="devices-layout"><div class="device-list"><button v-for="d in filtered" :key="d.id" @click="choose(d)" :class="['device-choice',d.kind,{active:chosen?.id===d.id}]" :aria-label="'查看设备 '+d.name"><b>{{d.kind==='radar'?'◉':d.kind==='jammer'?'◆':'✣'}} {{d.name}}</b><span>{{d.kind_label}} · {{d.position?.name||'未登记阵地归属'}}</span><small>{{d.status_label}}</small></button></div>
    <article v-if="chosen" class="device-detail"><h3>{{chosen.name}} <small>{{chosen.kind_label}} · 模拟数据</small></h3><code>{{chosen.uri}}</code><p :class="{error:chosen.stale||!chosen.in_latest_frame}">{{chosen.status_label}} · 来源帧 {{chosen.state_tick||'—'}}</p>
    <div class="devices-toolbar"><button @click="tab='state'">配置与实时状态</button><button @click="tab='mapping'">本体字段映射</button><button @click="tab='json'">来源 MQTT JSON</button><button v-if="chosen.state?.transform" @click="locate(chosen)">定位该设备</button></div>
    <template v-if="tab==='state'"><dl><div><dt>部署关系</dt><dd>{{chosen.deployed_at?(chosen.position?.name||'原阵地已移除，关系待核对'):'未登记'}} {{chosen.deployed_at||''}}</dd></div><div><dt>登记来源</dt><dd>{{chosen.configuration_source}}</dd></div><div><dt>阵营</dt><dd>{{faction(chosen.state?.faction?.side)}}（仿真阵营不代表授权）</dd></div><div><dt>位置（经度 / 纬度）</dt><dd>{{chosen.state?.transform?.longitude_deg??'未提供'}} / {{chosen.state?.transform?.latitude_deg??'未提供'}}</dd></div><div><dt>绝对海拔</dt><dd>{{chosen.state?.transform?.altitude_m??'未提供'}} 米；垂直基准待确认</dd></div><div><dt>UTC 发布 / 接收时间</dt><dd>{{chosen.published_at||'—'}} / {{chosen.received_at||'—'}}</dd></div>
    <template v-if="chosen.kind==='uav'"><div><dt>地速 / 空速</dt><dd>{{chosen.state?.motion?.speed_mps??'未提供'}} / {{chosen.state?.flight?.airspeed_mps??'未提供'}} 米/秒</dd></div><div><dt>运动模式</dt><dd>{{mode(chosen.state?.motion?.mode)}}</dd></div><div><dt>导航锁定 / 遥控连通 / 遥测连通</dt><dd>{{bool(chosen.state?.rf_link?.gnss_locked)}} / {{bool(chosen.state?.rf_link?.rc_linked)}} / {{bool(chosen.state?.rf_link?.telemetry_linked)}}</dd></div><div><dt>摧毁状态</dt><dd>{{bool(chosen.state?.health?.destroyed)}}</dd></div></template>
    <div v-if="chosen.kind==='radar'"><dt>实时工作状态与探测对象</dt><dd>未提供。初始配置不能证明当前工作正常；态势中没有具体探测记录。</dd></div>
    <template v-if="chosen.kind==='jammer'"><div><dt>设备总开关 / 当前实际发射</dt><dd>{{bool(chosen.state?.jammer?.enabled)}} / {{bool(chosen.state?.jammer?.emitting)}}</dd></div><div><dt>中心频率 / 带宽</dt><dd>{{chosen.state?.jammer?.freq_hz??'未提供'}} / {{chosen.state?.jammer?.bandwidth_hz??'未提供'}} Hz</dd></div><div><dt>作用对象与效果</dt><dd>未提供；演示状态轮播不计算或认定影响了某架无人机。</dd></div></template></dl><details><summary>初始配置（不是实时状态）</summary><pre>{{pretty(chosen.parameters)}}</pre></details></template>
    <template v-if="tab==='mapping'"><p>类定义属于 TBox；具体设备、部署关系和状态属于 ABox。阵营与设备类型分别表达。</p><table><thead><tr><th>来源</th><th>本体表达</th><th>中文含义</th></tr></thead><tbody><tr><td>设备登记 kind</td><td>rdf:type → cu:{{chosen.kind==='uav'?'UAV':chosen.kind==='radar'?'RadarSensor':'Jammer'}}</td><td>属于哪种设备</td></tr><tr><td>登记 deployed_at</td><td>cu:deployedAt → cu:Position 实例</td><td>明确登记的阵地归属；空值不建关系</td></tr><tr><td>本帧状态</td><td>cu:latestDeviceState → cu:DeviceState</td><td>对象与状态分开</td></tr><tr><td>transform.longitude_deg / latitude_deg</td><td>cu:lon / cu:lat</td><td>状态中的经纬度</td></tr><tr><td>rf_link.rc_linked</td><td>cu:rcLinked</td><td>无人机遥控链路是否连通</td></tr><tr><td>jammer.enabled / emitting</td><td>cu:emitterEnabled / emitterEmitting</td><td>开启与实际发射不同</td></tr></tbody></table></template>
    <template v-if="tab==='json'"><p>主题：{{data?.topic}}。下方实体原始字段来自最后一次上报；本帧缺席不清空旧状态，也不当作当前仍有上报。</p><pre>{{pretty(chosen.state)}}</pre><details><summary>最新完整 MQTT 态势消息</summary><pre>{{pretty(data?.frame)}}</pre></details><details><summary>设备登记消息</summary><pre>{{pretty(data?.registry)}}</pre></details></template>
    </article></div>
    <details v-if="ttl" :open="tab==='ttl'"><summary>设备事实 TTL（点击获取时的快照）</summary><pre>{{ttl}}</pre></details>
    <div class="device-query"><h3>业务问题：某阵地部署了哪些设备？</h3><label>阵地 <select v-model="position" aria-label="查询设备归属阵地"><option value="">全部阵地</option><option v-for="p in data?.positions||[]" :key="p.id" :value="p.id">{{p.name}}</option></select></label><button @click="runQuery" :disabled="busy">执行部署关系 SPARQL</button><template v-if="query"><pre>{{query.sparql}}</pre><p>查询到 {{query.rows.length}} 条明确登记的部署关系。</p><ul><li v-for="(row,i) in query.rows" :key="i">{{row.name?.value}} → 部署于 → {{row.positionName?.value}}</li></ul></template></div>
    <div v-if="report" role="status" class="device-validation"><b>SHACL：{{report.conforms?'结构通过':'存在结构问题'}}</b><p>{{report.focus_count}} 个校验对象；校验不证明设备性能或作用关系。</p><ul><li v-for="(r,i) in report.results" :key="i">{{r.message}} · {{r.focus}}</li></ul></div>
  </section>`
};
