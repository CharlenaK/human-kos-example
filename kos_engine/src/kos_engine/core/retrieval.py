"""Hybrid facet-isolated retrieval: FTS5 BM25 + int8 dequantized e5-small + z-score + RRF."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import numpy as np

from kos_engine.core.models import (
    ALL_FACETS,
    AeiDistribution,
    FacetCandidate,
    FacetType,
    RetrievalMode,
)
from kos_engine.core.text_utils import build_fts5_query, contains_cjk, extract_cjk_terms

if TYPE_CHECKING:
    from kos_engine.core.workspace import KosWorkspace

_RRF_K = 60.0


def _load_facet_embeddings(
    ws: "KosWorkspace", pack_id: str, schema: str, facet: FacetType
) -> Tuple[List[str], np.ndarray]:
    cache_key = (pack_id, facet)
    if cache_key in ws._vec_cache:
        return ws._vec_cache[cache_key]

    rows = ws._con.execute(
        f"""
        SELECT e.node_id, e.scale, e.vector_blob, e.dim
        FROM {schema}.kos_embeddings e
        JOIN {schema}.kos_facet_pool p ON p.node_id = e.node_id
        WHERE p.facet_type = ? AND p.is_active = 1
        """,
        (facet,),
    ).fetchall()

    if not rows:
        empty = ([], np.zeros((0, 384), dtype=np.float32))
        ws._vec_cache[cache_key] = empty
        return empty

    node_ids: List[str] = []
    dim = int(rows[0]["dim"])
    mat = np.empty((len(rows), dim), dtype=np.float32)
    for i, r in enumerate(rows):
        node_ids.append(str(r["node_id"]))
        q = np.frombuffer(r["vector_blob"], dtype=np.int8).astype(np.float32)
        vec = q * float(r["scale"])
        norm = float(np.linalg.norm(vec))
        if norm > 1e-12:
            vec = vec / norm
        mat[i] = vec

    result = (node_ids, mat)
    ws._vec_cache[cache_key] = result
    return result


def _bm25_search_schema(
    ws: "KosWorkspace",
    schema: str,
    pack_id: str,
    fts_query: str,
    facet: FacetType,
    limit: int,
) -> List[Tuple[str, float, Dict]]:
    if not fts_query:
        return []
    rows = ws._con.execute(
        f"""
        WITH fts_hits AS (
            SELECT node_id, bm25(kos_fts) AS bm25_raw
            FROM {schema}.kos_fts AS kos_fts
            WHERE kos_fts MATCH ?
            ORDER BY bm25(kos_fts) ASC
            LIMIT ?
        )
        SELECT n.node_id, n.facet_type, n.canonical_label_en, n.canonical_label_zh,
               n.label_zh_status, n.breadcrumb_path, n.definition_summary,
               n.info_content, n.map_x, n.map_y, n.min_zoom_tier,
               n.source_id, pr.license_spdx, pr.dist_tier,
               h.bm25_raw
        FROM fts_hits h
        JOIN {schema}.kos_facet_pool p ON p.node_id = h.node_id AND p.facet_type = ? AND p.is_active = 1
        JOIN {schema}.kos_nodes n ON n.node_id = p.node_id
        JOIN {schema}.kos_provenance pr ON pr.source_id = n.source_id
        ORDER BY h.bm25_raw ASC
        LIMIT ?
        """,
        (fts_query, limit + 10, facet, limit),
    ).fetchall()

    out: List[Tuple[str, float, Dict]] = []
    for r in rows:
        d = dict(r)
        d["pack_id"] = pack_id
        # SQLite bm25() returns negative scores where more negative = better match
        out.append((str(r["node_id"]), -float(r["bm25_raw"]), d))
    return out


def _cn_alias_expand(ws: "KosWorkspace", query_text: str, max_en: int = 8) -> List[str]:
    if "cn_rel" not in ws._attached or not contains_cjk(query_text):
        return []
    alias = ws._attached["cn_rel"].db_alias
    cjk_terms = extract_cjk_terms(query_text, max_terms=6)
    if not cjk_terms:
        return []
    fts_expr = " OR ".join(f'"{t}"' for t in cjk_terms)
    rows = ws._con.execute(
        f"""
        SELECT a.en_term
        FROM {alias}.cn_alias_fts AS cn_alias_fts
        JOIN {alias}.cn_alias a ON a.rowid = cn_alias_fts.rowid
        WHERE cn_alias_fts MATCH ?
        ORDER BY a.weight DESC
        LIMIT ?
        """,
        (fts_expr, max_en * 2),
    ).fetchall()
    en_terms: List[str] = []
    seen = set()
    for r in rows:
        en = str(r["en_term"]).strip()
        low = en.lower()
        if en and low not in seen:
            seen.add(low)
            en_terms.append(en)
        if len(en_terms) >= max_en:
            break
    return en_terms


def _fetch_node_rows(ws: "KosWorkspace", schema: str, pack_id: str, node_ids: Sequence[str], facet: FacetType) -> Dict[str, Dict]:
    if not node_ids:
        return {}
    placeholders = ",".join("?" for _ in node_ids)
    rows = ws._con.execute(
        f"""
        SELECT n.node_id, n.facet_type, n.canonical_label_en, n.canonical_label_zh,
               n.label_zh_status, n.breadcrumb_path, n.definition_summary,
               n.info_content, n.map_x, n.map_y, n.min_zoom_tier,
               n.source_id, pr.license_spdx, pr.dist_tier
        FROM {schema}.kos_facet_pool p
        JOIN {schema}.kos_nodes n ON n.node_id = p.node_id
        JOIN {schema}.kos_provenance pr ON pr.source_id = n.source_id
        WHERE p.facet_type = ? AND p.is_active = 1 AND n.node_id IN ({placeholders})
        """,
        (facet, *node_ids),
    ).fetchall()
    out: Dict[str, Dict] = {}
    for r in rows:
        d = dict(r)
        d["pack_id"] = pack_id
        out[str(r["node_id"])] = d
    return out


def search_facet(
    ws: "KosWorkspace",
    query_text: str,
    facet: FacetType,
    *,
    mode: RetrievalMode = "hybrid",
    top_k: int = 20,
    ext_packs: Optional[Sequence[str]] = None,
    use_cn_alias_bridge: bool = False,
    zscore_normalize: bool = True,
) -> List[FacetCandidate]:
    """Search within a SINGLE isolated facet (DOMAIN/ACTIVITY/PROCESS/ARTIFACT/STANCE)."""
    if facet not in ALL_FACETS:
        raise ValueError(f"Invalid facet_type '{facet}'; must be one of {ALL_FACETS}")
    top_k = max(1, min(int(top_k), 200))
    pool_limit = top_k if mode == "bm25" else max(top_k * 3, 60)

    with ws._lock:
        target_packs: List[Tuple[str, str]] = [("core", "main")]
        requested = list(ext_packs) if ext_packs is not None else list(ws._attached.keys())
        for pid in requested:
            if pid == "core":
                continue
            info = ws.attach_extension(pid)
            if info.pack_kind == "standard":
                target_packs.append((pid, info.db_alias))

        if use_cn_alias_bridge and "cn_rel" not in ws._attached and ws.ext_dir and (ws.ext_dir / "cn_rel.sqlite").is_file():
            ws.attach_extension("cn_rel")

        bm25_ranks: Dict[str, int] = {}
        bm25_scores: Dict[str, float] = {}
        vec_ranks: Dict[str, int] = {}
        cos_scores: Dict[str, float] = {}
        z_scores: Dict[str, float] = {}
        matched_via: Dict[str, List[str]] = {}
        node_meta: Dict[str, Dict] = {}

        # 1. BM25 lexical recall
        if mode in ("bm25", "hybrid"):
            fts_query = build_fts5_query(query_text, facet_type=facet)
            bm25_hits: List[Tuple[str, float, Dict, str]] = []
            for pid, sch in target_packs:
                for nid, score, meta in _bm25_search_schema(ws, sch, pid, fts_query, facet, pool_limit):
                    bm25_hits.append((nid, score, meta, "bm25"))

            if use_cn_alias_bridge and "cn_rel" in ws._attached:
                en_terms = _cn_alias_expand(ws, query_text)
                if en_terms:
                    bridge_query = build_fts5_query(" ".join(en_terms), facet_type=facet)
                    for pid, sch in target_packs:
                        for nid, score, meta in _bm25_search_schema(ws, sch, pid, bridge_query, facet, top_k):
                            bm25_hits.append((nid, score * 0.85, meta, "cn_alias_bridge"))

            bm25_hits.sort(key=lambda x: x[1], reverse=True)
            rank_idx = 0
            for nid, score, meta, tag in bm25_hits:
                node_meta.setdefault(nid, meta)
                matched_via.setdefault(nid, [])
                if tag not in matched_via[nid]:
                    matched_via[nid].append(tag)
                if nid not in bm25_scores:
                    rank_idx += 1
                    bm25_ranks[nid] = rank_idx
                    bm25_scores[nid] = score
                elif score > bm25_scores[nid]:
                    bm25_scores[nid] = score

        # 2. Vector recall (int8 dequantization + per-facet z-score; graceful fallback if unavailable)
        if mode in ("vector", "hybrid"):
            q_vec = ws.encoder.encode_query(query_text)
            if q_vec is not None:
                all_vec_hits: List[Tuple[str, float, str, str]] = []
                for pid, sch in target_packs:
                    if pid != "core" and not ws._attached[pid].has_embeddings:
                        # Zero-embedding large packs (lcsh/dila/aat/glottolog/periodo) degrade gracefully
                        continue
                    nids, mat = _load_facet_embeddings(ws, pid, sch, facet)
                    if len(nids) == 0:
                        continue
                    sims = mat @ q_vec
                    # Take top pool_limit in this pack
                    k_take = min(pool_limit, len(nids))
                    if k_take < len(nids):
                        top_idx = np.argpartition(-sims, k_take)[:k_take]
                        top_idx = top_idx[np.argsort(-sims[top_idx])]
                    else:
                        top_idx = np.argsort(-sims)
                    # Compute facet-wide z-score stats across the full facet matrix
                    mean_s = float(np.mean(sims))
                    std_s = float(np.std(sims))
                    for idx in top_idx:
                        nid = nids[int(idx)]
                        cs = float(sims[int(idx)])
                        zs = (cs - mean_s) / std_s if (zscore_normalize and std_s > 1e-9) else 0.0
                        all_vec_hits.append((nid, cs, pid, sch))
                        if nid not in cos_scores or cs > cos_scores[nid]:
                            cos_scores[nid] = cs
                            z_scores[nid] = zs

                all_vec_hits.sort(key=lambda x: x[1], reverse=True)
                needed_by_pack: Dict[Tuple[str, str], List[str]] = {}
                rank_idx = 0
                for nid, cs, pid, sch in all_vec_hits:
                    if nid in vec_ranks:
                        continue
                    rank_idx += 1
                    vec_ranks[nid] = rank_idx
                    matched_via.setdefault(nid, [])
                    if "vector" not in matched_via[nid]:
                        matched_via[nid].append("vector")
                    if nid not in node_meta:
                        needed_by_pack.setdefault((pid, sch), []).append(nid)
                    if rank_idx >= pool_limit:
                        break

                for (pid, sch), nids in needed_by_pack.items():
                    node_meta.update(_fetch_node_rows(ws, sch, pid, nids, facet))
            elif mode == "vector":
                # Pure vector requested but encoder unavailable -> graceful FTS5 fallback
                fts_query = build_fts5_query(query_text, facet_type=facet)
                for pid, sch in target_packs:
                    for rank_idx, (nid, score, meta) in enumerate(
                        _bm25_search_schema(ws, sch, pid, fts_query, facet, top_k), start=1
                    ):
                        node_meta.setdefault(nid, meta)
                        bm25_ranks[nid] = rank_idx
                        bm25_scores[nid] = score
                        matched_via.setdefault(nid, []).append("bm25_fallback")

        # 3. Reciprocal Rank Fusion + z-score bonus
        candidates: List[FacetCandidate] = []
        for nid, meta in node_meta.items():
            # Hard invariant: never leak another facet
            if meta["facet_type"] != facet:
                continue
            rrf = 0.0
            if nid in bm25_ranks:
                rrf += 1.0 / (_RRF_K + bm25_ranks[nid])
            if nid in vec_ranks:
                rrf += 1.0 / (_RRF_K + vec_ranks[nid])
            zs = z_scores.get(nid)
            if zs is not None and zscore_normalize:
                rrf += max(0.0, min(zs, 5.0)) * 0.002

            candidates.append(
                FacetCandidate(
                    node_id=nid,
                    facet_type=meta["facet_type"],
                    canonical_label_en=meta.get("canonical_label_en"),
                    canonical_label_zh=meta.get("canonical_label_zh"),
                    label_zh_status=meta.get("label_zh_status", "missing"),
                    breadcrumb_path=meta["breadcrumb_path"],
                    definition_summary=meta.get("definition_summary"),
                    info_content=float(meta.get("info_content", 1.0)),
                    map_x=float(meta.get("map_x", 0.0)),
                    map_y=float(meta.get("map_y", 0.0)),
                    min_zoom_tier=int(meta.get("min_zoom_tier", 2)),
                    source_id=meta["source_id"],
                    license_spdx=meta["license_spdx"],
                    dist_tier=meta["dist_tier"],
                    pack_id=meta.get("pack_id", "core"),
                    bm25_score=bm25_scores.get(nid),
                    cosine_score=cos_scores.get(nid),
                    z_score=zs,
                    fused_score=round(rrf, 6),
                    matched_via=matched_via.get(nid, []),
                )
            )

        candidates.sort(key=lambda c: (c.fused_score, c.z_score or -99.0, c.bm25_score or -99.0), reverse=True)
        return candidates[:top_k]


def search_all_facets(
    ws: "KosWorkspace",
    query_text: str,
    facets: Sequence[FacetType] = ALL_FACETS,
    *,
    mode: RetrievalMode = "hybrid",
    top_k: int = 10,
    ext_packs: Optional[Sequence[str]] = None,
    use_cn_alias_bridge: bool = False,
    zscore_normalize: bool = True,
) -> Dict[FacetType, List[FacetCandidate]]:
    """Run physically isolated retrieval independently per facet (zero cross-facet mixing)."""
    result: Dict[FacetType, List[FacetCandidate]] = {}
    for facet in facets:
        result[facet] = search_facet(
            ws,
            query_text=query_text,
            facet=facet,
            mode=mode,
            top_k=top_k,
            ext_packs=ext_packs,
            use_cn_alias_bridge=use_cn_alias_bridge,
            zscore_normalize=zscore_normalize,
        )
    return result


def get_aei_calibration(ws: "KosWorkspace", axis_type: str, axis_key: str) -> Optional[AeiDistribution]:
    with ws._lock:
        row = ws._con.execute(
            """
            SELECT axis_type, axis_key, axis_label, geography, release_version,
                   directive_pct, feedback_loop_pct, task_iteration_pct,
                   learning_pct, validation_pct, none_pct, total_pct, source_id
            FROM kos_aei_calibration
            WHERE axis_type = ? AND axis_key = ?
            LIMIT 1
            """,
            (axis_type, axis_key),
        ).fetchone()
        if row is None:
            return None
        return AeiDistribution(**dict(row))


def list_aei_calibration(ws: "KosWorkspace", axis_type: str = "onet_task", limit: int = 20) -> List[AeiDistribution]:
    limit = max(1, min(int(limit), 200))
    with ws._lock:
        rows = ws._con.execute(
            """
            SELECT axis_type, axis_key, axis_label, geography, release_version,
                   directive_pct, feedback_loop_pct, task_iteration_pct,
                   learning_pct, validation_pct, none_pct, total_pct, source_id
            FROM kos_aei_calibration
            WHERE axis_type = ?
            ORDER BY task_iteration_pct DESC
            LIMIT ?
            """,
            (axis_type, limit),
        ).fetchall()
        return [AeiDistribution(**dict(r)) for r in rows]
