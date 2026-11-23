"""FastAPI Local HTTP / Viewport API + static 2D Knowledge World Map host."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kos_engine.bridge.attach import confirm_attach, propose_attach
from kos_engine.bridge.db import PersonalBridgeDB
from kos_engine.bridge.importers.cherry_studio import import_cherry_studio_backup
from kos_engine.bridge.importers.open_webui import import_open_webui_export
from kos_engine.bridge.models import AttachConfirmRequest
from kos_engine.bridge.serendipity import compute_topic_collections, generate_serendipity_briefing
from kos_engine.core.models import ALL_FACETS, FacetType, RetrievalMode
from kos_engine.core.workspace import KosWorkspace


class ExtensionRequest(BaseModel):
    pack_id: str


class FacetSearchRequest(BaseModel):
    query_text: str
    facet: FacetType
    mode: RetrievalMode = "hybrid"
    top_k: int = Field(20, ge=1, le=200)
    ext_packs: Optional[List[str]] = None
    use_cn_alias_bridge: bool = False
    zscore_normalize: bool = True


class AllFacetsSearchRequest(BaseModel):
    query_text: str
    facets: List[FacetType] = Field(default_factory=lambda: list(ALL_FACETS))
    mode: RetrievalMode = "hybrid"
    top_k: int = Field(8, ge=1, le=100)
    ext_packs: Optional[List[str]] = None
    use_cn_alias_bridge: bool = False
    zscore_normalize: bool = True


class TraverseRequest(BaseModel):
    seed_node_ids: List[str] = Field(..., min_length=1)
    max_hops: int = Field(2, ge=1, le=4)
    relations: Optional[List[str]] = None
    include_negative: bool = False
    min_ic: float = 1.5
    exclude_roots: bool = True
    max_nodes: int = Field(80, ge=5, le=500)
    cross_field_only: bool = False
    ext_packs: Optional[List[str]] = None


class ProvenanceInspectRequest(BaseModel):
    node_ids: Optional[List[str]] = None
    pack_ids: Optional[List[str]] = None


class AttachProposeRequest(BaseModel):
    query_text: str
    mode: RetrievalMode = "hybrid"
    top_k_per_facet: int = Field(6, ge=1, le=30)
    ext_packs: Optional[List[str]] = None
    use_cn_alias_bridge: bool = False


class SerendipityRequest(BaseModel):
    seed_node_ids: Optional[List[str]] = None
    max_hops: int = Field(2, ge=1, le=3)
    min_ic: float = 1.5
    top_k: int = Field(8, ge=1, le=30)
    ext_packs: Optional[List[str]] = None
    persist: bool = True


class OpenWebUIImportRequest(BaseModel):
    payload: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None
    export_path: Optional[str] = None
    dry_run: bool = True


class CherryStudioImportRequest(BaseModel):
    backup_path: str = Field(..., description="Explicit path to a Cherry Studio .sqlite/.db or .json backup file")
    dry_run: bool = True
    filter_secrets: bool = True


def _fallback_map_html() -> str:
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/>"
        "<title>Human KOS 2D World Map</title></head>"
        "<body style='font-family:sans-serif;padding:24px'>"
        "<h2>Human KOS 2D World Map</h2>"
        "<p>Map frontend static bundle has not been built yet. Run <code>pnpm build</code> inside <code>kos_engine/web</code>.</p>"
        "</body></html>"
    )


def create_app(
    workspace: KosWorkspace,
    bridge_db: PersonalBridgeDB,
    *,
    static_map_dir: Optional[Path] = None,
) -> FastAPI:
    app = FastAPI(
        title="kos-engine Local API",
        version="0.1.0",
        description="Client-agnostic L2 Adapter Contract v1.0 HTTP/Viewport API and L3 DB III manager.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    map_dir = static_map_dir or (Path(__file__).resolve().parent.parent / "static" / "map")

    @app.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/map")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon_empty() -> Response:
        return Response(status_code=204)

    @app.get("/health")
    def health() -> Dict[str, Any]:
        meta = workspace.get_meta()
        return {
            "status": "ok",
            "schema_version": meta.schema_version,
            "layout_version": meta.layout_version,
            "embedding_version": meta.embedding_version,
            "active_packages": meta.active_packages,
            "encoder_available": workspace.encoder.available,
            "bridge_stats": bridge_db.get_stats(),
        }

    @app.get("/v1/meta")
    def get_meta() -> Dict[str, Any]:
        meta = workspace.get_meta()
        return {
            "meta": meta.model_dump(),
            "available_extensions": workspace.list_available_extensions(),
            "attached_extensions": {k: v.model_dump() for k, v in workspace.get_attached_packs().items()},
        }

    @app.post("/v1/extensions/attach")
    def attach_extension(req: ExtensionRequest) -> Dict[str, Any]:
        try:
            info = workspace.attach_extension(req.pack_id)
            return info.model_dump()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/extensions/detach")
    def detach_extension(req: ExtensionRequest) -> Dict[str, Any]:
        workspace.detach_extension(req.pack_id)
        return {"detached": req.pack_id, "active_packages": workspace.active_packages}

    @app.post("/v1/search/facet")
    def api_search_facet(req: FacetSearchRequest) -> Dict[str, Any]:
        try:
            cands = workspace.search_facet(
                query_text=req.query_text,
                facet=req.facet,
                mode=req.mode,
                top_k=req.top_k,
                ext_packs=req.ext_packs,
                use_cn_alias_bridge=req.use_cn_alias_bridge,
                zscore_normalize=req.zscore_normalize,
            )
            packs = sorted({c.pack_id for c in cands} | {"core"})
            boundary = workspace.inspect_license_boundary(
                node_ids=[c.node_id for c in cands],
                pack_ids=packs,
            )
            return {
                "facet": req.facet,
                "mode": req.mode,
                "count": len(cands),
                "candidates": [c.model_dump() for c in cands],
                "license_boundary": boundary.model_dump(),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/search/all")
    def api_search_all(req: AllFacetsSearchRequest) -> Dict[str, Any]:
        try:
            by_facet = workspace.search_all_facets(
                query_text=req.query_text,
                facets=req.facets,
                mode=req.mode,
                top_k=req.top_k,
                ext_packs=req.ext_packs,
                use_cn_alias_bridge=req.use_cn_alias_bridge,
                zscore_normalize=req.zscore_normalize,
            )
            all_ids = [c.node_id for cands in by_facet.values() for c in cands]
            packs = sorted({c.pack_id for cands in by_facet.values() for c in cands} | {"core"})
            boundary = workspace.inspect_license_boundary(node_ids=all_ids, pack_ids=packs)
            return {
                "query_text": req.query_text,
                "mode": req.mode,
                "results": {f: [c.model_dump() for c in cands] for f, cands in by_facet.items()},
                "license_boundary": boundary.model_dump(),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/aei/{axis_type}")
    def api_list_aei(axis_type: str, limit: int = Query(20, ge=1, le=200)) -> List[Dict[str, Any]]:
        return [d.model_dump() for d in workspace.list_aei_calibration(axis_type=axis_type, limit=limit)]

    @app.get("/v1/aei/{axis_type}/{axis_key}")
    def api_get_aei(axis_type: str, axis_key: str) -> Dict[str, Any]:
        item = workspace.get_aei_calibration(axis_type=axis_type, axis_key=axis_key)
        if item is None:
            raise HTTPException(status_code=404, detail="AEI calibration key not found")
        return item.model_dump()

    @app.get("/v1/nodes/{node_id:path}")
    def api_get_node(
        node_id: str,
        include_negative: bool = Query(False),
        min_ic: float = Query(1.5),
        neighbor_limit: int = Query(25, ge=1, le=100),
    ) -> Dict[str, Any]:
        node = workspace.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
        ancestry = workspace.get_ancestry(node_id)
        neighbors = workspace.get_neighbors(
            node_id,
            polarity="all" if include_negative else 1,
            min_ic=min_ic,
            exclude_roots=True,
            limit=neighbor_limit,
        )
        boundary = workspace.inspect_license_boundary(
            node_ids=[node_id, *[n.neighbor_id for n in neighbors]],
            pack_ids=sorted({node.get("pack_id", "core"), *[n.pack_id for n in neighbors]}),
        )
        return {
            "node": node,
            "ancestry": [a.model_dump() for a in ancestry],
            "neighbors": [n.model_dump() for n in neighbors],
            "license_boundary": boundary.model_dump(),
        }

    @app.post("/v1/traverse")
    def api_traverse(req: TraverseRequest) -> Dict[str, Any]:
        try:
            subgraph = workspace.traverse_multi_hop(
                seed_node_ids=req.seed_node_ids,
                max_hops=req.max_hops,
                relations=req.relations,
                include_negative=req.include_negative,
                min_ic=req.min_ic,
                exclude_roots=req.exclude_roots,
                max_nodes=req.max_nodes,
                cross_field_only=req.cross_field_only,
                ext_packs=req.ext_packs,
            )
            return subgraph.model_dump()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/provenance/inspect")
    def api_provenance(req: ProvenanceInspectRequest) -> Dict[str, Any]:
        try:
            report = workspace.inspect_license_boundary(node_ids=req.node_ids, pack_ids=req.pack_ids)
            return report.model_dump()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/viewport")
    def api_viewport(
        min_x: float = Query(0.0),
        min_y: float = Query(0.0),
        max_x: float = Query(10000.0),
        max_y: float = Query(10000.0),
        zoom_tier: int = Query(1, ge=0, le=3),
        facets: Optional[str] = Query(None, description="Comma-separated facet_types"),
        limit: int = Query(2000, ge=1, le=5000),
        include_edges: bool = Query(True),
    ) -> Dict[str, Any]:
        facet_list: Optional[List[FacetType]] = None
        if facets:
            facet_list = [f.strip().upper() for f in facets.split(",") if f.strip().upper() in ALL_FACETS]  # type: ignore[misc]
        vp = workspace.query_viewport(
            bbox=(min_x, min_y, max_x, max_y),
            zoom_tier=zoom_tier,
            facets=facet_list,
            limit=limit,
            include_edges=include_edges,
        )
        return vp.model_dump()

    @app.get("/v1/partitions")
    def api_partitions(facet: Optional[FacetType] = Query(None)) -> List[Dict[str, Any]]:
        return [p.model_dump() for p in workspace.get_map_partitions(facet=facet)]

    # ---- L3 DB III Bridge Endpoints ----

    @app.post("/v1/bridge/attach/propose")
    def api_attach_propose(req: AttachProposeRequest) -> Dict[str, Any]:
        proposal = propose_attach(
            workspace,
            query_text=req.query_text,
            mode=req.mode,
            top_k_per_facet=req.top_k_per_facet,
            ext_packs=req.ext_packs,
            use_cn_alias_bridge=req.use_cn_alias_bridge,
        )
        return proposal.model_dump()

    @app.post("/v1/bridge/attach/confirm")
    def api_attach_confirm(req: AttachConfirmRequest) -> Dict[str, Any]:
        try:
            res = confirm_attach(workspace, bridge_db, req)
            return res.model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/bridge/sessions")
    def api_bridge_sessions(
        limit: int = Query(50, ge=1, le=500),
        source_client: Optional[str] = Query(None),
    ) -> List[Dict[str, Any]]:
        return [s.model_dump() for s in bridge_db.list_sessions(limit=limit, source_client=source_client)]

    @app.get("/v1/bridge/activations")
    def api_bridge_activations(limit: int = Query(100, ge=1, le=1000)) -> List[Dict[str, Any]]:
        return [a.model_dump() for a in bridge_db.list_activations(limit=limit)]

    @app.get("/v1/bridge/collections")
    def api_bridge_collections(limit: int = Query(20, ge=1, le=100)) -> List[Dict[str, Any]]:
        return [c.model_dump() for c in compute_topic_collections(bridge_db, limit=limit)]

    @app.post("/v1/bridge/serendipity")
    def api_bridge_serendipity(req: SerendipityRequest) -> Dict[str, Any]:
        briefing = generate_serendipity_briefing(
            workspace,
            bridge_db,
            seed_node_ids=req.seed_node_ids,
            max_hops=req.max_hops,
            min_ic=req.min_ic,
            top_k=req.top_k,
            ext_packs=req.ext_packs,
            persist=req.persist,
        )
        return briefing.model_dump()

    @app.get("/v1/bridge/briefings")
    def api_bridge_briefings(limit: int = Query(10, ge=1, le=50)) -> List[Dict[str, Any]]:
        return bridge_db.list_briefings(limit=limit)

    @app.post("/v1/import/open-webui")
    def api_import_owui(req: OpenWebUIImportRequest) -> Dict[str, Any]:
        try:
            src = req.payload if req.payload is not None else req.export_path
            if src is None:
                raise ValueError("Provide either 'payload' or 'export_path'")
            res = import_open_webui_export(bridge_db, src, dry_run=req.dry_run)
            return res.model_dump()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/import/cherry-studio")
    def api_import_cherry(req: CherryStudioImportRequest) -> Dict[str, Any]:
        try:
            res = import_cherry_studio_backup(
                bridge_db,
                backup_path=req.backup_path,
                dry_run=req.dry_run,
                filter_secrets=req.filter_secrets,
            )
            return res.model_dump()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ---- Hosted WebGL 2D Knowledge World Map ----

    @app.get("/map", response_class=HTMLResponse)
    def serve_map_index() -> HTMLResponse:
        index_html = map_dir / "index.html"
        if index_html.is_file():
            return HTMLResponse(content=index_html.read_text(encoding="utf-8"))
        return HTMLResponse(content=_fallback_map_html())

    if map_dir.is_dir():
        app.mount("/map/assets", StaticFiles(directory=str(map_dir)), name="map_assets")

    return app
