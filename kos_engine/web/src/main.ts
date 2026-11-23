import "./styles/app.css";
import { ALL_FACETS, FACET_LABELS, type FacetType, type LicenseBoundary, kosApi } from "./api";
import { installDiagnostics } from "./diagnostics";
import { KnowledgeWorldMap } from "./mapView";
import { initWorkbench } from "./workbenchView";

declare global {
  interface Window {
    openwebui?: {
      sendMessage?: (content: string) => void;
    };
  }
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(msg: string): void {
  const el = document.getElementById("kos-toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("is-hidden");
  window.setTimeout(() => el.classList.add("is-hidden"), 2800);
}

function updateComplianceBanner(boundary: LicenseBoundary): void {
  const banner = document.getElementById("compliance-banner");
  const badge = document.getElementById("compliance-badge");
  const text = document.getElementById("compliance-text");
  if (!banner || !badge || !text) return;

  if (boundary.local_only_triggered) {
    banner.classList.remove("is-hidden");
    badge.textContent = "LOCAL ONLY";
    badge.classList.add("is-error");
    text.textContent = boundary.summary;
  } else if (boundary.share_alike_triggered) {
    banner.classList.remove("is-hidden");
    badge.textContent = "CC BY-SA";
    badge.classList.remove("is-error");
    text.textContent = boundary.summary;
  } else {
    banner.classList.add("is-hidden");
  }
}

function resolveInitialTheme(): "light" | "dark" {
  const q = new URLSearchParams(window.location.search).get("theme");
  if (q === "dark" || q === "light") return q;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: "light" | "dark"): void {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById("theme-toggle-btn");
  if (btn) {
    btn.textContent = theme === "dark" ? "切换浅色" : "切换深色";
  }
}

async function bootstrap(): Promise<void> {
  let currentTheme = resolveInitialTheme();
  applyTheme(currentTheme);

  const sigmaEl = document.getElementById("sigma-container") as HTMLElement;
  const voronoiCanvas = document.getElementById("voronoi-canvas") as HTMLCanvasElement;
  const labelCanvas = document.getElementById("label-canvas") as HTMLCanvasElement;
  const counterEl = document.getElementById("viewport-counter") as HTMLElement;
  const drawerEl = document.getElementById("node-drawer") as HTMLElement;
  const drawerFacetRow = document.getElementById("drawer-facet-row") as HTMLElement;
  const drawerTitle = document.getElementById("drawer-title") as HTMLElement;
  const drawerSubtitle = document.getElementById("drawer-subtitle") as HTMLElement;
  const drawerBody = document.getElementById("drawer-body") as HTMLElement;

  let selectedNodeId: string | null = null;
  let selectedNodeLabel = "";
  let includeNegativeEdges = false;

  const map = new KnowledgeWorldMap(
    sigmaEl,
    voronoiCanvas,
    labelCanvas,
    (nodeId) => void openInspector(nodeId),
    (statusText) => {
      counterEl.textContent = statusText;
    },
  );
  installDiagnostics(map);

  // Theme toggle + Open WebUI parent postMessage theme sync
  document.getElementById("theme-toggle-btn")?.addEventListener("click", () => {
    currentTheme = currentTheme === "dark" ? "light" : "dark";
    applyTheme(currentTheme);
    map.refreshTheme();
  });

  window.addEventListener("message", (ev) => {
    const data = ev.data;
    if (data && typeof data === "object" && (data.theme === "dark" || data.theme === "light")) {
      currentTheme = data.theme;
      applyTheme(currentTheme);
      map.refreshTheme();
    }
  });

  // Tab switching
  const tabButtons = Array.from(document.querySelectorAll<HTMLButtonElement>(".kos-tab"));
  function activateTab(tabName: "map" | "workbench"): void {
    for (const btn of tabButtons) {
      const active = btn.dataset.tab === tabName;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", String(active));
    }
    document.getElementById("view-map")?.classList.toggle("is-active", tabName === "map");
    document.getElementById("view-workbench")?.classList.toggle("is-active", tabName === "workbench");
    if (tabName === "map") {
      window.requestAnimationFrame(() => map.refreshTheme());
    } else if (tabName === "workbench") {
      void workbench.refresh();
    }
  }

  for (const btn of tabButtons) {
    btn.addEventListener("click", () => activateTab((btn.dataset.tab as "map" | "workbench") || "map"));
  }

  // Build 5 Orthogonal Facet Filter Chips
  const activeFacets = new Set<FacetType>(ALL_FACETS);
  const facetBar = document.getElementById("facet-filter-bar") as HTMLElement;
  for (const facet of ALL_FACETS) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "kos-facet-chip is-active";
    chip.innerHTML = `<span class="kos-swatch" data-facet="${facet}"></span><span>${facet}</span>`;
    chip.addEventListener("click", () => {
      if (activeFacets.has(facet)) {
        activeFacets.delete(facet);
        chip.classList.remove("is-active");
      } else {
        activeFacets.add(facet);
        chip.classList.add("is-active");
      }
      map.setFacets(activeFacets);
    });
    facetBar.appendChild(chip);
  }

  // LoD selector
  const lodBtns = Array.from(document.querySelectorAll<HTMLButtonElement>("#lod-selector [data-lod]"));
  for (const btn of lodBtns) {
    btn.addEventListener("click", () => {
      for (const b of lodBtns) b.classList.remove("is-active");
      btn.classList.add("is-active");
      map.setZoomTier(Number(btn.dataset.lod || "1"));
    });
  }

  document.getElementById("toggle-voronoi")?.addEventListener("change", (ev) => {
    map.setShowVoronoi((ev.target as HTMLInputElement).checked);
  });

  document.getElementById("btn-reset-camera")?.addEventListener("click", () => map.resetCamera());

  // On-demand extension mount/unmount buttons
  const extBtns = Array.from(document.querySelectorAll<HTMLButtonElement>("#ext-pack-bar [data-ext]"));
  for (const btn of extBtns) {
    btn.addEventListener("click", async () => {
      const packId = btn.dataset.ext!;
      const mounted = btn.classList.contains("is-active");
      btn.disabled = true;
      try {
        if (mounted) {
          await kosApi.detachExtension(packId);
          btn.classList.remove("is-active");
          showToast(`已卸载扩展包 ${packId}`);
        } else {
          const info = await kosApi.attachExtension(packId);
          btn.classList.add("is-active");
          if (info.share_alike) {
            updateComplianceBanner({
              share_alike_triggered: true,
              local_only_triggered: false,
              required_notices: [],
              summary: `已挂载 CC BY-SA 扩展包（${packId}），对外导出衍生结果时应保留 ShareAlike 署名声明。`,
            });
          }
          showToast(`已按需挂载只读扩展包 ${packId}`);
        }
      } catch (err) {
        showToast(`扩展包操作失败：${String(err)}`);
      } finally {
        btn.disabled = false;
      }
    });
  }

  // Global 5-Facet Isolated Search
  const searchForm = document.getElementById("global-search-form") as HTMLFormElement;
  const searchInput = document.getElementById("global-search-input") as HTMLInputElement;
  const modeSelect = document.getElementById("global-mode-select") as HTMLSelectElement;
  const searchPopover = document.getElementById("search-popover") as HTMLElement;
  const searchBody = document.getElementById("search-results-body") as HTMLElement;

  document.getElementById("close-search-popover")?.addEventListener("click", () => {
    searchPopover.classList.add("is-hidden");
  });

  searchForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const q = searchInput.value.trim();
    if (!q) return;
    activateTab("map");
    try {
      const res = await kosApi.searchAll(q, (modeSelect.value as "hybrid" | "bm25") || "hybrid", 4);
      updateComplianceBanner(res.license_boundary);
      searchBody.innerHTML = "";
      for (const facet of ALL_FACETS) {
        const list = res.results[facet] || [];
        if (list.length === 0) continue;
        const sec = document.createElement("div");
        sec.className = "kos-facet-group";
        sec.innerHTML = `<div class="kos-facet-group-title"><span class="kos-swatch" data-facet="${facet}"></span><span>${FACET_LABELS[facet]}</span></div>`;
        for (const c of list) {
          const lbl = c.canonical_label_zh || c.canonical_label_en || c.node_id;
          const row = document.createElement("div");
          row.className = "kos-inner-row";
          row.innerHTML = `
            <div class="kos-inner-row-main">
              <span class="kos-row-label">${escapeHtml(lbl)}</span>
              <span class="kos-row-meta">${escapeHtml(c.breadcrumb_path)}</span>
              <span class="kos-code-id">${escapeHtml(c.node_id)} · ${escapeHtml(c.license_spdx)}</span>
            </div>
          `;
          row.addEventListener("click", () => {
            searchPopover.classList.add("is-hidden");
            map.focusNode({
              node_id: c.node_id,
              map_x: c.map_x,
              map_y: c.map_y,
              facet_type: c.facet_type,
              label: lbl,
            });
            void openInspector(c.node_id);
          });
          sec.appendChild(row);
        }
        searchBody.appendChild(sec);
      }
      if (!searchBody.hasChildNodes()) {
        searchBody.innerHTML = `<div class="kos-row-meta">五个正交分面均未检索到匹配概念。</div>`;
      }
      searchPopover.classList.remove("is-hidden");
    } catch (err) {
      showToast(`检索失败：${String(err)}`);
    }
  });

  // Node Inspector Drawer
  async function openInspector(nodeId: string): Promise<void> {
    selectedNodeId = nodeId;
    drawerEl.classList.remove("is-hidden");
    drawerTitle.textContent = "加载概念详情…";
    drawerSubtitle.textContent = nodeId;
    drawerBody.innerHTML = "";

    try {
      const data = await kosApi.getNode(nodeId, includeNegativeEdges);
      const n = data.node;
      updateComplianceBanner(data.license_boundary);

      const primaryLabel = n.canonical_label_zh || n.canonical_label_en || n.node_id;
      selectedNodeLabel = primaryLabel;

      drawerFacetRow.innerHTML = `
        <span class="kos-swatch" data-facet="${n.facet_type}"></span>
        <span class="kos-badge-neutral">${escapeHtml(n.facet_type)}</span>
        <span class="kos-badge-neutral ${n.dist_tier === "dist_ext_sa" ? "kos-badge-warn" : "kos-badge-ok"}">${escapeHtml(n.license_spdx)}</span>
      `;
      drawerTitle.textContent = primaryLabel;
      drawerSubtitle.textContent = n.canonical_label_en && n.canonical_label_zh ? n.canonical_label_en : n.node_id;

      const icPct = Math.min(100, Math.round((n.info_content / 8) * 100));
      const nbrRows = data.neighbors
        .slice(0, 12)
        .map((e) => {
          const nl = e.neighbor_label_zh || e.neighbor_label_en || e.neighbor_id;
          const badgeCls = e.polarity < 0 ? "kos-badge-error" : "";
          return `
            <div class="kos-inner-row" data-jump-node="${escapeHtml(e.neighbor_id)}">
              <div class="kos-inner-row-main">
                <span class="kos-row-label">${escapeHtml(nl)}</span>
                <span class="kos-code-id">${escapeHtml(e.relation_type)} · w=${e.weight.toFixed(2)} · IC ${e.neighbor_info_content.toFixed(2)}</span>
              </div>
              <span class="kos-badge-neutral ${badgeCls}">${e.polarity < 0 ? "负边" : e.direction}</span>
            </div>
          `;
        })
        .join("");

      drawerBody.innerHTML = `
        <div>
          <div class="kos-label-micro">面包屑路径</div>
          <div class="kos-row-meta">${escapeHtml(n.breadcrumb_path)}</div>
        </div>
        <div>
          <div class="kos-label-micro">信息量 IC = ${n.info_content.toFixed(2)} · LoD T${n.min_zoom_tier} · (${n.map_x.toFixed(0)}, ${n.map_y.toFixed(0)})</div>
          <div class="kos-ic-track"><div class="kos-ic-fill" style="width:${icPct}%"></div></div>
        </div>
        ${
          n.definition_summary
            ? `<div><div class="kos-label-micro">定义摘要</div><div class="kos-row-meta">${escapeHtml(n.definition_summary)}</div></div>`
            : ""
        }
        <label class="kos-toggle-inline">
          <input type="checkbox" id="drawer-neg-toggle" ${includeNegativeEdges ? "checked" : ""} />
          <span>包含负边（polarity = -1，默认关闭）</span>
        </label>
        <div>
          <div class="kos-label-micro">1 跳邻居（IC ≥ 1.5，已防根坍缩 · ${data.neighbors.length}）</div>
          <div class="kos-stack-list">${nbrRows || '<div class="kos-row-meta">当前门禁下无相邻边。</div>'}</div>
        </div>
        <div>
          <div class="kos-label-micro">Provenance 溯源</div>
          <div class="kos-code-id">${escapeHtml(n.source_id)} · ${escapeHtml(n.license_spdx)} · ${escapeHtml(n.dist_tier)}</div>
        </div>
      `;

      drawerBody.querySelector("#drawer-neg-toggle")?.addEventListener("change", (ev) => {
        includeNegativeEdges = (ev.target as HTMLInputElement).checked;
        if (selectedNodeId) void openInspector(selectedNodeId);
      });

      for (const el of Array.from(drawerBody.querySelectorAll<HTMLElement>("[data-jump-node]"))) {
        el.addEventListener("click", () => {
          const targetId = el.dataset.jumpNode;
          if (targetId) void openInspector(targetId);
        });
      }
    } catch (err) {
      drawerBody.innerHTML = `<div class="kos-row-meta">加载失败：${escapeHtml(String(err))}</div>`;
    }
  }

  document.getElementById("close-drawer-btn")?.addEventListener("click", () => {
    drawerEl.classList.add("is-hidden");
  });

  window.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      drawerEl.classList.add("is-hidden");
      searchPopover.classList.add("is-hidden");
    }
  });

  document.getElementById("btn-expand-2hop")?.addEventListener("click", async () => {
    if (!selectedNodeId) return;
    try {
      const sub = await kosApi.traverse([selectedNodeId], 2, includeNegativeEdges);
      map.overlayTraversal(sub);
      updateComplianceBanner(sub.license_boundary);
      showToast(`已在地图高亮 ${sub.nodes.length} 节点 / ${sub.edges.length} 边（2-hop）`);
    } catch (err) {
      showToast(`沿边展开失败：${String(err)}`);
    }
  });

  document.getElementById("btn-explore-chat")?.addEventListener("click", async () => {
    if (!selectedNodeId) return;
    const prompt = `/attach 围绕概念「${selectedNodeLabel}」(${selectedNodeId}) 展开跨领域探索，请结合其相邻节点给出问题切入点。`;
    if (typeof window.openwebui?.sendMessage === "function") {
      window.openwebui.sendMessage(prompt);
      showToast("已通过 Open WebUI 回调发起新探索对话。");
      return;
    }
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: "openwebui:sendMessage", content: prompt, nodeId: selectedNodeId }, "*");
      showToast("已向宿主窗口发送探索指令。");
      return;
    }
    try {
      await navigator.clipboard.writeText(prompt);
      showToast("已复制探索提示词到剪贴板。");
    } catch {
      showToast(prompt);
    }
  });

  // Init Workbench Tab (T3.7)
  const workbench = initWorkbench({
    onFocusNodeOnMap: (node) => {
      activateTab("map");
      map.focusNode(node);
      void openInspector(node.node_id);
    },
    onComplianceUpdate: updateComplianceBanner,
    onToast: showToast,
  });

  // Meta handshake + initial map render
  try {
    const meta = await kosApi.getMeta();
    const badge = document.getElementById("meta-badge");
    if (badge) {
      badge.textContent = `L1 v${meta.meta.schema_version} · ${meta.meta.core_node_count.toLocaleString()} 节点`;
    }
  } catch {
    showToast("连接 kos-engine API 失败，请确认本地服务已启动。");
  }

  await map.init();
}

void bootstrap();
