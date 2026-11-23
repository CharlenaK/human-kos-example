"""Offline contract verification tests for Open WebUI v0.13.4 zero-fork thin adapter kit (P3-A7).

Validates directly against Open WebUI v0.13.4 specifications inspected in
`Client Reference/Open WebUI/repo/backend/open_webui/utils/mcp/apps.py`,
`functions.py`, and `routers/automations.py` without modifying Open WebUI source.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from dateutil.rrule import rrulestr

from kos_engine.api.http_app import create_app
from kos_engine.api.mcp_server import (
    MCP_APP_MAX_BYTES,
    MCP_APP_MIME_TYPE,
    MCP_APP_RESOURCE_URI,
    build_mcp_app_ui_meta,
    load_mcp_app_html,
)
from kos_engine.bridge.db import PersonalBridgeDB
from kos_engine.core.workspace import KosWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ADAPTER_DIR = REPO_ROOT / "adapters" / "open_webui"
L1_CORE = Path(
    os.environ.get("KOS_CORE_DB")
    or next(
        (
            str(b / r)
            for b in (REPO_ROOT, REPO_ROOT.parent)
            for r in ("kos_build/release/human_kos_core.sqlite", "data/human_kos_core.sqlite")
            if (b / r).is_file()
        ),
        str(REPO_ROOT / "data" / "human_kos_core.sqlite"),
    )
)
L1_EXT_DIR = Path(os.environ.get("KOS_EXT_DIR") or (L1_CORE.parent / "human_kos_ext"))

# Exact domain regex copied from Open WebUI v0.13.4 backend/open_webui/utils/mcp/apps.py
_OWUI_APP_CSP_DOMAIN_RE = re.compile(
    r"(?:https?|wss?)://(?:\*\.)?(?:[a-zA-Z0-9.-]+|\[[a-fA-F0-9:]+\])(?::[0-9]{1,5})?"
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mcp_app_bundle_matches_open_webui_v0134_apps_py() -> None:
    """Verify built 2D map HTML meets Open WebUI 5 MB limit, ui:// URI, MIME, and app_csp."""
    meta = build_mcp_app_ui_meta("http://127.0.0.1:8787")
    ui = meta["ui"]
    assert ui["resourceUri"] == MCP_APP_RESOURCE_URI
    assert ui["resourceUri"].startswith("ui://")

    for key, values in ui["csp"].items():
        assert isinstance(values, list)
        for v in values:
            assert _OWUI_APP_CSP_DOMAIN_RE.fullmatch(v), f"Invalid CSP domain in {key}: {v}"
            if key != "connectDomains":
                assert v.startswith(("http://", "https://"))

    html = load_mcp_app_html(api_origin="http://127.0.0.1:8787")
    size_bytes = len(html.encode("utf-8"))
    assert 10_000 < size_bytes < MCP_APP_MAX_BYTES, f"Unexpected bundle size: {size_bytes}"
    # Must contain zero external CDN script/link tags (would violate default-src 'none')
    assert not re.search(r'<script[^>]+src=["\']https?://', html, re.IGNORECASE)
    assert not re.search(r'<link[^>]+href=["\']https?://', html, re.IGNORECASE)
    assert MCP_APP_MIME_TYPE == "text/html;profile=mcp-app"


def test_rrule_automation_and_mcp_config_valid() -> None:
    auto_path = ADAPTER_DIR / "automations" / "serendipity_rrule.json"
    auto = json.loads(auto_path.read_text(encoding="utf-8"))
    rule = rrulestr(auto["rrule"], dtstart=datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc))
    upcoming = [rule.after(datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc))]
    assert upcoming[0] is not None
    assert "kos_generate_serendipity_briefing" in auto["prompt"]

    mcp_cfg = json.loads((ADAPTER_DIR / "mcp" / "mcp_server_config.json").read_text(encoding="utf-8"))
    assert len(mcp_cfg["servers"]) >= 2
    assert mcp_cfg["servers"][0]["mcp_apps"]["mime_type"] == MCP_APP_MIME_TYPE


@pytest.mark.asyncio
async def test_open_webui_filter_and_action_end_to_end(tmp_path: Path) -> None:
    """Exercise Open WebUI Filter (/attach propose + confirm) and Action against live FastAPI ASGI app."""
    ws = KosWorkspace.open_workspace(L1_CORE, L1_EXT_DIR, model_dir=None)
    bridge = PersonalBridgeDB(tmp_path / "personal_bridge.sqlite")
    app = create_app(ws, bridge)

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as client:
            filter_mod = _load_module(ADAPTER_DIR / "functions" / "kos_attach_filter.py", "kos_attach_filter")
            action_mod = _load_module(ADAPTER_DIR / "functions" / "kos_explore_action.py", "kos_explore_action")

            filt = filter_mod.Filter(http_client=client)
            events = []

            async def emitter(ev):
                events.append(ev)

            # 1. /attach propose injects strictly isolated 5-facet candidates into system message
            body = {
                "chat_id": "owui-e2e-1",
                "metadata": {"title": "图谱与智能体架构"},
                "messages": [{"role": "user", "content": "/attach 大语言模型与知识图谱"}],
            }
            out_body = await filt.inlet(body, __event_emitter__=emitter)
            assert out_body["messages"][0]["role"] == "system"
            sys_ctx = out_body["messages"][0]["content"]
            for facet in ("DOMAIN", "ACTIVITY", "PROCESS", "ARTIFACT", "STANCE"):
                assert f"### {facet}" in sys_ctx

            # 2. /attach confirm writes verified L1 node into DB III
            proc_node = ws.search_facet("大语言模型", "PROCESS", mode="bm25", top_k=1)[0]
            confirm_body = {
                "chat_id": "owui-e2e-1",
                "metadata": {"title": "图谱与智能体架构"},
                "messages": [
                    {"role": "user", "content": f"/attach confirm PROCESS:{proc_node.node_id}"},
                ],
            }
            out_confirm = await filt.inlet(confirm_body, __event_emitter__=emitter)
            assert "Human KOS DB III 挂载成功" in out_confirm["messages"][0]["content"]
            assert bridge.get_stats()["mappings"] == 1

            # 3. Action function performs 2-hop traversal and emits exploration card
            act = action_mod.Action(http_client=client)
            act_res = await act.action(
                {"messages": [{"role": "user", "content": "knowledge graph machine learning reasoning"}]},
                __event_emitter__=emitter,
            )
            assert act_res["status"] == "ok"
            assert act_res["node_count"] >= 1
            assert "Human KOS 沿边拓扑探索摘要" in act_res["markdown"]
    finally:
        bridge.close()
        ws.close()
