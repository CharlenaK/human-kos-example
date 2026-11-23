# 把 Human KOS 接进 Open WebUI（零改源码图文指南）

> 适用：Open WebUI `v0.13.4` 及以上；`kos-engine` 可以在本机跑，也可以在 Docker 里跑。
> 目标：装完之后，你在聊天框里输入 `/attach 某个话题`，就能拿到五个维度的知识锚点；点消息上的按钮，就能看 2D 知识地图。

---

## 0. 先认识四个词

| 词 | 一句话解释 |
| :--- | :--- |
| **kos-engine** | 本项目自带的小服务。它读你的知识库、记住你的映射、画出地图。它和 Open WebUI 是两个独立程序，靠 HTTP 说话。 |
| **MCP** | 一种「让 AI 客户端发现并使用外部工具」的通用插座。Open WebUI 通过它看到 `kos-engine` 提供的 11 个工具。 |
| **Filter（过滤器）** | 一条贴在聊天管道上的小插件。它在消息发给模型**之前**动刀，`/attach` 就是它实现的。 |
| **Valve（阀门）** | 插件面板里的可调参数，比如「kos-engine 的地址是多少」。 |

另外两个词会反复出现：

- **DB II / L1**：只读的知识库（`human_kos_core.sqlite` + 扩展包），程序永远不会写它。
- **DB III**：你自己的映射账本（`personal_bridge.sqlite`），只有它会写。

---

## 1. 准备两样东西

### 1.1 知识库文件

去 [Human KOS Releases](https://github.com/CharlenaK/human-kos/releases/latest) 下载：

1. **必装**：`human_kos_core.sqlite`（约 238 MB，8.4 万个概念）。
2. **选装**：`human_kos_ext/` 目录里的扩展包（`unesco`、`lcsh`、`aat`、`cn_rel` …）。

放成下面这样，程序就会自动认出来（扩展包必须和核心库**在同一个文件夹**，且文件夹名就叫 `human_kos_ext`）：

```text
my-kos-data/
├── human_kos_core.sqlite
└── human_kos_ext/
    ├── unesco.sqlite
    ├── lcsh.sqlite
    └── ...
```

> 只放核心库也能用，只是「按需挂载」那一行会是空的。想用扩展包，就把它们放进去，或者启动时用 `--ext-dir` 指过去。

### 1.2 一个能跑 Python 的环境

只需要装一次 [`uv`](https://docs.astral.sh/uv/)：

- **Windows（PowerShell）**：`irm https://astral.sh/uv/install.ps1 | iex`
- **macOS / Linux**：`curl -LsSf https://astral.sh/uv/install.sh | sh`

然后拿到本项目代码，装依赖：

```bash
git clone https://github.com/CharlenaK/human-kos-example.git
cd human-kos-example/kos_engine
uv sync
```

---

## 2. 启动 kos-engine（一个窗口，先别关）

### 2.1 先想清楚一件事：谁在访问它？

`kos-engine` 会被**两个不同的角色**访问，地址可能不一样：

| 谁 | 用来干什么 | 常见地址 |
| :--- | :--- | :--- |
| **Open WebUI 自己** | 调 `/attach`、调工具、取视口数据 | 同机：`127.0.0.1`；Open WebUI 在 Docker 里：`host.docker.internal` |
| **你的浏览器** | 打开 2D 地图 | 永远是 `127.0.0.1`（地图在你自己电脑的浏览器里跑） |

记住这个区别，后面所有「连不上」的问题几乎都出在这里。

### 2.2 起服务

```bash
cd human_kos_example/kos_engine

# 同机部署（Open WebUI 直接跑在你这台电脑上，不在 Docker 里）
uv run kos-engine --core /path/to/my-kos-data/human_kos_core.sqlite serve --port 8787
```

如果 Open WebUI 跑在 **Docker** 里，用下面这条（多一个 `--host 0.0.0.0`，让容器能连进来）：

```bash
uv run kos-engine --core /path/to/my-kos-data/human_kos_core.sqlite serve --host 0.0.0.0 --port 8787
```

看到 `Uvicorn running on http://...:8787` 就成了。验证：

- 浏览器打开 <http://127.0.0.1:8787/health>，应返回一段 `{"status":"ok", ...}` 的 JSON；
- 浏览器打开 <http://127.0.0.1:8787/map>，应看到 2D 知识地图。

> 地图页 HUD 上的「按需挂载」会列出你 `human_kos_ext/` 里的全部扩展包，点一下即挂载、再点一下卸载。

---

## 3. 把 MCP 服务接进 Open WebUI

### 3.1 再开一个窗口，启动 MCP 服务

```bash
cd human_kos_example/kos_engine

# 同机部署
uv run kos-engine mcp --transport streamable-http --port 8788 --api-origin http://127.0.0.1:8787
```

Open WebUI 在 **Docker** 里时，加一个「允许的主机名」（否则 Open WebUI 会被 421 挡住）：

```bash
uv run kos-engine mcp --transport streamable-http --port 8788 ^
  --allow-host host.docker.internal:8788 ^
  --api-origin http://127.0.0.1:8787
```

（上面用 `^` 把一行拆成多行，那是 **cmd** 的写法；用 **PowerShell** 的话换成反引号 `` ` ``，用 **macOS / Linux** 的话换成 `\`。嫌麻烦就整条写在一行里。）

三个参数的含义：

- `--port 8788`：MCP 服务的端口。**不要用 8000**，那是 Open Terminal 的默认端口，会打架。
- `--allow-host host.docker.internal:8788`：告诉服务「来自 Docker 的这个主机名是合法的」。
- `--api-origin http://127.0.0.1:8787`：地图在 iframe 里要取数据时用的地址——这里要填**浏览器**能访问到的地址。

### 3.2 在 Open WebUI 里加连接

1. 右上角头像 → **管理员面板** → **设置** → 左侧「工具」分组下的 **扩展功能**；
2. 找到「外部工具服务器」，点 **添加连接**；
3. 按下面填写：

| 字段 | 填什么 |
| :--- | :--- |
| 类型 | 点一下按钮，切到 **MCP 流式 HTTP** |
| 名称 | `Human KOS Engine`（随便起） |
| URL | 同机：`http://127.0.0.1:8788/mcp`；Docker：`http://host.docker.internal:8788/mcp` |
| 认证方式 | **无身份验证** |

4. 点 **验证连接**。看到「连接成功」再点 **保存**。

> 如果验证失败：先看第 8 节排错表。最常见的两个原因是「URL 少了 `/mcp`」和「服务端没加 `--allow-host`」。

### 3.3 建一个「带工具」的模型

连接建好只代表「Open WebUI 认识这个服务了」，模型还不会自动获得这些工具。补一步：

1. 打开 **工作空间 → 模型 → 创建**；
2. 名字填 `KOS (MCP)`（随便起）；**基础模型（来自）** 选你平时用的那个模型；
3. 往下滚动，在 **工具** 里选 `Human KOS Engine`；
4. 点 **保存并创建**。

第 4 步装完聊天插件后，回到这个模型把 **筛选 / 操作** 也选上（见 4.2），三样就齐了。

---

## 4. 装两个聊天插件（Filter + Action）

### 4.1 装在哪

Open WebUI 的函数不在「工作空间」里，而在 **管理员面板 → 函数**。

点右上角 **创建** 旁边的下拉箭头 → **从链接导入**，把下面两个文件的原始链接贴进去（也可以直接 **创建** 后把文件内容整段粘进代码框）：

- `adapters/open_webui/functions/kos_attach_filter.py`
- `adapters/open_webui/functions/kos_explore_action.py`

保存后，列表里会出现两条：

- `Human KOS Five-Facet /attach Filter`（标签 `FILTER`）
- `Human KOS Topological Explore Action`（标签 `ACTION`）

### 4.2 启用，并挂到模型上

1. 每条函数右侧都有一个 **「已启用」** 开关，打开它；
2. 回到 **工作空间 → 模型**，点开第 3.3 步建的 `KOS (MCP)`，往下滚动：
   - **筛选** → 选 `Human KOS Five-Facet /attach Filter`
   - **操作** → 选 `Human KOS Topological Explore Action`
3. 保存。

> 三步缺一不可：开关决定「函数能不能跑」，模型里的「工具 / 筛选 / 操作」决定「哪个模型用它」。
> 这一版 Open WebUI 的函数页没有「全局」开关，挂到模型上是唯一的图形化做法。

### 4.3 改 Valve（关键一步）

点函数右侧的 **配置项**：

- 每个字段默认只显示一个 **默认** 按钮，点它变成 **自定义**，才会出现输入框；
- 把 **Kos Api Url** 改成 Open WebUI 能访问到的地址：
  - 同机部署：`http://127.0.0.1:8787`
  - Open WebUI 在 Docker 里：`http://host.docker.internal:8787`
- **Public Map Base** 留空即可（同机部署）；Docker 部署时填 `http://127.0.0.1:8787`，这样聊天里出现的地图链接才是你浏览器能点开的。

保存后，回到聊天页，输入：

```text
/attach 知识图谱与认知科学
```

你应该先看到状态提示「正在检索 Human KOS 五维正交分面候选…」，随后模型按 `DOMAIN / ACTIVITY / PROCESS / ARTIFACT / STANCE` 五个分面列出候选。确认后输入：

```text
/attach confirm DOMAIN:oa:T11148 PROCESS:ccs:10010147.10010178.10010187
```

这条会被写进你自己的 DB III（`personal_bridge.sqlite`）。

### 4.4 用 Action 按钮看地图

任意一条模型回复的工具栏里，会多出一个 **Human KOS Topological Explore Action** 按钮。点它会：

1. 用这条回复的内容找 3 个种子概念；
2. 沿真实图谱边走 2 跳；
3. 在消息里追加一段「沿边拓扑探索摘要」，并给出地图链接。

> 小提醒：目前这版 Open WebUI 里，追加的内容有时要等你重新打开这条对话才显示；按钮点击后会先出现一行状态「沿边拓扑探索完成：N 节点 / M 条边」，以它为准。

---

## 5. 让模型在对话里直接开地图（MCP App）

选中带工具的模型，然后说一句：

```text
请调用 kos_open_map 打开知识地图
```

首次调用会弹出「允许 / 拒绝」的确认框（Open WebUI 默认每次工具调用都要你点同意），点 **允许** 即可。之后对话里会出现一个内嵌的 2D 地图面板：

- 面板里可以拖拽、缩放、切 LoD、打开节点详情；
- 点「在对话中探索」会把选中节点发回对话，开一段新的追问。

> 如果面板里显示「视口拉取失败」，说明 `--api-origin` 填的地址你的浏览器打不开，或者用了旧版本（旧版本的沙箱策略会拦掉取数请求）。确认 `--api-origin` 是 `http://127.0.0.1:8787`，并更新到最新代码。

---

## 6. 定时简报（可选）

Open WebUI 的 **自动化任务** 支持按 RRULE 周期跑一条提示词。本仓库给了模板 `adapters/open_webui/automations/serendipity_rrule.json`：

1. 打开 **自动化任务** → **创建**；
2. 标题随便起；提示词把模板里的 `prompt` 整段粘进去；
3. 定时选「每周」，或选「自定义」直接填 `FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=9;BYMINUTE=0`；
4. **模型** 选第 3.3 步里那个挂了工具的模型（例如 `KOS (MCP)`）；
5. 保存。

> 自动化弹窗里没有「选工具」这一项，工具是跟着模型走的——所以第 3.3 步不能跳。

---

## 7. 四个地址，一次记清

| 场景 | Open WebUI 填的地址 | 浏览器打开的地址 |
| :--- | :--- | :--- |
| 全部在你这台电脑上 | `http://127.0.0.1:8787` | `http://127.0.0.1:8787/map` |
| Open WebUI 在 Docker 里 | `http://host.docker.internal:8787` | `http://127.0.0.1:8787/map` |
| MCP 服务（同机） | `http://127.0.0.1:8788/mcp` | — |
| MCP 服务（Docker） | `http://host.docker.internal:8788/mcp` | — |

一句话：**Open WebUI 用「容器能看见的名字」，浏览器用 `127.0.0.1`。**

---

## 8. 排错表

| 你看到的 | 多半是因为 | 怎么办 |
| :--- | :--- | :--- |
| 验证连接失败，日志里是 `421 Misdirected Request` | MCP 服务不认 `host.docker.internal` 这个主机名 | 启动时加 `--allow-host host.docker.internal:8788` |
| 启动 MCP 时报 `[Errno 10048] ... 8000` | 8000 被 Open Terminal 占了 | 加 `--port 8788` |
| 聊天里报 `All connection attempts failed` | Open WebUI 连不到 `kos_api_url` | Docker 部署把 Valve 改成 `http://host.docker.internal:8787`；同机部署确认 8787 在跑 |
| 输入 `/attach` 没反应 | 函数没启用，或模型里没挂「筛选」 | 见 4.2 |
| 地图面板空白、提示「视口拉取失败」 | `--api-origin` 不是浏览器能访问的地址 | 改成 `http://127.0.0.1:8787` |
| 地图 HUD 里「按需挂载」是空的 | 没放扩展包，或没放在核心库同级的 `human_kos_ext/` | 见 1.1 |
| 模型说「没有找到这个工具」 | 模型没挂工具服务器 | 见 3.3 |
| 点探索按钮后只看到一行状态、没看到卡片 | 这版 Open WebUI 的已知表现 | 重新打开这条对话即可看到完整卡片 |

---

## 9. 安全与边界（三句话）

1. **L1 只读**：`kos-engine` 用只读方式打开核心库与扩展包，不会、也不能修改它们。
2. **DB III 独立**：你的会话映射写在 `.kos_local/personal_bridge.sqlite`（可用 `--bridge-db` 改路径），不进仓库、不上传。
3. **许可要保留**：`CC BY-SA`（如 `unesco`、`cn_rel`、`dila`）的节点被用在对外产物里时，应保留署名并以相同方式共享；地图挂载这些包时会自动弹出提示。
