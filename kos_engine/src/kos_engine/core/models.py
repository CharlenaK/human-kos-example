"""Typed data models for L2 Adapter Contract v1.0."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

FacetType = Literal["DOMAIN", "ACTIVITY", "PROCESS", "ARTIFACT", "STANCE"]
ALL_FACETS: Tuple[FacetType, ...] = ("DOMAIN", "ACTIVITY", "PROCESS", "ARTIFACT", "STANCE")

ExtPackId = Literal[
    "aat",
    "cn_rel",
    "compendium",
    "dila",
    "edam",
    "glottolog",
    "iscedf",
    "lcsh",
    "periodo",
    "unesco",
]
KNOWN_EXT_PACKS: Tuple[str, ...] = (
    "aat",
    "cn_rel",
    "compendium",
    "dila",
    "edam",
    "glottolog",
    "iscedf",
    "lcsh",
    "periodo",
    "unesco",
)

DistTier = Literal["dist_core", "dist_ext_permissive", "dist_ext_sa", "local_only"]
RetrievalMode = Literal["bm25", "vector", "hybrid"]
TraversalDirection = Literal["out", "in", "both"]

DEFAULT_TRAVERSAL_RELATIONS: Tuple[str, ...] = (
    "oa:cooccur",
    "skos:related",
    "skos:closeMatch",
    "skos:exactMatch",
    "skos:broader",
    "skos:narrower",
    "esco:essentialSkill",
    "onet:task_of",
    "cn:HasPrerequisite",
    "cn:HasSubevent",
    "cn:UsedFor",
    "cn:CapableOf",
)


class ProvenanceInfo(BaseModel):
    source_id: str
    source_name: str
    version: str
    license_spdx: str
    dist_tier: str
    attribution_text: str
    homepage_url: Optional[str] = None
    notes: Optional[str] = None
    pack_id: str = "core"


class LicenseBoundaryReport(BaseModel):
    checked_node_count: int = 0
    checked_packs: List[str] = Field(default_factory=list)
    sources: List[ProvenanceInfo] = Field(default_factory=list)
    share_alike_triggered: bool = False
    local_only_triggered: bool = False
    required_notices: List[str] = Field(default_factory=list)
    summary: str = ""


class KosMetaManifest(BaseModel):
    schema_version: str
    embedding_model: str
    embedding_version: str
    embedding_dim: int
    embedding_quant: str
    layout_version: str
    build_profile: str
    built_at: Optional[str] = None
    packed_at: Optional[str] = None
    core_node_count: int = 0
    active_packages: List[str] = Field(default_factory=list)
    sha256_verified: Optional[bool] = None
    raw_meta: Dict[str, str] = Field(default_factory=dict)


class AttachedPackInfo(BaseModel):
    pack_id: str
    db_alias: str
    file_path: str
    pack_kind: Literal["standard", "cn_rel"]
    node_count: int = 0
    embedding_count: int = 0
    edge_count: int = 0
    has_embeddings: bool = False
    license_spdx_list: List[str] = Field(default_factory=list)
    dist_tiers: List[str] = Field(default_factory=list)
    share_alike: bool = False
    local_only: bool = False


class FacetCandidate(BaseModel):
    node_id: str
    facet_type: FacetType
    canonical_label_en: Optional[str] = None
    canonical_label_zh: Optional[str] = None
    label_zh_status: str = "missing"
    breadcrumb_path: str
    definition_summary: Optional[str] = None
    info_content: float = 1.0
    map_x: float = 0.0
    map_y: float = 0.0
    min_zoom_tier: int = 2
    source_id: str
    license_spdx: str
    dist_tier: str
    pack_id: str = "core"
    bm25_score: Optional[float] = None
    cosine_score: Optional[float] = None
    z_score: Optional[float] = None
    fused_score: float = 0.0
    matched_via: List[str] = Field(default_factory=list)


class AeiDistribution(BaseModel):
    axis_type: str
    axis_key: str
    axis_label: Optional[str] = None
    geography: str = "GLOBAL"
    release_version: str
    directive_pct: float
    feedback_loop_pct: float
    task_iteration_pct: float
    learning_pct: float
    validation_pct: float
    none_pct: float
    total_pct: float
    source_id: str


class BreadcrumbNode(BaseModel):
    node_id: str
    facet_type: FacetType
    canonical_label_en: Optional[str] = None
    canonical_label_zh: Optional[str] = None
    depth: int
    is_root: bool
    info_content: float
    source_id: str


class NeighborEdge(BaseModel):
    source_id: str
    target_id: str
    neighbor_id: str
    direction: Literal["out", "in"]
    relation_type: str
    weight: float
    polarity: int = 1
    provenance_source_id: str
    pack_id: str = "core"
    neighbor_label_en: Optional[str] = None
    neighbor_label_zh: Optional[str] = None
    neighbor_facet_type: Optional[FacetType] = None
    neighbor_breadcrumb: Optional[str] = None
    neighbor_info_content: float = 1.0
    neighbor_is_root: bool = False
    license_spdx: str = ""
    dist_tier: str = "dist_core"
    evidence: Optional[Dict[str, Any]] = None


class TraversalNode(BaseModel):
    node_id: str
    facet_type: Optional[FacetType] = None
    canonical_label_en: Optional[str] = None
    canonical_label_zh: Optional[str] = None
    breadcrumb_path: str = ""
    info_content: float = 1.0
    is_root: bool = False
    hop: int = 0
    map_x: float = 0.0
    map_y: float = 0.0
    source_id: str = ""
    license_spdx: str = ""
    dist_tier: str = "dist_core"
    pack_id: str = "core"


class TraversalEdge(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    weight: float
    polarity: int = 1
    hop: int = 1
    provenance_source_id: str
    pack_id: str = "core"
    license_spdx: str = ""
    dist_tier: str = "dist_core"


class TraversalSubgraph(BaseModel):
    seed_node_ids: List[str]
    max_hops: int
    include_negative: bool
    min_info_content: float
    exclude_roots: bool
    nodes: List[TraversalNode] = Field(default_factory=list)
    edges: List[TraversalEdge] = Field(default_factory=list)
    license_boundary: LicenseBoundaryReport = Field(default_factory=LicenseBoundaryReport)


class ViewportNode(BaseModel):
    node_id: str
    spatial_id: int
    facet_type: FacetType
    canonical_label_en: Optional[str] = None
    canonical_label_zh: Optional[str] = None
    breadcrumb_path: str
    info_content: float
    map_x: float
    map_y: float
    domain_partition_id: str
    min_zoom_tier: int
    source_id: str
    license_spdx: str
    dist_tier: str


class ViewportEdge(BaseModel):
    source_id: str
    target_id: str
    relation_type: str
    weight: float
    polarity: int = 1


class ViewportResponse(BaseModel):
    bbox: Tuple[float, float, float, float]
    zoom_tier: int
    total_returned: int
    truncated: bool
    nodes: List[ViewportNode] = Field(default_factory=list)
    edges: List[ViewportEdge] = Field(default_factory=list)


class MapPartitionGeoJSON(BaseModel):
    partition_id: str
    facet_type: FacetType
    label_en: str
    label_zh: Optional[str] = None
    layout_version: str
    centroid_x: float
    centroid_y: float
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    node_count: int
    geometry: Dict[str, Any]
