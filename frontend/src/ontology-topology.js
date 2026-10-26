import { computed, ref, watch } from 'vue/dist/vue.esm-bundler.js';

const CU = 'http://counteruav.org/counterUav#';
const node = (key, label, type, id, uri, x, y, detail = '') => ({ key, label, type, id, uri, x, y, detail });
const edge = (from, to, property, label) => ({ from, to, property, label });

// 主屏只投影已由 /api/situation 和 /api/devices 返回的关系；不臆造探测、干扰或归属关系。
export function buildTopology({ target, assessment, position, device, schema = false }) {
  if (device && device.kind !== 'uav') {
    const classId = device.kind === 'radar' ? 'RadarSensor' : 'Jammer';
    const name = device.kind === 'radar' ? '雷达设备' : '干扰器';
    const nodes = [node('entity', schema ? name : device.name, schema ? '类' : name,
      schema ? classId : device.id, schema ? CU + classId : device.uri || CU + device.id, 50, 20,
      schema ? '设备类定义；部署关系由登记数据给出。' : device.status_label)];
    const edges = [];
    if (schema || (device.deployed_at && position?.id === device.deployed_at)) {
      nodes.push(node('position', schema ? '阵地' : position.name, schema ? '类' : '阵地实例',
        schema ? 'Position' : position.id, schema ? CU + 'Position' : CU + position.id, 20, 77));
      edges.push(edge('entity', 'position', 'deployedAt', '部署于'));
    }
    if (schema || device.state) {
      nodes.push(node('state', schema ? '设备状态' : '最近状态', schema ? '类' : '状态实例',
        schema ? 'DeviceState' : `state-${device.id}`,
        schema ? CU + 'DeviceState' : `urn:airontology:telemetry:state-${device.id}`, 80, 77,
        schema ? '状态与设备分开建模。' : `${device.status_label} · 帧 ${device.state_tick || '—'}`));
      edges.push(edge('entity', 'state', 'latestDeviceState', '最新状态'));
    }
    return { nodes, edges, note: schema ? 'TBox：这里展示设备类、阵地类与对象属性。' : 'ABox：部署关系来自设备登记；状态来自最近一帧 MQTT。' };
  }
  if (!target) return { nodes: [], edges: [], note: '等待地图中的无人机观测。' };
  const nodes = [node('entity', schema ? '无人机目标' : target.name, schema ? '类' : '无人机实例',
    schema ? 'BlueDevice' : target.id, schema ? CU + 'BlueDevice' : target.uri || CU + target.id,
    18, 20, schema ? '持续存在的目标，与每条观测分开。' : `${target.stale ? '观测过期' : '当前观测'} · ${target.timestamp || '—'}`)];
  const edges = [];
  if (schema || target.observation_id) {
    nodes.push(node('observation', schema ? '观测记录' : '最新观测', schema ? '类' : '观测实例',
      schema ? 'Observation' : target.observation_id,
      schema ? CU + 'Observation' : CU + target.observation_id, 82, 20,
      schema ? '某来源在某时刻上报的位置与速度。' : `${target.source || '来源待核实'} · ${target.timestamp || '—'}`));
    edges.push(edge('entity', 'observation', 'latestObservation', '最新观测'));
  }
  if (schema || assessment) {
    nodes.push(node('assessment', schema ? '评估记录' : '距离评估', schema ? '类' : '评估实例',
      schema ? 'Assessment' : assessment.id, schema ? CU + 'Assessment' : assessment.uri || CU + assessment.id,
      50, 50, schema ? '针对目标与阵地的一条独立评估。' : `${assessment.distance.toFixed(1)} 米 · ${assessment.level_label}${assessment.config_pending ? ' · 旧规则' : ''}`));
    edges.push(edge('entity', 'assessment', 'latestAssessment', '当前评估'));
    if (schema || assessment?.observation_id === target.observation_id) {
      edges.push(edge('assessment', 'observation', 'basedOnObservation', '依据观测'));
    }
  }
  if (schema || (assessment && position?.id === assessment.position_id)) {
    nodes.push(node('position', schema ? '阵地' : position.name, schema ? '类' : '阵地实例',
      schema ? 'Position' : position.id, schema ? CU + 'Position' : CU + position.id, 18, 82,
      schema ? '评估针对的固定阵地。' : '仅有关联距离评估；无人机不隶属于阵地。'));
    edges.push(edge('assessment', 'position', 'toPosition', '针对阵地'));
  }
  if (schema || assessment?.rule_version) {
    nodes.push(node('rule', schema ? '距离规则' : '规则快照', schema ? '类' : '规则实例',
      schema ? 'DistanceRule' : assessment.rule_version,
      schema ? CU + 'DistanceRule' : CU + assessment.rule_version, 82, 82,
      schema ? '每次评估保留当时的规则。' : `${assessment.thresholds?.join(' / ') || '—'} 米（高 / 中 / 低）`));
    edges.push(edge('assessment', 'rule', 'usedRule', '采用规则'));
  }
  return { nodes, edges, note: schema ? 'TBox：显示所选目标涉及的类与对象属性，不表示一次具体观测。' : 'ABox：当前 RDF 事实的精简投影；无人机不隶属于阵地。点击节点查看依据。' };
}

export default {
  props: ['target', 'assessment', 'position', 'device', 'mode'],
  setup(props) {
    const tab = ref('abox');
    const selectedNode = ref('entity');
    const topology = computed(() => buildTopology({
      target: props.target, assessment: props.assessment, position: props.position,
      device: props.device, schema: tab.value === 'tbox',
    }));
    const active = computed(() => topology.value.nodes.find(n => n.key === selectedNode.value) || topology.value.nodes[0]);
    const lines = computed(() => topology.value.edges.map(e => ({ ...e,
      fromNode: topology.value.nodes.find(n => n.key === e.from),
      toNode: topology.value.nodes.find(n => n.key === e.to),
    })).filter(e => e.fromNode && e.toNode));
    watch(() => `${props.target?.id || ''}|${props.device?.id || ''}|${props.assessment?.id || ''}|${tab.value}`,
      () => { selectedNode.value = 'entity'; });
    return { tab, selectedNode, topology, active, lines };
  },
  template: `<section class="ontology-live" aria-label="所选对象本体拓扑">
    <div class="ontology-live-head"><div><h3>本体关系 · RDF/OWL</h3><small>{{device?.name || target?.name || '等待目标'}} · {{mode==='replay'?'历史快照':'当前态势'}}</small></div>
      <div class="topology-tabs" role="group" aria-label="本体视图"><button :class="{active:tab==='abox'}" @click="tab='abox'">ABox 事实</button><button :class="{active:tab==='tbox'}" @click="tab='tbox'">TBox 定义</button></div>
    </div>
    <div class="topology-canvas" v-if="topology.nodes.length">
      <svg class="topology-links" viewBox="0 0 300 240" preserveAspectRatio="none" aria-hidden="true"><defs><marker id="topology-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 8 4 0 8" fill="#3e9fc9"/></marker></defs>
        <g v-for="e in lines" :key="e.from+'-'+e.to"><line :x1="e.fromNode.x*3" :y1="e.fromNode.y*2.4" :x2="e.toNode.x*3" :y2="e.toNode.y*2.4" stroke="#3e9fc9" stroke-width="1.5" marker-end="url(#topology-arrow)"/><text :x="(e.fromNode.x+e.toNode.x)*1.5" :y="(e.fromNode.y+e.toNode.y)*1.2-5" text-anchor="middle">{{e.label}}</text></g>
      </svg>
      <button v-for="n in topology.nodes" :key="n.key" class="topology-node" :class="[n.key,{active:active?.key===n.key}]" :style="{left:n.x+'%',top:n.y+'%'}" :aria-label="'查看'+n.type+n.label" @click="selectedNode=n.key"><small>{{n.type}}</small><b>{{n.label}}</b></button>
    </div>
    <p v-else class="topology-empty">{{topology.note}}</p>
    <div class="topology-detail" v-if="active"><b>{{active.label}}</b><span>{{active.detail || topology.note}}</span><code :title="active.uri">{{active.uri}}</code></div>
    <p class="topology-note">{{topology.note}}</p>
  </section>`,
};
