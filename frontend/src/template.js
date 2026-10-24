export default `
<div class="workspace" :class="{screen:viewMode==='screen'}">
  <header>
    <div class="brand-mark">A<span>O</span></div><div class="brand">AirOntology<small>无人机本体 · 观测与评估工作台</small></div>
    <span class="edition">{{target?.data_mode==='simulated'?'模拟数据':target?.data_mode==='operational'?'业务接入声明':target?'来源待核实':'本体演示'}}</span>
    <nav class="view-switch" aria-label="工作台视图"><button :class="{active:viewMode==='screen'}" @click="changeView('screen')">态势大屏</button><button :class="{active:viewMode==='learning'}" @click="changeView('learning')">本体学习</button></nav>
    <div class="header-right"><span class="status-dot" :class="{online:mode==='live'&&health?.mqtt.connected}"></span>{{status}}<span class="divider"></span><button @click="openConfig" :disabled="mode!=='live'">阵地与规则配置</button></div>
  </header>
  <main>
    <div class="page-title"><div><div class="eyebrow">OBSERVE · ASSESS · EXPLAIN</div><h1>每一次评估，都有可追溯的依据</h1><p>选择一个阵地，比较目标距离；打开评估，查看观测、规则与对象关系。</p></div><div class="pipeline">无人机 <b>→</b> 观测记录 <b>→</b> 评估记录 <b>→</b> 阵地 / 规则</div></div>
    <div v-if="error" class="alert" role="alert">{{error}}</div>
    <div class="overview">
      <div><span class="metric-label">当前目标</span><strong>{{data?.targets.length ?? '—'}}<small>架</small></strong></div>
      <div><span class="metric-label">关联阵地</span><strong>{{data?.positions.length ?? '—'}}<small>处</small></strong></div>
      <div><span class="metric-label">独立评估</span><strong>{{data?.assessments.length ?? '—'}}<small>条</small></strong></div>
      <div><span class="metric-label">选中目标 / 选中阵地</span><strong class="level-metric" :style="{color:assessment?.color}">{{assessment?.level_label || '待评估'}}</strong></div>
      <div class="dependency"><span :class="{connected:health?.mqtt.connected}">● MQTT {{health?.mqtt.connected?'已连接':'未连接'}}</span><span :class="{connected:health?.fuseki}">● Fuseki {{health?.fuseki?'可用':'未连接'}}</span></div>
    </div>
    <aside class="screen-objects" aria-label="对象与关系">
      <div class="screen-rail-head"><h2>对象与关系</h2><span>{{data?.targets.length||0}} 架目标</span></div>
      <p class="rail-hint">阵地与设备部署关系来自登记；无人机是独立目标。</p>
      <section class="rail-group" v-for="p in data?.positions" :key="p.id">
        <button class="rail-position" :class="{active:p.id===point?.id}" @click="choosePosition(p.id)"><span class="rail-position-symbol">⌁</span><b>{{p.name}}</b><small>阵地</small></button>
        <div class="rail-equipment" v-for="d in screenDevices.filter(x=>x.deployed_at===p.id&&x.kind!=='uav')" :key="d.id"><span :class="d.kind">{{d.kind==='radar'?'◎':'⌁'}}</span>{{d.name}}<small>{{d.kind==='jammer'&&d.state?.jammer ? (d.state.jammer.emitting?'上报发射':'上报未发射') : d.status_label}}</small></div>
      </section>
      <section class="rail-targets"><h3>无人机目标 <span>{{data?.targets.length||0}}</span></h3>
        <button v-for="t in data?.targets" :key="t.id" class="rail-target" :class="{active:t.id===target?.id,stale:t.stale}" @click="chooseTarget(t.id)"><span class="rail-aircraft">✦</span><span class="rail-target-name">{{t.name}}<small>{{t.stale?'观测过期':(t.assessments.find(a=>a.position_id===point?.id)?.level_label||'待评估')}} · {{t.speed.toFixed(1)}} m/s</small></span><span class="rail-level" :style="{background:t.stale?'#748195':t.assessments.find(a=>a.position_id===point?.id)?.color||'#748195'}"></span></button>
      </section>
    </aside>
    <nav class="knowledge-nav" aria-label="本体导航"><a href="#alarm-panel">告警看板</a><button @click="openLearning">本体学习工作台</button><button @click="openDevices()">设备与阵地关系</button><button @click="openEvidence">多源观测与证据</button><button @click="openKnowledge('structure')">TBox · 类与属性定义</button><button @click="openKnowledge('abox')">ABox · 实例与关系</button></nav>
    <section id="alarm-panel" class="alarm-panel" :class="{urgent:alarmEntries.some(a=>a.level==='HighAttention')}" aria-labelledby="alarm-title">
      <div class="alarm-heading"><h2 id="alarm-title">{{mode==='live'?'实时距离告警':'历史快照 · 距离告警'}}</h2><strong>{{alarmEntries.length}} 条关注 · {{staleTargets.length}} 架数据过期</strong><span>{{formatTime(data?.at)}}</span></div>
      <p class="alarm-help">覆盖所有阵地，同一无人机可关联多条告警；仅按距离分级，不代表黑飞或综合威胁。{{mode==='live'?'随实时态势刷新。':'当前显示历史数据。'}}</p>
      <div class="alarm-list" aria-label="距离告警列表"><button v-for="a in alarmEntries" :key="a.id" class="alarm-card" :style="{'--alarm-color':a.color}" @click="choosePosition(a.position_id);inspect(a)"><strong>{{a.level_label}}</strong><b>{{a.target_name}} → {{a.position_name}}</b><span>{{a.distance.toFixed(1)}} 米 · 查看依据 ↗</span></button><p v-if="!alarmEntries.length">{{!data?'正在加载态势…':!data.targets.length?'等待无人机观测':pendingCount?'规则已变更，等待新观测完成评估':staleTargets.length?'暂无有效距离告警，存在过期数据':'当前无距离分级告警'}}</p></div>
      <div v-if="staleTargets.length || pendingCount" class="data-warning"><span v-for="t in staleTargets" :key="t.id">数据过期：{{t.name}}（{{t.age_seconds}} 秒前）</span><span v-if="pendingCount">{{pendingCount}} 条评估等待新规则生效</span></div>
    </section>
    <div class="replay-bar panel">
      <span class="mode-label" :class="{historical:mode==='replay'}">{{mode==='live'?'实时态势':mode==='loading'?'加载历史中':'历史快照 · 只读'}}</span>
      <button @click="loadHistory" :disabled="!target||mode==='loading'">加载选中目标历史</button>
      <template v-if="mode==='replay'">
        <button @click="togglePlayback" :disabled="records.length<2">{{playing?'暂停回放':'播放回放'}}</button>
        <input aria-label="回放进度" class="timeline" type="range" min="0" :max="records.length-1" v-model.number="frame" @input="stopPlayback();seek()">
        <span class="frame-label">{{frame+1}} / {{records.length}} · {{formatTime(records[frame]?.timestamp)}}</span><button @click="live">返回实时</button>
      </template>
      <div v-if="mode==='live'&&viewMode==='screen'" class="live-observation-line"><span>{{target?.name||'等待目标'}} · 已观测 {{recentTrail.length}} 点</span><div class="observation-track" aria-label="近期已观测位置时间线"><i v-for="p in recentTrail.slice(-20)" :key="p.timestamp" :title="formatTime(p.timestamp)"></i></div><span>{{formatTime(target?.timestamp)}}</span></div>
      <span v-else class="muted replay-help">实时接入持续运行，回放不会发布或修改数据。</span>
    </div>
    <section class="situation-grid">
      <div class="panel map-panel">
        <div class="panel-heading"><h2><span class="section-index">01</span>{{mode==='replay'?'历史态势':'实时态势'}}</h2><div><label class="follow"><input type="checkbox" v-model="follow">跟随目标</label><button @click="locate">定位全景 ↗</button></div></div>
        <div class="map-controls"><label><input type="checkbox" v-model="showTrails" @change="draw">无人机轨迹</label><label><input type="checkbox" v-model="showRanges" @change="draw">距离分级圈</label><button @click="openDevices()">设备与关系</button><span>圆形：无人机 · 旗标：阵地 · 雷达标：雷达 · 菱形：干扰器</span></div>
        <div class="map-wrap"><div id="map"></div><div class="map-badge">{{status}} · {{point?.name || '等待阵地'}}<span v-if="data">{{formatTime(data.at)}}</span></div><div v-if="mapMessage" class="tile-notice">{{mapMessage}}</div><div class="legend"><span><i style="background:#e45555"></i>高关注</span><span><i style="background:#ed9b32"></i>中关注</span><span><i style="background:#3899ce"></i>低关注</span><span><i style="background:#5aab87"></i>阈值外</span></div></div>
        <div class="map-caption">WGS84 · 水平距离 / 米<span>颜色针对选中阵地；距离远近不等于综合威胁</span></div>
      </div>
      <aside class="panel details">
        <div class="panel-heading"><h2><span class="section-index">02</span>对象详情</h2><span class="tag">实例</span></div>
        <div class="selection-fields"><label>无人机<select aria-label="选择无人机" :value="target?.id" @change="chooseTarget($event.target.value)"><option v-for="t in data?.targets" :value="t.id">{{t.name}}</option></select></label><label>阵地<select aria-label="选择阵地" :value="point?.id" @change="choosePosition($event.target.value)"><option v-for="p in data?.positions" :value="p.id">{{p.name}}</option></select></label></div>
        <template v-if="target"><div class="object-state" :style="{color:target.stale?'#87939e':assessment?.color}">● {{target.stale?'观测数据已过期':assessment?.level_label||'待新观测评估'}}</div>
          <dl><div><dt>经度 / 纬度</dt><dd>{{target.lon.toFixed(6)}} / {{target.lat.toFixed(6)}}</dd></div><div><dt>速度</dt><dd>{{target.speed.toFixed(1)}} m/s</dd></div><div><dt>到选中阵地距离</dt><dd>{{assessment ? assessment.distance.toFixed(1)+' m':'待评估'}}</dd></div><div><dt>数据来源</dt><dd>{{target.source}} · {{({simulated:"模拟数据",operational:"业务接入声明（未验证）"})[target.data_mode]||"来源待核实"}}</dd></div><div><dt>观测时间</dt><dd>{{formatTime(target.timestamp)}}</dd></div></dl>
          <div v-if="assessment?.config_pending" class="pending">配置已更新，等待此目标的下一条观测。</div>
          <div class="relation-card"><span>一架无人机 · 多个独立评估</span><button v-for="a in target.assessments" :key="a.id" class="assessment-chip" @click="choosePosition(a.position_id);inspect(a)"><b>{{a.position_name}}</b><span :style="{color:a.color}">{{a.distance.toFixed(1)}}m · {{a.level_label}}</span></button></div>
          <button class="wide-button" @click="openKnowledge('instance')">查看选中目标的 RDF 事实 ↓</button>
        </template><div v-else class="empty">{{loading?'正在连接数据服务':'等待模拟器发布观测'}}</div>
      </aside>
    </section>
    <aside class="screen-insights" aria-label="当前关注与本体事实">
      <div class="screen-rail-head"><h2>当前关注</h2><span>{{mode==='live'?'实时':'历史快照'}}</span></div>
      <div class="insight-scroll">
        <section class="focus-card" :style="{'--focus-color':target?.stale?'#899bad':assessment?.color||'#6e8da4'}" v-if="target">
          <div class="focus-top"><span class="focus-symbol">✦</span><div><h3>{{target.name}}</h3><small>{{target.stale?'数据过期':assessment?.level_label||'等待新观测'}}</small></div></div>
          <p>与{{point?.name||'选中阵地'}}的水平距离</p><strong>{{assessment?assessment.distance.toFixed(1):'—'}}<small> 米</small></strong>
          <dl><div><dt>速度</dt><dd>{{target.speed.toFixed(1)}} m/s</dd></div><div><dt>观测时间</dt><dd>{{formatTime(target.timestamp)}}</dd></div><div v-if="mode==='live'&&selectedDevice?.state?.transform"><dt>演示高度</dt><dd>{{selectedDevice.state.transform.altitude_m?.toFixed(0)||'—'}} m</dd></div><div v-if="mode==='live'&&selectedDevice?.parameters?.demo_route_profile"><dt>合成航线</dt><dd>{{selectedDevice.parameters.demo_route_profile}}</dd></div></dl>
          <div class="focus-disclaimer">仅按距离分级，不代表黑飞或综合威胁。</div>
        </section>
        <section class="insight-section"><div class="insight-title"><h3>距离关注</h3><span>{{alarmEntries.length}} 条</span></div><div class="insight-alerts"><button v-for="a in alarmEntries.slice(0,5)" :key="a.id" :style="{'--alarm-color':a.color}" @click="choosePosition(a.position_id);inspect(a)"><b>{{a.target_name}}</b><span>{{a.position_name}} · {{a.distance.toFixed(0)}} 米</span><strong>{{a.level_label}}</strong></button><p v-if="!alarmEntries.length">暂无有效距离关注；等待观测或目标位于阈值外。</p></div></section>
        <section class="insight-section"><div class="insight-title"><h3>数据来源与处理</h3><span>可追溯</span></div><div class="source-flow"><span>{{target?.data_mode==='simulated'?'模拟 MQTT':target?.source||'待接入'}}<br><small>上报观测</small></span><b>→</b><span>Python<br><small>计算距离</small></span><b>→</b><span>RDF<br><small>记录评估</small></span></div><p class="source-note">{{target?.data_mode==='simulated'?'当前是合成演示数据。':'当前来源须按接入记录核实。'}}雷达、干扰器状态不等于探测或干扰效果。</p></section>
        <section class="insight-section"><div class="insight-title"><h3>本体关系 · RDF/OWL</h3><button @click="openDevices()">查看设备 ↗</button></div><p class="ontology-relation" v-for="d in selectedDeployments" :key="d.id"><b>{{d.name}}</b><span>部署于</span><b>{{point?.name}}</b></p><p class="ontology-relation"><b>{{target?.name||'无人机'}}</b><span>关联独立距离评估</span><b>{{point?.name||'阵地'}}</b></p><small class="source-note">无人机不隶属于阵地；关系可在学习工作台查证。</small></section>
        <section class="insight-section"><div class="insight-title"><h3>本体查询与验证</h3><span>学习入口</span></div><div class="insight-actions"><button @click="openKnowledge('structure')">TBox 类定义</button><button @click="openKnowledge('abox')">ABox 实例</button><button @click="openKnowledge('instance')">TTL 文本</button><button @click="openLearning">SPARQL / SHACL ↗</button></div></section>
      </div>
    </aside>
    <section class="analysis-grid">
      <div class="panel ranking-panel"><div class="panel-heading"><h2><span class="section-index">03</span>{{point?.name || '阵地'}} · 距离排序</h2><span class="tag">近 → 远</span></div>
        <div class="table-scroll"><table><thead><tr><th>目标</th><th>水平距离</th><th>等级 / 状态</th><th>依据</th></tr></thead><tbody><tr v-for="a in ranked" :key="a.id" :class="{selected:a.target_id===target?.id}"><td><button class="text-button" @click="chooseTarget(a.target_id)">{{a.target_name}}</button></td><td>{{a.distance.toFixed(1)}} m</td><td><span :style="{color:a.stale?'#87939e':a.color}">{{a.level_label}}</span><small v-if="a.stale"> · 过期</small><small v-if="a.config_pending"> · 旧配置</small></td><td><button @click="inspect(a)">查看评估</button></td></tr><tr v-if="!ranked.length"><td colspan="4">该阵地暂无评估，等待新观测。</td></tr></tbody></table></div>
        <div class="ontology-footer">仅依据水平距离排序；过期数据保留展示，不作为当前有效判断。</div>
      </div>
      <div class="panel explanation-panel"><div class="panel-heading"><h2><span class="section-index">04</span>评估依据与关联链</h2><button v-if="trace" @click="trace=null">跟随最新</button><span v-else class="tag">跟随最新</span></div>
        <template v-if="explanation"><div class="explanation-content"><div class="chain"><span>{{explanation.target_name}}</span><b>→</b><span>观测记录</span><b>→</b><span>评估记录</span><b>→</b><span>{{explanation.position_name}}</span></div><div class="reason" :style="{borderColor:explanation.color}"><b :style="{color:explanation.color}">{{explanation.level_label}}</b><span>{{explanation.reason}}</span></div><dl><div><dt>观测来源</dt><dd>{{explanation.source}}</dd></div><div><dt>评估时间</dt><dd>{{formatTime(explanation.timestamp)}}</dd></div><div><dt>观测标识</dt><dd class="mono">{{explanation.observation_id}}</dd></div><div><dt>规则版本</dt><dd class="mono">{{explanation.rule_version}}</dd></div><div><dt>当时阵地坐标</dt><dd>{{explanation.position_lon.toFixed(6)}} / {{explanation.position_lat.toFixed(6)}}</dd></div><div><dt>阈值（高 / 中 / 低）</dt><dd>{{explanation.thresholds.join(' / ')}} m</dd></div></dl><div class="muted trace-note">{{trace?'已锁定这条评估，实时更新不会改变它；历史保留到期后可被清理。':'每条评估关联一条观测、一处阵地和一个规则版本。'}}</div></div></template><div v-else class="empty">点击左侧“查看评估”，了解判断依据。</div>
      </div>
    </section>
    <section id="knowledge-panel" class="panel ontology-panel"><div class="panel-heading ontology-heading"><h2><span class="section-index">05</span>TBox / ABox · 本体与事实</h2><div class="tabs"><button :class="{active:tab==='structure'}" @click="selectTab('structure')">TBox 中文结构</button><button :class="{active:tab==='definition'}" @click="selectTab('definition')">TBox 定义 TTL</button><button :class="{active:tab==='abox'}" @click="selectTab('abox')">ABox 实时实例</button><button :class="{active:tab==='instance'}" @click="selectTab('instance')">选中实例 TTL</button></div><button v-if="tab==='definition'||tab==='instance'" @click="copy">复制文本</button></div>
      <div v-if="tab==='structure'" class="structure-grid"><div v-for="g in groups" :key="g.kind"><div class="group-heading">{{g.kind}}<span>{{g.items.length}}</span></div><div v-for="item in g.items" :key="item.id" class="schema-row"><div><b>{{item.label}}</b><code>{{item.id}}</code></div><small>{{item.comment || ('取值：'+item.range)}}</small></div></div></div>
      <div v-else-if="tab==='abox'" class="abox-view"><div class="code-note">ABox（实例事实）：{{mode==='live'?'当前实时态势，每秒轮询更新':'回放时间的历史快照'}} · {{formatTime(data?.at)}}。此处展示当前态势投影，并非全部历史 RDF 数据。</div>
        <div class="abox-summary"><span>无人机实例 {{data?.targets.length||0}}</span><span>阵地实例 {{data?.positions.length||0}}</span><span>评估实例 {{data?.assessments.length||0}}</span></div>
        <div class="abox-grid"><article v-for="t in data?.targets" :key="t.id"><h3>{{t.name}} <small>无人机实例</small></h3><code>{{t.uri || t.id}}</code><p>位置：{{t.lon}}, {{t.lat}} · 来源：{{t.source || '—'}}</p><p>观测：{{t.observation_id || '—'}} · {{formatTime(t.timestamp)}} {{t.stale?'（已过期）':''}}</p><button @click="chooseTarget(t.id);selectTab('instance')">查看该目标 TTL</button></article><article v-for="p in data?.positions" :key="p.id"><h3>{{p.name}} <small>阵地实例</small></h3><code>{{p.id}}</code><p>位置：{{p.lon}}, {{p.lat}}</p></article></div>
        <div class="abox-table"><table><thead><tr><th>评估实例</th><th>关联无人机 → 阵地</th><th>关联观测 / 规则</th><th>事实与依据</th></tr></thead><tbody><tr v-for="a in data?.assessments" :key="a.id"><td><code>{{a.id}}</code></td><td>{{a.target_name}} → {{a.position_name}}</td><td><code>{{a.observation_id}}</code><br><code>{{a.rule_version}}</code></td><td><button @click="choosePosition(a.position_id);inspect(a)">{{a.distance.toFixed(1)}} 米 · {{a.level_label}} · 查看依据</button><small>{{a.stale?'数据过期':a.config_pending?'等待新规则评估':''}}</small></td></tr></tbody></table></div><p v-if="!data?.targets.length" class="code-note">暂无无人机实例，等待 MQTT 观测数据。</p>
      </div>
      <div v-else class="code-section"><div class="code-note">{{tab==='definition'?'模型定义：新增观测记录、评估记录和规则类别。':mode==='replay'?'历史快照：显示回放时间对应的观测、评估和规则，不是当前实时状态。':'最新事实：无人机通过当前评估关联观测、阵地和规则。'}}</div><pre><code>{{tab==='definition'?definition:instance||'暂无目标实例'}}</code></pre></div>
      <div class="ontology-footer"><span>对象属性连接对象，数据属性连接数值；距离和等级属于评估记录。</span><span>Python 计算 · RDF/OWL 表达 · SPARQL 查询</span></div>
    </section>
    <p v-if="deviceError" class="alert">设备状态读取失败：{{deviceError}}；保留上次记录，请核对时间。</p>
    <DeviceWorkbench :request="request" :data="deviceData" :selected-id="selectedDeviceId" :locate="locateDevice" :replay="mode!=='live'" />
    <LearningWorkbench :request="request" :data="data" :mode="mode" :highlight="highlightQuery" :focus-row="focusQueryRow" />
    <EvidenceWorkbench :request="request" :active="viewMode==='learning'" :locate="locateEvidence" :clear-point="clearEvidencePoint" />
    <footer>AirOntology<span>从观测到评估，理解业务关系。</span><span>有界历史 · 不启用自动推理</span></footer>
  </main>
  <AgentPanel :request="request" :data="data" :point="point" :mode="mode" :locate-candidate="locateAgentCandidate" />
  <div v-if="configOpen&&draft" class="modal-backdrop" @click.self="configOpen=false"><section class="config-modal" role="dialog" aria-modal="true" aria-labelledby="config-title"><div class="panel-heading"><h2 id="config-title">阵地与距离规则</h2><button @click="configOpen=false">关闭</button></div><form @submit.prevent="saveConfig"><p class="config-tip">配置存入 Fuseki，重启后保留。从下一条观测生效，过去的评估不重算。初始环境变量不覆盖已保存配置。</p><div v-if="configError" role="alert" class="alert">{{configError}}</div><div class="config-positions"><div v-for="(p,index) in draft.positions" :key="index" class="config-position"><label>编号<input required pattern="[A-Za-z0-9_-]{1,100}" v-model="p.id"></label><label>名称<input required maxlength="80" v-model="p.name"></label><label>经度<input required type="number" step="any" min="-180" max="180" v-model.number="p.lon"></label><label>纬度<input required type="number" step="any" min="-90" max="90" v-model.number="p.lat"></label><button type="button" @click="draft.positions.splice(index,1)" :disabled="draft.positions.length===1">删除</button></div></div><button type="button" @click="addPosition" :disabled="draft.positions.length>=10">＋ 添加阵地（最多10处）</button><div class="rule-inputs"><label>高关注阈值 / 米<input required type="number" step="any" min="0.001" v-model.number="draft.high_threshold"></label><label>中关注阈值 / 米<input required type="number" step="any" min="0.001" v-model.number="draft.medium_threshold"></label><label>低关注阈值 / 米<input required type="number" step="any" min="0.001" max="100000" v-model.number="draft.low_threshold"></label><label>数据过期时间 / 秒<input required type="number" min="2" max="3600" step="any" v-model.number="draft.stale_seconds"></label><label>每目标保留观测数<input required type="number" min="10" max="1000" step="1" v-model.number="draft.history_limit"></label></div><p class="muted">必须满足：高阈值 &lt; 中阈值 &lt; 低阈值。历史数量减少后会清理旧记录。</p><div class="config-actions"><small>当前版本：{{configVersion}}</small><button type="submit" :disabled="saving">{{saving?'正在保存…':'保存配置'}}</button></div></form></section></div>
  <div v-if="toast" class="toast" role="status">{{toast}}</div>
</div>`;
