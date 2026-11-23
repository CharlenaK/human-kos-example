"""Contract tests for FastAPI HTTP/Viewport API and FastMCP + MCP Apps (P3-A5)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kos_engine.api.http_app import create_app
from kos_engine.api.mcp_server import (
    MCP_APP_MAX_BYTES,
    MCP_APP_MIME_TYPE,
    MCP_APP_RESOURCE_URI,
    build_mcp_app_ui_meta,
    create_mcp_server,
)
from kos_engine.bridge.db import PersonalBridgeDB
from kos_engine.core.workspace import KosWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
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


@pytest.fixture()
def env(tmp_path: Path):
    ws = KosWorkspace.open_workspace(L1_CORE, L1_EXT_DIR, model_dir=None)
    bridge = PersonalBridgeDB(tmp_path / "personal_bridge.sqlite")
    app = create_app(ws, bridge)
    client = TestClient(app)
    mcp = create_mcp_server(ws, bridge, api_origin="http://127.0.0.1:8787")
    yield ws, bridge, client, mcp
    bridge.close()
    ws.close()


def test_http_api_full_loop(env) -> None:
    ws, bridge, client, _ = env

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["schema_version"] == "1.0.0"

    r_meta = client.get("/v1/meta")
    assert r_meta.status_code == 200
    assert "unesco" in r_meta.json()["available_extensions"]

    r_search = client.post(
        "/v1/search/facet",
        json={"query_text": "大语言模型", "facet": "PROCESS", "mode": "bm25", "top_k": 5},
    )
    assert r_search.status_code == 200
    body = r_search.json()
    assert body["count"] > 0
    assert all(c["facet_type"] == "PROCESS" for c in body["candidates"])

    # Propose -> Confirm -> Collections -> Serendipity
    r_prop = client.post(
        "/v1/bridge/attach/propose",
        json={"query_text": "知识图谱与强化学习", "mode": "bm25", "top_k_per_facet": 4},
    )
    assert r_prop.status_code == 200
    prop = r_prop.json()
    assert set(prop["candidates_by_facet"].keys()) == {"DOMAIN", "ACTIVITY", "PROCESS", "ARTIFACT", "STANCE"}

    oa_seed = ws._con.execute(
        "SELECT source_id FROM kos_edges WHERE relation_type='oa:cooccur' LIMIT 1"
    ).fetchone()[0]
    oa_node = ws.get_node(str(oa_seed))
    r_conf = client.post(
        "/v1/bridge/attach/confirm",
        json={
            "session": {
                "source_client": "open_webui",
                "external_session_id": "http-sess-1",
                "title": "强化学习与知识图谱联调",
                "content_text": "讨论图谱沿边遍历和策略学习。",
            },
            "bindings": [
                {"facet_type": oa_node["facet_type"], "node_id": oa_node["node_id"], "confidence": 0.9}
            ],
        },
    )
    assert r_conf.status_code == 200
    assert len(r_conf.json()["applied_bindings"]) == 1

    r_ser = client.post("/v1/bridge/serendipity", json={"max_hops": 2, "min_ic": 1.5, "top_k": 5})
    assert r_ser.status_code == 200
    assert len(r_ser.json()["items"]) >= 1

    # Viewport & Partitions
    r_vp = client.get("/v1/viewport?min_x=0&min_y=0&max_x=10000&max_y=10000&zoom_tier=1&limit=200")
    assert r_vp.status_code == 200
    assert r_vp.json()["total_returned"] > 0

    r_parts = client.get("/v1/partitions")
    assert r_parts.status_code == 200
    assert len(r_parts.json()) > 5


@pytest.mark.asyncio
async def test_mcp_tools_and_mcp_app_resource(env) -> None:
    _, _, _, mcp = env

    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    for expected in (
        "kos_get_meta",
        "kos_search_facet",
        "kos_search_all_facets",
        "kos_traverse_multi_hop",
        "kos_inspect_provenance",
        "kos_attach_session",
        "kos_generate_serendipity_briefing",
        "kos_open_map",
    ):
        assert expected in tool_names

    # Verify MCP App tool metadata matches Open WebUI utils/mcp/apps.py contract
    open_map_tool = next(t for t in tools if t.name == "kos_open_map")
    meta_dict = getattr(open_map_tool, "meta", None) or {}
    assert meta_dict.get("ui", {}).get("resourceUri") == MCP_APP_RESOURCE_URI

    # Verify MCP App resource MIME type and < 5 MB limit
    resources = await mcp.list_resources()
    map_res = next(r for r in resources if str(r.uri) == MCP_APP_RESOURCE_URI)
    assert getattr(map_res, "mime_type", getattr(map_res, "mimeType", None)) == MCP_APP_MIME_TYPE

    contents = await mcp.read_resource(MCP_APP_RESOURCE_URI)
    html_text = "".join(
        getattr(c, "content", getattr(c, "text", "")) for c in contents
    )
    assert "<!doctype html>" in html_text.lower()
    assert len(html_text.encode("utf-8")) < MCP_APP_MAX_BYTES

    # Invoke kos_search_facet via MCPServer
    res = await mcp.call_tool(
        "kos_search_facet",
        {"query_text": "哲学", "facet": "DOMAIN", "mode": "bm25", "top_k": 5},
    )
    blocks = res.content if hasattr(res, "content") else (res[0] if isinstance(res, tuple) else res)
    parsed = json.loads(blocks[0].text)
    assert parsed["facet"] == "DOMAIN"
    assert len(parsed["candidates"]) > 0
