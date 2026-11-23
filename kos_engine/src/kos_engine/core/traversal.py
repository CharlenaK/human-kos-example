"""Adjacency and multi-hop graph traversal with negative-edge guard, IC floor, and cross-pack bridging."""

from __future__ import annotations

import collections
import json
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Set, Tuple

from kos_engine.core.models import (
    DEFAULT_TRAVERSAL_RELATIONS,
    BreadcrumbNode,
    NeighborEdge,
    TraversalDirection,
    TraversalEdge,
    TraversalNode,
    TraversalSubgraph,
)

if TYPE_CHECKING:
    from kos_engine.core.workspace import KosWorkspace

_CN_REL_PREFIX = "cn:"


def _top_field_key(breadcrumb_path: Optional[str]) -> str:
    if not breadcrumb_path:
        return ""
    parts = [p.strip() for p in breadcrumb_path.split(">") if p.strip()]
    if len(parts) >= 2:
        return f"{parts[0]} > {parts[1]}"
    return parts[0] if parts else ""


def _parse_evidence(raw: Optional[str]) -> Optional[Dict]:
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {"raw": obj}
    except Exception:
        return {"raw": raw}


def get_neighbors(
    ws: "KosWorkspace",
    node_id: str,
    *,
    relations: Optional[Sequence[str]] = None,
    direction: TraversalDirection = "both",
    polarity: int | str = 1,
    min_weight: float = 0.0,
    min_ic: float = 1.5,
    exclude_roots: bool = True,
    limit: int = 50,
) -> List[NeighborEdge]:
    """Retrieve 1-hop neighbors across core + attached extensions with negative-edge & IC guards."""
    rel_list = list(relations) if relations else list(DEFAULT_TRAVERSAL_RELATIONS)
    if polarity in (-1, "all") and relations is None and "icf:excludes" not in rel_list:
        rel_list.append("icf:excludes")
    limit = max(1, min(int(limit), 500))

    with ws._lock:
        schemas: List[Tuple[str, str]] = [("core", "main")] + [
            (pid, info.db_alias) for pid, info in ws._attached.items() if info.pack_kind == "standard"
        ]
        results: List[NeighborEdge] = []
        seen_keys: Set[Tuple[str, str, str, str]] = set()

        rel_placeholders = ",".join("?" for _ in rel_list)
        pol_clause = "" if polarity == "all" else "AND e.polarity = ?"
        root_clause = "AND n2.is_root = 0" if exclude_roots else ""

        for pid, sch in schemas:
            if direction in ("out", "both"):
                params: List = [node_id, *rel_list]
                if polarity != "all":
                    params.append(int(polarity))
                params.extend([float(min_weight), float(min_ic), limit])
                rows = ws._con.execute(
                    f"""
                    SELECT e.source_id, e.target_id, e.relation_type, e.weight, e.polarity,
                           e.provenance_source_id, e.evidence_json,
                           n2.canonical_label_en, n2.canonical_label_zh, n2.facet_type,
                           n2.breadcrumb_path, n2.info_content, n2.is_root,
                           pr.license_spdx, pr.dist_tier
                    FROM {sch}.kos_edges e
                    JOIN {sch}.kos_nodes n2 ON n2.node_id = e.target_id
                    JOIN {sch}.kos_provenance pr ON pr.source_id = e.provenance_source_id
                    WHERE e.source_id = ?
                      AND e.relation_type IN ({rel_placeholders})
                      {pol_clause}
                      AND e.weight >= ?
                      AND n2.info_content >= ?
                      {root_clause}
                    ORDER BY e.weight DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
                for r in rows:
                    k = (str(r["source_id"]), str(r["target_id"]), str(r["relation_type"]), pid)
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)
                    results.append(
                        NeighborEdge(
                            source_id=str(r["source_id"]),
                            target_id=str(r["target_id"]),
                            neighbor_id=str(r["target_id"]),
                            direction="out",
                            relation_type=str(r["relation_type"]),
                            weight=float(r["weight"]),
                            polarity=int(r["polarity"]),
                            provenance_source_id=str(r["provenance_source_id"]),
                            pack_id=pid,
                            neighbor_label_en=r["canonical_label_en"],
                            neighbor_label_zh=r["canonical_label_zh"],
                            neighbor_facet_type=r["facet_type"],
                            neighbor_breadcrumb=r["breadcrumb_path"],
                            neighbor_info_content=float(r["info_content"]),
                            neighbor_is_root=bool(r["is_root"]),
                            license_spdx=str(r["license_spdx"]),
                            dist_tier=str(r["dist_tier"]),
                            evidence=_parse_evidence(r["evidence_json"]),
                        )
                    )

            if direction in ("in", "both"):
                params = [node_id, *rel_list]
                if polarity != "all":
                    params.append(int(polarity))
                params.extend([float(min_weight), float(min_ic), limit])
                rows = ws._con.execute(
                    f"""
                    SELECT e.source_id, e.target_id, e.relation_type, e.weight, e.polarity,
                           e.provenance_source_id, e.evidence_json,
                           n2.canonical_label_en, n2.canonical_label_zh, n2.facet_type,
                           n2.breadcrumb_path, n2.info_content, n2.is_root,
                           pr.license_spdx, pr.dist_tier
                    FROM {sch}.kos_edges e
                    JOIN {sch}.kos_nodes n2 ON n2.node_id = e.source_id
                    JOIN {sch}.kos_provenance pr ON pr.source_id = e.provenance_source_id
                    WHERE e.target_id = ?
                      AND e.relation_type IN ({rel_placeholders})
                      {pol_clause}
                      AND e.weight >= ?
                      AND n2.info_content >= ?
                      {root_clause}
                    ORDER BY e.weight DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
                for r in rows:
                    k = (str(r["source_id"]), str(r["target_id"]), str(r["relation_type"]), pid)
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)
                    results.append(
                        NeighborEdge(
                            source_id=str(r["source_id"]),
                            target_id=str(r["target_id"]),
                            neighbor_id=str(r["source_id"]),
                            direction="in",
                            relation_type=str(r["relation_type"]),
                            weight=float(r["weight"]),
                            polarity=int(r["polarity"]),
                            provenance_source_id=str(r["provenance_source_id"]),
                            pack_id=pid,
                            neighbor_label_en=r["canonical_label_en"],
                            neighbor_label_zh=r["canonical_label_zh"],
                            neighbor_facet_type=r["facet_type"],
                            neighbor_breadcrumb=r["breadcrumb_path"],
                            neighbor_info_content=float(r["info_content"]),
                            neighbor_is_root=bool(r["is_root"]),
                            license_spdx=str(r["license_spdx"]),
                            dist_tier=str(r["dist_tier"]),
                            evidence=_parse_evidence(r["evidence_json"]),
                        )
                    )

        # Cross-pack bridge into ConceptNet cn_rel.cn_relations when attached
        cn_rels = [r[len(_CN_REL_PREFIX) :] for r in rel_list if r.startswith(_CN_REL_PREFIX)]
        if cn_rels and "cn_rel" in ws._attached and polarity in (1, "all"):
            seed_node = ws.get_node(node_id)
            if seed_node and seed_node.get("canonical_label_en"):
                label_norm = str(seed_node["canonical_label_en"]).strip().lower()
                alias = ws._attached["cn_rel"].db_alias
                cn_ph = ",".join("?" for _ in cn_rels)
                cn_rows = ws._con.execute(
                    f"""
                    SELECT r.relation_type, r.start_term, r.end_term, r.weight, r.source_id,
                           pr.license_spdx, pr.dist_tier
                    FROM {alias}.cn_relations r
                    JOIN {alias}.kos_provenance pr ON pr.source_id = r.source_id
                    WHERE lower(r.start_term) = ? AND r.relation_type IN ({cn_ph})
                    ORDER BY r.weight DESC
                    LIMIT 15
                    """,
                    (label_norm, *cn_rels),
                ).fetchall()
                for cr in cn_rows:
                    end_term = str(cr["end_term"]).strip().lower()
                    matched = ws._con.execute(
                        """
                        SELECT n.node_id, n.canonical_label_en, n.canonical_label_zh, n.facet_type,
                               n.breadcrumb_path, n.info_content, n.is_root
                        FROM kos_nodes n
                        WHERE lower(n.canonical_label_en) = ? AND n.info_content >= ?
                        LIMIT 1
                        """,
                        (end_term, float(min_ic)),
                    ).fetchone()
                    if matched is None or (exclude_roots and bool(matched["is_root"])):
                        continue
                    rel_full = f"cn:{cr['relation_type']}"
                    k = (node_id, str(matched["node_id"]), rel_full, "cn_rel")
                    if k in seen_keys:
                        continue
                    seen_keys.add(k)
                    results.append(
                        NeighborEdge(
                            source_id=node_id,
                            target_id=str(matched["node_id"]),
                            neighbor_id=str(matched["node_id"]),
                            direction="out",
                            relation_type=rel_full,
                            weight=float(cr["weight"]),
                            polarity=1,
                            provenance_source_id=str(cr["source_id"]),
                            pack_id="cn_rel",
                            neighbor_label_en=matched["canonical_label_en"],
                            neighbor_label_zh=matched["canonical_label_zh"],
                            neighbor_facet_type=matched["facet_type"],
                            neighbor_breadcrumb=matched["breadcrumb_path"],
                            neighbor_info_content=float(matched["info_content"]),
                            neighbor_is_root=bool(matched["is_root"]),
                            license_spdx=str(cr["license_spdx"]),
                            dist_tier=str(cr["dist_tier"]),
                            evidence={"bridge": "cn_relations", "start_term": cr["start_term"], "end_term": cr["end_term"]},
                        )
                    )

        results.sort(key=lambda e: e.weight, reverse=True)
        return results[:limit]


def traverse_multi_hop(
    ws: "KosWorkspace",
    seed_node_ids: Sequence[str],
    *,
    max_hops: int = 2,
    relations: Optional[Sequence[str]] = None,
    include_negative: bool = False,
    min_ic: float = 1.5,
    exclude_roots: bool = True,
    max_nodes: int = 80,
    cross_field_only: bool = False,
    ext_packs: Optional[Sequence[str]] = None,
) -> TraversalSubgraph:
    """Bounded BFS multi-hop edge traversal with IC floor, root exclusion, and negative-edge guard."""
    max_hops = max(1, min(int(max_hops), 4))
    max_nodes = max(5, min(int(max_nodes), 500))
    polarity: int | str = "all" if include_negative else 1

    with ws._lock:
        if ext_packs:
            for pid in ext_packs:
                if pid != "core":
                    ws.attach_extension(pid)

        visited_nodes: Dict[str, TraversalNode] = {}
        seed_fields: Set[str] = set()
        queue: collections.deque[Tuple[str, int]] = collections.deque()

        for sid in seed_node_ids:
            info = ws.get_node(sid)
            if info is None:
                continue
            seed_fields.add(_top_field_key(info.get("breadcrumb_path")))
            visited_nodes[sid] = TraversalNode(
                node_id=sid,
                facet_type=info["facet_type"],
                canonical_label_en=info.get("canonical_label_en"),
                canonical_label_zh=info.get("canonical_label_zh"),
                breadcrumb_path=info.get("breadcrumb_path", ""),
                info_content=float(info.get("info_content", 1.0)),
                is_root=bool(info.get("is_root", 0)),
                hop=0,
                map_x=float(info.get("map_x", 0.0)),
                map_y=float(info.get("map_y", 0.0)),
                source_id=str(info.get("source_id", "")),
                license_spdx=str(info.get("license_spdx", "")),
                dist_tier=str(info.get("dist_tier", "dist_core")),
                pack_id=str(info.get("pack_id", "core")),
            )
            queue.append((sid, 0))

        edges_out: List[TraversalEdge] = []
        seen_edges: Set[Tuple[str, str, str, str]] = set()
        touched_packs: Set[str] = {n.pack_id for n in visited_nodes.values()}

        while queue and len(visited_nodes) < max_nodes:
            curr_id, hop = queue.popleft()
            if hop >= max_hops:
                continue

            nbrs = get_neighbors(
                ws,
                curr_id,
                relations=relations,
                direction="both",
                polarity=polarity,
                min_ic=min_ic,
                exclude_roots=exclude_roots,
                limit=30,
            )
            for edge in nbrs:
                nid = edge.neighbor_id
                if cross_field_only and hop + 1 == max_hops:
                    nbr_field = _top_field_key(edge.neighbor_breadcrumb)
                    if nbr_field and nbr_field in seed_fields:
                        continue

                ek = (edge.source_id, edge.target_id, edge.relation_type, edge.pack_id)
                if ek not in seen_edges:
                    seen_edges.add(ek)
                    touched_packs.add(edge.pack_id)
                    edges_out.append(
                        TraversalEdge(
                            source_id=edge.source_id,
                            target_id=edge.target_id,
                            relation_type=edge.relation_type,
                            weight=edge.weight,
                            polarity=edge.polarity,
                            hop=hop + 1,
                            provenance_source_id=edge.provenance_source_id,
                            pack_id=edge.pack_id,
                            license_spdx=edge.license_spdx,
                            dist_tier=edge.dist_tier,
                        )
                    )

                if nid not in visited_nodes:
                    if len(visited_nodes) >= max_nodes:
                        break
                    full = ws.get_node(nid)
                    visited_nodes[nid] = TraversalNode(
                        node_id=nid,
                        facet_type=edge.neighbor_facet_type,
                        canonical_label_en=edge.neighbor_label_en,
                        canonical_label_zh=edge.neighbor_label_zh,
                        breadcrumb_path=edge.neighbor_breadcrumb or "",
                        info_content=edge.neighbor_info_content,
                        is_root=edge.neighbor_is_root,
                        hop=hop + 1,
                        map_x=float(full["map_x"]) if full else 0.0,
                        map_y=float(full["map_y"]) if full else 0.0,
                        source_id=str(full["source_id"]) if full else edge.provenance_source_id,
                        license_spdx=str(full["license_spdx"]) if full else edge.license_spdx,
                        dist_tier=str(full["dist_tier"]) if full else edge.dist_tier,
                        pack_id=str(full["pack_id"]) if full else edge.pack_id,
                    )
                    queue.append((nid, hop + 1))

        boundary = ws.inspect_license_boundary(
            node_ids=list(visited_nodes.keys()),
            pack_ids=sorted(touched_packs),
        )
        return TraversalSubgraph(
            seed_node_ids=list(seed_node_ids),
            max_hops=max_hops,
            include_negative=include_negative,
            min_info_content=min_ic,
            exclude_roots=exclude_roots,
            nodes=sorted(visited_nodes.values(), key=lambda n: (n.hop, -n.info_content)),
            edges=edges_out,
            license_boundary=boundary,
        )


def get_ancestry(ws: "KosWorkspace", node_id: str) -> List[BreadcrumbNode]:
    """Return taxonomic ancestry chain from root down to `node_id`."""
    chain: List[BreadcrumbNode] = []
    seen: Set[str] = set()
    curr_id: Optional[str] = node_id
    with ws._lock:
        while curr_id and curr_id not in seen and len(chain) < 32:
            seen.add(curr_id)
            row = ws.get_node(curr_id)
            if row is None:
                break
            chain.append(
                BreadcrumbNode(
                    node_id=str(row["node_id"]),
                    facet_type=row["facet_type"],
                    canonical_label_en=row.get("canonical_label_en"),
                    canonical_label_zh=row.get("canonical_label_zh"),
                    depth=int(row.get("depth", 0)),
                    is_root=bool(row.get("is_root", 0)),
                    info_content=float(row.get("info_content", 1.0)),
                    source_id=str(row["source_id"]),
                )
            )
            curr_id = row.get("parent_id")
    chain.reverse()
    return chain
