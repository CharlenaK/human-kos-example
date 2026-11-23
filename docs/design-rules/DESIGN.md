# Human KOS Design System (`DESIGN.md`)

> **读取时机**：新增或修改任何 2D 地图、MCP App 面板、`/attach` 候选卡片、漫游简报视图或控制台样式之前。先读「阅读路由」、§1 与 §7，再按需读对应章节；索引与治理规则见 [`kos-design-system.md`](<kos-design-system.md>)。
> **规范用词**：本文采用 RFC 2119 / RFC 8174 与 GB/T 1.1-2020 语义（**应 / 不应**、**宜 / 不宜**、**可 / 不必**、**能 / 不能**）。
> **数值单源**：所有 Token 数值以 [`tokens.dtcg.json`](<tokens.dtcg.json>) 为唯一编辑源，经 `tokens_guard.py --generate` 输出至 `kos_engine/web/src/styles/tokens.css`。

---

## 阅读路由

| 要做的事 | 消费入口 | 规则位置 |
| :--- | :--- | :--- |
| 页面背景、侧栏、卡片、分隔线 | `--kos-surface` / `--kos-card` / `--kos-board` | §2 层级色系、§6 深度哲学 |
| 为五维正交分面着色 | `--kos-facet-domain` … `--kos-facet-stance` | §2 五维分面身份色 |
| 表达 ShareAlike / `local_only` / 负边 / 校验结果 | `--kos-warning-fg` / `--kos-error-fg` / `--kos-success-fg` / `--kos-focus-ring` | §2 语义与许可门禁色 |
| 设置字号、字重、行高与中英混排 | `--kos-font-ui` / `--kos-font-code` / `--kos-text-*` | §3 排版规范 |
| 制作按钮、分面胶囊、检视抽屉、`/attach` 卡片 | 共享基础样式类 | §4 核心组件 |
| 选择圆角 | 两步判定树（先登记图元，后普通控件三档） | §5 两步圆角判定树 |
| 处理浮层阴影与叠放顺序 | `--kos-shadow-floating` / `--kos-z-*` | §6 深度与层级刻度 |
| 适配 Light / Dark 与 Open WebUI iframe | `[data-theme="light"\|"dark"]` + `prefers-color-scheme` | §8 双模式交付门槛 |
| 编写许可告警、负边提示、空态文案 | 直白陈述 + 规范用词 | §9 微文案与交互约定 |

---

## 1. Visual Theme & Atmosphere（光学透镜视觉氛围）

Human KOS 是面向人类用户的「光学透镜与知识世界地图」，不是娱乐化面板，也不是信息过载的监控大屏。界面应遵循四条基准原则：

1. **注意力留给知识结构**：冷静的纸感灰度构成全部容器与工作区底色；彩色仅用于区分**五维正交分面**与**已登记的语义/合规状态**，不用于装饰。
2. **边界替代阴影**：页面层级通过 `Surface` / `Card` 背景差与 `1px solid Board` 细线建立；基准视觉语言采用**零阴影**，仅浮层（弹窗、下拉菜单、悬停提示、浮动工具栏）可使用登记的 `--kos-shadow-floating`。
3. **无装饰噪音**：工作区不应放置吉祥物、渐变霓虹背景或无数据映射意义的装饰插画；2D 地图中每个视觉通道（坐标、分区多边形、节点颜色、边线样式、节点大小）均应稳定对应 L1/L3 数据字段。
4. **跨宿主一致**：同一套 Web 视图将在独立浏览器与 Open WebUI MCP Apps（5 MB 沙箱 iframe）两种环境中运行；样式应零外链 CDN、零宿主页样式假定，并在 Light 与 Dark 双模式下同等清晰。

---

## 2. Color Palette & Roles（颜色体系与白名单）

灰度规则近乎绝对：凡未在本节与 [`tokens.dtcg.json`](<tokens.dtcg.json>) 中登记的非灰度色值，均不应引入 UI 组件。

### 2.1 三层灰度体系（Layer System · Light & Dark）

| 角色 | Token | Light | Dark | 用途 |
| :--- | :--- | :--- | :--- | :--- |
| **Surface** | `--kos-surface` | `#f8f8f6` | `#1f1f1e` | 整窗与地图底层画布背景（单一平铺底色） |
| **Card** | `--kos-card` | `#ffffff` | `#2c2c2a` | 抬升表面：检视抽屉、`/attach` 卡片、弹窗、输入框、浮动 HUD 面板 |
| **Board** | `--kos-board` | `#d7d7d4` | `#3c3c3a` | 1px 细分隔线、卡片描边、控件静息边框 |
| **Chip / Hover** | `--kos-surface-chip` | `#e5e5e5` | `#3c3c3a` | 中性胶囊底色、悬停态、选中行柔底 |
| **Subtle Hover** | `--kos-surface-hover` | `#efefec` | `#343432` | 轻悬停底色（表格行、次要列表项） |

### 2.2 中性文字阶梯（Ordered Ink Ladder）

文字层级严格按对比度单调递减，不应通过调整元素 `opacity` 伪造层级：

| 角色 | Token | Light | Dark | 用途 |
| :--- | :--- | :--- | :--- | :--- |
| **Primary** | `--kos-text-primary` | `#262626` | `#d4d4d4` | 标题、节点主标签、正文、按钮文字（普通界面不使用纯黑 `#000000`） |
| **Secondary** | `--kos-text-secondary` | `#525252` | `#a3a3a3` | 副标签、面包屑路径、说明正文、次级图标 |
| **Tertiary** | `--kos-text-tertiary` | `#737373` | `#7d7d7a` | 元数据、时间戳、IC 数值、来源编码（不应作输入框 placeholder） |
| **Placeholder** | `--kos-text-placeholder` | `#a3a3a3` | `#595956` | 输入框占位提示与禁用态辅助文字 |
| **Inverse CTA** | `--kos-cta-bg` / `--kos-cta-fg` | `#262626` / `#ffffff` | `#f2f2ef` / `#1f1f1e` | 主动作胶囊按钮（如「确认挂载 `/attach`」「打开探索」） |

### 2.3 五维正交分面身份色（Registered Facet Identity Palette）

以下五色为 Human KOS 专属登记的**类别身份色**，**仅用于编码 `facet_type`**（地图节点、Voronoi 分区低饱和底色、分面图例方块 `facet-legend-swatch`、分面标签左色点）。五色**不应**用于表达健康状态、错误、警告或成功：

| `facet_type` | 语义 | 前景 / 节点 Token | Light | Dark | Voronoi 区域柔和填充 Token |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`DOMAIN`** | 学科与世界知识 | `--kos-facet-domain` | `#2563eb` | `#60a5fa` | `--kos-facet-domain-soft` |
| **`ACTIVITY`** | 人类活动、职业与技能 | `--kos-facet-activity` | `#059669` | `#34d399` | `--kos-facet-activity-soft` |
| **`PROCESS`** | 计算与研究流程 | `--kos-facet-process` | `#7c3aed` | `#a78bfa` | `--kos-facet-process-soft` |
| **`ARTIFACT`** | 器物、材料、风格与历史时期 | `--kos-facet-artifact` | `#d97706` | `#fbbf24` | `--kos-facet-artifact-soft` |
| **`STANCE`** | 人机交互模式与认知姿态 | `--kos-facet-stance` | `#0891b2` | `#22d3ee` | `--kos-facet-stance-soft` |

### 2.4 语义与合规门禁色（Registered Semantic & Governance Colors）

仅限对应语义与合规边界表面，不应扩散至普通容器背景：

| 语义角色 | Token | Light | Dark | 登记消费场景 |
| :--- | :--- | :--- | :--- | :--- |
| **Focus Blue** | `--kos-focus-ring` | `#417cdd` | `#5b93f0` | 键盘 `:focus-visible` 焦点环、激活态输入框软环（鼠标点击普通按钮不显示） |
| **Verified / Permissive** | `--kos-success-fg` | `#2aae5b` | `#3fb950` | `dist_core` / `dist_ext_permissive` 许可校验通过、幂等导入完成图标 |
| **ShareAlike / Warning** | `--kos-warning-fg` | `#ea6b17` | `#f59e0b` | 触及 `dist_ext_sa`（CC BY-SA）时的合规横幅图标与边界标记、FTS5 降级提示图标 |
| **Negative Edge / `local_only` / Error** | `--kos-error-fg` | `#d91f37` | `#f87171` | 显式开启的负边（`polarity = -1`）虚线与角标、触及 `local_only` 源报警、校验失败提示 |
| **Traversal Bridge Accent** | `--kos-bridge-edge` | `#1d4ed8` | `#60a5fa` | 沿边多跳高亮路径（`oa:cooccur` / `skos:related` / `skos:closeMatch`）与高亮选中环 |

---

## 3. Typography Rules（排版与 CJK 纪律）

### 3.1 字体栈

- **UI 无衬线栈（`--kos-font-ui`）**：`'Inter Variable', Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'HarmonyOS Sans SC', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Segoe UI', Roboto, sans-serif`。
  - **CJK 优先于 `Segoe UI`**：Windows 上 `Segoe UI` 包含偏窄的中日韩标点字形，将 CJK 字体排在 `Segoe UI` 之前可避免中文书名号、顿号与引号出现半全角混排。
- **代码与标识等宽栈（`--kos-font-code`）**：`ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', 'PingFang SC', 'Microsoft YaHei UI', monospace`。仅用于 `node_id`、SPDX 标识、路径、SQL 与 JSON 预览，不用于普通标题或按钮。

### 3.2 四档字重阶梯与 CJK 约束

全站字重仅允许四档整百值：`400` / `500` / `600` / `700`，不应使用中间值或 `800+`：

| 字重 | 角色 | 使用边界 |
| :--- | :--- | :--- |
| **`400`（Regular）** | 正文、节点定义摘要、代码、面包屑 | 默认阅读字重 |
| **`500`（Medium）** | **全部 UI 标题**、按钮标签、Tab 标签、表单项标签 | 桌面界面标题统一 `500`，层级靠字号与字色区分 |
| **`600`（Semibold）** | 限量局部加重（分面徽标、表头、选中项强调） | 不用于大标题；新增使用应说明为何 `500` 不足 |
| **`700`（Bold）** | 豁免域专用（Markdown 正文 `<strong>`） | 不用于普通 UI chrome；**中文层级不应依赖 `600` vs `700`**（防 CJK 伪粗体发糊） |

### 3.3 桌面字号白名单与行高

- **字号白名单**：UI 段 `{10, 11, 12, 13, 14, 15, 16}px`；标题段 `{18, 20, 24, 28}px`。下限 `10px`（仅用于非阅读微标签，如计数与 LoD 档位），不应出现 `9px` 以下或任意小数像素字号。
- **行高规则**：一律使用**无单位比例**（标题 `1.2–1.3`，控件 `1.4`，多行摘要/简报正文 `1.5–1.6`），不应在缩放文本上硬编码固定 `px` 行高。

| 角色 | 字号 | 字重 | 行高 | 典型位置 |
| :--- | :--- | :--- | :--- | :--- |
| 页面 / 视图主标题 | `20px` | `500` | `1.3` | 控制台顶部标题、地图空态标题 |
| 抽屉 / 卡片标题 | `16px` | `500` | `1.25` | 节点检视抽屉标题、漫游简报卡片标题 |
| 列表主标签与正文 | `14px` | `500` / `400` | `1.5` | 候选概念中文/英文规范名、漫游说明正文 |
| UI 控件与说明 | `13px` | `500` / `400` | `1.45` | 按钮文字、分面筛选胶囊、工具提示、面包屑 |
| 元数据与标签 | `12px` | `400` / `500` | `1.4` | `node_id`、SPDX 标签、相似度 z-score、IC 值 |
| 微标签（非阅读） | `11px` / `10px` | `500` | `1.2` | LoD 档位 `T0–T3`、跳数角标 `1-hop`、`SA` 徽标 |

---

## 4. Core Component Specifications（核心组件规范）

1. **按钮（Buttons）**：高度标准 `32px`（紧凑 `28px`），文字 `13px / 500`，一律采用胶囊圆角（`9999px`）。主操作使用反相 CTA（`--kos-cta-bg` / `--kos-cta-fg`）；次要操作使用 `--kos-card` + `1px solid --kos-board`；危险确认操作仅最终确认按钮使用 `--kos-error-fg` 实底，取消按钮保持中性。
2. **五维分面筛选胶囊（Facet Filter Chips）**：采用胶囊帧（`9999px`），内部左端放 `8×8px` 的 `facet-legend-swatch`（`2px` 圆角登记数据标记，填充对应 `--kos-facet-*` 身份色）；标签文字与背景保持中性灰度，选中态切换为 `--kos-surface-chip` + `1px solid --kos-board`，不整颗涂成高饱和彩色块。
3. **`/attach` 五维候选卡（5-Facet Candidate Picker）**：外框为 `Card`（`12px` 圆角、`1px solid --kos-board`），按 `DOMAIN / ACTIVITY / PROCESS / ARTIFACT / STANCE` 物理分区展示 Top-K 候选（永不跨分面混排）；每个候选项为 `8px` 圆角内控行，依次呈现规范标签、面包屑路径、IC / 融合分值、来源 SPDX 标签与复选框。
4. **节点检视抽屉（Node Inspector Drawer）**：右侧停靠面板（`340px–380px` 宽），`Card` 底色 + 左侧 `1px solid --kos-board`，呈现：规范中英名、五维分面标签、完整 `breadcrumb_path`、IC 与坐标元数据、邻居与多跳沿边展开按钮（默认 `polarity = 1`，显式提供「包含负边」开关）、归属 `kos_provenance` 声明及「在对话中探索」动作按钮。
5. **合规门禁横幅（Provenance / ShareAlike Banner）**：容器 `12px` 圆角，底色保持 `--kos-card` 与 `1px solid --kos-board`，仅左侧 `16×16` 图标与前缀徽标使用 `--kos-warning-fg`（触及 `dist_ext_sa`）或 `--kos-error-fg`（触及 `local_only`），同时以直白文本列明 `requiredNotices`，使颜色永不成为唯一信息通道。
6. **受控漫游简报卡（Serendipity Briefing Card）**：每条推荐应结构化展示「种子会话/节点 → 沿边路径（`oa:cooccur` / `skos:related` / `skos:closeMatch`）→ 目标概念 → 信息量 IC 与证据来源」，支持一键在 2D 地图中定位路径。

---

## 5. Layout Principles & Border Radius Decision Tree（布局与两步圆角判定树）

### 5.1 间距与留白

- 基础网格为 `4px` 递增阶梯：`4 / 8 / 12 / 16 / 20 / 24px`。
- 留白优先于密集堆砌：地图视口应占据 ≥ 75% 的可视面积，顶部仅保留单行紧凑搜索与五维胶囊条，详情通过右侧抽屉渐进披露。

### 5.2 两步圆角判定树（Step 1 优先于 Step 2）

圆角作用于单个**可见层**而非整个组件树；不应凭「看起来小」随意发明档位。

#### Step 1 — 已登记形状（Registered Shapes）

| 类别 | 成员 ID / 适用范围 | 圆角 |
| :--- | :--- | :--- |
| **Data Mark（数据标记）** | `facet-legend-swatch`（8px 分面色块）、`ic-meter-bar`（IC 信息量条）、`activation-heat-cell`（激活衰减热格）、`zoom-lod-pip`（LoD 0–3 指示格） | **`2px`**（四角统一） |
| **Keyboard Keycap（快捷键帽）** | `/attach`、`⌘K`、`Esc` 等 `<kbd>` 提示框 | **`4px`** |
| **Text Highlight Mark（检索高亮）** | BM25 / FTS5 命中的文本高亮底色 | **`2px`** |
| **Intrinsic Geometry（固有几何豁免）** | WebGL 2D 地图节点圆、边线、Voronoi 多边形边界、SVG 图标内部路径（源码标 `/* design: intrinsic-geometry — <reason> */`） | 不适用 CSS 控件圆角刻度 |

#### Step 2 — 普通控件三档（Ordinary Control Tiers）

未命中 Step 1 的所有普通可见层，仅允许以下三档：

| 档位 | Token | 数值 | 适用对象 |
| :--- | :--- | :--- | :--- |
| **Pill（胶囊）** | `--kos-radius-pill` | `9999px` | 全部按钮、Tab 切换项、分面筛选胶囊、单行搜索/输入框、徽章 |
| **Container（容器）** | `--kos-radius-container` | `12px` | 卡片、抽屉面板、浮层 HUD、弹窗、代码块容器、合规横幅 |
| **Inner Control（内控）** | `--kos-radius-inner` | `8px` | 多行 `<textarea>`（无论是否嵌套）、下拉菜单选中/悬停行、卡片内候选列表行 |

> 受控圆角清单仅为 **`0px / 2px / 4px / 8px / 12px / 9999px`**；不应使用 `3px / 6px / 10px / 16px` 等清单外任意圆角。

---

## 6. Depth, Elevation & Z-Index Scale（深度与层级刻度）

| 层级 | 处理方式 | 适用对象 |
| :--- | :--- | :--- |
| **Flat (Level 0)** | 无阴影、无边框，`--kos-surface` | 全窗背景、地图底布 |
| **Bordered (Level 1)** | `1px solid var(--kos-board)`，无阴影 | 侧栏、分隔区块、静态卡片 |
| **Lifted (Card)** | `--kos-card` + `1px solid var(--kos-board)`，无阴影 | 检视抽屉、表单面板、简报卡片 |
| **Floating** | `--kos-card` + `1px solid var(--kos-board)` + `var(--kos-shadow-floating)` | 地图悬浮 HUD、下拉菜单、Tooltip、模态弹窗、Toast |

**层级刻度（不应在组件内手写任意 `z-index` 数值）**：
- `--kos-z-map`: `10`（WebGL + Voronoi 地图画布）
- `--kos-z-hud`: `20`（缩放控件、图例、LoD 指示条）
- `--kos-z-drawer`: `30`（右侧节点检视抽屉与侧栏）
- `--kos-z-popover`: `40`（搜索建议、下拉菜单、Tooltip）
- `--kos-z-modal`: `50`（确认弹窗、导入预览弹窗）
- `--kos-z-toast`: `60`（短时状态通知）

---

## 7. Do's and Don'ts

### Do（应做）
- 应通过 `--kos-*` 语义 Token 消费全部颜色、字号、圆角、阴影与 z-index。
- 应同步实现 Light 与 Dark 双模式，确保两种模式下节点、Voronoi 边界、面包屑与禁用态对比度均清晰可读。
- 应在 2D 地图严格按 `queryViewport(bbox, zoomTier)` 分页加载（单帧 ≤ 5,000 点），以 R\*Tree + 固化 UMAP 坐标实现零前端力导向计算。
- 应在触及 ShareAlike（`dist_ext_sa`）、`local_only` 或负边（`polarity = -1`）时，同时给出文字说明与登记语义色图标。

### Don't（不应做）
- 不应在组件 CSS/TS/HTML 中硬编码裸 hex / `rgb()` / `rgba()`（WebGL Canvas 读取计算后的 CSS 变量，不写死第二份色板）。
- 不应把五维分面身份色借用于错误、警告或成功状态，也不应把整行卡片染成高饱和色块。
- 不应为页内普通卡片或按钮添加随意投影或渐变背景。
- 不应在 MCP App 静态包中引用外部 CDN 字体、脚本或样式（将触发 Open WebUI `app_csp` 拦截）。

---

## 8. Light / Dark Dual-Mode Delivery Gate & Token Architecture

1. **单源链路**：[`tokens.dtcg.json`](<tokens.dtcg.json>) → `python docs/design-rules/tokens_guard.py --generate` → `kos_engine/web/src/styles/tokens.css`。
2. **宿主主题联动**：
   - 默认跟随 `prefers-color-scheme`，支持通过 URL 查询参数 `?theme=light|dark`、Open WebUI 宿主 `postMessage` 主题信号或顶栏切换按钮显式设置 `document.documentElement.dataset.theme`；
   - WebGL（Sigma v4）与 Voronoi Canvas 在主题切换时读取 `getComputedStyle(document.documentElement)` 实时重绘，与 DOM 控件共享同一套数值来源。
3. **双模式交付门槛**：每个新增/修改的界面须在同一次交付中同时覆盖 Light 与 Dark 的全部受影响状态（默认、悬停、选中、聚焦、禁用、加载、空态、错误）。验证说明应诚实写明实际检查了哪些模式；发现任一模式不可读或对比度失真即视为缺陷并修复后再交付。

---

## 9. Micro-Copy & Interaction Conventions（微文案与交互约定）

1. **焦点管理**：按钮与标签仅在 `:focus-visible` 显示 `2px` `--kos-focus-ring` 焦点环；文本输入框聚焦时显示软环，保证键盘全程可达。
2. **动效克制**：遵循 `prefers-reduced-motion: reduce`；抽屉与面板过渡使用 `--kos-motion-fast`（`150ms`）与 `--kos-motion-base`（`220ms`），地图相机平滑缩放不超过 `280ms`。
3. **直白合规文案**：面向用户的许可与数据边界提示应直接说明事实与下一步动作，例如：
   - ShareAlike：`当前结果包含 CC BY-SA 扩展包（cn_rel），对外导出衍生内容时应保留 ShareAlike 署名声明。`
   - 负边开关：`默认仅展示正向关系边（polarity = 1）；开启后将以红色虚线标示排斥/冲突边（polarity = -1）。`
   - 导入安全：`导入器仅处理您显式指定的备份文件；未指定路径时不会读取本机历史记录。`
