# kos-engine

Independent Python 3.11+ L2 Adapter Contract v1.0 engine, L3 `personal_bridge.sqlite` (DB III) manager, FastAPI HTTP/Viewport API, FastMCP Server (with MCP Apps), and WebGL 2D Knowledge World Map host for **Human KOS Database II (L1)**.

## Core Invariants

1. **Read-Only L1 (DB II)**: Opens `human_kos_core.sqlite` and `human_kos_ext/*.sqlite` strictly via `mode=ro` + `PRAGMA query_only = ON`. Never mutates DB II.
2. **Three-Database Isolation**: DB I (client sessions, read-only import), DB II (read-only KOS standard base), DB III (`personal_bridge.sqlite`, independent local writable ledger).
3. **Lightweight Vector Inference**: Uses `onnxruntime` + `tokenizers` + `numpy` for `intfloat/multilingual-e5-small` (`"query: "` prefix, int8 dequantization, per-facet z-score + RRF), with automatic FTS5 fallback when no ONNX model directory is provided.
4. **Client-Agnostic**: Zero coupling to any client fork; exposes Python SDK, Local HTTP/Viewport API, and MCP Server (stdio + Streamable HTTP + MCP Apps).

## Quick Start

```powershell
cd kos_engine
uv sync --extra dev
uv run pytest -v
uv run kos-engine serve --core ../kos_build/release/human_kos_core.sqlite --port 8787
```
