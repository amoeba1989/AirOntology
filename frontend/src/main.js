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

createApp({
  setup() {
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
      timer,
      playTimer,
      closed = false,
      polling = false,
      initialized = false,
      snapshotToken = 0;
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
        const marker = L.marker([p.lat, p.lon], {
          icon: L.divIcon({
            className: "",
            html: `<div class="position-icon ${p.id === point.value?.id ? "selected-marker" : ""}">⌖</div>`,
            iconSize: [34, 34],
            iconAnchor: [17, 17],
          }),
        }).addTo(layers);
        marker.bindTooltip(tooltip(p.name), {
          permanent: true,
          direction: "bottom",
          offset: [0, 17],
          className: "map-label",
        });
        marker.on("click", () => choosePosition(p.id));
      }
      const thresholds = assessment.value?.thresholds || data.value.thresholds;
      if (point.value)
        [...thresholds]
          .reverse()
          .forEach((radius, i) =>
            L.circle([point.value.lat, point.value.lon], {
              radius,
              color: ["#5da7ce", "#dda456", "#d97979"][i],
              weight: 1,
              dashArray: "5 7",
              fillOpacity: 0.025,
            }).addTo(layers),
          );
      for (const t of data.value.targets) {
        const evaluation = t.assessments.find(
            (a) => a.position_id === point.value?.id,
          ),
          color = t.stale ? "#87939e" : evaluation?.color || "#87939e";
        const marker = L.marker([t.lat, t.lon], {
          icon: L.divIcon({
            className: "",
            html: `<div class="drone-icon ${t.id === target.value?.id ? "selected-marker" : ""}" style="--marker:${color}">✣</div>`,
            iconSize: [38, 38],
            iconAnchor: [19, 19],
          }),
        }).addTo(layers);
        marker.bindTooltip(tooltip(t.name), {
          permanent: true,
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
            [target.value.lat, target.value.lon],
            [a.position_lat, a.position_lon],
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
      pathLayer?.remove();
      pathLayer = null;
      if (mode.value === "replay" && records.value.length > 1)
        pathLayer = L.polyline(
          records.value.map((r) => [r.lat, r.lon]),
          { color: "#527ba0", weight: 2, opacity: 0.5 },
        ).addTo(map);
      if (!initialized) {
        initialized = true;
        locate();
      }
      if (follow.value && target.value)
        map.panTo([target.value.lat, target.value.lon], {
          animate: true,
          duration: 0.3,
        });
    }
    function locate() {
      const coords = [
        ...(data.value?.positions || []),
        ...(data.value?.targets || []),
      ].map((p) => [p.lat, p.lon]);
      if (coords.length)
        map.fitBounds(L.latLngBounds(coords).pad(0.3), {
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
      trace.value = null;
      draw();
      if (tab.value === "instance")
        try {
          await loadInstance();
        } catch (e) {
          error.value = e.message;
        }
    }
    function choosePosition(id) {
      positionId.value = id;
      trace.value = null;
      draw();
    }
    async function inspect(entry) {
      selected.value = entry.target_id;
      trace.value = entry;
      draw();
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
          normalizeSelection();
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
      pathLayer?.remove();
      pathLayer = null;
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
      await nextTick();
      map = L.map("map", { zoomControl: false }).setView(
        [39.9045, 116.4077],
        16,
      );
      layers = L.layerGroup().addTo(map);
      L.control.zoom({ position: "bottomright" }).addTo(map);
      L.tileLayer(
        import.meta.env.VITE_TILE_URL ||
          "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
          maxZoom: 19,
          attribution:
            import.meta.env.VITE_TILE_ATTRIBUTION ||
            "&copy; OpenStreetMap contributors",
        },
      )
        .addTo(map)
        .on(
          "tileerror",
          () => (mapMessage.value = "底图暂不可用，目标和阵地仍可显示。"),
        );
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
      timer = setInterval(poll, 1000);
    });
    onUnmounted(() => {
      closed = true;
      snapshotToken++;
      clearInterval(timer);
      stopPlayback();
      map?.remove();
    });
    return {
      data,
      health,
      target,
      point,
      assessment,
      explanation,
      ranked,
      groups,
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
