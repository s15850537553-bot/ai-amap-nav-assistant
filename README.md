# Carmind导航验证demo

版本：v2026.06.26  
版本日期：2026-06-26  
作者：阿晓

这是一个 Web Demo，用于验证“GPT 复杂出行任务理解 + 高德开放平台 Skill/地图能力”的 AI 导航助手方案。

## 功能

- 自然语言输入导航需求
- GPT 输出结构化导航任务 JSON
- 高德 Web Service API 或 Mock 模式完成 POI 搜索、地理编码、路径规划
- 可切换高德 WebService adapter 与 Skill/MCP adapter
- 高德 JS API 或 Canvas Mock 地图展示路线
- 推荐路线卡片、推荐理由、工具调用日志
- 多段行程定时触发：用户上车且满足条件时，自动推荐下一段路线
- 沿途地点推荐增强：当用户要求推荐景点、美食、咖啡、餐厅等地点时，补充地点介绍、推荐理由和来源
- 内置产品文档中的 8 个典型场景测试用例

## MVP 构成思路

```text
自然语言输入
-> GPT 任务理解，输出 navigation_task JSON
-> 高德 Web Service 或 Skill/MCP Adapter 执行 POI/路线工具调用
-> route_ranker 生成推荐路线与理由
-> 前端高德 JS API 在地图内算路/渲染
```

当前可稳定演示的是 `Web Service API + JS API` 链路；`Skill/MCP Adapter` 用于展示后续 Agent 化接入方式，真实 Skill/MCP runtime 可在 `backend/amap_skill_adapter.py` 中替换。

## 沿途地点推荐与联网搜索

当用户输入包含“推荐旅游景点”“推荐美食”“找餐厅”“找咖啡”等需求时，系统按产品链路拆成三层：

1. 联网模型地点发现：通过 `backend/online_search_adapter.py` 先搜索真实候选地点和介绍，默认 provider 为千问/DashScope。
2. 高德 POI 校验层：把联网模型推荐的地点名交给高德 Web Service，校验是否存在对应 POI，并获取地址、坐标。
3. 路线串联层：将高德匹配成功的 POI 串入路径规划和地图渲染。

推荐配置千问联网搜索：

```powershell
$env:PLACE_SEARCH_PROVIDER="qwen"
$env:DASHSCOPE_API_KEY="你的阿里云百炼 API Key"
$env:QWEN_MODEL="qwen-plus-latest"
```

如果没有配置 `DASHSCOPE_API_KEY`，系统不会编造联网模型候选地点，会保留原始 POI 类型给高德兜底搜索。

高德 POI 查询同样遵循这个原则：如果 Web Service API 返回错误或无结果，系统会显示“待联网确认：地点类型”，不会生成假的店名或地址。

## 多段行程定时触发验证

页面中的“多段行程定时触发验证”用于验证一个核心产品能力：

```text
多段行程不是固定脚本，也不是一次性全部发起导航，
而是基于用户当前输入生成完整出行计划，
再在行程执行过程中由后台定时任务持续检查：
上一段是否完成、用户是否已上车、时间/地点条件是否满足。
满足条件后，系统自动推荐并生成下一步出行路线。
```

Demo 流程：

1. 在输入框中输入完整出行计划。
2. 点击“启动多段行程”，系统按当前输入生成分段计划。
2. 点击“模拟用户上车”，系统触发第一段路线。
3. 点击“模拟到达当前点”，当前段完成，下一段进入等待。
4. 再次点击“模拟用户上车”，系统自动触发下一段路线。
5. 每段路线生成后，可点击该段卡片或“查看本段地图”，在右侧高德地图查看该段路线。

对应接口：

```text
POST /api/itinerary/start
POST /api/itinerary/event       {"event_type":"user_onboard"}
POST /api/itinerary/event       {"event_type":"arrived"}
GET  /api/itinerary/status
```

## 配置高德 Key

复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

配置：

```powershell
$env:AMAP_WEB_SERVICE_KEY="你的高德 Web Service Key"
$env:AMAP_WEB_SERVICE_PRIVATE_KEY="如果 Web服务 Key 开启数字签名，则填写私钥"
$env:AMAP_ADAPTER="webservice"
$env:AMAP_JS_API_KEY="你的高德 JS API Key"
$env:AMAP_SECURITY_JS_CODE="你的高德 Web端安全密钥"
```

说明：

- `AMAP_WEB_SERVICE_KEY` 用于后端 POI 搜索、地理编码、路径规划。
- `AMAP_WEB_SERVICE_PRIVATE_KEY` 用于 Web 服务数字签名；如果控制台关闭了数字签名，可不配置。
- 如果工具日志出现 `INVALID_USER_SIGNATURE`，说明当前高德 Key 需要数字签名或 Key 类型不匹配，需要在高德控制台检查 Web服务 Key 与安全密钥配置。
- `AMAP_ADAPTER` 可选 `webservice` 或 `skill`；`skill` 会启用高德 Skill/MCP 适配层日志。
- `AMAP_JS_API_KEY` 用于前端地图展示和路线渲染。
- `AMAP_SECURITY_JS_CODE` 用于高德 JS API 的安全密钥校验。
- 未配置时系统自动走 Mock 模式，仍可完成 Demo 验收。

## 配置 GPT API Key

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API Key"
$env:OPENAI_MODEL="gpt-4.1-mini"
$env:OPENAI_WEB_SEARCH_MODEL="支持联网搜索的模型"
```

未配置 `OPENAI_API_KEY` 时，后端会使用本地规则模拟 GPT 结构化 JSON 输出，便于离线验收。

## 启动项目

```powershell
cd C:\Users\横槊赋诗\Documents\工作\ai-amap-nav-assistant
python -m backend.api_server
```

打开浏览器：

```text
http://127.0.0.1:8000
```

如端口被占用：

```powershell
$env:PORT="8010"
python -m backend.api_server
```

如果要在同一局域网内分享给别人测评：

```powershell
$env:HOST="0.0.0.0"
$env:PORT="8000"
python -m backend.api_server
```

然后把本机局域网 IP 拼成链接，例如：

```text
http://你的局域网IP:8000/?q=去公司路上找个咖啡店，别太绕
```

页面里的“复制测评链接”会自动把当前输入话术写入 `q=` 参数。别人打开这个链接时，会自动恢复该话术并执行规划。

如果要分享到公网，需要把服务部署到一台公网可访问的机器，或使用内网穿透工具；同时在高德开放平台为 Web端 Key 配置对应域名白名单。

## 分享给外部用户

本地 `127.0.0.1` 和局域网 IP 只能给自己或同一网络的人访问。要给外部用户测评，需要一个公网 HTTPS 地址。

### 方案 A：部署到 Render

1. 把本项目上传到 GitHub 仓库。
2. 在 Render 创建 Blueprint 或 Web Service，选择本项目。
3. Render 会读取 `render.yaml`。
4. 在 Render 环境变量中配置：

```text
AMAP_WEB_SERVICE_KEY
AMAP_WEB_SERVICE_PRIVATE_KEY
AMAP_JS_API_KEY
AMAP_SECURITY_JS_CODE
OPENAI_API_KEY
AMAP_ADAPTER=skill
HOST=0.0.0.0
```

5. 部署完成后，Render 会给出类似：

```text
https://ai-amap-nav-assistant.onrender.com
```

可分享测评链接：

```text
https://你的公网域名/?q=我早上去送小孩上学，路上推荐个咖啡店，然后去公司别太绕。
```

### 方案 B：Docker 部署

```powershell
docker build -t ai-amap-nav-assistant .
docker run -p 8000:8000 `
  -e HOST=0.0.0.0 `
  -e AMAP_ADAPTER=skill `
  -e AMAP_WEB_SERVICE_KEY="你的Key" `
  -e AMAP_JS_API_KEY="你的Key" `
  -e AMAP_SECURITY_JS_CODE="你的安全密钥" `
  ai-amap-nav-assistant
```

### 方案 C：临时内网穿透

如果网络允许，可以运行：

```powershell
.\scripts\start_cloudflare_tunnel.ps1
```

它会尝试生成一个 `trycloudflare.com` 临时 HTTPS 地址。这个方式适合临时演示，不保证稳定。

### 高德 Key 注意事项

外部域名确定后，需要到高德开放平台 Web端 Key 设置中，把公网域名加入白名单。否则页面能打开，但高德 JS 地图可能加载失败。

如果当前机器的 `python` 命令指向 Windows Store 占位程序，也可以使用 Codex bundled Python：

```powershell
& "C:\Users\横槊赋诗\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m backend.api_server
```

## 运行测试用例

```powershell
cd C:\Users\横槊赋诗\Documents\工作\ai-amap-nav-assistant
python -m backend.run_tests
```

测试数据位于：

```text
test_cases/navigation_cases.json
```

## 项目结构

```text
frontend/
  index.html
  styles.css
  app.js
backend/
  navigation_planner.py
  amap_adapter.py
  amap_skill_adapter.py
  mock_context.py
  route_ranker.py
  api_server.py
prompts/
  navigation_planner.md
schemas/
  navigation_task.schema.json
test_cases/
  navigation_cases.json
```

## 核心场景

1. 我要先去送孩子上学，然后再去上班
2. 我现在回家，同时要买份外卖送到家，送到家的时刻要晚于我到家的时间
3. 我现在回家，顺路去加个油
4. 我现在回家，电量好像不太够，帮我安排一下
5. 我朋友说在万达地铁口等我，我让他在哪里等我比较好
6. 我现在要马上去芜湖出差，时间有点赶，帮我找最合适的一班高铁、二等座、靠过道
7. 去虹桥机场接我老婆，顺便买个她会喜欢的礼物，安排好一定要准时接机，不要迟到了，然后找个餐厅吃饭，最后去放松一下缓解一下老婆出差的疲惫
8. 我早上要先去送孩子上学送个东西，7:40前必须到；老婆要去高铁站，8:30前到；我自己10点还有重要会议；中间帮我找个顺路吃早餐的地方，别绕路；去公司开完会，我要去客户那边，徐汇那边，下午要参加家长会，然后回家收拾一下行李出差3天，晚上还要去机场，有点赶，中间帮我安排好吃午饭的地方，晚饭我就在飞机上吃了

8 个场景都会在 GPT JSON 中体现 `scenario_id`、导航目标/途经点、约束、`external_actions`、`execution_plan` 或 `decision_points`。复杂第 8 个场景同时可用“多段行程定时触发验证”面板演示执行中的下一段路线推荐。
