export default `
<div class="workspace">
  <header>
    <div class="brand-mark">A<span>O</span></div><div class="brand">AirOntology<small>无人机本体 · 观测与评估工作台</small></div>
    <span class="edition">DEMO / V2.0</span>
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
    <div class="replay-bar panel">
      <span class="mode-label" :class="{historical:mode==='replay'}">{{mode==='live'?'实时态势':mode==='loading'?'加载历史中':'历史快照 · 只读'}}</span>
      <button @click="loadHistory" :disabled="!target||mode==='loading'">加载选中目标历史</button>
      <template v-if="mode==='replay'">
        <button @click="togglePlayback" :disabled="records.length<2">{{playing?'暂停回放':'播放回放'}}</button>
        <input aria-label="回放进度" class="timeline" type="range" min="0" :max="records.length-1" v-model.number="frame" @input="stopPlayback();seek()">
        <span class="frame-label">{{frame+1}} / {{records.length}} · {{formatTime(records[frame]?.timestamp)}}</span><button @click="live">返回实时</button>
      </template>
      <span v-else class="muted replay-help">实时接入持续运行，回放不会发布或修改数据。</span>
    </div>
    <section class="situation-grid">
      <div class="panel map-panel">
        <div class="panel-heading"><h2><span class="section-index">01</span>{{mode==='replay'?'历史态势':'实时态势'}}</h2><div><label class="follow"><input type="checkbox" v-model="follow">跟随目标</label><button @click="locate">定位全景 ↗</button></div></div>
        <div class="map-controls"><label><input type="checkbox" v-model="showTrails" @change="draw">无人机轨迹</label><label><input type="checkbox" v-model="showRanges" @change="draw">距离分级圈</label><span>圆形：无人机 · 方形旗标：阵地</span></div>
        <div class="map-wrap"><div id="map"></div><div class="map-badge">{{status}} · {{point?.name || '等待阵地'}}<span v-if="data">{{formatTime(data.at)}}</span></div><div v-if="mapMessage" class="tile-notice">{{mapMessage}}</div><div class="legend"><span><i style="background:#e45555"></i>高关注</span><span><i style="background:#ed9b32"></i>中关注</span><span><i style="background:#3899ce"></i>低关注</span><span><i style="background:#5aab87"></i>阈值外</span></div></div>
        <div class="map-caption">WGS84 · 水平距离 / 米<span>颜色针对选中阵地；距离远近不等于综合威胁</span></div>
      </div>
      <aside class="panel details">
        <div class="panel-heading"><h2><span class="section-index">02</span>对象详情</h2><span class="tag">实例</span></div>
        <div class="selection-fields"><label>无人机<select aria-label="选择无人机" :value="target?.id" @change="chooseTarget($event.target.value)"><option v-for="t in data?.targets" :value="t.id">{{t.name}}</option></select></label><label>阵地<select aria-label="选择阵地" :value="point?.id" @change="choosePosition($event.target.value)"><option v-for="p in data?.positions" :value="p.id">{{p.name}}</option></select></label></div>
        <template v-if="target"><div class="object-state" :style="{color:target.stale?'#87939e':assessment?.color}">● {{target.stale?'观测数据已过期':assessment?.level_label||'待新观测评估'}}</div>
          <dl><div><dt>经度 / 纬度</dt><dd>{{target.lon.toFixed(6)}} / {{target.lat.toFixed(6)}}</dd></div><div><dt>速度</dt><dd>{{target.speed.toFixed(1)}} m/s</dd></div><div><dt>到选中阵地距离</dt><dd>{{assessment ? assessment.distance.toFixed(1)+' m':'待评估'}}</dd></div><div><dt>数据来源</dt><dd>{{target.source}}</dd></div><div><dt>观测时间</dt><dd>{{formatTime(target.timestamp)}}</dd></div></dl>
          <div v-if="assessment?.config_pending" class="pending">配置已更新，等待此目标的下一条观测。</div>
          <div class="relation-card"><span>一架无人机 · 多个独立评估</span><button v-for="a in target.assessments" :key="a.id" class="assessment-chip" @click="choosePosition(a.position_id);inspect(a)"><b>{{a.position_name}}</b><span :style="{color:a.color}">{{a.distance.toFixed(1)}}m · {{a.level_label}}</span></button></div>
          <button class="wide-button" @click="selectTab('instance')">查看选中目标的 RDF 事实 ↓</button>
        </template><div v-else class="empty">{{loading?'正在连接数据服务':'等待模拟器发布观测'}}</div>
      </aside>
    </section>
    <section class="analysis-grid">
      <div class="panel ranking-panel"><div class="panel-heading"><h2><span class="section-index">03</span>{{point?.name || '阵地'}} · 距离排序</h2><span class="tag">近 → 远</span></div>
        <div class="table-scroll"><table><thead><tr><th>目标</th><th>水平距离</th><th>等级 / 状态</th><th>依据</th></tr></thead><tbody><tr v-for="a in ranked" :key="a.id" :class="{selected:a.target_id===target?.id}"><td><button class="text-button" @click="chooseTarget(a.target_id)">{{a.target_name}}</button></td><td>{{a.distance.toFixed(1)}} m</td><td><span :style="{color:a.stale?'#87939e':a.color}">{{a.level_label}}</span><small v-if="a.stale"> · 过期</small><small v-if="a.config_pending"> · 旧配置</small></td><td><button @click="inspect(a)">查看评估</button></td></tr><tr v-if="!ranked.length"><td colspan="4">该阵地暂无评估，等待新观测。</td></tr></tbody></table></div>
        <div class="ontology-footer">仅依据水平距离排序；过期数据保留展示，不作为当前有效判断。</div>
      </div>
      <div class="panel explanation-panel"><div class="panel-heading"><h2><span class="section-index">04</span>评估依据与关联链</h2><button v-if="trace" @click="trace=null">跟随最新</button><span v-else class="tag">跟随最新</span></div>
        <template v-if="explanation"><div class="explanation-content"><div class="chain"><span>{{explanation.target_name}}</span><b>→</b><span>观测记录</span><b>→</b><span>评估记录</span><b>→</b><span>{{explanation.position_name}}</span></div><div class="reason" :style="{borderColor:explanation.color}"><b :style="{color:explanation.color}">{{explanation.level_label}}</b><span>{{explanation.reason}}</span></div><dl><div><dt>观测来源</dt><dd>{{explanation.source}}</dd></div><div><dt>评估时间</dt><dd>{{formatTime(explanation.timestamp)}}</dd></div><div><dt>观测标识</dt><dd class="mono">{{explanation.observation_id}}</dd></div><div><dt>规则版本</dt><dd class="mono">{{explanation.rule_version}}</dd></div><div><dt>当时阵地坐标</dt><dd>{{explanation.position_lon.toFixed(6)}} / {{explanation.position_lat.toFixed(6)}}</dd></div><div><dt>阈值（高 / 中 / 低）</dt><dd>{{explanation.thresholds.join(' / ')}} m</dd></div></dl><div class="muted trace-note">{{trace?'已锁定这条评估，实时更新不会改变它；历史保留到期后可被清理。':'每条评估关联一条观测、一处阵地和一个规则版本。'}}</div></div></template><div v-else class="empty">点击左侧“查看评估”，了解判断依据。</div>
      </div>
    </section>
    <section class="panel ontology-panel"><div class="panel-heading ontology-heading"><h2><span class="section-index">05</span>本体与事实</h2><div class="tabs"><button :class="{active:tab==='structure'}" @click="selectTab('structure')">中文结构</button><button :class="{active:tab==='definition'}" @click="selectTab('definition')">本体定义 TTL</button><button :class="{active:tab==='instance'}" @click="selectTab('instance')">当前实例 TTL</button></div><button v-if="tab!=='structure'" @click="copy">复制文本</button></div>
      <div v-if="tab==='structure'" class="structure-grid"><div v-for="g in groups" :key="g.kind"><div class="group-heading">{{g.kind}}<span>{{g.items.length}}</span></div><div v-for="item in g.items" :key="item.id" class="schema-row"><div><b>{{item.label}}</b><code>{{item.id}}</code></div><small>{{item.comment || ('取值：'+item.range)}}</small></div></div></div>
      <div v-else class="code-section"><div class="code-note">{{tab==='definition'?'模型定义：新增观测记录、评估记录和规则类别。':mode==='replay'?'历史快照：显示回放时间对应的观测、评估和规则，不是当前实时状态。':'最新事实：无人机通过当前评估关联观测、阵地和规则。'}}</div><pre><code>{{tab==='definition'?definition:instance||'暂无目标实例'}}</code></pre></div>
      <div class="ontology-footer"><span>对象属性连接对象，数据属性连接数值；距离和等级属于评估记录。</span><span>Python 计算 · RDF/OWL 表达 · SPARQL 查询</span></div>
    </section>
    <footer>AirOntology<span>从观测到评估，理解业务关系。</span><span>有界历史 · 不启用自动推理</span></footer>
  </main>
  <div v-if="configOpen&&draft" class="modal-backdrop" @click.self="configOpen=false"><section class="config-modal" role="dialog" aria-modal="true" aria-labelledby="config-title"><div class="panel-heading"><h2 id="config-title">阵地与距离规则</h2><button @click="configOpen=false">关闭</button></div><form @submit.prevent="saveConfig"><p class="config-tip">配置存入 Fuseki，重启后保留。从下一条观测生效，过去的评估不重算。初始环境变量不覆盖已保存配置。</p><div v-if="configError" role="alert" class="alert">{{configError}}</div><div class="config-positions"><div v-for="(p,index) in draft.positions" :key="index" class="config-position"><label>编号<input required pattern="[A-Za-z0-9_-]{1,100}" v-model="p.id"></label><label>名称<input required maxlength="80" v-model="p.name"></label><label>经度<input required type="number" step="any" min="-180" max="180" v-model.number="p.lon"></label><label>纬度<input required type="number" step="any" min="-90" max="90" v-model.number="p.lat"></label><button type="button" @click="draft.positions.splice(index,1)" :disabled="draft.positions.length===1">删除</button></div></div><button type="button" @click="addPosition" :disabled="draft.positions.length>=10">＋ 添加阵地（最多10处）</button><div class="rule-inputs"><label>高关注阈值 / 米<input required type="number" step="any" min="0.001" v-model.number="draft.high_threshold"></label><label>中关注阈值 / 米<input required type="number" step="any" min="0.001" v-model.number="draft.medium_threshold"></label><label>低关注阈值 / 米<input required type="number" step="any" min="0.001" max="100000" v-model.number="draft.low_threshold"></label><label>数据过期时间 / 秒<input required type="number" min="2" max="3600" step="any" v-model.number="draft.stale_seconds"></label><label>每目标保留观测数<input required type="number" min="10" max="1000" step="1" v-model.number="draft.history_limit"></label></div><p class="muted">必须满足：高阈值 &lt; 中阈值 &lt; 低阈值。历史数量减少后会清理旧记录。</p><div class="config-actions"><small>当前版本：{{configVersion}}</small><button type="submit" :disabled="saving">{{saving?'正在保存…':'保存配置'}}</button></div></form></section></div>
  <div v-if="toast" class="toast" role="status">{{toast}}</div>
</div>`;
