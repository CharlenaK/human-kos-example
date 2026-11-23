# Third-Party Notices & Attributions

This repository's original source code and documentation are released under the **MIT License** (see [`MIT.txt`](./MIT.txt)).

We gratefully acknowledge the following design systems, reference architectures, open-source libraries, and open-data bases that informed or power this example implementation:

---

## 1. Visual Design System Reference

- **Cindy Design System (`makecindy/cindy`)**
  - Source: <https://github.com/makecindy/cindy/blob/main/docs/design-rules/cindy-design-system.md> and <https://github.com/makecindy/cindy/blob/main/docs/design-rules/DESIGN.md>
  - What we borrowed: Engineering governance and visual discipline — specifically the three-tier calm paper-like grayscale layer system (`Surface` / `Card` / `Board`), strictly registered non-gray color whitelist, CJK-first typography stack before `Segoe UI`, four-step weight ladder, two-step border-radius decision tree (registered data marks & keycaps vs. ordinary control tiers), zero-shadow base philosophy, single-source DTCG token generation + static guard, and the Light/Dark dual-mode delivery gate.
  - Note: All CSS tokens (`--kos-*`), five-facet identity palette, component markup, and documentation text in `docs/design-rules/` were authored specifically for Human KOS; no Cindy source files or brand assets are copied into this repository.

## 2. Architectural & Client Integration References

- **ChatCrystal** — Apache License 2.0 (<https://github.com/nicepkg/ChatCrystal>)
  - Referenced for its Sigma.js v4 + Graphology WebGL graph rendering stack and content-fingerprint idempotent import patterns.
- **Open WebUI (`v0.13.4`)** — Open WebUI License (<https://github.com/open-webui/open-webui>)
  - Integrated strictly externally via official MCP, MCP Apps (`text/html;profile=mcp-app`, 5 MB sandboxed iframe), Python Filter/Action Functions, and RRULE Automations. **Zero lines** of Open WebUI source code are forked, modified, or redistributed in this repository.
- **Human KOS Database II (L1)** — MIT + Permissive/Isolated Open Data (<https://github.com/CharlenaK/human-kos>)
  - External read-only knowledge base consumed by `kos-engine`. When optional ShareAlike extension packs (`cn_rel`, `unesco`, `dila`, `edam`, `iscedf`) are attached at runtime, downstream sharing of derived outputs must retain the corresponding `CC BY-SA` attribution notices surfaced by `inspect_license_boundary()`.

## 3. Core Open-Source Libraries

| Package | License | Role |
| :--- | :--- | :--- |
| **FastAPI** &amp; **Uvicorn** &amp; **Pydantic** | MIT / BSD-3-Clause | Local HTTP &amp; Viewport API server |
| **MCP Python SDK (`mcp`)** | MIT | Model Context Protocol server (`stdio` / Streamable HTTP / MCP Apps) |
| **ONNX Runtime** | MIT | Lightweight CPU inference for `intfloat/multilingual-e5-small` (zero PyTorch) |
| **HuggingFace `tokenizers`** | Apache-2.0 | Fast Rust-backed SentencePiece / BPE query tokenization |
| **NumPy** | BSD-3-Clause | `int8` vector dequantization and per-facet z-score normalization |
| **Sigma.js v4** &amp; **Graphology** | MIT | WebGL 2D graph rendering engine |
| **Vite** &amp; **`vite-plugin-singlefile`** | MIT | Self-contained single-HTML frontend bundler (`< 5 MB`, zero external CDN) |
| **Bombadil (`@antithesishq/bombadil`)** | Apache-2.0 / MIT | Property-based temporal-logic UI test specification (`kos_engine/web/bombadil.spec.ts`) |
