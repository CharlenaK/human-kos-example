# Open WebUI `v0.13.4` 零 Fork 薄接入套件

本目录提供面向 **Open WebUI `v0.13.4`** 的零源码修改（Zero-Fork）参考接入层，严格遵循 Phase 2 锁定结论（DEC-28 / G-05a=C / G-05b=1）：

- **0 行 Open WebUI 源码修改**：全部 L2 Adapter Contract、L3 DB III（`personal_bridge.sqlite`）与 2D WebGL 知识世界地图均由独立进程 `kos-engine` 托管；不修改也不重分发 Open WebUI 本体，不触发其 50 用户品牌限制条款。
- **旁路原生知识库、直连 L1**：不将 84,552 个 KOS 节点导入 Open WebUI 的 Chroma/向量库，避免存储翻倍与图谱边结构丢失。

## 套件内容

| 文件 | 角色 | 对接 Open WebUI `v0.13.4` 原生扩展位 |
| :--- | :--- | :--- |
| [`functions/kos_attach_filter.py`](<functions/kos_attach_filter.py>) | `/attach` 五维候选召回与 DB III 确认写回 | Workspace → Functions（Filter `inlet`/`outlet` + `Valves`） |
| [`functions/kos_explore_action.py`](<functions/kos_explore_action.py>) | 一键沿边 2-hop 拓扑探索与 2D 地图跳转 | Workspace → Functions（Action 按钮） |
| [`mcp/mcp_server_config.json`](<mcp/mcp_server_config.json>) | MCP Tools + MCP Apps（`ui://kos-engine/map`）配置 | Admin → External Tools / MCP Servers（含 Tether stdio） |
| [`automations/serendipity_rrule.json`](<automations/serendipity_rrule.json>) | RRULE 定时受控漫游简报模板 | Automations（`routers/automations.py`） |

## 无 Docker 接入步骤（4 步）

1. **启动独立 `kos-engine` 本地 HTTP + 2D 地图服务**（只读 L1 + 独立 DB III）：
   ```powershell
   cd kos_engine
   uv sync
   uv run kos-engine serve --host 127.0.0.1 --port 8787
   ```
   打开独立浏览器 `http://127.0.0.1:8787/map` 即可使用 2D 知识世界地图与映射工作台。
2. **启动 MCP Server（供 Open WebUI 调用工具与 MCP App 平行 Tab 地图）**：
   - Streamable HTTP：`uv run kos-engine mcp --transport streamable-http --api-origin http://127.0.0.1:8787`
   - 或在 Open WebUI Tether 中按 `mcp/mcp_server_config.json` 配置本地 `stdio`。
3. **在 Open WebUI 导入两个 Python Function**：
   - 进入 `Workspace → Functions → + New Function`，分别粘贴 `kos_attach_filter.py` 与 `kos_explore_action.py`；
   - 在 `Valves` 中核对 `kos_api_url`（默认 `http://127.0.0.1:8787`）并启用。
4. **在 Open WebUI 配置 RRULE Automation**：
   - 参照 `automations/serendipity_rrule.json` 新建定时任务，绑定 `mcp:kos-engine` 工具集。

## 日常使用示例

- 对话内输入 `/attach 知识图谱与认知科学` → Filter 调用 `kos-engine` 返回严格隔离的五维候选列表；
- 勾选确认后输入 `/attach confirm DOMAIN:oa:T10001 PROCESS:ccs:10010147` → 经 L1 校验后写入独立可写 DB III（`personal_bridge.sqlite`）；
- 调用 MCP 工具 `kos_open_map` → 在 Open WebUI 并行 Tab / MCP App 5 MB 沙箱 iframe 中渲染交互式 2D 知识世界地图（点击节点可回调 `openwebui.sendMessage()` 发起新探索）。
