const cases = [
  "我先送孩子上学，然后去公司",
  "去公司路上找个咖啡店，别太绕",
  "回家路上加个油",
  "我 8 点半火车，现在出发来得及吗？",
  "这条路太堵了，换一条",
];

const state = {
  amapLoaded: false,
  map: null,
  driving: null,
  polylines: [],
  markers: [],
  selectedRoute: null,
  lastPlan: null,
};

const form = document.querySelector("#plannerForm");
const input = document.querySelector("#userInput");
const routesEl = document.querySelector("#routes");
const logsEl = document.querySelector("#logs");
const taskJson = document.querySelector("#taskJson");
const mockMap = document.querySelector("#mockMap");
const keyStatus = document.querySelector("#keyStatus");
const shareButton = document.querySelector("#shareButton");

function setupCases() {
  const wrap = document.querySelector("#quickCases");
  cases.forEach((text) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", () => {
      input.value = text;
      form.requestSubmit();
    });
    wrap.appendChild(button);
  });
}

async function loadContext() {
  const res = await fetch("/api/context");
  const data = await res.json();
  const ctx = data.context;
  const adapter = data.amap_adapter || "webservice";
  document.querySelector("#contextLine").textContent = `家：${ctx.home.address}｜公司：${ctx.company.address}｜油量 ${ctx.vehicle.fuel_percent}%｜SOC ${ctx.vehicle.soc_percent}%｜AMap ${adapter}`;
  if (data.amap_js_key) {
    keyStatus.textContent = data.amap_security_js_code ? "高德 JS Key 已配置" : "高德 JS Key 已配置，缺少安全密钥";
    await loadAmap(data.amap_js_key, data.amap_security_js_code);
  } else {
    keyStatus.textContent = "未配置 Key，使用 Mock 地图";
  }
}

function loadAmap(key, securityJsCode) {
  return new Promise((resolve) => {
    if (securityJsCode) {
      window._AMapSecurityConfig = { securityJsCode };
    }
    window._amapInit = () => {
      state.amapLoaded = true;
      state.map = new AMap.Map("map", { zoom: 11, center: [121.47, 31.22], viewMode: "2D" });
      mockMap.classList.add("hidden");
      AMap.plugin(["AMap.Driving"], () => {
        state.driving = new AMap.Driving({
          map: state.map,
          policy: AMap.DrivingPolicy.LEAST_TIME,
          showTraffic: true,
          hideMarkers: false,
        });
        if (state.selectedRoute) {
          drawRoute(state.selectedRoute);
        }
      });
      resolve();
    };
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}&callback=_amapInit`;
    script.onerror = () => {
      keyStatus.textContent = "高德 JS 加载失败，使用 Mock 地图";
      resolve();
    };
    document.head.appendChild(script);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "规划中";
  try {
    const res = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_input: input.value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "规划失败");
    updateShareUrl(input.value);
    render(data);
  } catch (error) {
    logsEl.innerHTML = `<div class="log-item"><strong>error</strong>${escapeHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "规划";
  }
});

function render(data) {
  state.lastPlan = data;
  taskJson.textContent = JSON.stringify(data.task, null, 2);
  renderRoutes(data.routes);
  renderLogs(data.logs);
  drawRoute(data.routes[0]);
}

function renderRoutes(routes) {
  routesEl.innerHTML = "";
  routes.forEach((route, index) => {
    const card = document.createElement("article");
    card.tabIndex = 0;
    card.className = `route-card ${index === 0 ? "selected" : ""}`;
    card.innerHTML = `
      <div class="route-head"><span>${route.rank}. ${escapeHtml(route.title)}</span><span>${escapeHtml(route.provider)}</span></div>
      <div class="route-metrics">
        <span class="metric">${Math.round(route.duration_s / 60)} 分钟</span>
        <span class="metric">${(route.distance_m / 1000).toFixed(1)} 公里</span>
        <span class="metric">过路费 ¥${route.tolls_yuan}</span>
        <span class="metric">${route.traffic_lights} 个红绿灯</span>
      </div>
      <div class="reason">${escapeHtml(route.reason)}</div>
      <div class="reason">点击卡片后，将在右侧高德地图内生成算路结果。</div>
    `;
    const selectRoute = () => {
      document.querySelectorAll(".route-card").forEach((item) => item.classList.remove("selected"));
      card.classList.add("selected");
      drawRoute(route);
    };
    card.addEventListener("click", selectRoute);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectRoute();
      }
    });
    routesEl.appendChild(card);
  });
}

function renderLogs(logs) {
  logsEl.innerHTML = "";
  logs.forEach((log) => {
    const item = document.createElement("div");
    item.className = "log-item";
    item.innerHTML = `<strong>${escapeHtml(log.tool || "tool")}</strong><pre>${escapeHtml(JSON.stringify(log, null, 2))}</pre>`;
    logsEl.appendChild(item);
  });
}

function drawRoute(route) {
  state.selectedRoute = route;
  if (state.amapLoaded && state.map && window.AMap) {
    drawAmapRoute(route);
    return;
  }
  drawMockMap(route);
}

function drawAmapRoute(route) {
  clearAmapOverlays();
  if (state.driving && route.origin?.location && route.destination?.location) {
    const origin = toLngLat(route.origin.location);
    const destination = toLngLat(route.destination.location);
    const waypoints = (route.waypoints || []).filter((place) => place.location).map((place) => toLngLat(place.location));
    const options = waypoints.length ? { waypoints } : {};
    state.driving.search(origin, destination, options, (status) => {
      if (status !== "complete") {
        drawAmapPolyline(route);
        keyStatus.textContent = "高德地图已加载，算路失败时显示后端路线";
      } else {
        keyStatus.textContent = "高德地图已加载，已在地图内算路";
      }
    });
    return;
  }
  drawAmapPolyline(route);
}

function drawAmapPolyline(route) {
  clearAmapOverlays();
  const path = route.polyline.map(parseLngLat);
  const polyline = new AMap.Polyline({ path, strokeColor: "#0f8b8d", strokeWeight: 7, strokeOpacity: 0.9 });
  const start = new AMap.Marker({ position: path[0], label: { content: "起点" } });
  const end = new AMap.Marker({ position: path[path.length - 1], label: { content: "终点" } });
  state.polylines.push(polyline);
  state.markers.push(start, end);
  state.map.add([polyline, start, end]);
  state.map.setFitView([polyline, start, end], false, [40, 40, 40, 40]);
}

function clearAmapOverlays() {
  if (state.driving) {
    state.driving.clear();
  }
  if (state.polylines.length || state.markers.length) {
    state.map.remove([...state.polylines, ...state.markers]);
  }
  state.polylines = [];
  state.markers = [];
}

function drawMockMap(route) {
  const canvas = mockMap;
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(720, Math.floor(rect.width * scale));
  canvas.height = Math.max(420, Math.floor(rect.height * scale));
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  const width = canvas.width / scale;
  const height = canvas.height / scale;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#eaf0f1";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d2dddf";
  ctx.lineWidth = 1;
  for (let x = 0; x < width; x += 42) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y < height; y += 42) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  const points = route.polyline.map((point) => {
    const [lng, lat] = point.split(",").map(Number);
    return { lng, lat };
  });
  const lngs = points.map((p) => p.lng);
  const lats = points.map((p) => p.lat);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const pad = 56;
  const project = (p) => ({
    x: pad + ((p.lng - minLng) / Math.max(0.001, maxLng - minLng)) * (width - pad * 2),
    y: height - pad - ((p.lat - minLat) / Math.max(0.001, maxLat - minLat)) * (height - pad * 2),
  });
  const projected = points.map(project);
  ctx.strokeStyle = "#0f8b8d";
  ctx.lineWidth = 7;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  projected.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.stroke();
  projected.forEach((p, i) => {
    ctx.fillStyle = i === 0 ? "#2f7d32" : i === projected.length - 1 ? "#d95d39" : "#f2b705";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.fillStyle = "#172026";
  ctx.font = "14px Microsoft YaHei, Arial";
  ctx.fillText(`${route.title} · ${(route.distance_m / 1000).toFixed(1)} 公里 · ${Math.round(route.duration_s / 60)} 分钟`, 18, 28);
}

function parseLngLat(point) {
  const [lng, lat] = point.split(",").map(Number);
  return [lng, lat];
}

function toLngLat(point) {
  const [lng, lat] = parseLngLat(point);
  return new AMap.LngLat(lng, lat);
}

function updateShareUrl(text) {
  const url = new URL(window.location.href);
  url.searchParams.set("q", text);
  window.history.replaceState({}, "", url);
}

async function copyShareLink() {
  updateShareUrl(input.value);
  const shareUrl = window.location.href;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(shareUrl);
  } else {
    input.focus();
    window.prompt("复制测评链接", shareUrl);
  }
  shareButton.textContent = "已复制";
  setTimeout(() => {
    shareButton.textContent = "复制测评链接";
  }, 1400);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

window.addEventListener("resize", () => {
  if (state.selectedRoute && !state.amapLoaded) drawMockMap(state.selectedRoute);
});

shareButton.addEventListener("click", () => {
  copyShareLink().catch((error) => {
    logsEl.innerHTML = `<div class="log-item"><strong>share</strong>${escapeHtml(error.message)}</div>`;
  });
});

const initialQuery = new URLSearchParams(window.location.search).get("q");
if (initialQuery) {
  input.value = initialQuery;
}

setupCases();
loadContext().then(() => form.requestSubmit());
