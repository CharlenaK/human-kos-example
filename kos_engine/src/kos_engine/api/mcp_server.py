"""FastMCP Server (stdio + Streamable HTTP) with Open WebUI v0.13.4 MCP Apps support.

Exposes L2 Adapter Contract v1.0 tools, L3 DB III `/attach` & controlled serendipity
briefing tools, and the `ui://kos-engine/map` MCP App resource (`text/html;profile=mcp-app`,
strictly < 5 MB and compliant with Open WebUI `utils/mcp/apps.py` CSP rules).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from mcp.server.mcpserver import MCPServer as _MCPServer
except ImportError:  # pragma: no cover - fallback for mcp<2
    from mcp.server.fastmcp import FastMCP as _MCPServer  # type: ignore[no-redef]

from kos_engine.bridge.attach import confirm_attach, propose_attach
from kos_engine.bridge.db import PersonalBridgeDB
from kos_engine.bridge.models import AttachConfirmRequest, FacetBinding, SessionInput
from kos_engine.bridge.serendipity import compute_topic_collections, generate_serendipity_briefing
from kos_engine.core.models import ALL_FACETS, FacetType, RetrievalMode
from kos_engine.core.workspace import KosWorkspace

MCP_APP_MIME_TYPE = "text/html;profile=mcp-app"
MCP_APP_RESOURCE_URI = "ui://kos-engine/map"
MCP_APP_MAX_BYTES = 5 * 1024 * 1024


def build_mcp_app_ui_meta(api_origin: str = "http://127.0.0.1:8787") -> Dict[str, Any]:
    """Build `_meta.ui` payload matching Open WebUI v0.13.4 `utils/mcp/apps.py`.

    Open WebUI derives the sandbox CSP from the **resource** metadata
    (`resources/read` content `_meta`, falling back to `resources/list`), not from
    the tool metadata. Without it the iframe gets `connect-src 'none'` and the map
    cannot fetch `/v1/viewport`. The same payload is therefore attached to both the
    tool and the `ui://kos-engine/map` resource.
    """
    return {
        "ui": {
            "resourceUri": MCP_APP_RESOURCE_URI,
            "csp": {
                "connectDomains": [api_origin],
                "resourceDomains": [],
                "frameDomains": [],
                "baseUriDomains": [],
            },
        }
    }


def load_mcp_app_html(static_map_dir: Optional[Path] = None, api_origin: str = "http://127.0.0.1:8787") -> str:
    """Return self-contained HTML bundle for MCP App sandbox iframe (< 5 MB, zero external CDN)."""
    map_dir = static_map_dir or (Path(__file__).resolve().parent.parent / "static" / "map")
    single_file = map_dir / "mcp-app.html"
    index_file = map_dir / "index.html"
    target = single_file if single_file.is_file() else index_file
    if target.is_file():
        html = target.read_text(encoding="utf-8")
        # Inject runtime API base meta tag if not already present so sandboxed iframe knows kos-engine URL
        inject = f'<meta name="kos-api-origin" content="{api_origin}" />'
        if "kos-api-origin" not in html and "</head>" in html:
            html = html.replace("</head>", f"  {inject}\n</head>", 1)
        if len(html.encode("utf-8")) > MCP_APP_MAX_BYTES:
            raise ValueError(f"MCP App HTML exceeds Open WebUI 5 MB limit ({len(html.encode('utf-8'))} bytes)")
        return html
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/>"
        f'<meta name="kos-api-origin" content="{api_origin}" />'
        "<title>Human KOS 2D World Map (MCP App)</title></head>"
        "<body><main style='padding:16px;font-family:sans-serif'>"
        "<h3>Human KOS 2D Knowledge World Map</h3>"
        "<p>Run frontend build inside <code>kos_engine/web</code> to populate the WebGL map bundle.</p>"
        "</main></body></html>"
    )


def create_mcp_server(
    workspace: KosWorkspace,
    bridge_db: PersonalBridgeDB,
    *,
    api_origin: str = "http://127.0.0.1:8787",
    static_map_dir: Optional[Path] = None,
) -> _MCPServer:
    mcp = _MCPServer("kos-engine")

    @mcp.tool()
    def kos_get_meta() -> str:
        """Return L1 KOS kos_meta manifest, active packages, and DB III statistics."""
        payload = {
            "meta": workspace.get_meta().model_dump(),
            "available_extensions": workspace.list_available_extensions(),
            "bridge_stats": bridge_db.get_stats(),
        }
        return json.dumps(payload, ensure_ascii=False)

    @mcp.tool()
    def kos_attach_extension(pack_id: str) -> str:
        """Attach a read-only Tier B extension pack (e.g. unesco, cn_rel, lcsh, dila, edam)."""
        info = workspace.attach_extension(pack_id)
        return info.model_dump_json()

    @mcp.tool()
    def kos_detach_extension(pack_id: str) -> str:
        """Detach a previously mounted Tier B extension pack."""
        workspace.detach_extension(pack_id)
        return json.dumps({"detached": pack_id, "active_packages": workspace.active_packages}, ensure_ascii=False)

    @mcp.tool()
    def kos_search_facet(
        query_text: str,
        facet: FacetType,
        mode: RetrievalMode = "hybrid",
        top_k: int = 10,
        ext_packs: Optional[List[str]] = None,
        use_cn_alias_bridge: bool = False,
    ) -> str:
        """Search strictly inside one orthogonal KOS facet (DOMAIN/ACTIVITY/PROCESS/ARTIFACT/STANCE)."""
        cands = workspace.search_facet(
            query_text=query_text,
            facet=facet,
            mode=mode,
            top_k=top_k,
            ext_packs=ext_packs,
            use_cn_alias_bridge=use_cn_alias_bridge,
        )
        boundary = workspace.inspect_license_boundary(
            node_ids=[c.node_id for c in cands],
            pack_ids=sorted({c.pack_id for c in cands} | {"core"}),
        )
        return json.dumps(
            {
                "facet": facet,
                "candidates": [c.model_dump() for c in cands],
                "license_boundary": boundary.model_dump(),
            },
            ensure_ascii=False,
        )

    @mcp.tool()
    def kos_search_all_facets(
        query_text: str,
        mode: RetrievalMode = "hybrid",
        top_k_per_facet: int = 6,
        ext_packs: Optional[List[str]] = None,
        use_cn_alias_bridge: bool = False,
    ) -> str:
        """Propose physically isolated Top-K candidates across all 5 orthogonal facets for /attach."""
        proposal = propose_attach(
            workspace,
            query_text=query_text,
            mode=mode,
            top_k_per_facet=top_k_per_facet,
            ext_packs=ext_packs,
            use_cn_alias_bridge=use_cn_alias_bridge,
        )
        return proposal.model_dump_json()

    @mcp.tool()
    def kos_traverse_multi_hop(
        seed_node_ids: List[str],
        max_hops: int = 2,
        relations: Optional[List[str]] = None,
        include_negative: bool = False,
        min_ic: float = 1.5,
        exclude_roots: bool = True,
        max_nodes: int = 60,
        cross_field_only: bool = False,
        ext_packs: Optional[List[str]] = None,
    ) -> str:
        """Execute bounded multi-hop edge traversal with polarity=1 default, IC>=1.5 floor, and root exclusion."""
        subgraph = workspace.traverse_multi_hop(
            seed_node_ids=seed_node_ids,
            max_hops=max_hops,
            relations=relations,
            include_negative=include_negative,
            min_ic=min_ic,
            exclude_roots=exclude_roots,
            max_nodes=max_nodes,
            cross_field_only=cross_field_only,
            ext_packs=ext_packs,
        )
        return subgraph.model_dump_json()

    @mcp.tool()
    def kos_inspect_provenance(
        node_ids: Optional[List[str]] = None,
        pack_ids: Optional[List[str]] = None,
    ) -> str:
        """Inspect SPDX provenance, ShareAlike (dist_ext_sa), and local_only compliance notices."""
        report = workspace.inspect_license_boundary(node_ids=node_ids, pack_ids=pack_ids)
        return report.model_dump_json()

    @mcp.tool()
    def kos_attach_session(
        source_client: str,
        external_session_id: str,
        title: str,
        content_text: str,
        bindings: List[Dict[str, Any]],
    ) -> str:
        """Validate selected 5-facet bindings against L1 and persist session mapping into DB III."""
        parsed_bindings = [FacetBinding(**b) for b in bindings]
        req = AttachConfirmRequest(
            session=SessionInput(
                source_client=source_client,
                external_session_id=external_session_id,
                title=title,
                content_text=content_text,
            ),
            bindings=parsed_bindings,
        )
        res = confirm_attach(workspace, bridge_db, req)
        return res.model_dump_json()

    @mcp.tool()
    def kos_generate_serendipity_briefing(
        seed_node_ids: Optional[List[str]] = None,
        max_hops: int = 2,
        min_ic: float = 1.5,
        top_k: int = 8,
        ext_packs: Optional[List[str]] = None,
    ) -> str:
        """Generate a deterministic, topology-backed Controlled Serendipity Briefing (JSON + Markdown)."""
        briefing = generate_serendipity_briefing(
            workspace,
            bridge_db,
            seed_node_ids=seed_node_ids,
            max_hops=max_hops,
            min_ic=min_ic,
            top_k=top_k,
            ext_packs=ext_packs,
            persist=True,
        )
        return briefing.model_dump_json()

    @mcp.tool()
    def kos_list_topic_collections(limit: int = 20) -> str:
        """Return dynamically aggregated Named Topic Collections from DB III."""
        cols = compute_topic_collections(bridge_db, limit=limit)
        return json.dumps([c.model_dump() for c in cols], ensure_ascii=False)

    @mcp.tool(meta=build_mcp_app_ui_meta(api_origin))
    def kos_open_map(
        focus_node_id: Optional[str] = None,
        zoom_tier: int = 1,
        facet: Optional[FacetType] = None,
    ) -> str:
        """Open the interactive Human KOS 2D Knowledge World Map (MCP App ui://kos-engine/map)."""
        focus = workspace.get_node(focus_node_id) if focus_node_id else None
        payload = {
            "map_url": f"{api_origin}/map",
            "resource_uri": MCP_APP_RESOURCE_URI,
            "mime_type": MCP_APP_MIME_TYPE,
            "zoom_tier": zoom_tier,
            "facet": facet,
            "focus_node": (
                {
                    "node_id": focus["node_id"],
                    "label": focus.get("canonical_label_zh") or focus.get("canonical_label_en"),
                    "map_x": focus["map_x"],
                    "map_y": focus["map_y"],
                    "facet_type": focus["facet_type"],
                }
                if focus
                else None
            ),
        }
        return json.dumps(payload, ensure_ascii=False)

    @mcp.resource(
        MCP_APP_RESOURCE_URI,
        mime_type=MCP_APP_MIME_TYPE,
        meta=build_mcp_app_ui_meta(api_origin),
    )
    def kos_map_app_resource() -> str:
        """Self-contained interactive WebGL 2D Knowledge World Map for Open WebUI MCP Apps."""
        return load_mcp_app_html(static_map_dir=static_map_dir, api_origin=api_origin)

    return mcp
