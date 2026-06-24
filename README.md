# AI + 高德导航助手 MVP

这是一个 Web Demo，用于验证“GPT 复杂出行任务理解 + 高德开放平台 Skill/地图能力”的 AI 导航助手方案。

## 功能

- 自然语言输入导航需求
- GPT 输出结构化导航任务 JSON
- 高德 Web Service API 或 Mock 模式完成 POI 搜索、地理编码、路径规划
- 可切换高德 WebService adapter 与 Skill/MCP adapter
- 高德 JS API 或 Canvas Mock 地图展示路线
- 推荐路线卡片、推荐理由、工具调用日志
- 内置 5 个核心验收场景测试用例

## MVP 构成思路

```text
自然语言输入
-> GPT 任务理解，输出 navigation_task JSON
-> 高德 Web Service 或 Skill/MCP Adapter 执行 POI/路线工具调用
-> route_ranker 生成推荐路线与理由
-> 前端高德 JS API 在地图内算路/渲染
```

当前可稳定演示的是 `Web Service API + JS API` 链路；`Skill/MCP Adapter` 用于展示后续 Agent 化接入方式，真实 Skill/MCP runtime 可在 `backend/amap_skill_adapter.py` 中替换。

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
- `AMAP_ADAPTER` 可选 `webservice` 或 `skill`；`skill` 会启用高德 Skill/MCP 适配层日志。
- `AMAP_JS_API_KEY` 用于前端地图展示和路线渲染。
- `AMAP_SECURITY_JS_CODE` 用于高德 JS API 的安全密钥校验。
- 未配置时系统自动走 Mock 模式，仍可完成 Demo 验收。

## 配置 GPT API Key

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API Key"
$env:OPENAI_MODEL="gpt-4.1-mini"
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

1. 我先送孩子上学，然后去公司
2. 去公司路上找个咖啡店，别太绕
3. 回家路上加个油
4. 我 8 点半火车，现在出发来得及吗？
5. 这条路太堵了，换一条
