"""2D Knowledge World Map spatial viewport (R*Tree + 4-tier LoD) and Voronoi partitions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

from kos_engine.core.models import (
    ALL_FACETS,
    FacetType,
    MapPartitionGeoJSON,
    ViewportEdge,
    ViewportNode,
    ViewportResponse,
)

if TYPE_CHECKING:
    from kos_engine.core.workspace import KosWorkspace

MAX_VIEWPORT_LIMIT = 5000


def query_viewport(
    ws: "KosWorkspace",
    bbox: Tuple[float, float, float, float],
    zoom_tier: int = 1,
    *,
    facets: Optional[Sequence[FacetType]] = None,
    limit: int = 2000,
    include_edges: bool = True,
) -> ViewportResponse:
    """Query frozen UMAP 2D coordinates via SQLite R*Tree (`kos_spatial`) + 4-level LoD."""
    min_x, min_y, max_x, max_y = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    if min_x > max_x:
        min_x, max_x = max_x, min_x
    if min_y > max_y:
        min_y, max_y = max_y, min_y
    zoom_tier = max(0, min(int(zoom_tier), 3))
    effective_limit = max(1, min(int(limit), MAX_VIEWPORT_LIMIT))

    facet_list = [f for f in (facets or ALL_FACETS) if f in ALL_FACETS]
    if not facet_list:
        facet_list = list(ALL_FACETS)
    facet_ph = ",".join("?" for _ in facet_list)

    with ws._lock:
        rows = ws._con.execute(
            f"""
            SELECT n.node_id, n.spatial_id, n.facet_type,
                   n.canonical_label_en, n.canonical_label_zh,
                   n.breadcrumb_path, n.info_content,
                   n.map_x, n.map_y, n.domain_partition_id, n.min_zoom_tier,
                   n.source_id, pr.license_spdx, pr.dist_tier
            FROM kos_spatial s
            JOIN kos_nodes n ON n.spatial_id = s.id
            JOIN kos_provenance pr ON pr.source_id = n.source_id
            WHERE s.max_x >= ? AND s.min_x <= ?
              AND s.max_y >= ? AND s.min_y <= ?
              AND n.min_zoom_tier <= ?
              AND n.facet_type IN ({facet_ph})
            ORDER BY n.min_zoom_tier ASC, n.info_content DESC
            LIMIT ?
            """,
            (min_x, max_x, min_y, max_y, zoom_tier, *facet_list, effective_limit + 1),
        ).fetchall()

        truncated = len(rows) > effective_limit
        rows = rows[:effective_limit]
        nodes = [ViewportNode(**dict(r)) for r in rows]

        edges: List[ViewportEdge] = []
        if include_edges and len(nodes) >= 2:
            # Fetch a bounded set of intra-viewport edges (prioritize bridge & parent edges)
            node_ids = [n.node_id for n in nodes[:1500]]
            ph = ",".join("?" for _ in node_ids)
            edge_rows = ws._con.execute(
                f"""
                SELECT source_id, target_id, relation_type, weight, polarity
                FROM kos_edges
                WHERE polarity = 1
                  AND source_id IN ({ph})
                  AND target_id IN ({ph})
                ORDER BY CASE relation_type
                    WHEN 'oa:cooccur' THEN 0
                    WHEN 'skos:closeMatch' THEN 1
                    WHEN 'skos:related' THEN 2
                    ELSE 3
                END, weight DESC
                LIMIT 3000
                """,
                (*node_ids, *node_ids),
            ).fetchall()
            edges = [ViewportEdge(**dict(er)) for er in edge_rows]

        return ViewportResponse(
            bbox=(min_x, min_y, max_x, max_y),
            zoom_tier=zoom_tier,
            total_returned=len(nodes),
            truncated=truncated,
            nodes=nodes,
            edges=edges,
        )


def get_map_partitions(ws: "KosWorkspace", facet: Optional[FacetType] = None) -> List[MapPartitionGeoJSON]:
    """Return frozen Voronoi partition GeoJSON polygons from `kos_map_partitions`."""
    with ws._lock:
        if facet is not None:
            if facet not in ALL_FACETS:
                raise ValueError(f"Invalid facet '{facet}'")
            rows = ws._con.execute(
                """
                SELECT partition_id, facet_type, label_en, label_zh, layout_version,
                       centroid_x, centroid_y, min_x, max_x, min_y, max_y,
                       polygon_geojson, node_count
                FROM kos_map_partitions
                WHERE facet_type = ?
                ORDER BY node_count DESC
                """,
                (facet,),
            ).fetchall()
        else:
            rows = ws._con.execute(
                """
                SELECT partition_id, facet_type, label_en, label_zh, layout_version,
                       centroid_x, centroid_y, min_x, max_x, min_y, max_y,
                       polygon_geojson, node_count
                FROM kos_map_partitions
                ORDER BY facet_type, node_count DESC
                """
            ).fetchall()

        out: List[MapPartitionGeoJSON] = []
        for r in rows:
            parsed = json.loads(r["polygon_geojson"])
            if isinstance(parsed, dict) and "type" in parsed:
                geom = parsed
            elif isinstance(parsed, list):
                # L1 stores closed ring [[x, y], ...]; normalize to standard GeoJSON Polygon
                ring = parsed
                if ring and isinstance(ring[0], list) and ring[0] and isinstance(ring[0][0], (int, float)):
                    geom = {"type": "Polygon", "coordinates": [ring]}
                else:
                    geom = {"type": "Polygon", "coordinates": ring}
            else:
                geom = {"type": "Polygon", "coordinates": []}
            out.append(
                MapPartitionGeoJSON(
                    partition_id=str(r["partition_id"]),
                    facet_type=r["facet_type"],
                    label_en=str(r["label_en"]),
                    label_zh=r["label_zh"],
                    layout_version=str(r["layout_version"]),
                    centroid_x=float(r["centroid_x"]),
                    centroid_y=float(r["centroid_y"]),
                    min_x=float(r["min_x"]),
                    max_x=float(r["max_x"]),
                    min_y=float(r["min_y"]),
                    max_y=float(r["max_y"]),
                    node_count=int(r["node_count"]),
                    geometry=geom,
                )
            )
        return out
