# KOS Design System 索引与治理台账

> **文档角色**：`docs/design-rules/` 设计系统总索引、治理合同与版本决策台账。
> **设计参考**：借鉴 [Cindy Design System](https://github.com/makecindy/cindy/blob/main/docs/design-rules/cindy-design-system.md)（及其正本 [DESIGN.md](https://github.com/makecindy/cindy/blob/main/docs/design-rules/DESIGN.md)）的「冷静灰度底色 + 严格登记功能色 + 两步圆角判定树 + Token 单源 + 亮暗双模门槛」工程化治理方法，并按 Human KOS 光学透镜与知识世界地图场景独立适配。
> **规范用词**：采用 RFC 2119 / RFC 8174 与 GB/T 1.1-2020 第 9 章语义（**应 / 不应**、**宜 / 不宜**、**可 / 不必**、**能 / 不能**）。
> **适用路径**：`kos_engine/web/**`、`kos_engine/static/map/**`、`adapters/open_webui/**` 中一切面向人类用户的界面、卡片与可视化表面。

---

## 1. 文档索引

| 文件 | 角色 | 内容概要 |
| :--- | :--- | :--- |
| [`DESIGN.md`](<DESIGN.md>) | **视觉规范正本** | 阅读路由、视觉氛围（§1）、颜色与五维分面身份色（§2）、排版与 CJK 纪律（§3）、核心组件（§4）、布局与两步圆角判定树（§5）、深度与层级刻度（§6）、Do/Don't（§7）、亮暗双模门槛与 Token 架构（§8）、微文案与交互约定（§9） |
| [`tokens.dtcg.json`](<tokens.dtcg.json>) | **数值唯一权威源（Single Source of Truth）** | DTCG 风格 JSON：Light / Dark 语义色、五维分面色、语义/许可门禁色、字号白名单、字重阶梯、圆角刻度、阴影与 z-index |
| [`tokens_guard.py`](<tokens_guard.py>) | **Token 生成器与静态守卫** | 从 `tokens.dtcg.json` 确定性生成 `kos_engine/web/src/styles/tokens.css`，并扫描 UI 源码拦截未登记裸色值与白名单外圆角 |

---

## 2. 四种真相边界（Governance Truth Boundaries）

1. **规则真相** = [`DESIGN.md`](<DESIGN.md>)：规范视觉语言、角色分工、登记白名单与交互契约；新增视觉豁免前应先更新本规范并登记于下表。
2. **数值真相** = [`tokens.dtcg.json`](<tokens.dtcg.json>)：一切颜色、字号、圆角、阴影与层级数值均应仅在此文件编辑，由 `tokens_guard.py --generate` 同步至 CSS 变量；不应在组件文件中手写裸 hex / rgba 或偏离刻度的 `border-radius`。
3. **机器守卫真相** = [`tokens_guard.py`](<tokens_guard.py>)（及 pytest 集成测试）：拦截源码中未登记的硬编码色值、白名单外圆角与 Light/Dark 键失配；对 WebGL Canvas / Voronoi 多边形等固有几何，通过显式注释 `/* design: intrinsic-geometry — <reason> */` 标明边界。
4. **视觉真相** = Light 与 Dark 双模式下的实际运行渲染：每次视觉改动均应在交付报告中如实记录已核查的模式与未核查项，不应将「零裸色值通过静态扫描」等同于「双模式视觉验收完成」。

---

## 3. 新贡献者 / Agent 工作流

1. 修改任何 UI 前，先读 [`DESIGN.md`](<DESIGN.md>) 顶部「阅读路由」、§1 与 §7，再按需查阅对应章节。
2. 调整或新增设计数值时，仅修改 [`tokens.dtcg.json`](<tokens.dtcg.json>)，运行 `python docs/design-rules/tokens_guard.py --generate` 重新生成 `kos_engine/web/src/styles/tokens.css`。
3. 提交前运行 `python docs/design-rules/tokens_guard.py --check`，确保 `violations = 0` 且 Light/Dark 键集完全一致。
4. 在 MCP App（Open WebUI 5 MB 沙箱 iframe）与独立浏览器两种承载形态下，界面均应通过 `:root` / `[data-theme="dark"]` 与 `prefers-color-scheme` 无缝适配亮暗双模，不应依赖外部 CDN 字体或外链样式表。

---

## 4. 设计决策与版本台账

| 编号 | 日期 | 裁决摘要 | 依据 |
| :--- | :--- | :--- | :--- |
| **KOS-DS-001** | 2026-11-23 | 建立 Human KOS Phase 3 视觉设计系统 v1.0：采纳三层灰度（`Surface` / `Card` / `Board`）、五维正交分面身份色（`DOMAIN`/`ACTIVITY`/`PROCESS`/`ARTIFACT`/`STANCE` 专用，不兼作健康状态色）、许可合规门禁语义色（Focus Blue / SA Orange / Negative Red / Verified Green）、CJK 优先于 `Segoe UI` 的字体栈、标题统一 `500` 字重、两步圆角判定树（数据标记 `2px` / 快捷键帽 `4px` / 内控 `8px` / 容器 `12px` / 胶囊 `9999px`）、零阴影基准与 Light/Dark 双模交付门槛。 | 用户指示借鉴 Cindy 设计系统并产出规范文本（G-P3-03 = A） |
