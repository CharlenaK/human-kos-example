# Verification &amp; Quality Report

## 1. Automated Conformance Suite

Run from `kos_engine/`:

```bash
# Design System static token & radius guard
python ../docs/design-rules/tokens_guard.py --check

# Full Python conformance & Open WebUI v0.13.4 contract test suite (23 tests)
uv run pytest tests/ ../adapters/open_webui/tests/ -v

# Quick CLI health probe
uv run kos-engine --core /path/to/human_kos_core.sqlite probe
```

| Suite | Coverage | Result |
| :--- | :--- | :---: |
| `tests/test_adapter_contract.py` | Read-only `mode=ro` enforcement, `kos_meta` handshake + SHA-256, `local_only` guard, on-demand `ATTACH`/`DETACH`, 5-facet zero-mixing, Chinese FTS5 BM25 P95 (`< 20 ms`), ONNX `e5-small` `int8` z-score &amp; FTS5 fallback, `cn_rel` alias bridge &amp; ShareAlike guard, AEI calibration, multi-hop traversal with negative-edge opt-in &amp; IC `>= 1.5`, R\*Tree 4-tier LoD viewport &amp; Voronoi GeoJSON | **13 / 13 PASS** |
| `tests/test_bridge_and_importers.py` | DB III L1-collision guard, `/attach` propose + confirm, R4 content-fingerprint cross-client reconnection, activation half-life decay, dynamic `Named Topic Collections`, deterministic Serendipity Briefing, Open WebUI &amp; synthetic Cherry Studio SQLite/JSON idempotent importers | **4 / 4 PASS** |
| `tests/test_api_and_mcp.py` | FastAPI `/v1/*` full loop + `mcp` `MCPServer` tools &amp; `ui://kos-engine/map` MCP App resource (`< 5 MB`) | **2 / 2 PASS** |
| `tests/test_design_system_guard.py` | `tokens.dtcg.json` Light/Dark parity, `tokens.css` freshness, zero raw hex/rgb/off-ladder radii/numeric z-index | **1 / 1 PASS** |
| `adapters/open_webui/tests/test_open_webui_contracts.py` | Open WebUI `v0.13.4` `apps.py` CSP/5MB/0-CDN validation, RRULE validity, Filter `/attach` + Action 2-hop end-to-end ASGI tests | **3 / 3 PASS** |

## 2. Performance Benchmarks (Reference Hardware, CPU-Only)

- **Chinese FTS5 BM25 (single isolated facet)**: P50 = **3.52 ms**, P95 = **14.29 ms** (`< 20 ms` target)
- **ONNX Runtime `multilingual-e5-small` query encode (CPU, zero PyTorch)**: **5.64 ms** (`384d` L2-normalized)
- **Single-file 2D Map + Workbench bundle**: **516 KB** (133 KB gzip, `< 5 MB` MCP App limit, zero external CDN)

## 3. UI Stability Diagnostics &amp; Bombadil Property Specification

- **In-browser 3-phase diagnostic suite** (`kos_engine/web/src/diagnostics.ts`, `await window.__KOS_DIAG__.runFullSuite()`): compares `T0_BEFORE` → `T1_AFTER_ACTION` → `T2_AFTER_VIEWPORT_UPDATE` across pan/drag, deep zoom, wide zoom, search-focus, and reset-viewport — verified **`0 px`** post-update anchor drift, **`0 px`** map shift when opening the floating right inspector drawer, **`0`** overflowing labels, crisp native Canvas2D CJK labels at LoD `T3` (2,500 nodes), and deterministic spiral micro-spread for coincident L1 clusters.
- **Bombadil specification** (`kos_engine/web/bombadil.spec.ts`): type-checked against `@antithesishq/bombadil@0.8.0`. On Linux / macOS / WSL with Chromium:
  ```bash
  bombadil browser test --headless --time-limit 60s --exit-on-violation http://127.0.0.1:8787/map kos_engine/web/bombadil.spec.ts
  ```
