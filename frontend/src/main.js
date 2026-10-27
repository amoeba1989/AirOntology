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
import template from "./template.js";
import { mergeTrail, trailSegments } from "./map-utils.js";
import { wgs84ToGcj02, gcj02ToWgs84, attachAmapSatellite } from "./amap-basemap.js";
import { darkBasemapConfig, ESRI_ATTRIBUTION } from "./map-basemap.js";
import LearningWorkbench from "./learning.js";
import AgentPanel from "./agent-panel.js";
import EvidenceWorkbench from "./evidence.js";
import DeviceWorkbench from "./devices.js";
import OntologyTopology from "./ontology-topology.js";
// 用户提供的四类业务图标统一存放在 public/icons，业务关系和颜色仍由数据决定。
const icons = Object.freeze({
  uav: "/icons/uav.png",
  position: "/icons/position.png",
  radar: "/icons/radar.png",
  jammer: "/icons/jammer.png",
});

createApp({
  components: { LearningWorkbench, AgentPanel, EvidenceWorkbench, DeviceWorkbench, OntologyTopology },
  setup() {
    const deviceData=ref(null),deviceError=ref(''),deviceReadAt=ref(''),selectedDeviceId=ref('');
    let devicePolling=false,deviceTimer;
    async function pollDevices(){
      if(devicePolling||closed)return;devicePolling=true;
      try{const value=await request('/api/devices');if(!closed){deviceData.value=value;deviceReadAt.value=new Date().toISOString();deviceError.value='';draw();}}
      catch(e){deviceError.value=e.name==='TimeoutError'?'设备接口响应超时':e.message;}finally{devicePolling=false;}
    }
    async function openDevices(id){
      if(typeof id==='string')selectedDeviceId.value=id;
      await changeView('learning');
      document.getElementById('devices-panel')?.scrollIntoView?.({block:'start'});
    }
    async function locateDevice(d){
      if(mode.value!=='live')await live();
      if(!d.state?.transform)return;
      await changeView('screen');
      map.setView(displayPoint(d.state.transform.latitude_deg,d.state.transform.longitude_deg),17,{animate:false});
      selectMapDevice(d);
    }
    const data = ref(null),
      health = ref(null),
      selected = ref("drone001"),
      positionId = ref("pos001");
    const tab = ref("structure"),
      items = ref([]),
      definition = ref(""),
      instance = ref(""),
      error = ref(""),
      toast = ref("");
    const mode = ref("live"),
      loading = ref(true),
      follow = ref(false),
      mapMessage = ref(""),
      trace = ref(null);
    const showTrails = ref(true),
      showRanges = ref(true),
      showDevices = ref(true);
    const routeView = () => location.pathname.replace(/\/$/, '') === '/back' ? 'learning' : 'screen';
    const viewMode = ref(routeView());
    async function changeView(value) {
      const path = value === 'learning' ? '/back' : '/';
      if (location.pathname !== path) history.pushState({ view: value }, '', path);
      viewMode.value = value;
      await nextTick();
      map?.invalidateSize();
    }
    async function syncRoute() {
      viewMode.value = routeView();
      await nextTick();
      map?.invalidateSize();
    }
    async function locateAgentCandidate(candidate, snapshot) {
      if (mode.value !== 'live') await live();
      const current = data.value?.targets.find(t => t.id === candidate.target_id);
      if (!current) { notice('该目标已不在当前态势中，请重新提问'); return; }
      if (!data.value.positions.some(p => p.id === snapshot.position.id)) {
        notice('本次回答的阵地已移除，请重新提问'); return;
      }
      await changeView('screen');
      await chooseTarget(current.id);
      choosePosition(snapshot.position.id);
      highlightQuery([{target:{value:current.uri || 'http://counteruav.org/counterUav#'+current.id}}]);
      map?.setView(displayPoint(current.lat,current.lon), 17, {animate:false});
      notice('已定位当前可用位置；回答依据固定为 '+formatTime(snapshot.at));
    }
    const queryHighlights = ref(new Set());
    function highlightQuery(rows) {
      queryHighlights.value = new Set(rows.flatMap(row => ['target','position'].map(key => row[key]?.value).filter(Boolean)));
      draw();
    }
    function focusQueryRow(row) {
      const targetURI = row.target?.value;
      const positionURI = row.position?.value;
      const id = value => value?.split('#').pop();
      const exists = data.value?.targets.some(t => t.id === id(targetURI)) || data.value?.positions.some(p => p.id === id(positionURI || targetURI));
      if (!exists) return;
      if (data.value?.targets.some(t => t.id === id(targetURI))) chooseTarget(id(targetURI));
      if (data.value?.positions.some(p => p.id === id(positionURI || targetURI))) choosePosition(id(positionURI || targetURI));
      highlightQuery([row]);
      document.getElementById('map')?.scrollIntoView?.({behavior:'smooth',block:'center'});
    }
    const trails = new Map();
    const recentTrail = ref([]);
    const historyLoaded = new Set();
    const records = ref([]),
      historyTarget = ref(""),
      frame = ref(0),
      playing = ref(false),
      replayBusy = ref(false);
    const configOpen = ref(false),
      draft = ref(null),
      configVersion = ref(""),
      saving = ref(false),
      configError = ref("");
    let map,
      layers,
      pathLayer,
      removeSatellite,
      satelliteActive = ref(false),
      satelliteAvailable = ref(false),
      mapStyle = ref('dark'),
      basemapName = ref('ArcGIS 深灰底图'),
      darkLayers = [],
      fallbackLayer,
      tileErrors = 0,
      satelliteKey = '',
      timer,
      playTimer,
      closed = false,
      polling = false,
      initialized = false,
      snapshotToken = 0;
    const displayPoint=(lat,lon)=>satelliteActive.value?wgs84ToGcj02(lat,lon):[lat,lon];
    async function switchBasemap(value) {
      if (!map || value === mapStyle.value) return;
      if (value === 'satellite') {
        if (!satelliteKey) { mapMessage.value = '高德卫星图尚未配置，继续显示 ArcGIS 深灰底图。'; return; }
        const center = map.getCenter();
        satelliteActive.value = true;
        map.setView(displayPoint(center.lat, center.lng), map.getZoom(), {animate:false});
        try {
          removeSatellite = await attachAmapSatellite(map, satelliteKey);
          darkLayers.forEach(layer => map.removeLayer(layer));
          fallbackLayer && map.removeLayer(fallbackLayer);
          document.getElementById('map')?.classList.add('satellite-overlay');
          mapStyle.value = 'satellite'; basemapName.value = '高德卫星影像'; mapMessage.value = '';
          draw();
        } catch (cause) {
          satelliteActive.value = false;
          map.setView([center.lat, center.lng], map.getZoom(), {animate:false});
          mapMessage.value = `卫星影像加载失败：${cause.message}`;
          draw();
        }
      } else {
        removeSatellite?.(); removeSatellite = null;
        document.getElementById('map')?.classList.remove('satellite-overlay');
        const center = map.getCenter();
        satelliteActive.value = false;
        map.setView(gcj02ToWgs84(center.lat, center.lng), map.getZoom(), {animate:false});
        if (tileErrors >= 3) fallbackLayer.addTo(map);
        else darkLayers.forEach(layer => layer.addTo(map));
        mapStyle.value = 'dark'; basemapName.value = tileErrors >= 3 ? '备用标准底图' : 'ArcGIS 深灰底图';
        mapMessage.value = tileErrors >= 3 ? 'ArcGIS 底图暂不可用，已切换备用底图。' : '';
        draw();
      }
    }
    const target = computed(
      () =>
        data.value?.targets.find((t) => t.id === selected.value) ||
        data.value?.targets[0],
    );
    const point = computed(
      () =>
        data.value?.positions.find((p) => p.id === positionId.value) ||
        data.value?.positions[0],
    );
    const assessment = computed(() =>
      target.value?.assessments.find((a) => a.position_id === point.value?.id),
    );
    const explanation = computed(() => trace.value || assessment.value);
    const ranked = computed(() =>
      [...(data.value?.assessments || [])]
        .filter((a) => a.position_id === point.value?.id)
        .sort((a, b) => a.distance - b.distance),
    );
    const alarmEntries = computed(() => [...(data.value?.assessments || [])]
      .filter(a => !a.stale && !a.config_pending && ["HighAttention", "MediumAttention", "LowAttention"].includes(a.level))
      .sort((a,b) => ["HighAttention", "MediumAttention", "LowAttention"].indexOf(a.level) - ["HighAttention", "MediumAttention", "LowAttention"].indexOf(b.level) || a.distance-b.distance));
    const staleTargets = computed(() => data.value?.targets.filter(t => t.stale) || []);
    const pendingCount = computed(() => data.value?.assessments.filter(a => a.config_pending).length || 0);
    const screenDevices = computed(() => mode.value === 'live' ? deviceData.value?.devices || [] : []);
    const selectedDevice = computed(() => screenDevices.value.find(d => d.id === target.value?.id));
    const selectedDeployments = computed(() => screenDevices.value.filter(d => d.deployed_at === point.value?.id && d.kind !== 'uav'));
    const selectedMapDevice = computed(() => screenDevices.value.find(d => d.id === selectedDeviceId.value && d.kind !== 'uav'));
    function selectMapDevice(d) {
      if (d.deployed_at && data.value?.positions.some(p => p.id === d.deployed_at)) positionId.value = d.deployed_at;
      selectedDeviceId.value = d.id;
      trace.value = null;
      draw();
    }
    async function openKnowledge(value) {
      await changeView('learning');
      await selectTab(value);
      await nextTick();
      document.getElementById("knowledge-panel")?.scrollIntoView?.({behavior:"smooth", block:"start"});
    }
    async function openLearning() {
      await changeView('learning');
      document.getElementById('learning-panel')?.scrollIntoView?.({block:'start'});
    }
    async function openEvidence() {
      await changeView('learning');
      document.getElementById('evidence-panel')?.scrollIntoView?.({block:'start'});
    }
    let evidenceLayer;
    function clearEvidencePoint() { evidenceLayer?.clearLayers(); }
    async function locateEvidence(o) {
      if(o.outcome!=='detected'||o.crs!=='WGS84'||!Number.isFinite(o.lon)||!Number.isFinite(o.lat))return;
      await changeView('learning');
      evidenceLayer ||= L.layerGroup().addTo(map);
      clearEvidencePoint();
      const label=document.createElement('span');
      label.textContent='原始观测（非确认无人机） · '+o.id+' · '+(({simulated:'模拟数据',operational:'业务接入声明（未验证）'})[o.data_mode]||'来源待核实')+' · '+o.observed_at+' · '+(o.fresh?'时间有效':'已过期');
      L.circleMarker(displayPoint(o.lat,o.lon),{radius:10,color:'#c084fc',weight:3,fillOpacity:.25}).bindTooltip(label).addTo(evidenceLayer);
      map.setView(displayPoint(o.lat,o.lon),16,{animate:false});
      document.getElementById('map')?.scrollIntoView?.({block:'center'});
      notice('已定位原始观测；不表示同一目标或确认无人机。');
    }
    const groups = computed(() =>
      ["类", "对象属性", "数据属性"].map((kind) => ({
        kind,
        items: items.value.filter((i) => i.kind === kind),
      })),
    );
    const status = computed(() =>
      error.value
        ? "服务异常"
        : mode.value === "replay"
          ? "历史回放"
          : !data.value?.targets.length
            ? "等待航迹"
            : target.value?.stale
              ? "数据过期"
              : "实时更新",
    );
    const formatTime = (value) =>
      value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
    const notice = (message) => {
      toast.value = message;
      setTimeout(() => (toast.value = ""), 3000);
    };
    async function request(path, text = false, options = {}) {
      const result = await fetch(path, {
        signal: AbortSignal.timeout(15000),
        ...options,
      });
      if (!result.ok) {
        let detail;
        try {
          detail = (await result.json()).detail;
        } catch {}
        throw new Error(
          typeof detail === "string"
            ? detail
            : `请求失败（${result.status}），请检查输入或服务状态`,
        );
      }
      return text ? result.text() : result.json();
    }
    const suffix = () =>
      mode.value === "replay" && data.value?.at
        ? `?at=${encodeURIComponent(data.value.at)}`
        : "";
    async function loadInstance() {
      if (!target.value) {
        instance.value = "";
        return;
      }
      const id = target.value.id,
        at = data.value?.at;
      const result = await request(
        `/api/targets/${encodeURIComponent(id)}/ttl${suffix()}`,
        true,
      );
      if (target.value?.id === id && data.value?.at === at)
        instance.value = result;
    }
    async function selectTab(value) {
      tab.value = value;
      if (value === "instance")
        try {
          await loadInstance();
        } catch (e) {
          error.value = e.message;
        }
    }
    function tooltip(text) {
      const el = document.createElement("span");
      el.textContent = text;
      return el;
    }
    function draw() {
      if (!map || !data.value) return;
      layers.clearLayers();
      for (const p of data.value.positions) {
        const marker = L.marker(displayPoint(p.lat, p.lon), {
          icon: L.divIcon({
            className: "",
            html: `<div class="position-icon ${queryHighlights.value.has('http://counteruav.org/counterUav#'+p.id) ? 'query-match' : ''} ${p.id === point.value?.id ? "selected-marker" : ""}"><img src="${icons.position}" alt=""></div>`,
            iconSize: [34, 34],
            iconAnchor: [17, 17],
          }),
        }).addTo(layers);
        marker.bindTooltip(tooltip(`阵地 · ${p.name}`), {
          permanent: true,
          direction: "bottom",
          offset: [0, 17],
          className: "map-label",
        });
        marker.on("click", () => choosePosition(p.id));
      }
      if(mode.value==='live' && showDevices.value) for(const d of deviceData.value?.devices||[]){
        if(d.kind==='uav'||!d.state?.transform)continue;
        const p=d.state.transform;
        const icon=icons[d.kind==='radar'?'radar':'jammer'];
        const stale=d.stale||!d.in_latest_frame||!!deviceError.value;
        const status=stale ? 'is-stale' : d.kind==='jammer' && d.state?.jammer?.emitting ? 'is-emitting' : 'is-current';
        const marker=L.marker(displayPoint(p.latitude_deg,p.longitude_deg),{icon:L.divIcon({className:'',html:`<div class="equipment-icon ${d.kind} ${status} ${d.id===selectedDeviceId.value?'selected-marker':''}"><img src="${icon}" alt=""></div>`,iconSize:[42,42],iconAnchor:[21,21]})}).addTo(layers);
        marker.bindTooltip(tooltip(d.kind_label+' · '+d.name+' · 模拟数据 · '+d.status_label),{direction:'top'});
        marker.on('click',()=>selectMapDevice(d));
      }
      const thresholds = assessment.value?.thresholds || data.value.thresholds;
      if (point.value && showRanges.value)
        [...thresholds].reverse().forEach((radius, i) => {
          const color = ["#d7aa76", "#efb77d", "#ff7f8d"][i];
          const circle = L.circle(displayPoint(point.value.lat, point.value.lon), {
            radius,
            color,
            weight: i === 2 ? 1.5 : 1,
            opacity: [.42,.55,.78][i],
            dashArray: ["5 8", "4 6", null][i],
            fillColor: color,
            fillOpacity: [.012,.018,.04][i],
            interactive: false,
          }).addTo(layers);
          L.marker([circle.getBounds().getNorth(), displayPoint(point.value.lat,point.value.lon)[1]], {
            interactive: false,
            icon: L.divIcon({
              className: "range-label",
              html: `${radius}m · ${["低", "中", "高"][i]}关注`,
              iconSize: [124, 24],
              iconAnchor: [62, 12],
            }),
          }).addTo(layers);
        });
      for (const t of data.value.targets) {
        const evaluation = t.assessments.find(
            (a) => a.position_id === point.value?.id,
          ),
          color = t.stale ? "#87939e" : evaluation?.color || "#87939e";
        const marker = L.marker(displayPoint(t.lat, t.lon), {
          icon: L.divIcon({
            className: "",
            html: `<div class="drone-icon ${queryHighlights.value.has('http://counteruav.org/counterUav#'+t.id) ? 'query-match' : ''} ${t.id === target.value?.id ? "selected-marker" : ""}" style="--marker:${color}"><img src="${icons.uav}" alt=""></div>`,
            iconSize: [44, 44],
            iconAnchor: [22, 22],
          }),
        }).addTo(layers);
        marker.bindTooltip(tooltip(`无人机 · ${t.name}${t.stale ? ' · 数据过期' : ''}`), {
          permanent: t.id === target.value?.id,
          direction: "top",
          offset: [0, -21],
          className: "map-label",
        });
        marker.on("click", () => chooseTarget(t.id));
      }
      if (target.value && assessment.value) {
        const a = assessment.value;
        L.polyline(
          [
            displayPoint(target.value.lat, target.value.lon),
            displayPoint(a.position_lat, a.position_lon),
          ],
          { color: a.color, weight: 2, dashArray: "6 7" },
        )
          .addTo(layers)
          .bindTooltip(`${a.distance.toFixed(1)} 米`, {
            permanent: true,
            direction: "center",
            className: "distance-label",
          });
      }
      pathLayer?.clearLayers();
      if (showTrails.value) {
        for (const t of data.value.targets) {
          const active = t.id === target.value?.id;
          const points =
            mode.value === "replay"
              ? t.id === historyTarget.value
                ? records.value.slice(0, frame.value + 1)
                : []
              : trails.get(t.id) || [];
          for (const segment of trailSegments(
            points.slice(active ? -45 : -16),
            t.timestamp,
            Math.max(10, (data.value.stale_seconds || 30) * 2),
          )) {
            const coords = segment.map((p) => displayPoint(p.lat, p.lon));
            if (active) L.polyline(coords, {
              color: '#6cddf4', weight: 7, opacity: .12,
              lineCap: 'round', lineJoin: 'round', interactive: false,
            }).addTo(pathLayer);
            L.polyline(coords, {
              color: active ? '#6cddf4' : '#77a7c0',
              weight: active ? 2.5 : 1.25,
              opacity: active ? .92 : .27,
              lineCap: 'round', lineJoin: 'round',
            })
              .addTo(pathLayer)
              .bindTooltip(tooltip(`${t.name} · 已观测轨迹`));
            if (active) segment.filter((_, index) => index % 8 === 0).forEach(p =>
              L.circleMarker(displayPoint(p.lat, p.lon), {
                radius: 2.3, color: '#6cddf4', fillColor: '#0a263b',
                fillOpacity: 1, weight: 1, interactive: false,
              }).addTo(pathLayer));
          }
        }
      }
      if (!initialized) {
        initialized = true;
        locate();
      }
      if (follow.value && target.value)
        map.panTo(displayPoint(target.value.lat, target.value.lon), {
          animate: true,
          duration: 0.3,
        });
    }
    function locate() {
      const coords = [
        ...(data.value?.positions || []),
        ...(data.value?.targets || []),
      ].map((p) => displayPoint(p.lat, p.lon));
      const bounds = L.latLngBounds(coords);
      if (point.value && showRanges.value) {
        const radius = Math.max(
          ...(assessment.value?.thresholds || data.value.thresholds),
        );
        bounds.extend(
          L.latLng(...displayPoint(point.value.lat, point.value.lon)).toBounds(radius * 2),
        );
      }
      if (bounds.isValid())
        map.fitBounds(bounds.pad(0.15), {
          padding: [45, 45],
          maxZoom: 17,
        });
    }
    function normalizeSelection() {
      if (!data.value?.targets.find((t) => t.id === selected.value))
        selected.value = data.value?.targets[0]?.id || "";
      if (!data.value?.positions.find((p) => p.id === positionId.value))
        positionId.value = data.value?.positions[0]?.id || "";
    }
    async function chooseTarget(id) {
      selected.value = id;
      selectedDeviceId.value = '';
      recentTrail.value = trails.get(id) || [];
      trace.value = null;
      draw();
      if (viewMode.value === 'learning' && tab.value === "instance")
        try {
          await loadInstance();
        } catch (e) {
          error.value = e.message;
        }
    }
    function choosePosition(id) {
      positionId.value = id;
      selectedDeviceId.value = '';
      trace.value = null;
      draw();
    }
    async function inspect(entry) {
      selected.value = entry.target_id;
      selectedDeviceId.value = '';
      trace.value = entry;
      draw();
      if (viewMode.value === 'screen') return;
      try {
        const result = await request(`/api/assessments/${entry.id}`);
        if (trace.value?.id === entry.id) trace.value = result;
      } catch (e) {
        notice(e.message);
      }
    }
    async function poll() {
      if (polling || closed) return;
      polling = true;
      try {
        const live = mode.value === "live";
        const [h, s] = await Promise.all([
          request("/api/health"),
          live ? request("/api/situation") : Promise.resolve(null),
        ]);
        if (closed) return;
        health.value = h;
        if (s && mode.value === "live") {
          data.value = s;
          for (const t of s.targets) {
            trails.set(t.id, mergeTrail(trails.get(t.id) || [], [t]));
            if (!historyLoaded.has(t.id)) {
              historyLoaded.add(t.id);
              request(
                `/api/history?target_id=${encodeURIComponent(t.id)}&limit=300`,
              )
                .then((result) => {
                  if (closed) return;
                  trails.set(
                    t.id,
                    mergeTrail(result.records, trails.get(t.id) || []),
                  );
                  if (selected.value === t.id) recentTrail.value = trails.get(t.id) || [];
                  if (mode.value === "live") draw();
                })
                .catch(() => notice("历史轨迹暂未加载，继续绘制实时观测轨迹"));
            }
          }
          normalizeSelection();
          recentTrail.value = trails.get(selected.value) || [];
          draw();
          if (tab.value === "instance") await loadInstance();
        }
        if (s && mode.value === "live") error.value = "";
      } catch (e) {
        error.value = e.message;
      } finally {
        loading.value = false;
        polling = false;
      }
    }
    function stopPlayback() {
      clearInterval(playTimer);
      playing.value = false;
    }
    async function seek() {
      if (!records.value.length) return;
      const token = ++snapshotToken;
      replayBusy.value = true;
      try {
        const result = await request(
          `/api/situation?at=${encodeURIComponent(records.value[frame.value].timestamp)}`,
        );
        if (token !== snapshotToken || mode.value !== "replay") return;
        data.value = result;
        normalizeSelection();
        trace.value = null;
        draw();
        error.value = "";
        if (tab.value === "instance") await loadInstance();
      } catch (e) {
        if (token === snapshotToken) error.value = e.message;
      } finally {
        if (token === snapshotToken) replayBusy.value = false;
      }
    }
    async function loadHistory() {
      stopPlayback();
      snapshotToken++;
      const id = target.value?.id;
      if (!id) {
        notice("请先等待无人机观测");
        return;
      }
      mode.value = "loading";
      trace.value = null;
      try {
        const result = await request(
          `/api/history?target_id=${encodeURIComponent(id)}&limit=1000`,
        );
        if (!result.records.length) {
          mode.value = "live";
          notice("该目标没有保留的历史观测");
          return;
        }
        records.value = result.records;
        historyTarget.value = id;
        frame.value = 0;
        mode.value = "replay";
        await seek();
      } catch (e) {
        mode.value = "live";
        error.value = e.message;
      }
    }
    function togglePlayback() {
      if (playing.value) {
        stopPlayback();
        return;
      }
      if (frame.value >= records.value.length - 1) frame.value = 0;
      playing.value = true;
      seek();
      playTimer = setInterval(() => {
        if (replayBusy.value) return;
        if (frame.value >= records.value.length - 1) {
          stopPlayback();
          return;
        }
        frame.value++;
        seek();
      }, 650);
    }
    async function live() {
      stopPlayback();
      snapshotToken++;
      mode.value = "live";
      trace.value = null;
      pathLayer?.clearLayers();
      await poll();
    }
    async function openConfig() {
      try {
        const result = await request("/api/config");
        draft.value = result.config;
        configVersion.value = result.version;
        configError.value = "";
        configOpen.value = true;
      } catch (e) {
        error.value = e.message;
      }
    }
    function addPosition() {
      if (draft.value.positions.length >= 10) return;
      let i = 1;
      while (
        draft.value.positions.some(
          (p) => p.id === `pos${String(i).padStart(3, "0")}`,
        )
      )
        i++;
      draft.value.positions.push({
        id: `pos${String(i).padStart(3, "0")}`,
        name: `新增阵地${i}`,
        lon: draft.value.positions[0].lon,
        lat: draft.value.positions[0].lat,
      });
    }
    async function saveConfig() {
      saving.value = true;
      configError.value = "";
      try {
        const result = await request("/api/config", false, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_version: configVersion.value,
            config: draft.value,
          }),
        });
        configVersion.value = result.version;
        configOpen.value = false;
        notice("配置已保存，从下一条观测开始生效；历史结果保持原样");
        await poll();
      } catch (e) {
        configError.value = e.message;
      } finally {
        saving.value = false;
      }
    }
    async function copy() {
      try {
        await navigator.clipboard.writeText(
          tab.value === "definition" ? definition.value : instance.value,
        );
        notice("已复制TTL文本");
      } catch {
        notice("请选中文本手动复制");
      }
    }
    onMounted(async () => {
      window.addEventListener('popstate', syncRoute);
      await nextTick();
      map = L.map("map", { zoomControl: false }).setView(
        [39.9045, 116.4077],
        16,
      );
      pathLayer = L.layerGroup().addTo(map);
      layers = L.layerGroup().addTo(map);
      L.control.zoom({ position: "bottomright" }).addTo(map);
      const basemap = darkBasemapConfig(import.meta.env.VITE_ARCGIS_TOKEN);
      fallbackLayer = L.tileLayer(import.meta.env.VITE_TILE_URL ||
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom:19, className:'fallback-tiles',
        attribution:import.meta.env.VITE_TILE_ATTRIBUTION || '&copy; OpenStreetMap contributors',
      });
      const darkBase = L.tileLayer(basemap.base, {maxZoom:19, maxNativeZoom:basemap.reference ? 16 : 19, attribution:ESRI_ATTRIBUTION})
        .on('tileerror', () => {
          if (++tileErrors === 3 && mapStyle.value === 'dark') {
            darkLayers.forEach(layer => map.removeLayer(layer));
            fallbackLayer.addTo(map); basemapName.value = '备用标准底图';
            mapMessage.value = 'ArcGIS 底图暂不可用，已切换备用底图；业务对象仍可显示。';
          }
        });
      darkLayers = [darkBase];
      if (basemap.reference) darkLayers.push(L.tileLayer(basemap.reference, {maxZoom:19, maxNativeZoom:16, attribution:ESRI_ATTRIBUTION}));
      darkLayers.forEach(layer => layer.addTo(map));
      try {
        const config=await request('/api/map/config');
        satelliteAvailable.value = !!config.enabled;
        satelliteKey = config.enabled ? config.key : '';
      } catch {
        satelliteAvailable.value = false;
      }
      try {
        const [o, ttl] = await Promise.all([
          request("/api/ontology"),
          request("/api/ontology/ttl", true),
        ]);
        items.value = o.items;
        definition.value = ttl;
      } catch (e) {
        error.value = e.message;
      }
      await poll();
      await pollDevices();
      deviceTimer=setInterval(pollDevices,5000);
      timer = setInterval(poll, 3000);
    });
    onUnmounted(() => {
      window.removeEventListener('popstate', syncRoute);
      closed = true;
      snapshotToken++;
      clearInterval(timer);
      clearInterval(deviceTimer);
      stopPlayback();
      removeSatellite?.();
      map?.remove();
    });
    return {
      viewMode,
      icons,
      satelliteActive,
      satelliteAvailable,
      mapStyle,
      basemapName,
      switchBasemap,
      deviceData,deviceError,deviceReadAt,selectedDeviceId,openDevices,locateDevice,
      changeView,
      locateAgentCandidate,
      openLearning,
      openEvidence,
      locateEvidence,
      clearEvidencePoint,
      request,
      highlightQuery,
      focusQueryRow,
      data,
      health,
      target,
      point,
      assessment,
      explanation,
      ranked,
      groups,
      alarmEntries,
      staleTargets,
      pendingCount,
      screenDevices,
      selectedDevice,
      selectedDeployments,
      selectedMapDevice,
      selectMapDevice,
      recentTrail,
      openKnowledge,
      tab,
      definition,
      instance,
      error,
      toast,
      status,
      formatTime,
      mode,
      loading,
      follow,
      showTrails,
      showRanges,
      showDevices,
      draw,
      mapMessage,
      selected,
      positionId,
      trace,
      records,
      historyTarget,
      frame,
      playing,
      replayBusy,
      configOpen,
      draft,
      configVersion,
      saving,
      configError,
      chooseTarget,
      choosePosition,
      inspect,
      selectTab,
      locate,
      copy,
      loadHistory,
      seek,
      togglePlayback,
      stopPlayback,
      live,
      openConfig,
      addPosition,
      saveConfig,
    };
  },
  template,
}).mount("#app");
