export type FacetType = "DOMAIN" | "ACTIVITY" | "PROCESS" | "ARTIFACT" | "STANCE";

export const ALL_FACETS: FacetType[] = ["DOMAIN", "ACTIVITY", "PROCESS", "ARTIFACT", "STANCE"];

export const FACET_LABELS: Record<FacetType, string> = {
  DOMAIN: "DOMAIN 学科领域",
  ACTIVITY: "ACTIVITY 人类活动",
  PROCESS: "PROCESS 计算流程",
  ARTIFACT: "ARTIFACT 器物历史",
  STANCE: "STANCE 交互姿态",
};

export interface LicenseBoundary {
  share_alike_triggered: boolean;
  local_only_triggered: boolean;
  required_notices: string[];
  summary: string;
}

export interface ViewportNode {
  node_id: string;
  spatial_id: number;
  facet_type: FacetType;
  canonical_label_en?: string | null;
  canonical_label_zh?: string | null;
  breadcrumb_path: string;
  info_content: number;
  map_x: number;
  map_y: number;
  domain_partition_id: string;
  min_zoom_tier: number;
  source_id: string;
  license_spdx: string;
  dist_tier: string;
}

export interface ViewportEdge {
  source_id: string;
  target_id: string;
  relation_type: string;
  weight: number;
  polarity: number;
}

export interface ViewportResponse {
  bbox: [number, number, number, number];
  zoom_tier: number;
  total_returned: number;
  truncated: boolean;
  nodes: ViewportNode[];
  edges: ViewportEdge[];
}

export interface MapPartition {
  partition_id: string;
  facet_type: FacetType;
  label_en: string;
  label_zh?: string | null;
  centroid_x: number;
  centroid_y: number;
  node_count: number;
  geometry: {
    type: string;
    coordinates: number[][][];
  };
}

export interface FacetCandidate {
  node_id: string;
  facet_type: FacetType;
  canonical_label_en?: string | null;
  canonical_label_zh?: string | null;
  breadcrumb_path: string;
  info_content: number;
  map_x: number;
  map_y: number;
  source_id: string;
  license_spdx: string;
  dist_tier: string;
  pack_id: string;
  fused_score: number;
  z_score?: number | null;
  bm25_score?: number | null;
  matched_via: string[];
}

export interface NeighborEdge {
  source_id: string;
  target_id: string;
  neighbor_id: string;
  direction: "out" | "in";
  relation_type: string;
  weight: number;
  polarity: number;
  pack_id: string;
  neighbor_label_en?: string | null;
  neighbor_label_zh?: string | null;
  neighbor_facet_type?: FacetType | null;
  neighbor_breadcrumb?: string | null;
  neighbor_info_content: number;
  license_spdx: string;
  dist_tier: string;
}

export interface TraversalSubgraph {
  seed_node_ids: string[];
  max_hops: number;
  include_negative: boolean;
  nodes: Array<{
    node_id: string;
    facet_type?: FacetType | null;
    canonical_label_en?: string | null;
    canonical_label_zh?: string | null;
    breadcrumb_path: string;
    info_content: number;
    hop: number;
    map_x: number;
    map_y: number;
    license_spdx: string;
    dist_tier: string;
  }>;
  edges: Array<{
    source_id: string;
    target_id: string;
    relation_type: string;
    weight: number;
    polarity: number;
    hop: number;
    pack_id: string;
  }>;
  license_boundary: LicenseBoundary;
}

function resolveApiOrigin(): string {
  const meta = document.querySelector('meta[name="kos-api-origin"]');
  const configured = meta?.getAttribute("content")?.trim();
  if (configured) {
    return configured.replace(/\/+$/, "");
  }
  if (window.location.origin && window.location.origin !== "null" && window.location.protocol.startsWith("http")) {
    return window.location.origin;
  }
  return "http://127.0.0.1:8787";
}

export const API_ORIGIN = resolveApiOrigin();

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_ORIGIN}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

export const kosApi = {
  getMeta: () =>
    requestJson<{
      meta: {
        schema_version: string;
        layout_version: string;
        core_node_count: number;
        active_packages: string[];
      };
      available_extensions: string[];
      attached_extensions?: Record<string, { share_alike: boolean; local_only: boolean }>;
    }>("/v1/meta"),

  attachExtension: (pack_id: string) =>
    requestJson<{ pack_id: string; share_alike: boolean; local_only: boolean }>("/v1/extensions/attach", {
      method: "POST",
      body: JSON.stringify({ pack_id }),
    }),

  detachExtension: (pack_id: string) =>
    requestJson<{ detached: string; active_packages: string[] }>("/v1/extensions/detach", {
      method: "POST",
      body: JSON.stringify({ pack_id }),
    }),

  getPartitions: () => requestJson<MapPartition[]>("/v1/partitions"),

  getViewport: (params: {
    min_x: number;
    min_y: number;
    max_x: number;
    max_y: number;
    zoom_tier: number;
    facets: FacetType[];
    limit?: number;
  }) => {
    const qs = new URLSearchParams({
      min_x: String(params.min_x),
      min_y: String(params.min_y),
      max_x: String(params.max_x),
      max_y: String(params.max_y),
      zoom_tier: String(params.zoom_tier),
      facets: params.facets.join(","),
      limit: String(params.limit ?? 2500),
      include_edges: "true",
    });
    return requestJson<ViewportResponse>(`/v1/viewport?${qs.toString()}`);
  },

  searchAll: (query_text: string, mode: "hybrid" | "bm25", top_k = 6) =>
    requestJson<{
      results: Record<FacetType, FacetCandidate[]>;
      license_boundary: LicenseBoundary;
    }>("/v1/search/all", {
      method: "POST",
      body: JSON.stringify({ query_text, mode, top_k }),
    }),

  getNode: (nodeId: string, includeNegative = false) =>
    requestJson<{
      node: ViewportNode & { definition_summary?: string | null; pack_id?: string };
      ancestry: Array<{ node_id: string; canonical_label_zh?: string; canonical_label_en?: string }>;
      neighbors: NeighborEdge[];
      license_boundary: LicenseBoundary;
    }>(`/v1/nodes/${encodeURIComponent(nodeId)}?include_negative=${includeNegative ? "true" : "false"}`),

  traverse: (seed_node_ids: string[], max_hops = 2, include_negative = false) =>
    requestJson<TraversalSubgraph>("/v1/traverse", {
      method: "POST",
      body: JSON.stringify({ seed_node_ids, max_hops, include_negative, min_ic: 1.5, exclude_roots: true }),
    }),

  proposeAttach: (query_text: string, mode: "hybrid" | "bm25" = "hybrid") =>
    requestJson<{
      query_text: string;
      candidates_by_facet: Record<FacetType, FacetCandidate[]>;
      license_boundary: LicenseBoundary;
    }>("/v1/bridge/attach/propose", {
      method: "POST",
      body: JSON.stringify({ query_text, mode, top_k_per_facet: 5 }),
    }),

  confirmAttach: (payload: {
    session: {
      source_client: string;
      external_session_id: string;
      title: string;
      content_text: string;
    };
    bindings: Array<{ facet_type: FacetType; node_id: string; pack_id: string; confidence: number }>;
  }) =>
    requestJson<{
      session: { session_uid: string; title: string };
      applied_bindings: Array<{ node_id: string; facet_type: FacetType; canonical_label: string }>;
      reconnected_by_fingerprint: boolean;
      license_boundary: LicenseBoundary;
    }>("/v1/bridge/attach/confirm", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getSessions: () =>
    requestJson<
      Array<{
        session_uid: string;
        source_client: string;
        title: string;
        updated_at: string;
        mappings: Array<{ facet_type: FacetType; node_id: string; canonical_label: string }>;
      }>
    >("/v1/bridge/sessions?limit=30"),

  getCollections: () =>
    requestJson<
      Array<{
        collection_id: string;
        anchor_node_id: string;
        anchor_label: string;
        facet_type: FacetType;
        session_count: number;
        effective_activation: number;
        cooccurring_facets: Record<string, string[]>;
      }>
    >("/v1/bridge/collections?limit=20"),

  runSerendipity: () =>
    requestJson<{
      briefing_id: string;
      generated_at: string;
      seed_node_count: number;
      items: Array<{
        target_node_id: string;
        target_label: string;
        target_facet_type: FacetType;
        target_breadcrumb: string;
        info_content: number;
        map_x: number;
        map_y: number;
        score: number;
        ucb_bonus: number;
        rationale: string;
        license_spdx: string;
        dist_tier: string;
      }>;
      license_boundary: LicenseBoundary;
      markdown: string;
    }>("/v1/bridge/serendipity", {
      method: "POST",
      body: JSON.stringify({ max_hops: 2, min_ic: 1.5, top_k: 8, persist: true }),
    }),

  importCherry: (backup_path: string, dry_run: boolean) =>
    requestJson<{
      receipt_id: string;
      dry_run: boolean;
      total_seen: number;
      inserted_count: number;
      updated_count: number;
      skipped_count: number;
      private_filtered_count: number;
      items: Array<{ external_session_id: string; title: string; status: string; reason?: string }>;
    }>("/v1/import/cherry-studio", {
      method: "POST",
      body: JSON.stringify({ backup_path, dry_run, filter_secrets: true }),
    }),
};
