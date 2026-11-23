import Graph from "graphology";
import Sigma from "sigma";
import {
  ALL_FACETS,
  type FacetType,
  type MapPartition,
  type TraversalSubgraph,
  type ViewportNode,
  kosApi,
} from "./api";

const WORLD_BBOX: { x: [number, number]; y: [number, number] } = {
  x: [0, 10000],
  y: [0, 10000],
};

const GOLDEN_ANGLE = 2.399963229728653;

interface ThemePalette {
  facet: Record<FacetType, string>;
  facetSoft: Record<FacetType, string>;
  edgeMuted: string;
  bridgeEdge: string;
  errorFg: string;
  voronoiStroke: string;
  textPrimary: string;
  textSecondary: string;
  card: string;
  board: string;
}

interface PinnedNode {
  node_id: string;
  map_x: number;
  map_y: number;
  facet_type: FacetType;
  label: string;
  info_content?: number;
}

export interface DrawnLabelBox {
  nodeId: string;
  text: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function readToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function readThemePalette(): ThemePalette {
  return {
    facet: {
      DOMAIN: readToken("--kos-facet-domain"),
      ACTIVITY: readToken("--kos-facet-activity"),
      PROCESS: readToken("--kos-facet-process"),
      ARTIFACT: readToken("--kos-facet-artifact"),
      STANCE: readToken("--kos-facet-stance"),
    },
    facetSoft: {
      DOMAIN: readToken("--kos-facet-domain-soft"),
      ACTIVITY: readToken("--kos-facet-activity-soft"),
      PROCESS: readToken("--kos-facet-process-soft"),
      ARTIFACT: readToken("--kos-facet-artifact-soft"),
      STANCE: readToken("--kos-facet-stance-soft"),
    },
    edgeMuted: readToken("--kos-map-edge-muted"),
    bridgeEdge: readToken("--kos-bridge-edge"),
    errorFg: readToken("--kos-error-fg"),
    voronoiStroke: readToken("--kos-map-voronoi-stroke"),
    textPrimary: readToken("--kos-text-primary"),
    textSecondary: readToken("--kos-text-secondary"),
    card: readToken("--kos-card"),
    board: readToken("--kos-board"),
  };
}

/**
 * Truncate overly long map node labels by display-width units (CJK = 2, ASCII = 1)
 * so resting labels stay compact; hover pill and inspector drawer always show full text.
 */
export function truncateMapLabel(raw: string, maxUnits = 24): string {
  const s = (raw || "").trim();
  if (!s) return "";
  let units = 0;
  let out = "";
  for (const ch of s) {
    const w = ch.charCodeAt(0) > 255 ? 2 : 1;
    if (units + w > maxUnits) {
      return `${out.trimEnd()}…`;
    }
    out += ch;
    units += w;
  }
  return out;
}

/**
 * Compute deterministic visual-only micro-spread coordinates for nodes sharing nearly
 * identical L1 UMAP coordinates (e.g. Compendium PA headings clamped near y=9980.0).
 * L1 SQLite data is never modified; nodes spread cleanly along a Fermat spiral on deep zoom.
 */
function spreadCoincidentCoords(nodes: ViewportNode[]): Map<string, [number, number]> {
  const buckets = new Map<string, ViewportNode[]>();
  for (const n of nodes) {
    const key = `${Math.round(n.map_x)}:${Math.round(n.map_y)}`;
    let list = buckets.get(key);
    if (!list) {
      list = [];
      buckets.set(key, list);
    }
    list.push(n);
  }

  const coords = new Map<string, [number, number]>();
  for (const list of buckets.values()) {
    if (list.length === 1) {
      coords.set(list[0].node_id, [list[0].map_x, list[0].map_y]);
      continue;
    }
    // Sort deterministically by node_id so positions never jitter across viewport reloads
    list.sort((a, b) => (a.node_id < b.node_id ? -1 : a.node_id > b.node_id ? 1 : 0));
    const cx = list.reduce((s, n) => s + n.map_x, 0) / list.length;
    const cy = list.reduce((s, n) => s + n.map_y, 0) / list.length;
    const spacing = 16;
    for (let i = 0; i < list.length; i += 1) {
      const r = i === 0 ? 0 : spacing * Math.sqrt(i);
      const angle = i * GOLDEN_ANGLE;
      const dx = Math.cos(angle) * r;
      const dy = Math.sin(angle) * r;
      const x = Math.max(20, Math.min(9980, cx + dx));
      const y = Math.max(20, Math.min(9980, cy + dy));
      coords.set(list[i].node_id, [x, y]);
    }
  }
  return coords;
}

export class KnowledgeWorldMap {
  private graph: Graph;
  private sigma: Sigma;
  private containerEl: HTMLElement;
  private voronoiCanvas: HTMLCanvasElement;
  private labelCanvas: HTMLCanvasElement;
  private partitions: MapPartition[] = [];
  private activeFacets = new Set<FacetType>(ALL_FACETS);
  private zoomTier = 1;
  private showVoronoi = true;
  private highlightedNodes = new Set<string>();
  private highlightedEdges = new Set<string>();
  private pinnedFocusNode: PinnedNode | null = null;
  private activeTraversal: TraversalSubgraph | null = null;
  private hoveredNodeId: string | null = null;
  private lastDrawnLabels: DrawnLabelBox[] = [];
  private palette: ThemePalette;
  private onNodeClick: (nodeId: string) => void;
  private onStatusUpdate: (msg: string) => void;
  private viewportTimer: number | null = null;
  private suppressCameraRefresh = false;
  private loadSeq = 0;
  private lastViewportKey = "";

  constructor(
    container: HTMLElement,
    voronoiCanvas: HTMLCanvasElement,
    labelCanvas: HTMLCanvasElement,
    onNodeClick: (nodeId: string) => void,
    onStatusUpdate: (msg: string) => void,
  ) {
    this.containerEl = container;
    this.voronoiCanvas = voronoiCanvas;
    this.labelCanvas = labelCanvas;
    this.onNodeClick = onNodeClick;
    this.onStatusUpdate = onStatusUpdate;
    this.palette = readThemePalette();
    this.graph = new Graph({ multi: false, allowSelfLoops: false });

    this.sigma = new Sigma(this.graph, container, {
      settings: {
        // Disable Sigma v4 WebGL SDF labels (whose fixed glyph atlas overflows/garbles CJK at T3);
        // crisp native OS DirectWrite/ClearType labels are rendered on the synced `#label-canvas`.
        renderLabels: false,
        allowInvalidContainer: true,
        itemSizesReference: "screen",
        stagePadding: 48,
        // Bounded zoomToSizeRatioFunction: keeps nodes compact & non-overlapping even at 2000x deep zoom
        zoomToSizeRatioFunction: (ratio: number) => Math.max(0.85, Math.min(1.6, Math.pow(Math.max(ratio, 0.0005), 0.12))),
        minCameraRatio: 0.0005,
        maxCameraRatio: 3.0,
      },
      styles: {
        nodes: {
          x: { attribute: "x" },
          y: { attribute: "y" },
          size: {
            whenState: "isHovered",
            then: (attrs) => Math.min(8.0, Number(attrs.size || 3.5) + 2.0),
            else: { attribute: "size", defaultValue: 3.5 },
          },
          color: { attribute: "color", defaultValue: this.palette.facet.DOMAIN },
          visibility: {
            whenState: "isHidden",
            then: "hidden",
            else: "visible",
          },
          zIndex: { attribute: "zIndex", defaultValue: 1 },
        },
        edges: {
          size: { attribute: "size", defaultValue: 0.9 },
          color: (attrs) => String(attrs.color || this.palette.edgeMuted),
          visibility: {
            whenState: "isHidden",
            then: "hidden",
            else: "visible",
          },
          zIndex: { attribute: "zIndex", defaultValue: 0 },
        },
      },
    });

    // Permanently pin Sigma's world normalization bbox to L1's frozen [0, 10000] x [0, 10000] domain
    this.sigma.setCustomBBox({ x: [...WORLD_BBOX.x], y: [...WORLD_BBOX.y] });

    this.sigma.on("clickNode", ({ node }) => {
      this.onNodeClick(node);
    });

    this.sigma.on("enterNode", ({ node }) => {
      this.hoveredNodeId = node;
      this.drawLabels();
    });

    this.sigma.on("leaveNode", () => {
      this.hoveredNodeId = null;
      this.drawLabels();
    });

    this.sigma.on("afterRender", () => {
      this.drawVoronoi();
      this.drawLabels();
    });

    this.sigma.getCamera().on("updated", () => {
      this.drawVoronoi();
      this.drawLabels();
      if (!this.suppressCameraRefresh) {
        this.scheduleViewportRefresh();
      }
    });

    window.addEventListener("resize", () => {
      this.drawVoronoi();
      this.drawLabels();
    });
  }

  getDiagnosticHandle() {
    return {
      sigma: this.sigma,
      graph: this.graph,
      stageEl: this.containerEl,
      voronoiCanvas: this.voronoiCanvas,
      labelCanvas: this.labelCanvas,
      highlightedNodes: this.highlightedNodes,
      getWorldBbox: () => this.currentWorldBbox(),
      getDrawnLabels: () => this.lastDrawnLabels,
    };
  }

  async init(): Promise<void> {
    try {
      this.partitions = await kosApi.getPartitions();
    } catch {
      this.partitions = [];
    }
    this.sigma.setCustomBBox({ x: [...WORLD_BBOX.x], y: [...WORLD_BBOX.y] });
    this.suppressCameraRefresh = true;
    this.sigma.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1.05, angle: 0 });
    this.suppressCameraRefresh = false;
    await this.loadViewport([0, 0, 10000, 10000], true);
    this.drawVoronoi();
    this.drawLabels();
  }

  refreshTheme(): void {
    this.palette = readThemePalette();
    this.graph.forEachNode((nid, attrs) => {
      const facet = (attrs.facetType as FacetType) || "DOMAIN";
      const isHighlight = this.highlightedNodes.has(nid);
      this.graph.setNodeAttribute(nid, "color", isHighlight ? this.palette.bridgeEdge : this.palette.facet[facet]);
    });
    this.graph.forEachEdge((eid, attrs) => {
      const neg = Number(attrs.polarity ?? 1) < 0;
      const hi = this.highlightedEdges.has(eid);
      const color = neg ? this.palette.errorFg : hi ? this.palette.bridgeEdge : this.palette.edgeMuted;
      this.graph.setEdgeAttribute(eid, "color", color);
    });
    const rect = this.voronoiCanvas.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      this.sigma.refresh();
      this.drawVoronoi();
      this.drawLabels();
    }
  }

  setFacets(facets: Set<FacetType>): void {
    this.activeFacets = new Set(facets);
    void this.loadViewport(this.currentWorldBbox(), true);
  }

  setZoomTier(tier: number): void {
    this.zoomTier = Math.max(0, Math.min(3, tier));
    void this.loadViewport(this.currentWorldBbox(), true);
  }

  setShowVoronoi(show: boolean): void {
    this.showVoronoi = show;
    this.drawVoronoi();
  }

  resetCamera(): void {
    if (this.viewportTimer !== null) {
      window.clearTimeout(this.viewportTimer);
      this.viewportTimer = null;
    }
    this.highlightedNodes.clear();
    this.highlightedEdges.clear();
    this.pinnedFocusNode = null;
    this.activeTraversal = null;
    this.hoveredNodeId = null;
    this.sigma.setCustomBBox({ x: [...WORLD_BBOX.x], y: [...WORLD_BBOX.y] });

    this.suppressCameraRefresh = true;
    this.sigma.getCamera().animate({ x: 0.5, y: 0.5, ratio: 1.05, angle: 0 }, { duration: 220 });
    window.setTimeout(() => {
      this.suppressCameraRefresh = false;
      void this.loadViewport([0, 0, 10000, 10000], true);
    }, 250);
  }

  focusNode(node: PinnedNode): void {
    if (this.viewportTimer !== null) {
      window.clearTimeout(this.viewportTimer);
      this.viewportTimer = null;
    }
    this.pinnedFocusNode = node;
    this.highlightedNodes.add(node.node_id);
    this.ensurePinnedNodeInGraph(node);
    this.sigma.setCustomBBox({ x: [...WORLD_BBOX.x], y: [...WORLD_BBOX.y] });
    this.sigma.refresh();

    const pos = this.sigma.getNodeDisplayData(node.node_id);
    const targetX = pos ? pos.x : node.map_x / 10000;
    const targetY = pos ? pos.y : node.map_y / 10000;

    this.suppressCameraRefresh = true;
    this.sigma.getCamera().animate({ x: targetX, y: targetY, ratio: 0.22 }, { duration: 240 });
    window.setTimeout(() => {
      this.suppressCameraRefresh = false;
      void this.loadViewport(this.currentWorldBbox(), true);
    }, 270);
  }

  overlayTraversal(sub: TraversalSubgraph): void {
    this.activeTraversal = sub;
    this.highlightedNodes.clear();
    this.highlightedEdges.clear();
    this.applyTraversalOverlay(sub);
    this.sigma.refresh();
    this.drawLabels();
  }

  private ensurePinnedNodeInGraph(node: PinnedNode): void {
    const shortLabel = truncateMapLabel(node.label);
    if (!this.graph.hasNode(node.node_id)) {
      this.graph.addNode(node.node_id, {
        x: node.map_x,
        y: node.map_y,
        size: 5.8,
        label: shortLabel,
        fullLabel: node.label,
        color: this.palette.bridgeEdge,
        facetType: node.facet_type,
        minZoomTier: 0,
        infoContent: node.info_content ?? 5.0,
        zIndex: 3,
      });
    } else {
      this.graph.setNodeAttribute(node.node_id, "color", this.palette.bridgeEdge);
      this.graph.setNodeAttribute(node.node_id, "size", 5.8);
      this.graph.setNodeAttribute(node.node_id, "zIndex", 3);
    }
  }

  private applyTraversalOverlay(sub: TraversalSubgraph): void {
    for (const n of sub.nodes) {
      const facet: FacetType = n.facet_type || "DOMAIN";
      const fullLabel = n.canonical_label_zh || n.canonical_label_en || n.node_id;
      const shortLabel = truncateMapLabel(fullLabel);
      this.highlightedNodes.add(n.node_id);
      if (!this.graph.hasNode(n.node_id)) {
        this.graph.addNode(n.node_id, {
          x: n.map_x,
          y: n.map_y,
          size: n.hop === 0 ? 5.8 : 4.4,
          label: shortLabel,
          fullLabel,
          color: n.hop === 0 ? this.palette.bridgeEdge : this.palette.facet[facet],
          facetType: facet,
          minZoomTier: n.hop === 0 ? 0 : 1,
          infoContent: n.info_content,
          zIndex: 2,
        });
      } else {
        this.graph.setNodeAttribute(n.node_id, "size", n.hop === 0 ? 5.8 : 4.4);
        this.graph.setNodeAttribute(n.node_id, "color", n.hop === 0 ? this.palette.bridgeEdge : this.palette.facet[facet]);
        this.graph.setNodeAttribute(n.node_id, "zIndex", 2);
      }
    }

    for (const e of sub.edges) {
      if (!this.graph.hasNode(e.source_id) || !this.graph.hasNode(e.target_id) || e.source_id === e.target_id) {
        continue;
      }
      const color = e.polarity < 0 ? this.palette.errorFg : this.palette.bridgeEdge;
      if (!this.graph.hasEdge(e.source_id, e.target_id)) {
        const eid = this.graph.addEdge(e.source_id, e.target_id, {
          color,
          size: e.polarity < 0 ? 2.0 : 1.6,
          polarity: e.polarity,
          zIndex: 2,
        });
        this.highlightedEdges.add(eid);
      } else {
        const eid = this.graph.edge(e.source_id, e.target_id);
        if (eid) {
          this.graph.setEdgeAttribute(eid, "color", color);
          this.graph.setEdgeAttribute(eid, "size", 1.8);
          this.graph.setEdgeAttribute(eid, "polarity", e.polarity);
          this.highlightedEdges.add(eid);
        }
      }
    }
  }

  private currentWorldBbox(): [number, number, number, number] {
    const rect = this.voronoiCanvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return [0, 0, 10000, 10000];
    }
    const tl = this.sigma.viewportToGraph({ x: 0, y: 0 });
    const br = this.sigma.viewportToGraph({ x: rect.width, y: rect.height });
    const rawMinX = Math.min(tl.x, br.x);
    const rawMaxX = Math.max(tl.x, br.x);
    const rawMinY = Math.min(tl.y, br.y);
    const rawMaxY = Math.max(tl.y, br.y);
    const spanX = Math.max(1, rawMaxX - rawMinX);
    const spanY = Math.max(1, rawMaxY - rawMinY);
    // Scale padding proportionally so deep zoom fetches precise local detail instead of wide 350-unit margins
    const padX = Math.min(350, Math.max(25, spanX * 0.14));
    const padY = Math.min(350, Math.max(25, spanY * 0.14));

    const minX = Math.max(0, rawMinX - padX);
    const maxX = Math.min(10000, rawMaxX + padX);
    const minY = Math.max(0, rawMinY - padY);
    const maxY = Math.min(10000, rawMaxY + padY);
    if (!Number.isFinite(minX) || !Number.isFinite(maxX) || maxX - minX < 1) {
      return [0, 0, 10000, 10000];
    }
    return [minX, minY, maxX, maxY];
  }

  private scheduleViewportRefresh(): void {
    if (this.viewportTimer !== null) {
      window.clearTimeout(this.viewportTimer);
    }
    this.viewportTimer = window.setTimeout(() => {
      this.viewportTimer = null;
      void this.loadViewport(this.currentWorldBbox(), false);
    }, 240);
  }

  private nodeSize(node: ViewportNode): number {
    const base =
      node.min_zoom_tier === 0 ? 4.6 : node.min_zoom_tier === 1 ? 3.5 : node.min_zoom_tier === 2 ? 2.7 : 2.2;
    return Math.min(5.2, base + Math.min(node.info_content, 5) * 0.13);
  }

  async loadViewport(bbox: [number, number, number, number], force = false): Promise<void> {
    const facets = Array.from(this.activeFacets).sort();
    if (facets.length === 0) {
      this.graph.clear();
      this.sigma.refresh();
      this.drawLabels();
      this.onStatusUpdate("已隐藏全部分面（0 节点）");
      return;
    }

    const span = Math.max(1, bbox[2] - bbox[0]);
    const quant = Math.max(1, Math.min(50, Math.round(span / 40)));
    const qKey = `${this.zoomTier}|${facets.join(",")}|${Math.round(bbox[0] / quant)},${Math.round(bbox[1] / quant)},${Math.round(bbox[2] / quant)},${Math.round(bbox[3] / quant)}`;
    if (!force && qKey === this.lastViewportKey) {
      return;
    }
    this.lastViewportKey = qKey;
    const seq = ++this.loadSeq;

    try {
      const vp = await kosApi.getViewport({
        min_x: bbox[0],
        min_y: bbox[1],
        max_x: bbox[2],
        max_y: bbox[3],
        zoom_tier: this.zoomTier,
        facets,
        limit: 2500,
      });

      if (seq !== this.loadSeq) {
        return;
      }

      this.sigma.setCustomBBox({ x: [...WORLD_BBOX.x], y: [...WORLD_BBOX.y] });

      const spreadCoords = spreadCoincidentCoords(vp.nodes);

      this.graph.clear();
      for (const n of vp.nodes) {
        const fullLabel = n.canonical_label_zh || n.canonical_label_en || n.node_id;
        const shortLabel = truncateMapLabel(fullLabel);
        const [dx, dy] = spreadCoords.get(n.node_id) || [n.map_x, n.map_y];
        this.graph.addNode(n.node_id, {
          x: dx,
          y: dy,
          rawX: n.map_x,
          rawY: n.map_y,
          size: this.nodeSize(n),
          label: shortLabel,
          fullLabel,
          color: this.highlightedNodes.has(n.node_id) ? this.palette.bridgeEdge : this.palette.facet[n.facet_type],
          facetType: n.facet_type,
          minZoomTier: n.min_zoom_tier,
          infoContent: n.info_content,
          zIndex: this.highlightedNodes.has(n.node_id) ? 2 : 1,
        });
      }

      for (const e of vp.edges) {
        if (
          e.source_id !== e.target_id &&
          this.graph.hasNode(e.source_id) &&
          this.graph.hasNode(e.target_id) &&
          !this.graph.hasEdge(e.source_id, e.target_id)
        ) {
          this.graph.addEdge(e.source_id, e.target_id, {
            color: e.polarity < 0 ? this.palette.errorFg : this.palette.edgeMuted,
            size: 0.7,
            polarity: e.polarity,
            zIndex: 0,
          });
        }
      }

      if (this.pinnedFocusNode) {
        this.ensurePinnedNodeInGraph(this.pinnedFocusNode);
      }
      if (this.activeTraversal) {
        this.applyTraversalOverlay(this.activeTraversal);
      }

      this.sigma.refresh();
      this.drawVoronoi();
      this.drawLabels();
      const capTag = vp.truncated ? "（已按视口截断）" : "";
      this.onStatusUpdate(`LoD T${vp.zoom_tier} · ${vp.total_returned} 节点 · ${vp.edges.length} 边 ${capTag}`.trim());
    } catch (err) {
      if (seq === this.loadSeq) {
        this.onStatusUpdate(`视口拉取失败: ${String(err)}`);
      }
    }
  }

  private drawVoronoi(): void {
    const canvas = this.voronoiCanvas;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.max(1, Math.floor(rect.width * dpr));
    const targetH = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    if (!this.showVoronoi || this.partitions.length === 0) return;

    const hudEl = document.querySelector(".kos-hud-top-left");
    const hudRect = hudEl ? hudEl.getBoundingClientRect() : null;
    const hudSafeRight = hudRect ? hudRect.right - rect.left + 16 : 0;
    const hudSafeBottom = hudRect ? hudRect.bottom - rect.top + 16 : 0;

    /* design: intrinsic-geometry — Voronoi GeoJSON polygons rendered on synced 2D canvas underlay */
    ctx.lineWidth = 1;
    ctx.font = `500 11px ${readToken("--kos-font-ui")}`;
    ctx.textAlign = "center";

    const layerParts = this.partitions
      .filter((p) => this.activeFacets.has(p.facet_type))
      .sort((a, b) => b.node_count - a.node_count);

    for (const part of layerParts) {
      const rings = part.geometry?.coordinates || [];
      for (const ring of rings) {
        if (!Array.isArray(ring) || ring.length < 3) continue;
        ctx.beginPath();
        for (let i = 0; i < ring.length; i += 1) {
          const [wx, wy] = ring[i];
          const pt = this.sigma.graphToViewport({ x: wx, y: wy });
          if (i === 0) ctx.moveTo(pt.x, pt.y);
          else ctx.lineTo(pt.x, pt.y);
        }
        ctx.closePath();
        ctx.fillStyle = this.palette.facetSoft[part.facet_type];
        ctx.fill();
        ctx.strokeStyle = this.palette.voronoiStroke;
        ctx.stroke();
      }
    }

    // Greedy non-overlapping Voronoi label placement avoiding the top-left HUD
    const placedBoxes: Array<[number, number, number, number]> = [];
    for (const part of layerParts) {
      if (part.node_count < 300) continue;
      const text = part.label_zh || part.label_en;
      const c = this.sigma.graphToViewport({ x: part.centroid_x, y: part.centroid_y });
      const w = ctx.measureText(text).width + 14;
      const h = 18;
      const x1 = c.x - w / 2;
      const y1 = c.y - h / 2;
      const x2 = c.x + w / 2;
      const y2 = c.y + h / 2;

      if (x1 < 8 || x2 > rect.width - 8 || y1 < 8 || y2 > rect.height - 8) continue;
      if (x1 < hudSafeRight && y1 < hudSafeBottom) continue;
      const overlaps = placedBoxes.some(([bx1, by1, bx2, by2]) => !(x2 < bx1 || x1 > bx2 || y2 < by1 || y1 > by2));
      if (overlaps) continue;

      placedBoxes.push([x1, y1, x2, y2]);
      ctx.fillStyle = this.palette.textSecondary;
      ctx.fillText(text, c.x, c.y);
    }
  }

  /**
   * Render crisp native OS Canvas2D labels for all LoD tiers (T0-T3), immune to Sigma v4
   * WebGL SDF CJK atlas overflow/garbling, with strict 2D bounding-box anti-overlap,
   * edge-clamping, HUD safe-zone avoidance, and full-title hover pill.
   */
  private drawLabels(): void {
    const canvas = this.labelCanvas;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.max(1, Math.floor(rect.width * dpr));
    const targetH = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== targetW || canvas.height !== targetH) {
      canvas.width = targetW;
      canvas.height = targetH;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    this.lastDrawnLabels = [];

    if (rect.width <= 0 || rect.height <= 0 || this.graph.order === 0) return;

    const cam = this.sigma.getCamera().getState();
    const hudEl = document.querySelector(".kos-hud-top-left");
    const hudRect = hudEl ? hudEl.getBoundingClientRect() : null;
    const hudSafeRight = hudRect ? hudRect.right - rect.left + 12 : 0;
    const hudSafeBottom = hudRect ? hudRect.bottom - rect.top + 12 : 0;

    // Collect visible candidates with priority
    interface Candidate {
      nodeId: string;
      shortLabel: string;
      fullLabel: string;
      px: number;
      py: number;
      radius: number;
      priority: number;
      isHovered: boolean;
      isHighlighted: boolean;
    }

    const candidates: Candidate[] = [];
    this.graph.forEachNode((nodeId, attrs) => {
      const wx = Number(attrs.x ?? 0);
      const wy = Number(attrs.y ?? 0);
      const pt = this.sigma.graphToViewport({ x: wx, y: wy });
      if (pt.x < -10 || pt.x > rect.width + 10 || pt.y < -10 || pt.y > rect.height + 10) {
        return;
      }
      const shortLabel = String(attrs.label || "");
      const fullLabel = String(attrs.fullLabel || shortLabel);
      if (!shortLabel) return;

      const isHovered = nodeId === this.hoveredNodeId;
      const isHighlighted = this.highlightedNodes.has(nodeId);
      const tier = Number(attrs.minZoomTier ?? 2);
      const ic = Number(attrs.infoContent ?? 1.0);
      const baseSize = Number(attrs.size ?? 3.5);
      const radius = this.sigma.scaleSize(baseSize, cam.ratio);

      let priority = (3 - tier) * 100 + Math.min(ic, 12);
      if (isHighlighted) priority += 500;
      if (isHovered) priority += 2000;

      candidates.push({
        nodeId,
        shortLabel,
        fullLabel,
        px: pt.x,
        py: pt.y,
        radius,
        priority,
        isHovered,
        isHighlighted,
      });
    });

    candidates.sort((a, b) => b.priority - a.priority);

    const fontUi = readToken("--kos-font-ui");
    /* design: intrinsic-geometry — Crisp Canvas2D node labels with anti-overlap collision table */
    ctx.font = `500 12px ${fontUi}`;
    ctx.textBaseline = "middle";

    const placed: Array<[number, number, number, number]> = [];
    // Allow more non-overlapping labels as the user zooms deeper
    const maxLabels = cam.ratio < 0.08 ? 140 : cam.ratio < 0.35 ? 90 : 55;
    const padMargin = 6;
    const textH = 16;

    for (const c of candidates) {
      if (!c.isHovered && this.lastDrawnLabels.length >= maxLabels) break;

      const text = c.isHovered ? c.fullLabel : c.shortLabel;
      const textW = ctx.measureText(text).width;
      const gap = c.radius + 5;

      // Prefer placing to the right; automatically flip left when near right edge of viewport
      let x1 = c.px + gap;
      let x2 = x1 + textW;
      if (x2 > rect.width - 10) {
        x2 = c.px - gap;
        x1 = x2 - textW;
      }

      if (c.isHovered) {
        // Clamp hover pill strictly inside viewport so full unabridged title is always 100% readable
        const boxPadX = 8;
        const boxPadY = 4;
        const pillW = Math.min(textW + boxPadX * 2, rect.width - 16);
        const pillH = textH + boxPadY * 2;
        let bx = Math.max(8, Math.min(rect.width - pillW - 8, x1 - boxPadX));
        let by = Math.max(8, Math.min(rect.height - pillH - 8, c.py - pillH / 2));

        ctx.fillStyle = this.palette.card;
        ctx.strokeStyle = this.palette.board;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(bx, by, pillW, pillH, 8);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = this.palette.textPrimary;
        ctx.textAlign = "left";
        ctx.fillText(text, bx + boxPadX, by + pillH / 2, pillW - boxPadX * 2);

        const box: [number, number, number, number] = [bx - 4, by - 4, bx + pillW + 4, by + pillH + 4];
        placed.push(box);
        this.lastDrawnLabels.push({ nodeId: c.nodeId, text, x1: bx, y1: by, x2: bx + pillW, y2: by + pillH });
        continue;
      }

      const y1 = c.py - textH / 2;
      const y2 = c.py + textH / 2;

      // Keep every label strictly inside viewport and clear of top-left floating HUD
      if (x1 < 8 || x2 > rect.width - 8 || y1 < 8 || y2 > rect.height - 8) continue;
      if (x1 < hudSafeRight && y1 < hudSafeBottom) continue;

      const collides = placed.some(
        ([bx1, by1, bx2, by2]) =>
          !(x2 + padMargin < bx1 || x1 - padMargin > bx2 || y2 + 3 < by1 || y1 - 3 > by2),
      );
      if (collides) continue;

      // Subtle card halo behind text for clean contrast over Voronoi borders and edges
      ctx.lineWidth = 3;
      ctx.strokeStyle = this.palette.card;
      ctx.lineJoin = "round";
      ctx.textAlign = "left";
      ctx.strokeText(text, x1, c.py);

      ctx.fillStyle = c.isHighlighted ? this.palette.bridgeEdge : this.palette.textPrimary;
      ctx.fillText(text, x1, c.py);

      placed.push([x1, y1, x2, y2]);
      this.lastDrawnLabels.push({ nodeId: c.nodeId, text, x1, y1, x2, y2 });
    }
  }
}
