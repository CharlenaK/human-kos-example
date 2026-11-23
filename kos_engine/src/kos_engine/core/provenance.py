"""Provenance and SPDX / ShareAlike / local_only license boundary guard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from kos_engine.core.models import LicenseBoundaryReport, ProvenanceInfo

if TYPE_CHECKING:
    from kos_engine.core.workspace import KosWorkspace


def inspect_license_boundary(
    ws: "KosWorkspace",
    *,
    node_ids: Optional[Sequence[str]] = None,
    pack_ids: Optional[Sequence[str]] = None,
) -> LicenseBoundaryReport:
    """Audit provenance and detect ShareAlike (`dist_ext_sa`) or `local_only` exposure."""
    with ws._lock:
        sources_by_key: Dict[Tuple[str, str], ProvenanceInfo] = {}
        checked_packs: List[str] = []
        node_set = list(dict.fromkeys(node_ids or []))

        target_packs: List[Tuple[str, str]] = [("core", "main")]
        for pid in pack_ids or []:
            if pid == "core":
                continue
            info = ws.attach_extension(pid)
            target_packs.append((pid, info.db_alias))
        if not pack_ids:
            for pid, info in ws._attached.items():
                target_packs.append((pid, info.db_alias))

        seen_pack_ids = set()
        dedup_packs: List[Tuple[str, str]] = []
        for pid, sch in target_packs:
            if pid not in seen_pack_ids:
                seen_pack_ids.add(pid)
                dedup_packs.append((pid, sch))

        # 1. Inspect provenance for explicitly requested node_ids
        if node_set:
            placeholders = ",".join("?" for _ in node_set)
            for pid, sch in dedup_packs:
                if pid != "core" and ws._attached[pid].pack_kind != "standard":
                    continue
                rows = ws._con.execute(
                    f"""
                    SELECT DISTINCT pr.source_id, pr.source_name, pr.version,
                                    pr.license_spdx, pr.dist_tier, pr.attribution_text,
                                    pr.homepage_url, pr.notes
                    FROM {sch}.kos_nodes n
                    JOIN {sch}.kos_provenance pr ON pr.source_id = n.source_id
                    WHERE n.node_id IN ({placeholders})
                    """,
                    node_set,
                ).fetchall()
                for r in rows:
                    sources_by_key[(pid, str(r["source_id"]))] = ProvenanceInfo(**dict(r), pack_id=pid)

        # 2. Inspect provenance for explicitly named packs (including cn_rel)
        if pack_ids:
            for pid in pack_ids:
                sch = "main" if pid == "core" else ws.attach_extension(pid).db_alias
                checked_packs.append(pid)
                if node_set and pid == "core":
                    continue
                rows = ws._con.execute(
                    f"""
                    SELECT source_id, source_name, version, license_spdx, dist_tier,
                           attribution_text, homepage_url, notes
                    FROM {sch}.kos_provenance
                    """
                ).fetchall()
                for r in rows:
                    sources_by_key[(pid, str(r["source_id"]))] = ProvenanceInfo(**dict(r), pack_id=pid)
        else:
            checked_packs = [pid for pid, _ in dedup_packs]

        sources = sorted(sources_by_key.values(), key=lambda s: (s.dist_tier, s.pack_id, s.source_id))
        sa_triggered = any(
            s.dist_tier == "dist_ext_sa" or "SA" in s.license_spdx.upper() for s in sources
        )
        local_triggered = any(s.dist_tier == "local_only" for s in sources)

        notices: List[str] = []
        seen_notices = set()
        for s in sources:
            line = f"[{s.source_id} | {s.license_spdx} | {s.dist_tier}] {s.attribution_text}"
            if line not in seen_notices:
                seen_notices.add(line)
                notices.append(line)

        if local_triggered:
            summary = "触发 local_only 边界：结果包含仅限本机使用的受限源，不应直接对外导出或分发。"
        elif sa_triggered:
            summary = "触发 ShareAlike 边界（dist_ext_sa）：对外导出衍生结果时应保留 CC BY-SA 署名与相同方式共享声明。"
        else:
            summary = "合规许可边界（dist_core / dist_ext_permissive）：保留标准来源署名即可安全使用。"

        return LicenseBoundaryReport(
            checked_node_count=len(node_set),
            checked_packs=checked_packs,
            sources=sources,
            share_alike_triggered=sa_triggered,
            local_only_triggered=local_triggered,
            required_notices=notices,
            summary=summary,
        )
