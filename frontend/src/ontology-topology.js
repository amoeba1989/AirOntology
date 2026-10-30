import { computed, ref, watch } from 'vue/dist/vue.esm-bundler.js';

const CU = 'http://counteruav.org/counterUav#';
const node = (key, label, kind, classId, id, uri, x, y, detail = '') =>
  ({ key, label, kind, classId, id, uri, x, y, detail });
const edge = (from, to, property, label, x, y) =>
  ({ from, to, property, label, x, y, kind: 'object' });

// 仅投影接口已读到的 RDF 关系。ABox 随实时态势更新；TBox 描述静态模型。
export function buildTopology({ target, assessment, position, device, schema = false, preview = false }) {
  if (device && device.kind !== 'uav') {
    const classId = device.kind === 'radar' ? 'RadarSensor' : 'Jammer';
    const className = device.kind === 'radar' ? '雷达设备' : '干扰器';
    const kind = schema ? 'class' : 'individual';
    const nodes = [node('entity', schema ? className : device.name, kind, classId,
      schema ? classId : device.id, schema ? CU + classId : device.uri || CU + device.id,
      50, 17, schema ? '设备类别；具体部署事实见 ABox。' : device.status_label)];
    const edges = [];
    if (schema || (device.deployed_at && position?.id === device.deployed_at)) {
      nodes.push(node('position', schema ? '阵地' : position.name, kind, 'Position',
        schema ? 'Position' : position.id, CU + (schema ? 'Position' : position.id), 20, 76,
        preview ? '部署关系来自本地模拟设备登记。' : '部署关系来自 MQTT 设备登记。'));
      edges.push(edge('entity', 'position', 'deployedAt', '部署于', 25, 46));
    }
    if (schema || device.state) {
      nodes.push(node('state', schema ? '设备状态' : '最近状态', kind, 'DeviceState',
        schema ? 'DeviceState' : `state-${device.id}`,
        schema ? CU + 'DeviceState' : `urn:airontology:telemetry:state-${device.id}`, 80, 76,
        schema ? '状态与设备分开建模。' : `${device.status_label} · 帧 ${device.state_tick || '—'}`));
      edges.push(edge('entity', 'state', 'latestDeviceState', '最新状态', 75, 46));
    }
    return { nodes, edges, note: schema ? '类之间的对象属性定义' : '登记部署与最近一帧设备状态；不代表探测或干扰效果。' };
  }
  if (!target) return { nodes: [], edges: [], note: '等待地图中的无人机观测。' };
  const kind = schema ? 'class' : 'individual';
  const nodes = [node('entity', schema ? '无人机目标' : target.name, kind, 'BlueDevice',
    schema ? 'BlueDevice' : target.id, schema ? CU + 'BlueDevice' : target.uri || CU + target.id,
    19, 19, schema ? '持续存在的目标类。' : `${target.stale ? '观测过期' : '当前观测'} · ${target.timestamp || '—'}`)];
  const edges = [];
  if (schema || target.observation_id) {
    nodes.push(node('observation', schema ? '观测记录' : '最新观测', kind, 'Observation',
      schema ? 'Observation' : target.observation_id,
      CU + (schema ? 'Observation' : target.observation_id), 81, 19,
      schema ? '某来源某时刻的观测记录。' : `${target.source || '来源待核实'} · ${target.timestamp || '—'}`));
    edges.push(edge('entity', 'observation', 'latestObservation', '最新观测', 50, 34));
  }
  if (schema || assessment) {
    nodes.push(node('assessment', schema ? '评估记录' : '距离评估', kind, 'Assessment',
      schema ? 'Assessment' : assessment.id, schema ? CU + 'Assessment' : assessment.uri || CU + assessment.id,
      50, 53, schema ? '按选中阵地独立生成的评估。' : `${assessment.distance.toFixed(1)} 米 · ${assessment.level_label}${assessment.config_pending ? ' · 旧规则' : ''}`));
    edges.push(edge('entity', 'assessment', 'latestAssessment', '当前评估', 29, 39));
    if (schema || assessment?.observation_id === target.observation_id)
      edges.push(edge('assessment', 'observation', 'basedOnObservation', '依据观测', 72, 39));
  }
  if (schema || (assessment && position?.id === assessment.position_id)) {
    nodes.push(node('position', schema ? '阵地' : position.name, kind, 'Position',
      schema ? 'Position' : position.id, CU + (schema ? 'Position' : position.id), 19, 85,
      schema ? '评估针对的阵地类别。' : '无人机不隶属于阵地；评估只针对这处阵地。'));
    edges.push(edge('assessment', 'position', 'toPosition', '针对阵地', 29, 72));
  }
  if (schema || assessment?.rule_version) {
    nodes.push(node('rule', schema ? '距离规则' : '规则快照', kind, 'DistanceRule',
      schema ? 'DistanceRule' : assessment.rule_version,
      CU + (schema ? 'DistanceRule' : assessment.rule_version), 81, 85,
      schema ? '每次评估保留当时的规则版本。' : `${assessment.thresholds?.join(' / ') || '—'} 米（高 / 中 / 低）`));
    edges.push(edge('assessment', 'rule', 'usedRule', '采用规则', 72, 72));
  }
  return { nodes, edges, note: schema ? 'TBox：类与对象属性的定义。' : preview ? 'ABox：当前事实来自本地模拟观测；无人机不隶属于阵地。' : 'ABox：当前事实随 MQTT 观测更新；无人机不隶属于阵地。' };
}

// 箭头从 RDF 三元组的主语指向宾语，止于节点边界。
export function lineFor(edgeData, nodes) {
  const a = nodes.find(n => n.key === edgeData.from);
  const b = nodes.find(n => n.key === edgeData.to);
  if (!a || !b) return null;
  const dx = (b.x - a.x) * 3.6, dy = (b.y - a.y) * 2.8;
  const distance = Math.hypot(dx, dy) || 1;
  const ux = dx / distance, uy = dy / distance;
  return { ...edgeData,
    x1: a.x * 3.6 + ux * 42, y1: a.y * 2.8 + uy * 27,
    x2: b.x * 3.6 - ux * 48, y2: b.y * 2.8 - uy * 31,
    labelX: edgeData.x * 3.6, labelY: edgeData.y * 2.8,
  };
}

export default {
  props: ['target', 'assessment', 'position', 'device', 'mode', 'preview'],
  setup(props) {
    const tab = ref('abox'), selectedNode = ref('entity');
    const topology = computed(() => buildTopology({
      target: props.target, assessment: props.assessment, position: props.position,
      device: props.device, schema: tab.value === 'tbox', preview: props.preview,
    }));
    const active = computed(() => topology.value.nodes.find(n => n.key === selectedNode.value) || topology.value.nodes[0]);
    const lines = computed(() => topology.value.edges.map(e => lineFor(e, topology.value.nodes)).filter(Boolean));
    const timestamp = computed(() => props.device?.published_at || props.target?.timestamp || '');
    const eventId = computed(() => props.device ? `帧 ${props.device.state_tick || '—'}` :
      props.target?.observation_id || '等待观测');
    watch(() => `${props.target?.id || ''}|${props.device?.id || ''}`,
      () => { tab.value = 'abox'; selectedNode.value = 'entity'; });
    watch(tab, () => { selectedNode.value = 'entity'; });
    return { tab, selectedNode, topology, active, lines, timestamp, eventId };
  },
  template: `<section class="ontology-live" aria-label="所选对象本体拓扑">
    <div class="ontology-live-head"><div><h3>本体关系 · RDF/OWL</h3><small>{{device?.name || target?.name || '等待目标'}}</small></div>
      <div class="topology-tabs" role="group" aria-label="本体视图"><button :class="{active:tab==='abox'}" @click="tab='abox'">ABox 实时事实</button><button :class="{active:tab==='tbox'}" @click="tab='tbox'">TBox 模型</button></div>
    </div>
    <div class="topology-timestamp" v-if="tab==='abox'"><span class="live-pip" :class="{historical:mode==='replay'}"></span>{{mode==='replay'?'回放快照':'实时订阅投影'}} · {{eventId}}<time :datetime="timestamp">{{timestamp ? new Date(timestamp).toLocaleTimeString('zh-CN',{hour12:false}) : '—'}}</time></div>
    <div class="topology-timestamp" v-else>类与属性定义固定；实例事实请切回 ABox</div>
    <div class="topology-canvas" v-if="topology.nodes.length" :class="{schema:tab==='tbox'}">
      <svg class="topology-links" viewBox="0 0 360 280" preserveAspectRatio="none" aria-hidden="true"><defs><marker id="topology-object-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 10 5 0 10Z" fill="#59bce7"/></marker></defs>
        <g v-for="e in lines" :key="e.property"><line :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2" class="topology-object-edge" marker-end="url(#topology-object-arrow)"/><rect :x="e.labelX-30" :y="e.labelY-10" width="60" height="19" rx="4" class="topology-edge-back"/><text :x="e.labelX" :y="e.labelY+3" text-anchor="middle">{{e.label}}</text></g>
      </svg>
      <button v-for="n in topology.nodes" :key="n.key" class="topology-node" :class="[n.key,n.kind,{active:active?.key===n.key}]" :style="{left:n.x+'%',top:n.y+'%'}" :aria-label="'查看'+(n.kind==='class'?'类':'实例')+n.label" @click="selectedNode=n.key"><small>{{n.kind==='class'?'OWL 类':'RDF 实例'}}</small><b>{{n.label}}</b></button>
    </div>
    <p v-else class="topology-empty">{{topology.note}}</p>
    <div class="topology-legend" aria-label="本体关系图例"><span><i :class="tab==='tbox'?'legend-class':'legend-individual'"></i>{{tab==='tbox'?'类（Class）':'实例（Individual）'}}</span><span><i class="legend-object"></i>对象属性 · 指向宾语</span><span><i class="legend-data"></i>数据属性见下方</span></div>
    <div class="topology-detail" v-if="active"><div><b>{{active.label}}</b><span>{{active.detail}}</span></div><code :title="active.uri">{{active.uri}}</code><p v-if="tab==='abox'&&active.key==='assessment'&&assessment&&!device"><em>cu:distanceToPosition</em> {{assessment.distance.toFixed(1)}} 米 · <em>cu:hasDistanceLevel</em> {{assessment.level_label}}</p><p v-else><em>rdf:type</em> cu:{{active.classId}}</p></div>
    <p class="topology-note">{{topology.note}}</p>
  </section>`,
};
