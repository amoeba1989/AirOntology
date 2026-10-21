import {
  createApp,
  ref,
  computed,
  onMounted,
  onUnmounted,
  nextTick,
} from "vue/dist/vue.esm-bundler.js";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./style.css";

createApp({
  setup() {
    const tab = ref("structure"),
      data = ref(null),
      selected = ref(null),
      health = ref(null);
    const items = ref([]),
      definition = ref(""),
      instance = ref(""),
      error = ref(""),
      toast = ref("");
    const mapMessage = ref(""),
      copied = ref(false),
      loading = ref(true),
      follow = ref(false);
    let map,
      pointLayer,
      targetLayer,
      linkLayer,
      circles,
      timer,
      cancelled = false,
      polling = false;
    const target = computed(
      () =>
        data.value?.targets.find((t) => t.id === selected.value) ||
        data.value?.targets[0],
    );
    const groups = computed(() =>
      ["类", "对象属性", "数据属性"].map((kind) => ({
        kind,
        items: items.value.filter((i) => i.kind === kind),
      })),
    );
    const status = computed(() =>
      error.value
        ? "服务异常"
        : !data.value?.targets.length
          ? "等待航迹"
          : target.value?.stale
            ? "数据过期"
            : "实时更新",
    );
    const formatTime = (value) =>
      value
        ? new Date(value).toLocaleTimeString("zh-CN", { hour12: false })
        : "—";
    const showToast = (message) => {
      toast.value = message;
      setTimeout(() => {
        toast.value = "";
      }, 2400);
    };
    async function get(path, text = false) {
      const r = await fetch(path, { signal: AbortSignal.timeout(8000) });
      if (!r.ok)
        throw new Error(`请求失败（${r.status}），请检查后端及 Fuseki 服务`);
      return text ? r.text() : r.json();
    }
    async function loadInstance() {
      const id = target.value?.id;
      if (!id) {
        instance.value = "";
        return;
      }
      const ttl = await get(`/api/targets/${encodeURIComponent(id)}/ttl`, true);
      if (id === target.value?.id) instance.value = ttl;
    }
    async function selectTab(value) {
      tab.value = value;
      if (value === "instance") {
        try {
          await loadInstance();
        } catch (e) {
          error.value = e.message;
        }
      }
    }
    function draw() {
      if (!map || !data.value) return;
      const p = data.value.position;
      const center = [p.lat, p.lon];
      if (!pointLayer) {
        pointLayer = L.marker(center, {
          icon: L.divIcon({
            className: "",
            html: '<div class="position-icon">⌖</div>',
            iconSize: [34, 34],
            iconAnchor: [17, 17],
          }),
        }).addTo(map);
        pointLayer.bindTooltip(p.name, {
          permanent: true,
          direction: "bottom",
          offset: [0, 17],
          className: "map-label",
        });
        circles = L.layerGroup().addTo(map);
        [...data.value.thresholds]
          .reverse()
          .forEach((radius, i) =>
            L.circle(center, {
              radius,
              color: ["#5da7ce", "#dda456", "#d97979"][i],
              weight: 1,
              dashArray: "5 7",
              fillOpacity: 0.025,
            }).addTo(circles),
          );
        map.setView(center, 17);
      }
      targetLayer?.remove();
      linkLayer?.remove();
      if (target.value) {
        const t = target.value,
          loc = [t.lat, t.lon];
        const color = t.stale ? "#87939e" : t.color;
        targetLayer = L.marker(loc, {
          icon: L.divIcon({
            className: "",
            html: `<div class="drone-icon" style="--marker:${color}">✣</div>`,
            iconSize: [38, 38],
            iconAnchor: [19, 19],
          }),
        }).addTo(map);
        targetLayer.bindTooltip(t.name, {
          permanent: true,
          direction: "top",
          offset: [0, -21],
          className: "map-label",
        });
        targetLayer.on("click", () => {
          selected.value = t.id;
          showToast("已选中无人机，可在右侧查看本体属性");
        });
        linkLayer = L.polyline([center, loc], {
          color,
          weight: 2,
          dashArray: "6 7",
        }).addTo(map);
        linkLayer.bindTooltip(`${t.distance.toFixed(1)} 米`, {
          permanent: true,
          direction: "center",
          className: "distance-label",
        });
        if (follow.value) map.panTo(loc, { animate: true, duration: 0.4 });
      }
    }
    function locate() {
      if (!map || !data.value) return;
      const p = data.value.position;
      const bounds = L.latLng(p.lat, p.lon).toBounds(
        data.value.thresholds[2] * 2.5,
      );
      if (target.value) bounds.extend([target.value.lat, target.value.lon]);
      map.fitBounds(bounds, { padding: [40, 40] });
    }
    async function poll() {
      if (polling || cancelled) return;
      polling = true;
      try {
        const [s, h] = await Promise.all([
          get("/api/situation"),
          get("/api/health"),
        ]);
        if (cancelled) return;
        data.value = s;
        health.value = h;
        error.value = "";
        if (!selected.value && s.targets.length)
          selected.value = s.targets[0].id;
        draw();
        if (tab.value === "instance") await loadInstance();
      } catch (e) {
        if (!cancelled) error.value = e.message;
      } finally {
        loading.value = false;
        polling = false;
      }
    }
    async function copy() {
      try {
        await navigator.clipboard.writeText(
          tab.value === "definition" ? definition.value : instance.value,
        );
        copied.value = true;
        setTimeout(() => (copied.value = false), 1600);
      } catch {
        showToast("当前浏览器不支持自动复制，请选中文本手动复制");
      }
    }
    onMounted(async () => {
      await nextTick();
      map = L.map("map", {
        zoomControl: false,
        attributionControl: true,
      }).setView([39.9045, 116.4077], 17);
      L.control.zoom({ position: "bottomright" }).addTo(map);
      const tileUrl =
        import.meta.env.VITE_TILE_URL ||
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
      const tileAttribution =
        import.meta.env.VITE_TILE_ATTRIBUTION ||
        "&copy; OpenStreetMap contributors";
      const tiles = L.tileLayer(tileUrl, {
        maxZoom: 19,
        attribution: tileAttribution,
      }).addTo(map);
      tiles.on(
        "tileerror",
        () =>
          (mapMessage.value =
            "底图暂不可用，目标和阵地仍可查看；可在配置中更换底图。"),
      );
      try {
        const [o, ttl] = await Promise.all([
          get("/api/ontology"),
          get("/api/ontology/ttl", true),
        ]);
        items.value = o.items;
        definition.value = ttl;
      } catch (e) {
        error.value = e.message;
      }
      await poll();
      timer = setInterval(poll, 1000);
    });
    onUnmounted(() => {
      cancelled = true;
      clearInterval(timer);
      map?.remove();
    });
    return {
      tab,
      data,
      target,
      health,
      groups,
      definition,
      instance,
      error,
      toast,
      status,
      formatTime,
      mapMessage,
      loading,
      follow,
      selectTab,
      locate,
      copy,
      copied,
    };
  },
  template: `
  <div class="workspace">
    <header><div class="brand-mark">A<span>O</span></div><div class="brand">AirOntology<small>无人机本体 · 实时观测工作台</small></div><span class="edition">DEMO / V1.0</span><div class="header-right"><span class="status-dot" :class="{online:status==='实时更新'}"></span>{{status}}<span class="divider"></span><span class="muted">单目标 · 单阵地</span></div></header>
    <main>
      <div class="page-title"><div><div class="eyebrow">ONTOLOGY IN ACTION</div><h1>从实时位置，到可查询的业务事实</h1><p>在地图中观察目标，在本体中理解对象、属性与关系。</p></div><div class="pipeline">MQTT <b>→</b> Python <b>→</b> RDF / OWL <b>→</b> Fuseki <b>→</b> WebGIS</div></div>
      <div v-if="error" class="alert" role="alert">{{error}}</div>
      <div class="overview"><div><span class="metric-label">监测目标</span><strong>{{data?.targets.length ?? '—'}}<small>架</small></strong></div><div><span class="metric-label">固定阵地</span><strong>{{data ? '1':'—'}}<small>处</small></strong></div><div><span class="metric-label">当前水平距离</span><strong>{{target ? target.distance.toFixed(1) : '—'}}<small>米</small></strong></div><div><span class="metric-label">距离关注等级</span><strong class="level-metric" :style="{color:target?.color}">{{target?.level_label || '等待数据'}}</strong></div><div class="dependency"><span :class="{'connected':health?.mqtt.connected}">● MQTT {{health?.mqtt.connected ? '已连接':'未连接'}}</span><span :class="{'connected':health?.fuseki}">● Fuseki {{health?.fuseki ? '可用':'未连接'}}</span></div></div>
      <section class="situation-grid">
        <div class="panel map-panel"><div class="panel-heading"><h2><span class="section-index">01</span> 实时态势</h2><div><label class="follow"><input type="checkbox" v-model="follow"> 跟随目标</label><button @click="locate">定位全景 ↗</button></div></div><div class="map-wrap"><div id="map"></div><div class="map-badge"><span class="status-dot" :class="{online:status==='实时更新'}"></span>{{status}}<span v-if="target">· {{formatTime(target.timestamp)}}</span></div><div v-if="mapMessage" class="tile-notice">{{mapMessage}}</div><div class="legend"><span><i style="background:#e45555"></i>高 ≤{{data?.thresholds[0] ?? 100}}m</span><span><i style="background:#ed9b32"></i>中 ≤{{data?.thresholds[1] ?? 200}}m</span><span><i style="background:#3899ce"></i>低 ≤{{data?.thresholds[2] ?? 300}}m</span><span><i style="background:#5aab87"></i>阈值外</span></div></div><div class="map-caption">WGS84 坐标 · 水平距离 / 米 <span>仅按距离分级，不代表综合威胁判断</span></div></div>
        <aside class="panel details"><div class="panel-heading"><h2><span class="section-index">02</span> 对象详情</h2><span class="tag">实例</span></div><template v-if="target"><div class="object-title"><div class="object-icon">✣</div><div><h3>{{target.name}}</h3><span>BlueDevice / 无人机目标</span></div></div><div class="object-state" :style="{color:target.stale?'#7b8794':target.color}">● {{target.stale ? '观测数据已过期' : target.level_label+' · 实时观测'}}</div><dl><div><dt>经度</dt><dd>{{target.lon.toFixed(6)}}°</dd></div><div><dt>纬度</dt><dd>{{target.lat.toFixed(6)}}°</dd></div><div><dt>速度</dt><dd>{{target.speed.toFixed(1)}} m/s</dd></div><div><dt>水平距离</dt><dd>{{target.distance.toFixed(1)}} m</dd></div><div><dt>关联阵地</dt><dd>{{data.position.name}}</dd></div><div><dt>观测时间</dt><dd>{{formatTime(target.timestamp)}}</dd></div></dl><div class="relation-card"><span>对象关系</span><div>{{target.name}} <b>→</b> {{data.position.name}}</div><small>monitoredAgainst · 关联阵地</small></div><button class="wide-button" @click="selectTab('instance')">查看这个对象的 RDF 事实 ↓</button></template><div v-else class="empty"><div>⌁</div><b>{{loading?'正在连接数据服务':'等待第一条航迹'}}</b><p>启动模拟器后，将自动显示对象属性和关系。</p></div></aside>
      </section>
      <section class="panel ontology-panel"><div class="panel-heading ontology-heading"><h2><span class="section-index">03</span> 本体与事实</h2><div class="tabs"><button :class="{active:tab==='structure'}" @click="selectTab('structure')">中文结构</button><button :class="{active:tab==='definition'}" @click="selectTab('definition')">本体定义 TTL</button><button :class="{active:tab==='instance'}" @click="selectTab('instance')">当前实例 TTL</button></div><button v-if="tab!=='structure'" @click="copy" :disabled="tab==='instance'&&!instance">{{copied?'已复制':'复制文本'}}</button></div><div v-if="tab==='structure'" class="structure-grid"><div v-for="group in groups" :key="group.kind"><div class="group-heading">{{group.kind}}<span>{{group.items.length}}</span></div><div v-for="item in group.items" :key="item.id" class="schema-row"><div><b>{{item.label}}</b><code>{{item.id}}</code></div><small v-if="item.comment">{{item.comment}}</small><small v-else-if="item.range">取值：{{item.range}}</small></div></div></div><div v-else class="code-section"><div class="code-note">{{tab==='definition'?'模型定义（TBox）：描述有哪些类、属性和关系，位置更新不会修改此定义。':'实例事实（ABox）：由 MQTT 数据和 Python 计算结果更新；从 Fuseki 查询，并附关联阵地和等级。'}}</div><pre v-if="tab==='definition'||instance"><code>{{tab==='definition'?definition:instance}}</code></pre><div v-else class="empty">暂无目标实例，请先启动模拟器。</div></div><div class="ontology-footer"><span><b>学习提示</b> 类是“对象的类别”；实例是“具体对象”；数据属性连接数值，对象属性连接另一个对象。</span><span>计算：Python · 表达：RDF / OWL · 查询：SPARQL</span></div></section>
      <footer>AirOntology <span>从一条观测开始，理解本体。</span><span>演示环境 · 只保留最新状态 · 不启用自动推理</span></footer>
    </main><div v-if="toast" class="toast" role="status">{{toast}}</div>
  </div>`,
}).mount("#app");
