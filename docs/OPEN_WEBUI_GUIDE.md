# Open WebUI `v0.13.4` Zero-Fork Integration Guide

This guide explains how to connect **Open WebUI (`v0.13.4+`)** to standalone `kos-engine` without modifying or forking a single line of Open WebUI source code.

## Prerequisites

1. Download `human_kos_core.sqlite` from [`CharlenaK/human-kos`](https://github.com/CharlenaK/human-kos/releases/latest).
2. Have `kos-engine` installed in `kos_engine/` (`uv sync`).
3. Have a running Open WebUI `v0.13.4+` instance (local Python, Docker, or remote).

## Step 1 — Start Local `kos-engine` HTTP &amp; Map Service

```bash
cd kos_engine
uv run kos-engine --core /path/to/human_kos_core.sqlite serve --host 127.0.0.1 --port 8787
```

Verify health at `http://127.0.0.1:8787/health` and the standalone map at `http://127.0.0.1:8787/map`.

## Step 2 — Register the MCP Server (Tools + Embedded 2D Map App)

Option A — **Streamable HTTP**:
```bash
cd kos_engine
uv run kos-engine --core /path/to/human_kos_core.sqlite mcp --transport streamable-http --api-origin http://127.0.0.1:8787
```
Then add the server URL in Open WebUI **Admin → External Tools / MCP Servers** following [`adapters/open_webui/mcp/mcp_server_config.json`](../adapters/open_webui/mcp/mcp_server_config.json).

Option B — **Local stdio via Open WebUI Tether**:
Use the `kos-engine-stdio-tether` entry in [`adapters/open_webui/mcp/mcp_server_config.json`](../adapters/open_webui/mcp/mcp_server_config.json).

When the model calls `kos_open_map`, Open WebUI detects `ui://kos-engine/map` (`text/html;profile=mcp-app`, ~516 KB `< 5 MB`, zero external CDN) and renders the interactive 2D map inside a sandboxed parallel Tab iframe. Clicking **「在对话中探索」** triggers `openwebui.sendMessage(...)` to launch a new grounded chat.

## Step 3 — Import the Two Thin Python Functions

In Open WebUI **Workspace → Functions → + New Function**:

1. Paste [`adapters/open_webui/functions/kos_attach_filter.py`](../adapters/open_webui/functions/kos_attach_filter.py), verify `Valves.kos_api_url = "http://127.0.0.1:8787"`, and enable it.
   - Type `/attach <your topic>` in chat → injects 5 physically isolated candidate lists for human review.
   - Type `/attach confirm DOMAIN:oa:T11010 PROCESS:ccs:10010147` → validates against L1 and persists to DB III (`personal_bridge.sqlite`).
2. Paste [`adapters/open_webui/functions/kos_explore_action.py`](../adapters/open_webui/functions/kos_explore_action.py) and enable it for one-click 2-hop topological exploration from any message toolbar.

## Step 4 — Schedule Periodic Controlled Serendipity Briefings

In Open WebUI **Automations**, create a recurring task using [`adapters/open_webui/automations/serendipity_rrule.json`](../adapters/open_webui/automations/serendipity_rrule.json) (`FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=9;BYMINUTE=0`), bound to `mcp:kos-engine`. The automation calls `kos_generate_serendipity_briefing` to produce a deterministic, topology-backed briefing complete with evidence paths and mandatory `CC BY-SA` attribution notices whenever ShareAlike packs are referenced.
