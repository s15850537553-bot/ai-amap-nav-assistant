const cases = [
  "我要先去送孩子上学，然后再去上班",
  "我现在回家，同时要买份外卖送到家，送到家的时刻要晚于我到家的时间",
  "我现在回家，顺路去加个油",
  "去公司路上推荐一个旅游景点和一家美食餐厅，别太绕",
  "我现在回家，电量好像不太够，帮我安排一下",
  "我朋友说在万达地铁口等我，我让他在哪里等我比较好",
  "我现在要马上去芜湖出差，时间有点赶，帮我找最合适的一班高铁、二等座、靠过道",
  "去虹桥机场接我老婆，顺便买个她会喜欢的礼物，安排好一定要准时接机，不要迟到了，然后找个餐厅吃饭，最后去放松一下缓解一下老婆出差的疲惫",
  "我早上要先去送孩子上学送个东西，7:40前必须到；老婆要去高铁站，8:30前到；我自己10点还有重要会议；中间帮我找个顺路吃早餐的地方，别绕路；去公司开完会，我要去客户那边，徐汇那边，下午要参加家长会，然后回家收拾一下行李出差3天，晚上还要去机场，有点赶，中间帮我安排好吃午饭的地方，晚饭我就在飞机上吃了",
];

const state = {
  amapLoaded: false,
  map: null,
  driving: null,
  polylines: [],
  markers: [],
  selectedRoute: null,
  selectedRouteSource: "plan",
  lastPlan: null,
  itineraryPoller: null,
  lastItineraryRouteId: null,
  itineraryBusy: false,
  itineraryBusyText: "",
  itineraryLastData: null,
  itineraryLocalEvents: [],
  mapMode: "plan",
  activeDrawToken: null,
};

const form = document.querySelector("#plannerForm");
const input = document.querySelector("#userInput");
const routesEl = document.querySelector("#routes");
const logsEl = document.querySelector("#logs");
const taskJson = document.querySelector("#taskJson");
const plannerReply = document.querySelector("#plannerReply");
const mockMap = document.querySelector("#mockMap");
const keyStatus = document.querySelector("#keyStatus");
const versionLine = document.querySelector("#versionLine");
const shareButton = document.querySelector("#shareButton");
const startItineraryButton = document.querySelector("#startItineraryButton");
const onboardButton = document.querySelector("#onboardButton");
const arrivedButton = document.querySelector("#arrivedButton");
const itineraryStatus = document.querySelector("#itineraryStatus");
const itinerarySegments = document.querySelector("#itinerarySegments");
const itineraryEvents = document.querySelector("#itineraryEvents");

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
  renderAppMeta(data.app || {});
  document.querySelector("#contextLine").textContent = `家：${ctx.home.address}｜公司：${ctx.company.address}｜油量 ${ctx.vehicle.fuel_percent}%｜SOC ${ctx.vehicle.soc_percent}%｜AMap ${adapter}`;
  if (data.amap_js_key) {
    keyStatus.textContent = data.amap_security_js_code ? "高德 JS Key 已配置" : "高德 JS Key 已配置，缺少安全密钥";
    await loadAmap(data.amap_js_key, data.amap_security_js_code);
  } else {
    keyStatus.textContent = "未配置 Key，使用 Mock 地图";
  }
}

function renderAppMeta(app) {
  const version = app.version || "v2026.06.26";
  const date = app.version_date || "2026-06-26";
  const commit = app.commit ? `｜提交 ${app.commit}` : "";
  versionLine.textContent = `版本：${version}｜日期：${date}${commit}`;
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
          drawRoute(state.selectedRoute, state.selectedRouteSource);
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
    state.mapMode = "plan";
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
  renderPlannerReply(data.reply);
  renderRoutes(data.routes);
  renderLogs(data.logs);
  drawRoute(data.routes[0], "plan");
}

function renderPlannerReply(reply) {
  if (!reply?.summary) {
    plannerReply.textContent = "暂无规划反馈。";
    return;
  }
  const lines = reply.summary.split("\n").filter(Boolean);
  plannerReply.innerHTML = lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("");
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
      ${renderRecommendations(route.recommendations)}
      <div class="reason">点击卡片后，将在右侧高德地图内生成算路结果。</div>
    `;
    const selectRoute = () => {
      document.querySelectorAll(".route-card").forEach((item) => item.classList.remove("selected"));
      card.classList.add("selected");
      state.mapMode = "plan";
      drawRoute(route, "plan");
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

function renderRecommendations(recommendations = []) {
  if (!recommendations.length) return "";
  const cards = recommendations
    .map((item) => {
      const source = item.source_url
        ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_title || "来源")}</a>`
        : escapeHtml(item.source_title || "联网搜索摘要");
      const routePlace = item.route_place_name ? `<span>${escapeHtml(item.route_place_name)}</span>` : "";
      const matchStatus = item.amap_match_status
        ? `<span class="${item.amap_match_status === "matched" ? "match-ok" : "match-miss"}">${item.amap_match_status === "matched" ? "高德已匹配" : "高德未匹配"}</span>`
        : "";
      return `
        <div class="recommendation-item">
          <div class="recommendation-head">
            <strong>${escapeHtml(item.name || "推荐地点")}</strong>
            <span>${escapeHtml(item.category || "推荐")}</span>
            ${routePlace}
            ${matchStatus}
          </div>
          <div class="recommendation-text">${escapeHtml(item.intro || "")}</div>
          <div class="recommendation-text">推荐理由：${escapeHtml(item.why || "")}</div>
          <div class="recommendation-source">来源：${source}</div>
        </div>
      `;
    })
    .join("");
  return `<div class="recommendations">${cards}</div>`;
}

function drawRoute(route, source = "plan") {
  if (!route) return;
  if (source === "plan" && state.mapMode === "itinerary") {
    return;
  }
  state.selectedRoute = route;
  state.selectedRouteSource = source;
  const token = `${source}:${route.id || route.title}:${Date.now()}`;
  state.activeDrawToken = token;
  if (state.amapLoaded && state.map && window.AMap) {
    drawAmapRoute(route, token, source);
    return;
  }
  drawMockMap(route);
  keyStatus.textContent = mapStatusText(route, source, "Mock 地图");
}

function drawAmapRoute(route, token, source) {
  clearAmapOverlays();
  if (state.driving && route.origin?.location && route.destination?.location) {
    const origin = toLngLat(route.origin.location);
    const destination = toLngLat(route.destination.location);
    const waypoints = (route.waypoints || []).filter((place) => place.location).map((place) => toLngLat(place.location));
    const options = waypoints.length ? { waypoints } : {};
    state.driving.search(origin, destination, options, (status) => {
      if (state.activeDrawToken !== token) return;
      if (status !== "complete") {
        drawAmapPolyline(route);
        keyStatus.textContent = `${mapStatusText(route, source, "后端路线")}｜高德算路失败`;
      } else {
        keyStatus.textContent = mapStatusText(route, source, "高德地图算路");
      }
    });
    return;
  }
  drawAmapPolyline(route);
  keyStatus.textContent = mapStatusText(route, source, "后端路线");
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

function clearMapView(message) {
  state.selectedRoute = null;
  state.selectedRouteSource = "itinerary";
  state.activeDrawToken = `clear:${Date.now()}`;
  if (state.amapLoaded && state.map && window.AMap) {
    clearAmapOverlays();
  }
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
  ctx.fillStyle = "#eef6f6";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#52666d";
  ctx.font = "15px Microsoft YaHei, Arial";
  ctx.fillText(message, 18, 32);
  keyStatus.textContent = message;
}

function mapStatusText(route, source, renderer) {
  const prefix = source === "itinerary" ? "地图显示当前行程段" : "地图显示推荐路线";
  return `${prefix}：${route.title}｜${renderer}`;
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

startItineraryButton.addEventListener("click", () => {
  state.itineraryLocalEvents = [];
  runItineraryAction(startItineraryButton, "生成计划中", "正在解析完整出行计划，并拆分每一段可触发路线...", async () => {
    state.mapMode = "itinerary";
    state.lastItineraryRouteId = null;
    clearMapView("多段行程已启动，等待用户上车后生成当前段路线");
    const data = await postItinerary("/api/itinerary/start", { user_input: input.value });
    renderItinerary(data);
    startItineraryPolling();
  });
});

onboardButton.addEventListener("click", () => {
  runItineraryAction(onboardButton, "推理中", "已模拟用户上车，正在判断触发条件、检索推荐点并调用高德生成下一段路线...", async () => {
    state.mapMode = "itinerary";
    const data = await postItinerary("/api/itinerary/event", { event_type: "user_onboard" });
    renderItinerary(data);
  });
});

arrivedButton.addEventListener("click", () => {
  runItineraryAction(arrivedButton, "检查中", "已模拟到达当前点，正在完成本段并检查下一段是否可触发...", async () => {
    state.mapMode = "itinerary";
    const data = await postItinerary("/api/itinerary/event", { event_type: "arrived" });
    renderItinerary(data);
  });
});

async function runItineraryAction(button, busyLabel, busyText, action) {
  const originalText = button.textContent;
  setItineraryBusy(true, busyText, button, busyLabel);
  appendLocalItineraryEvent(busyText);
  renderItinerary(state.itineraryLastData || { segments: [], events: [] });
  try {
    await action();
  } catch (error) {
    appendLocalItineraryEvent(`操作失败：${error.message}`);
    setItineraryStatus(`操作失败：${error.message}`, false);
  } finally {
    button.textContent = originalText;
    setItineraryBusy(false, "", null, "");
    if (state.itineraryLastData) {
      renderItinerary(state.itineraryLastData);
    } else {
      updateItineraryStatus(state.itineraryLastData);
    }
  }
}

function setItineraryBusy(isBusy, text, activeButton, activeLabel) {
  state.itineraryBusy = isBusy;
  state.itineraryBusyText = text;
  [startItineraryButton, onboardButton, arrivedButton].forEach((button) => {
    button.disabled = isBusy;
    button.classList.toggle("loading", isBusy && button === activeButton);
  });
  if (activeButton && activeLabel) {
    activeButton.textContent = activeLabel;
  }
  if (text) {
    setItineraryStatus(text, isBusy);
  }
}

function setItineraryStatus(text, isBusy = false) {
  itineraryStatus.textContent = text;
  itineraryStatus.classList.toggle("busy", isBusy);
}

function appendLocalItineraryEvent(detail) {
  state.itineraryLocalEvents.unshift({
    at: new Date().toLocaleTimeString(),
    tool: "local.ui",
    detail,
    local: true,
  });
  state.itineraryLocalEvents = state.itineraryLocalEvents.slice(0, 4);
}

async function postItinerary(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "多段行程操作失败");
  return data;
}

function startItineraryPolling() {
  if (state.itineraryPoller) {
    clearInterval(state.itineraryPoller);
  }
  state.itineraryPoller = setInterval(async () => {
    try {
      const res = await fetch("/api/itinerary/status");
      const data = await res.json();
      renderItinerary(data);
      if (data.status === "completed") {
        clearInterval(state.itineraryPoller);
        state.itineraryPoller = null;
      }
    } catch (error) {
      itineraryEvents.innerHTML = `<div class="event-item">定时检查失败：${escapeHtml(error.message)}</div>`;
    }
  }, 3000);
}

function renderItinerary(data) {
  state.itineraryLastData = data;
  updateItineraryStatus(data);
  itinerarySegments.innerHTML = "";
  (data.segments || []).forEach((segment, index) => {
    const item = document.createElement("div");
    const isCurrent = index === data.current_segment_index && data.status !== "completed";
    const isLocallyPlanning = state.itineraryBusy && isCurrent && !segment.route;
    item.className = `segment-card ${segment.status} ${segment.route ? "generated" : ""} ${isCurrent ? "current" : ""} ${isLocallyPlanning ? "planning" : ""}`;
    const summary = segment.route_summary
      ? `｜${segment.route_summary.duration_minutes} 分钟｜${segment.route_summary.distance_km} 公里`
      : "";
    const routeLabel = isLocallyPlanning ? "正在推理下一段路线..." : segment.recommended_route_id || "待生成";
    item.innerHTML = `
      <div class="segment-status">${escapeHtml(isLocallyPlanning ? "推理中" : statusText(segment.status))}</div>
      <div>
        <div class="segment-title">${index + 1}. ${escapeHtml(segment.title)}</div>
        <div class="segment-meta">触发：${escapeHtml(segment.trigger || "-")}</div>
        <div class="segment-meta">到达约束：${escapeHtml(segment.deadline || "无")}｜推荐路线：${escapeHtml(routeLabel)}${escapeHtml(summary)}</div>
        ${isLocallyPlanning ? `<div class="segment-thinking">正在综合用户上车事件、上一段完成状态、联网候选地点和高德路线结果...</div>` : ""}
        ${segment.planning_error ? `<div class="segment-error">${escapeHtml(segment.planning_error)}</div>` : ""}
        ${segment.route_summary?.reason ? `<div class="segment-meta">推荐理由：${escapeHtml(segment.route_summary.reason)}</div>` : ""}
        ${segment.route ? renderRecommendations(segment.route.recommendations) : ""}
        ${segment.route ? `<button type="button" class="segment-action">查看本段地图</button>` : ""}
      </div>
    `;
    const action = item.querySelector(".segment-action");
    if (action && segment.route) {
      action.addEventListener("click", (event) => {
        event.stopPropagation();
        state.mapMode = "itinerary";
        state.lastItineraryRouteId = segment.route.id;
        drawRoute(segment.route, "itinerary");
      });
    }
    if (segment.route) {
      item.addEventListener("click", () => {
        state.mapMode = "itinerary";
        state.lastItineraryRouteId = segment.route.id;
        drawRoute(segment.route, "itinerary");
      });
    }
    itinerarySegments.appendChild(item);
  });

  itineraryEvents.innerHTML = "";
  const events = [...state.itineraryLocalEvents, ...(data.events || []).slice(-12).reverse()];
  events.forEach((event) => {
    const item = document.createElement("div");
    item.className = `event-item ${event.local ? "local" : ""}`;
    item.textContent = `${event.at || ""} ${event.tool || "event"}｜${event.detail || event.status || ""}`;
    itineraryEvents.appendChild(item);
  });

  if (data.active_route && data.active_route.id !== state.lastItineraryRouteId) {
    state.mapMode = "itinerary";
    state.lastItineraryRouteId = data.active_route.id;
    drawRoute(data.active_route, "itinerary");
  }
}

function updateItineraryStatus(data) {
  if (state.itineraryBusy) return;
  if (!data || data.status === "idle") {
    setItineraryStatus("等待启动多段行程。", false);
    return;
  }
  if (data.status === "completed") {
    setItineraryStatus("全部行程段已完成。", false);
    return;
  }
  const segments = data.segments || [];
  const current = segments[data.current_segment_index];
  if (!current) {
    setItineraryStatus("多段行程运行中，等待下一次定时检查。", false);
    return;
  }
  if (current.route) {
    setItineraryStatus(`当前段路线已生成：${current.title}。可以查看地图或模拟到达当前点。`, false);
    return;
  }
  if (current.status === "planning") {
    setItineraryStatus(`正在后台推理当前段路线：${current.title}。可继续观察事件流，地图会在生成后自动更新。`, true);
    return;
  }
  setItineraryStatus(`下一段等待触发：${current.title}。点击“模拟用户上车”后生成路线。`, false);
}

function statusText(status) {
  return {
    waiting: "等待",
    planning: "推理中",
    active: "进行中",
    completed: "已完成",
  }[status] || status || "-";
}

const initialQuery = new URLSearchParams(window.location.search).get("q");
if (initialQuery) {
  input.value = initialQuery;
}

setupCases();
loadContext().then(() => form.requestSubmit());
