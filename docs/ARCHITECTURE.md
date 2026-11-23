# Architecture &amp; Adapter Contract v1.0

This technical guide explains how **Human KOS Example** separates data, search/graph logic, personal state, and client integration shells.

## 1. Three-Database Physical Separation

| Layer | Database | Access Mode | Role |
| :--- | :--- | :--- | :--- |
| **DB I** | Client chat history / backups (Open WebUI, Cherry Studio) | Read-only import | Source conversations; never mutated |
| **DB II (L1)** | `human_kos_core.sqlite` + `human_kos_ext/*.sqlite` | Strictly `mode=ro` + `PRAGMA query_only = ON` | Shared client-agnostic KOS base (`CharlenaK/human-kos`) |
| **DB III (L3)** | `personal_bridge.sqlite` (default `.kos_local/personal_bridge.sqlite`) | Local writable (SQLite WAL) | Personal 5-facet mappings, activation decay ledger, Named Topic Collections, serendipity briefings, import receipts |

`PersonalBridgeDB` explicitly refuses to initialize inside any `human_kos_*` path so DB III can never collide with L1.

## 2. L2 Adapter Contract v1.0 (`kos_engine/src/kos_engine/core/`)

All six contract domains are implemented in pure Python 3.11+ with zero client coupling:

1. **Read-Only Access &amp; On-Demand `ATTACH`** (`workspace.py`): Opens core and Tier B extensions (`aat`, `cn_rel`, `compendium`, `dila`, `edam`, `glottolog`, `iscedf`, `lcsh`, `periodo`, `unesco`) via `file:...?mode=ro` + `PRAGMA query_only = ON`; enforces `kos_meta` `schema_version` major check (`1.x`) and optional `MANIFEST.json` SHA-256 verification.
2. **Hybrid Retrieval &amp; `int8` Dequantization** (`retrieval.py`, `encoder.py`): Fuses SQLite FTS5 BM25 (CJK n-gram + English porter) with `onnxruntime` + `tokenizers` CPU inference for `intfloat/multilingual-e5-small` (`"query: "` prefix, `float = int8 * scale`, per-facet z-score + RRF). Gracefully falls back to FTS5 for zero-vector large packs (`lcsh`, `dila`, `aat`, `glottolog`, `periodo`) or when no ONNX model directory is configured. Supports `cn_rel.cn_alias_fts` zh→en bridging and `kos_aei_calibration` lookup.
3. **Strict Five-Facet Physical Isolation** (`retrieval.py`): Every query filters `kos_facet_pool(is_active = 1)` and `facet_type ∈ {DOMAIN, ACTIVITY, PROCESS, ARTIFACT, STANCE}` independently — never mixing Top-K candidates across facets.
4. **Adjacency &amp; Multi-Hop Edge Traversal** (`traversal.py`): Bounded BFS over `kos_edges` (`oa:cooccur`, `skos:related`, `skos:closeMatch`, `skos:broader`, etc.) and attached extension packs (`unesco`, `cn_rel.cn_relations`), with default `polarity = 1` (negative edges `polarity = -1` require explicit opt-in), `min_ic >= 1.5`, and `exclude_roots = True`.
5. **Provenance &amp; License Governance** (`provenance.py`): `inspect_license_boundary()` traces every node/pack to `kos_provenance`, returning `share_alike_triggered`, `local_only_triggered`, and deduplicated `required_notices`.
6. **Spatial Viewport &amp; Voronoi Partitions** (`spatial.py`): Queries `kos_spatial` R\*Tree + `min_zoom_tier` (0–3) capped at `<= 5,000` nodes per viewport frame, and normalizes `kos_map_partitions` polygons to standard GeoJSON.

## 3. Transport Projections (`kos_engine/src/kos_engine/api/`)

A single pure-Python core projects simultaneously to:

- **In-Process Python SDK**: `from kos_engine import KosWorkspace`
- **Local HTTP / Viewport API (`http_app.py`)**: FastAPI endpoints under `/v1/*` plus hosted single-file 2D Knowledge World Map at `/map`
- **MCP Server (`mcp_server.py`)**: Official `mcp>=2.3` `MCPServer` supporting `stdio` &amp; `streamable-http` plus Open WebUI MCP Apps resource `ui://kos-engine/map` (`text/html;profile=mcp-app`, `< 5 MB`, zero external CDN)

## 4. 2D Knowledge World Map (`kos_engine/web/`)

- **WebGL Nodes &amp; Edges**: Sigma.js v4 + Graphology with permanently pinned `customBBox({ x: [0, 10000], y: [0, 10000] })` (zero viewport-reload camera drift), `minCameraRatio: 0.0005` (2,000× zoom), bounded `zoomToSizeRatioFunction`, and deterministic golden-angle micro-spread for near-coincident L1 nodes (strictly visual-only; L1 untouched).
- **Synced Canvas2D Underlay &amp; Label Overlay**: Voronoi GeoJSON underlay + native OS Canvas2D labels (immune to WebGL SDF CJK glyph atlas overflow) with 2D bounding-box anti-overlap, viewport edge clamping, and full-title hover pill.
- **Built-in Diagnostics**: `window.__KOS_DIAG__.runFullSuite()` captures 3-phase snapshots (`T0_BEFORE` → `T1_AFTER_ACTION` → `T2_AFTER_VIEWPORT_UPDATE`) and pairs with `kos_engine/web/bombadil.spec.ts` (`@antithesishq/bombadil`).
