/**
 * 3-Phase UI Viewport & Camera Stability Diagnostic Framework for Human KOS 2D Map.
 *
 * Captures comparable structured snapshots across:
 *   - T0_BEFORE:                before user interaction (drag / wheel / search-focus / reset)
 *   - T1_AFTER_ACTION:          immediately after interaction settles (before viewport fetch completes)
 *   - T2_AFTER_VIEWPORT_UPDATE: immediately after `#viewport-counter` ("LoD T* · XXX 节点 · XXX 边") updates
 *
 * Also audits low-zoom label viewport overflow and high-zoom node size / overlap ratios.
 */

import type { KnowledgeWorldMap } from "./mapView";

export interface AnchorNodeSample {
  nodeId: string;
  label: string;
  worldX: number;
  worldY: number;
  screenX: number;
  screenY: number;
  screenRadiusPx: number;
  inViewport: boolean;
}

export interface LabelOverflowEntry {
  nodeId: string;
  label: string;
  labelPosition: "left" | "right";
  x1: number;
  x2: number;
  y1: number;
  y2: number;
  overflowEdge: string;
}

export interface OverlapStats {
  visibleNodeCount: number;
  maxScreenRadiusPx: number;
  medianScreenRadiusPx: number;
  overlappingPairs: number;
  sampledPairs: number;
  overlapRatio: number;
}

export interface VisibleElementSummary {
  activeTab: string;
  theme: string;
  viewportCounterText: string;
  drawerOpen: boolean;
  searchPopoverOpen: boolean;
  complianceBannerOpen: boolean;
  stageWidth: number;
  stageHeight: number;
  graphNodeCount: number;
  graphEdgeCount: number;
}

export interface MapDiagnosticSnapshot {
  phase: string;
  timestampMs: number;
  elements: VisibleElementSummary;
  camera: { x: number; y: number; ratio: number; angle: number };
  worldBbox: [number, number, number, number];
  customBBox: { x: [number, number]; y: [number, number] } | null;
  anchors: AnchorNodeSample[];
  labelOverflow: {
    checkedCount: number;
    overflowCount: number;
    samples: LabelOverflowEntry[];
  };
  overlapStats: OverlapStats;
}

export interface ThreePhaseDiff {
  probeName: string;
  t0_before: MapDiagnosticSnapshot;
  t1_after_action: MapDiagnosticSnapshot;
  t2_after_viewport_update: MapDiagnosticSnapshot;
  viewportCounterChanged: boolean;
  cameraDriftAfterUpdate: { dx: number; dy: number; dratio: number };
  maxAnchorJumpPxAfterUpdate: number;
  commonAnchorCount: number;
  stableAfterUpdate: boolean;
}

export class MapDiagnostics {
  private map: KnowledgeWorldMap;

  constructor(map: KnowledgeWorldMap) {
    this.map = map;
  }

  captureSnapshot(phase = "manual"): MapDiagnosticSnapshot {
    const h = this.map.getDiagnosticHandle();
    const sigma = h.sigma;
    const graph = h.graph;
    const stageRect = h.stageEl.getBoundingClientRect();
    const cam = sigma.getCamera().getState();
    const worldBbox = h.getWorldBbox();
    const customBBox = sigma.getCustomBBox();

    const anchors: AnchorNodeSample[] = [];
    const visiblePts: Array<{ x: number; y: number; r: number }> = [];
    const radii: number[] = [];
    const drawnLabels = h.getDrawnLabels();
    const overflowSamples: LabelOverflowEntry[] = [];
    for (const lb of drawnLabels) {
      const edges: string[] = [];
      if (lb.x1 < 0) edges.push("left");
      if (lb.x2 > stageRect.width) edges.push("right");
      if (lb.y1 < 0) edges.push("top");
      if (lb.y2 > stageRect.height) edges.push("bottom");
      if (edges.length > 0 && overflowSamples.length < 15) {
        overflowSamples.push({
          nodeId: lb.nodeId,
          label: lb.text,
          labelPosition: "right",
          x1: Math.round(lb.x1),
          x2: Math.round(lb.x2),
          y1: Math.round(lb.y1),
          y2: Math.round(lb.y2),
          overflowEdge: edges.join("+"),
        });
      }
    }

    graph.forEachNode((nodeId, attrs) => {
      const wx = Number(attrs.x ?? 0);
      const wy = Number(attrs.y ?? 0);
      const baseSize = Number(attrs.size ?? 3.5);
      const pt = sigma.graphToViewport({ x: wx, y: wy });
      const screenR = sigma.scaleSize(baseSize, cam.ratio);
      const inVp = pt.x >= 0 && pt.x <= stageRect.width && pt.y >= 0 && pt.y <= stageRect.height;

      if (inVp) {
        visiblePts.push({ x: pt.x, y: pt.y, r: screenR });
        radii.push(screenR);
      }

      if (anchors.length < 60 && (inVp || h.highlightedNodes.has(nodeId))) {
        anchors.push({
          nodeId,
          label: String(attrs.label || ""),
          worldX: Math.round(wx * 10) / 10,
          worldY: Math.round(wy * 10) / 10,
          screenX: Math.round(pt.x * 100) / 100,
          screenY: Math.round(pt.y * 100) / 100,
          screenRadiusPx: Math.round(screenR * 100) / 100,
          inViewport: inVp,
        });
      }
    });
    const checkedLabels = drawnLabels.length;

    // Pairwise overlap check on up to 250 visible nodes
    const samplePts = visiblePts.slice(0, 250);
    let overlappingPairs = 0;
    let sampledPairs = 0;
    for (let i = 0; i < samplePts.length; i += 1) {
      for (let j = i + 1; j < samplePts.length; j += 1) {
        sampledPairs += 1;
        const dx = samplePts[i].x - samplePts[j].x;
        const dy = samplePts[i].y - samplePts[j].y;
        const minDist = (samplePts[i].r + samplePts[j].r) * 0.9;
        if (dx * dx + dy * dy < minDist * minDist) {
          overlappingPairs += 1;
        }
      }
    }

    radii.sort((a, b) => a - b);
    const maxR = radii.length ? radii[radii.length - 1] : 0;
    const medR = radii.length ? radii[Math.floor(radii.length / 2)] : 0;

    const elements: VisibleElementSummary = {
      activeTab: document.getElementById("view-map")?.classList.contains("is-active") ? "map" : "workbench",
      theme: document.documentElement.dataset.theme || "light",
      viewportCounterText: (document.getElementById("viewport-counter")?.textContent || "").trim(),
      drawerOpen: !document.getElementById("node-drawer")?.classList.contains("is-hidden"),
      searchPopoverOpen: !document.getElementById("search-popover")?.classList.contains("is-hidden"),
      complianceBannerOpen: !document.getElementById("compliance-banner")?.classList.contains("is-hidden"),
      stageWidth: Math.round(stageRect.width),
      stageHeight: Math.round(stageRect.height),
      graphNodeCount: graph.order,
      graphEdgeCount: graph.size,
    };

    return {
      phase,
      timestampMs: Date.now(),
      elements,
      camera: {
        x: Math.round(cam.x * 100000) / 100000,
        y: Math.round(cam.y * 100000) / 100000,
        ratio: Math.round(cam.ratio * 100000) / 100000,
        angle: cam.angle,
      },
      worldBbox: [
        Math.round(worldBbox[0]),
        Math.round(worldBbox[1]),
        Math.round(worldBbox[2]),
        Math.round(worldBbox[3]),
      ],
      customBBox,
      anchors,
      labelOverflow: {
        checkedCount: checkedLabels,
        overflowCount: overflowSamples.length,
        samples: overflowSamples,
      },
      overlapStats: {
        visibleNodeCount: visiblePts.length,
        maxScreenRadiusPx: Math.round(maxR * 100) / 100,
        medianScreenRadiusPx: Math.round(medR * 100) / 100,
        overlappingPairs,
        sampledPairs,
        overlapRatio: sampledPairs > 0 ? Math.round((overlappingPairs / sampledPairs) * 10000) / 10000 : 0,
      },
    };
  }

  async runThreePhaseProbe(
    probeName: string,
    actionFn: () => Promise<void> | void,
    waitForUpdateMs = 900,
  ): Promise<ThreePhaseDiff> {
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const counterEl = document.getElementById("viewport-counter");
    const t0 = this.captureSnapshot("T0_BEFORE");

    let sawCounterUpdate = false;
    let resolveCounter!: () => void;
    const counterPromise = new Promise<void>((res) => {
      resolveCounter = res;
    });

    const obs = new MutationObserver(() => {
      sawCounterUpdate = true;
      resolveCounter();
    });
    if (counterEl) {
      obs.observe(counterEl, { childList: true, characterData: true, subtree: true });
    }

    await actionFn();
    await sleep(60);
    const t1 = this.captureSnapshot("T1_AFTER_ACTION");

    await Promise.race([counterPromise, sleep(waitForUpdateMs)]);
    await sleep(80);
    obs.disconnect();

    const t2 = this.captureSnapshot("T2_AFTER_VIEWPORT_UPDATE");

    // Compare common anchor nodes' screen positions between T1 and T2
    const t1Map = new Map(t1.anchors.map((a) => [a.nodeId, a]));
    let maxJump = 0;
    let commonCount = 0;
    for (const a2 of t2.anchors) {
      const a1 = t1Map.get(a2.nodeId);
      if (!a1) continue;
      commonCount += 1;
      const dist = Math.hypot(a2.screenX - a1.screenX, a2.screenY - a1.screenY);
      if (dist > maxJump) maxJump = dist;
    }

    const dx = Math.abs(t2.camera.x - t1.camera.x);
    const dy = Math.abs(t2.camera.y - t1.camera.y);
    const dratio = Math.abs(t2.camera.ratio - t1.camera.ratio);

    const stable = maxJump < 1.0 && dx < 1e-4 && dy < 1e-4 && dratio < 1e-4;
    return {
      probeName,
      t0_before: t0,
      t1_after_action: t1,
      t2_after_viewport_update: t2,
      viewportCounterChanged: sawCounterUpdate || t0.elements.viewportCounterText !== t2.elements.viewportCounterText,
      cameraDriftAfterUpdate: {
        dx: Math.round(dx * 100000) / 100000,
        dy: Math.round(dy * 100000) / 100000,
        dratio: Math.round(dratio * 100000) / 100000,
      },
      maxAnchorJumpPxAfterUpdate: Math.round(maxJump * 100) / 100,
      commonAnchorCount: commonCount,
      stableAfterUpdate: stable,
    };
  }

  async runFullSuite(): Promise<{
    allStable: boolean;
    probes: ThreePhaseDiff[];
  }> {
    const h = this.map.getDiagnosticHandle();
    const sigma = h.sigma;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const probes: ThreePhaseDiff[] = [];

    // Probe 1: Pan / drag camera
    probes.push(
      await this.runThreePhaseProbe("pan_drag", async () => {
        const cur = sigma.getCamera().getState();
        sigma.getCamera().setState({ x: cur.x + 0.12, y: cur.y - 0.08, ratio: cur.ratio });
      }),
    );

    // Probe 2: Wheel zoom IN to high zoom (ratio = 0.14)
    probes.push(
      await this.runThreePhaseProbe("zoom_in_high", async () => {
        const cur = sigma.getCamera().getState();
        sigma.getCamera().setState({ x: cur.x, y: cur.y, ratio: 0.14 });
      }),
    );

    // Probe 3: Wheel zoom OUT (ratio = 1.4)
    probes.push(
      await this.runThreePhaseProbe("zoom_out_wide", async () => {
        const cur = sigma.getCamera().getState();
        sigma.getCamera().setState({ x: cur.x, y: cur.y, ratio: 1.4 });
      }),
    );

    // Probe 4: Search keyword + click first node -> focus animation -> viewport update
    probes.push(
      await this.runThreePhaseProbe(
        "search_and_focus_node",
        async () => {
          const inp = document.getElementById("global-search-input") as HTMLInputElement;
          inp.value = "知识图谱";
          document.getElementById("global-search-form")?.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
          for (let i = 0; i < 60; i += 1) {
            if (document.querySelectorAll("#search-results-body .kos-inner-row").length > 0) break;
            await sleep(100);
          }
          const row = document.querySelector<HTMLElement>("#search-results-body .kos-inner-row");
          row?.click();
          await sleep(360);
        },
        1000,
      ),
    );

    // Close drawer cleanly
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

    // Probe 5: Reset Viewport button restores full [0..10000] map cleanly
    probes.push(
      await this.runThreePhaseProbe(
        "reset_viewport",
        async () => {
          document.getElementById("btn-reset-camera")?.click();
          await sleep(340);
        },
        1000,
      ),
    );

    return {
      allStable: probes.every((p) => p.stableAfterUpdate),
      probes,
    };
  }
}

declare global {
  interface Window {
    __KOS_DIAG__?: MapDiagnostics;
  }
}

export function installDiagnostics(map: KnowledgeWorldMap): MapDiagnostics {
  const diag = new MapDiagnostics(map);
  window.__KOS_DIAG__ = diag;
  return diag;
}
