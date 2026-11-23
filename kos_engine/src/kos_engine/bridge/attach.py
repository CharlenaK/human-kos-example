"""Five-facet `/attach` proposal and verified DB III confirmation workflow."""

from __future__ import annotations

from typing import List, Optional, Sequence

from kos_engine.bridge.db import PersonalBridgeDB
from kos_engine.bridge.models import (
    AttachConfirmRequest,
    AttachConfirmResponse,
    AttachProposal,
    FacetBinding,
)
from kos_engine.core.models import ALL_FACETS, RetrievalMode
from kos_engine.core.workspace import KosWorkspace


def propose_attach(
    ws: KosWorkspace,
    query_text: str,
    *,
    mode: RetrievalMode = "hybrid",
    top_k_per_facet: int = 6,
    ext_packs: Optional[Sequence[str]] = None,
    use_cn_alias_bridge: bool = False,
) -> AttachProposal:
    """Return 5 physically isolated candidate lists for human/LLM controlled `/attach` selection."""
    by_facet = ws.search_all_facets(
        query_text=query_text,
        facets=ALL_FACETS,
        mode=mode,
        top_k=top_k_per_facet,
        ext_packs=ext_packs,
        use_cn_alias_bridge=use_cn_alias_bridge,
        zscore_normalize=True,
    )
    node_ids = [c.node_id for cands in by_facet.values() for c in cands]
    packs = sorted({c.pack_id for cands in by_facet.values() for c in cands} | {"core"})
    boundary = ws.inspect_license_boundary(node_ids=node_ids, pack_ids=packs)
    return AttachProposal(
        query_text=query_text,
        mode=mode,
        candidates_by_facet=by_facet,
        license_boundary=boundary,
    )


def confirm_attach(
    ws: KosWorkspace,
    bridge_db: PersonalBridgeDB,
    req: AttachConfirmRequest,
) -> AttachConfirmResponse:
    """Validate selected nodes against L1 DB II (including facet match) and persist to DB III."""
    verified_bindings: List[FacetBinding] = []
    touched_packs = {"core"}

    for b in req.bindings:
        if b.pack_id != "core":
            ws.attach_extension(b.pack_id)
            touched_packs.add(b.pack_id)
        node = ws.get_node(b.node_id)
        if node is None:
            raise ValueError(f"Node '{b.node_id}' does not exist in L1 core or attached packs")
        if node["facet_type"] != b.facet_type:
            raise ValueError(
                f"Facet mismatch for node '{b.node_id}': declared '{b.facet_type}', L1 has '{node['facet_type']}'"
            )
        label = node.get("canonical_label_zh") or node.get("canonical_label_en") or b.node_id
        verified_bindings.append(
            FacetBinding(
                facet_type=node["facet_type"],
                node_id=b.node_id,
                pack_id=node.get("pack_id", b.pack_id),
                canonical_label=str(label),
                breadcrumb_path=str(node["breadcrumb_path"]),
                confidence=b.confidence,
                binding_source=b.binding_source,
            )
        )

    session_rec, reconnected, _ = bridge_db.upsert_session(req.session)
    applied = bridge_db.add_mappings(session_rec.session_uid, verified_bindings)
    updated_session = bridge_db.get_session(session_rec.session_uid)
    boundary = ws.inspect_license_boundary(
        node_ids=[b.node_id for b in applied],
        pack_ids=sorted(touched_packs),
    )
    return AttachConfirmResponse(
        session=updated_session,
        applied_bindings=applied,
        reconnected_by_fingerprint=reconnected,
        license_boundary=boundary,
    )
