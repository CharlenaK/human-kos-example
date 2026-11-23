"""Deterministic L3 Controlled Serendipity Briefing & Dynamic Named Topic Collections.

Zero paid external LLM API dependency (G-P3-04 = A): computes evidence-backed
cross-domain topological suggestions using L2 multi-hop traversal (`oa:cooccur`,
`skos:related`, `skos:closeMatch`) + IC floor + UCB novelty + reactivation decay,
emitting structured JSON + Markdown ready for human reading or Open WebUI Automation.
"""

from __future__ import annotations

import collections
import math
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set

from kos_engine.bridge.db import PersonalBridgeDB, _utcnow_iso
from kos_engine.bridge.models import (
    SerendipityBriefing,
    SerendipityEvidencePath,
    SerendipityItem,
    TopicCollection,
)
from kos_engine.core.workspace import KosWorkspace


def compute_topic_collections(bridge_db: PersonalBridgeDB, limit: int = 20) -> List[TopicCollection]:
    """Dynamically aggregate sessions into Named Topic Collections by shared KOS anchor nodes."""
    sessions = bridge_db.list_sessions(limit=500)
    activations = {a.node_id: a for a in bridge_db.list_activations(limit=1000)}

    by_anchor: Dict[str, List] = collections.defaultdict(list)
    anchor_meta: Dict[str, tuple] = {}
    for sess in sessions:
        for m in sess.mappings:
            if m.facet_type in ("DOMAIN", "PROCESS", "ARTIFACT"):
                by_anchor[m.node_id].append(sess)
                anchor_meta[m.node_id] = (m.canonical_label or m.node_id, m.facet_type)

    collections_out: List[TopicCollection] = []
    for node_id, sess_list in by_anchor.items():
        label, facet_type = anchor_meta[node_id]
        cooccur: Dict[str, List[str]] = collections.defaultdict(list)
        for sess in sess_list:
            for m in sess.mappings:
                if m.node_id != node_id:
                    lbl = m.canonical_label or m.node_id
                    if lbl not in cooccur[m.facet_type]:
                        cooccur[m.facet_type].append(lbl)
        act = activations.get(node_id)
        collections_out.append(
            TopicCollection(
                collection_id=f"col_{node_id.replace(':', '_')}",
                anchor_node_id=node_id,
                anchor_label=label,
                facet_type=facet_type,
                session_count=len(sess_list),
                effective_activation=act.effective_activation if act else 0.0,
                session_uids=[s.session_uid for s in sess_list],
                cooccurring_facets={k: v[:6] for k, v in cooccur.items()},
            )
        )

    collections_out.sort(key=lambda c: (c.session_count, c.effective_activation), reverse=True)
    return collections_out[:limit]


def generate_serendipity_briefing(
    ws: KosWorkspace,
    bridge_db: PersonalBridgeDB,
    *,
    seed_node_ids: Optional[Sequence[str]] = None,
    max_hops: int = 2,
    min_ic: float = 1.5,
    top_k: int = 8,
    ext_packs: Optional[Sequence[str]] = None,
    persist: bool = True,
) -> SerendipityBriefing:
    """Generate a deterministic, evidence-backed Controlled Serendipity Briefing."""
    now = datetime.now(timezone.utc)
    activations = bridge_db.list_activations(limit=200, now=now)
    act_by_node = {a.node_id: a for a in activations}
    total_touches = sum(a.touch_count for a in activations) + 1

    # Map node_id -> most recent session title for human-readable provenance
    sessions = bridge_db.list_sessions(limit=200)
    node_to_session_title: Dict[str, str] = {}
    node_to_facets: Dict[str, Set[str]] = collections.defaultdict(set)
    for sess in sessions:
        sess_facets = {m.facet_type for m in sess.mappings}
        for m in sess.mappings:
            node_to_session_title.setdefault(m.node_id, sess.title)
            node_to_facets[m.node_id].update(sess_facets)

    if seed_node_ids:
        seeds = list(dict.fromkeys(seed_node_ids))[:12]
    else:
        # Pick top active + one decaying older node for reactivation collision
        seeds = [a.node_id for a in activations[:8]]
        if len(activations) > 8:
            older = sorted(activations[8:], key=lambda a: a.effective_activation)[:2]
            seeds.extend(a.node_id for a in older)

    if not seeds:
        empty_boundary = ws.inspect_license_boundary(pack_ids=["core"])
        return SerendipityBriefing(
            briefing_id=f"brf_{uuid.uuid4().hex[:12]}",
            generated_at=_utcnow_iso(),
            seed_node_count=0,
            items=[],
            license_boundary=empty_boundary,
            markdown="# 受控漫游简报\n\n当前 DB III 尚无已挂载的五维概念种子。可先通过 `/attach` 挂载至少一条对话后再生成简报。\n",
        )

    seed_set = set(seeds)
    subgraph = ws.traverse_multi_hop(
        seeds,
        max_hops=max_hops,
        relations=["oa:cooccur", "skos:related", "skos:closeMatch", "skos:broader"],
        include_negative=False,
        min_ic=min_ic,
        exclude_roots=True,
        max_nodes=120,
        cross_field_only=False,
        ext_packs=ext_packs,
    )

    nodes_by_id = {n.node_id: n for n in subgraph.nodes}
    evidence_by_target: Dict[str, List[SerendipityEvidencePath]] = collections.defaultdict(list)
    for edge in subgraph.edges:
        # Identify which endpoint is farther from seed
        s_node = nodes_by_id.get(edge.source_id)
        t_node = nodes_by_id.get(edge.target_id)
        if s_node is None or t_node is None:
            continue
        if t_node.hop >= s_node.hop and t_node.node_id not in seed_set:
            frm, to = s_node, t_node
        elif s_node.hop >= t_node.hop and s_node.node_id not in seed_set:
            frm, to = t_node, s_node
        else:
            continue
        evidence_by_target[to.node_id].append(
            SerendipityEvidencePath(
                seed_node_id=frm.node_id,
                seed_label=frm.canonical_label_zh or frm.canonical_label_en or frm.node_id,
                seed_session_title=node_to_session_title.get(frm.node_id),
                relation_type=edge.relation_type,
                hop=edge.hop,
                weight=edge.weight,
                polarity=edge.polarity,
                pack_id=edge.pack_id,
            )
        )

    items: List[SerendipityItem] = []
    for target_id, paths in evidence_by_target.items():
        tnode = nodes_by_id.get(target_id)
        if tnode is None or tnode.facet_type is None:
            continue
        # Score = topological evidence + UCB novelty + reactivation collision + cross-facet longitudinal bonus
        best_weight = max(p.weight for p in paths)
        bridge_bonus = 1.25 if any(p.relation_type in ("oa:cooccur", "skos:related", "skos:closeMatch") for p in paths) else 0.85
        topo_score = (math.log1p(best_weight) + 0.35 * min(tnode.info_content, 6.0)) * bridge_bonus

        existing_act = act_by_node.get(target_id)
        target_touches = existing_act.touch_count if existing_act else 0
        ucb_bonus = round(math.sqrt(math.log(total_touches + 2.0) / (1.0 + target_touches)), 4)

        # Reactivation: previously touched but decayed concept re-entered via another active seed
        reactivation_score = 0.0
        if existing_act is not None and existing_act.effective_activation < existing_act.base_activation * 0.7:
            reactivation_score = round(0.6 * (existing_act.base_activation - existing_act.effective_activation), 4)

        seed_facets = set()
        for p in paths:
            seed_facets.update(node_to_facets.get(p.seed_node_id, set()))
        longitudinal_delta = bool(seed_facets and tnode.facet_type not in seed_facets)
        delta_bonus = 0.35 if longitudinal_delta else 0.0

        total_score = round(topo_score + 0.5 * ucb_bonus + reactivation_score + delta_bonus, 4)
        top_paths = sorted(paths, key=lambda p: (p.hop, -p.weight))[:3]
        p0 = top_paths[0]
        rationale_parts = [
            f"由「{p0.seed_label}」经 {p0.relation_type}（{p0.hop} 跳，权重 {p0.weight:.2f}）桥接，信息量 IC={tnode.info_content:.2f}。"
        ]
        if target_touches == 0:
            rationale_parts.append(f"属于尚未探索的相邻概念域（UCB 探索增益 +{ucb_bonus:.2f}）。")
        if reactivation_score > 0:
            rationale_parts.append(f"与既有衰减记忆发生重激活碰撞（+{reactivation_score:.2f}）。")
        if longitudinal_delta:
            rationale_parts.append(f"跨分面扩展至 {tnode.facet_type} 维度。")

        items.append(
            SerendipityItem(
                target_node_id=target_id,
                target_label=tnode.canonical_label_zh or tnode.canonical_label_en or target_id,
                target_facet_type=tnode.facet_type,
                target_breadcrumb=tnode.breadcrumb_path,
                info_content=tnode.info_content,
                map_x=tnode.map_x,
                map_y=tnode.map_y,
                score=total_score,
                ucb_bonus=ucb_bonus,
                reactivation_score=reactivation_score,
                longitudinal_delta=longitudinal_delta,
                rationale="".join(rationale_parts),
                evidence_paths=top_paths,
                license_spdx=tnode.license_spdx,
                dist_tier=tnode.dist_tier,
            )
        )

    items.sort(key=lambda x: x.score, reverse=True)
    items = items[: max(1, min(int(top_k), 30))]

    touched_nodes = list(seed_set | {it.target_node_id for it in items})
    touched_packs = sorted({p.pack_id for it in items for p in it.evidence_paths} | {"core"})
    boundary = ws.inspect_license_boundary(node_ids=touched_nodes, pack_ids=touched_packs)

    briefing_id = f"brf_{uuid.uuid4().hex[:12]}"
    generated_at = _utcnow_iso()

    md_lines = [
        f"# 受控漫游简报（{generated_at}）",
        "",
        f"- 种子概念数：{len(seeds)} · 拓扑推荐数：{len(items)} · 门禁：`polarity=1`, `IC >= {min_ic}`, `exclude_roots=true`",
        f"- 许可边界：{boundary.summary}",
        "",
    ]
    for idx, it in enumerate(items, start=1):
        md_lines.append(f"## {idx}. {it.target_label} (`{it.target_facet_type}` · `{it.target_node_id}`)")
        md_lines.append(f"- **路径位置**：{it.target_breadcrumb}")
        md_lines.append(f"- **推荐依据**：{it.rationale}")
        for ep in it.evidence_paths:
            sess_hint = f"（关联会话：{ep.seed_session_title}）" if ep.seed_session_title else ""
            md_lines.append(f"  - 证据边：`{ep.seed_label}` —[{ep.relation_type}, hop={ep.hop}, w={ep.weight:.2f}]→ `{it.target_label}` {sess_hint}")
        md_lines.append(f"- **来源许可**：`{it.license_spdx}` (`{it.dist_tier}`)")
        md_lines.append("")

    if boundary.share_alike_triggered:
        md_lines.append("> **ShareAlike 合规提示**：本简报包含 `dist_ext_sa` 扩展包来源，对外分享衍生内容时应保留对应 CC BY-SA 署名声明。")

    markdown = "\n".join(md_lines)
    briefing = SerendipityBriefing(
        briefing_id=briefing_id,
        generated_at=generated_at,
        seed_node_count=len(seeds),
        items=items,
        license_boundary=boundary,
        markdown=markdown,
    )
    if persist:
        bridge_db.save_briefing(
            briefing_id=briefing_id,
            generated_at=generated_at,
            seed_count=len(seeds),
            item_count=len(items),
            share_alike=boundary.share_alike_triggered,
            local_only=boundary.local_only_triggered,
            briefing_json=briefing.model_dump_json(),
            briefing_markdown=markdown,
        )
    return briefing
