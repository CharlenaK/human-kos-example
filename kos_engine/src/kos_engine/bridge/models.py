"""Pydantic data models for L3 DB III (personal_bridge.sqlite) and session importers."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from kos_engine.core.models import FacetCandidate, FacetType, LicenseBoundaryReport


class SessionInput(BaseModel):
    source_client: str = Field(..., description="Client identifier, e.g. 'open_webui', 'cherry_studio', 'cli'")
    external_session_id: str = Field(..., description="Original session/topic ID in source client")
    title: str = Field(..., description="Session title")
    content_text: str = Field("", description="Full or concatenated user/assistant text used for fingerprinting")
    excerpt: Optional[str] = None
    turn_count: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionRecord(BaseModel):
    session_uid: str
    source_client: str
    external_session_id: str
    content_sha256: str
    title: str
    excerpt: str
    turn_count: int
    created_at: str
    updated_at: str
    imported_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    mappings: List["FacetBinding"] = Field(default_factory=list)


class FacetBinding(BaseModel):
    facet_type: FacetType
    node_id: str
    pack_id: str = "core"
    canonical_label: str = ""
    breadcrumb_path: str = ""
    confidence: float = 1.0
    binding_source: Literal["user_attach", "auto_propose", "import"] = "user_attach"
    attached_at: Optional[str] = None


class AttachProposal(BaseModel):
    query_text: str
    mode: str
    candidates_by_facet: Dict[FacetType, List[FacetCandidate]]
    license_boundary: LicenseBoundaryReport


class AttachConfirmRequest(BaseModel):
    session: SessionInput
    bindings: List[FacetBinding] = Field(..., min_length=1)


class AttachConfirmResponse(BaseModel):
    session: SessionRecord
    applied_bindings: List[FacetBinding]
    reconnected_by_fingerprint: bool = False
    license_boundary: LicenseBoundaryReport


class NodeActivationRecord(BaseModel):
    node_id: str
    facet_type: FacetType
    pack_id: str
    canonical_label: str
    touch_count: int
    base_activation: float
    effective_activation: float
    last_touched_at: str
    half_life_days: float


class TopicCollection(BaseModel):
    collection_id: str
    anchor_node_id: str
    anchor_label: str
    facet_type: FacetType
    session_count: int
    effective_activation: float
    session_uids: List[str] = Field(default_factory=list)
    cooccurring_facets: Dict[str, List[str]] = Field(default_factory=dict)


class SerendipityEvidencePath(BaseModel):
    seed_node_id: str
    seed_label: str
    seed_session_title: Optional[str] = None
    relation_type: str
    hop: int
    weight: float
    polarity: int = 1
    pack_id: str = "core"


class SerendipityItem(BaseModel):
    target_node_id: str
    target_label: str
    target_facet_type: FacetType
    target_breadcrumb: str
    info_content: float
    map_x: float
    map_y: float
    score: float
    ucb_bonus: float
    reactivation_score: float
    longitudinal_delta: bool = False
    rationale: str
    evidence_paths: List[SerendipityEvidencePath] = Field(default_factory=list)
    license_spdx: str = ""
    dist_tier: str = "dist_core"


class SerendipityBriefing(BaseModel):
    briefing_id: str
    generated_at: str
    seed_node_count: int
    items: List[SerendipityItem] = Field(default_factory=list)
    license_boundary: LicenseBoundaryReport
    markdown: str


class ImportPreviewItem(BaseModel):
    external_session_id: str
    title: str
    turn_count: int
    content_sha256: str
    status: Literal["new", "update", "skip_duplicate", "skip_private"]
    reason: Optional[str] = None


class ImportResult(BaseModel):
    receipt_id: Optional[str] = None
    source_client: str
    dry_run: bool
    total_seen: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    private_filtered_count: int = 0
    items: List[ImportPreviewItem] = Field(default_factory=list)
