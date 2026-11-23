# Open WebUI `v0.13.4` 零 Fork 薄接入套件

本目录提供面向 **Open WebUI `v0.13.4`** 的零源码修改（Zero-Fork）参考接入层，严格遵循 Phase 2 锁定结论（DEC-28 / G-05a=C / G-05b=1）：

- **0 行 Open WebUI 源码修改**：全部 L2 Adapter Contract、L3 DB III（`personal_bridge.sqlite`）与 2D WebGL 知识世界地图均由独立进程 `kos-engine` 托管；不修改也不重分发 Open WebUI 本体，不触发其 50 用户品牌限制条款。
- **旁路原生知识库、直连 L1**：不将 84,552 个 KOS 节点导入 Open WebUI 的 Chroma/向量库，避免存储翻倍与图谱边结构丢失。

## 套件内容

| 文件 | 角色 | 对接 Open WebUI `v0.13.4` 原生扩展位 |
| :--- | :--- | :--- |
| [`functions/kos_attach_filter.py`](<functions/kos_attach_filter.py>) | `/attach` 五维候选召回与 DB III 确认写回 | 管理员面板 → 函数（Filter：`inlet`/`outlet` + `Valves`） |
| [`functions/kos_explore_action.py`](<functions/kos_explore_action.py>) | 一键沿边 2-hop 拓扑探索与 2D 地图跳转 | 管理员面板 → 函数（Action 按钮） |
| [`mcp/mcp_server_config.json`](<mcp/mcp_server_config.json>) | MCP Tools + MCP Apps（`ui://kos-engine/map`）字段对照表 | 管理员面板 → 设置 → 扩展功能 → 外部工具服务器 |
| [`automations/serendipity_rrule.json`](<automations/serendipity_rrule.json>) | RRULE 定时受控漫游简报模板 | 自动化任务 |

## 接入四步（完整图文见 [`docs/OPEN_WEBUI_GUIDE.md`](../../docs/OPEN_WEBUI_GUIDE.md)）

1. **起 HTTP 服务**（只读 L1 + 独立 DB III）：

   ```bash
   cd kos_engine
   uv sync
   uv run kos-engine --core <路径>/human_kos_core.sqlite serve --port 8787
   ```

2. **起 MCP 服务**（默认端口 **8788**，不要用 8000——那是 Open Terminal 的默认端口）：

   ```bash
   uv run kos-engine mcp --transport streamable-http --port 8788 --api-origin http://127.0.0.1:8787
   ```

   Open WebUI 跑在 Docker 里时，再加 `--allow-host host.docker.internal:8788`，否则会收到 HTTP 421。

3. **在 Open WebUI 加连接**：管理员面板 → 设置 → 扩展功能 → 外部工具服务器 → 添加连接 → 类型选 **MCP 流式 HTTP**，认证方式选 **无身份验证**。URL 用 `http://127.0.0.1:8788/mcp`（Docker 部署用 `http://host.docker.internal:8788/mcp`）。

4. **导入两个 Function**：管理员面板 → 函数 → 创建 → 粘贴（或「从链接导入」）两个 `.py` 文件，并打开「已启用」。

5. **把它们挂到模型上**：工作空间 → 模型 → 创建 → 基础模型选你常用的那个，然后在同一个页面里选上 **工具** = `Human KOS Engine`、**筛选** = `/attach Filter`、**操作** = `Topological Explore Action`，保存。之后选这个模型聊天即可。

6. **改 Valve**：点函数右侧 **配置项**（字段要先点「默认」变「自定义」才可编辑），把 `kos_api_url` 改成 Open WebUI 能访问到的地址（Docker 部署用 `http://host.docker.internal:8787`），并把 `public_map_base` 设为 `http://127.0.0.1:8787`（浏览器侧地址）。

> 想在内嵌地图里看到扩展包，记得把 `human_kos_ext/` 放在核心库同级；地图 HUD 的「按需挂载」会自动列出全部扩展包。

## 日常使用示例

- 对话内输入 `/attach 知识图谱与认知科学` → Filter 调用 `kos-engine` 返回严格隔离的五维候选列表；
- 勾选确认后输入 `/attach confirm DOMAIN:oa:T10001 PROCESS:ccs:10010147` → 经 L1 校验后写入独立可写 DB III（`personal_bridge.sqlite`）；
- 点消息工具栏的 **Human KOS Topological Explore Action** → 沿边 2-hop 展开，并在消息里追加「沿边拓扑探索摘要」；
- 让模型调用 MCP 工具 `kos_open_map` → 在 Open WebUI 并行 Tab / MCP App 沙箱 iframe 中渲染交互式 2D 知识世界地图（点击节点可回调 `openwebui.sendMessage()` 发起新探索）。
