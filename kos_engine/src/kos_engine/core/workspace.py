"""Read-only L1 KOS Workspace handle, kos_meta handshake, and on-demand ATTACH manager."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

import numpy as np

from kos_engine.core.encoder import OnnxE5Encoder
from kos_engine.core.models import (
    ALL_FACETS,
    KNOWN_EXT_PACKS,
    AeiDistribution,
    AttachedPackInfo,
    BreadcrumbNode,
    FacetCandidate,
    FacetType,
    KosMetaManifest,
    LicenseBoundaryReport,
    MapPartitionGeoJSON,
    NeighborEdge,
    ProvenanceInfo,
    RetrievalMode,
    TraversalDirection,
    TraversalSubgraph,
    ViewportResponse,
)


class KosSchemaVersionError(RuntimeError):
    """Raised when L1 kos_meta schema_version major is incompatible with Adapter Contract v1.0."""


class KosLicenseBoundaryError(PermissionError):
    """Raised when a local_only dataset is opened without allow_local_only=True."""


def _to_readonly_sqlite_uri(path: Path) -> str:
    resolved = path.resolve()
    posix = resolved.as_posix()
    # On Windows resolved.as_posix() is 'G:/...'; SQLite URI needs 'file:/G:/...' or 'file:///G:/...'
    encoded = quote(posix, safe="/:")
    if not encoded.startswith("/"):
        encoded = "/" + encoded
    return f"file:{encoded}?mode=ro"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class KosWorkspace:
    """Client-agnostic read-only L1 KOS workspace implementing Adapter Contract v1.0.

    All L1 databases (core and Tier B extensions) are opened strictly read-only
    (`mode=ro` + `PRAGMA query_only = ON`). No DDL or DML writes are ever issued
    against DB II.
    """

    SUPPORTED_SCHEMA_MAJOR = 1

    def __init__(
        self,
        core_path: Path | str,
        ext_dir: Optional[Path | str] = None,
        *,
        model_dir: Optional[Path | str] = None,
        verify_sha256: bool = False,
        allow_local_only: bool = False,
    ) -> None:
        self.core_path = Path(core_path).resolve()
        if not self.core_path.is_file():
            raise FileNotFoundError(f"L1 core database not found: {self.core_path}")

        if ext_dir is not None:
            self.ext_dir = Path(ext_dir).resolve()
        else:
            sibling = self.core_path.parent / "human_kos_ext"
            self.ext_dir = sibling if sibling.is_dir() else None

        self.allow_local_only = allow_local_only
        self._lock = threading.RLock()
        self._encoder = OnnxE5Encoder(Path(model_dir).resolve() if model_dir else None)

        uri = _to_readonly_sqlite_uri(self.core_path)
        self._con = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA query_only = ON;")

        self._attached: Dict[str, AttachedPackInfo] = {}
        # Cache of (pack_id, facet_type) -> (node_ids, float32_matrix)
        self._vec_cache: Dict[Tuple[str, str], Tuple[List[str], np.ndarray]] = {}

        self._sha256_verified: Optional[bool] = None
        if verify_sha256:
            self._sha256_verified = self._verify_manifest_sha256(self.core_path)

        self._meta = self._handshake_meta()

    @classmethod
    def open_workspace(
        cls,
        core_path: Path | str,
        ext_dir: Optional[Path | str] = None,
        *,
        model_dir: Optional[Path | str] = None,
        verify_sha256: bool = False,
        allow_local_only: bool = False,
    ) -> "KosWorkspace":
        return cls(
            core_path=core_path,
            ext_dir=ext_dir,
            model_dir=model_dir,
            verify_sha256=verify_sha256,
            allow_local_only=allow_local_only,
        )

    def close(self) -> None:
        with self._lock:
            self._vec_cache.clear()
            self._attached.clear()
            self._con.close()

    def __enter__(self) -> "KosWorkspace":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def encoder(self) -> OnnxE5Encoder:
        return self._encoder

    @property
    def active_packages(self) -> List[str]:
        with self._lock:
            return ["core", *sorted(self._attached.keys())]

    def list_available_extensions(self) -> List[str]:
        if self.ext_dir is None or not self.ext_dir.is_dir():
            return []
        found = []
        for pack_id in KNOWN_EXT_PACKS:
            if (self.ext_dir / f"{pack_id}.sqlite").is_file():
                found.append(pack_id)
        return found

    def _verify_manifest_sha256(self, file_path: Path) -> bool:
        manifest_path = self.core_path.parent / "MANIFEST.json"
        if not manifest_path.is_file():
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual = _sha256_file(file_path).lower()
        target_name = file_path.name
        candidates: List[str] = []

        def _collect(obj) -> None:
            if isinstance(obj, dict):
                name = str(obj.get("filename") or obj.get("path") or obj.get("file") or "")
                sha = obj.get("sha256")
                if sha and (name == target_name or name.endswith(f"/{target_name}") or name.endswith(f"\\{target_name}")):
                    candidates.append(str(sha).lower())
                for v in obj.values():
                    _collect(v)
            elif isinstance(obj, list):
                for item in obj:
                    _collect(item)

        _collect(manifest)
        if not candidates:
            return False
        if actual not in candidates:
            raise ValueError(f"SHA-256 mismatch for {file_path.name}: actual={actual}, expected={candidates}")
        return True

    def _handshake_meta(self) -> KosMetaManifest:
        with self._lock:
            rows = self._con.execute("SELECT key, value FROM kos_meta").fetchall()
            raw = {str(r["key"]): str(r["value"]) for r in rows}
            schema_ver = raw.get("schema_version", "")
            parts = schema_ver.split(".")
            if not parts or not parts[0].isdigit() or int(parts[0]) != self.SUPPORTED_SCHEMA_MAJOR:
                raise KosSchemaVersionError(
                    f"Unsupported L1 schema_version '{schema_ver}'; expected major {self.SUPPORTED_SCHEMA_MAJOR}.x"
                )

            if not self.allow_local_only:
                local_rows = self._con.execute(
                    "SELECT source_id FROM kos_provenance WHERE dist_tier = 'local_only' LIMIT 1"
                ).fetchall()
                if local_rows:
                    raise KosLicenseBoundaryError(
                        "L1 database contains 'local_only' provenance; pass allow_local_only=True explicitly to open it."
                    )

            core_count = int(self._con.execute("SELECT COUNT(*) FROM kos_nodes").fetchone()[0])
            return KosMetaManifest(
                schema_version=schema_ver,
                embedding_model=raw.get("embedding_model", OnnxE5Encoder.MODEL_ID),
                embedding_version=raw.get("embedding_version", OnnxE5Encoder.EMBEDDING_VERSION),
                embedding_dim=int(raw.get("embedding_dim", str(OnnxE5Encoder.DIM))),
                embedding_quant=raw.get("embedding_quant", "int8"),
                layout_version=raw.get("layout_version", "umap-n15-d01-cos-s42-v1"),
                build_profile=raw.get("build_profile", "core"),
                built_at=raw.get("built_at"),
                packed_at=raw.get("packed_at"),
                core_node_count=core_count,
                active_packages=["core"],
                sha256_verified=self._sha256_verified,
                raw_meta=raw,
            )

    def get_meta(self) -> KosMetaManifest:
        with self._lock:
            return self._meta.model_copy(update={"active_packages": self.active_packages})

    def attach_extension(self, pack_id: str) -> AttachedPackInfo:
        if pack_id not in KNOWN_EXT_PACKS:
            raise ValueError(f"Unknown extension pack_id '{pack_id}'; allowed={KNOWN_EXT_PACKS}")
        if self.ext_dir is None:
            raise FileNotFoundError("Extension directory ext_dir is not configured")

        with self._lock:
            if pack_id in self._attached:
                return self._attached[pack_id]

            pack_path = (self.ext_dir / f"{pack_id}.sqlite").resolve()
            if not pack_path.is_file():
                raise FileNotFoundError(f"Extension pack not found: {pack_path}")

            alias = f"ext_{pack_id}"
            uri = _to_readonly_sqlite_uri(pack_path)
            self._con.execute(f"ATTACH DATABASE ? AS {alias}", (uri,))

            try:
                tables = {
                    str(r[0])
                    for r in self._con.execute(
                        f"SELECT name FROM {alias}.sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                prov_rows = self._con.execute(
                    f"SELECT license_spdx, dist_tier FROM {alias}.kos_provenance"
                ).fetchall()
                licenses = sorted({str(r["license_spdx"]) for r in prov_rows})
                tiers = sorted({str(r["dist_tier"]) for r in prov_rows})
                local_only = "local_only" in tiers
                if local_only and not self.allow_local_only:
                    raise KosLicenseBoundaryError(
                        f"Extension pack '{pack_id}' contains local_only sources; set allow_local_only=True explicitly."
                    )
                share_alike = ("dist_ext_sa" in tiers) or any("SA" in lic.upper() for lic in licenses)

                if "cn_relations" in tables:
                    pack_kind = "cn_rel"
                    node_count = int(self._con.execute(f"SELECT COUNT(*) FROM {alias}.cn_alias").fetchone()[0])
                    edge_count = int(self._con.execute(f"SELECT COUNT(*) FROM {alias}.cn_relations").fetchone()[0])
                    emb_count = 0
                else:
                    pack_kind = "standard"
                    node_count = int(self._con.execute(f"SELECT COUNT(*) FROM {alias}.kos_nodes").fetchone()[0])
                    edge_count = int(self._con.execute(f"SELECT COUNT(*) FROM {alias}.kos_edges").fetchone()[0])
                    emb_count = (
                        int(self._con.execute(f"SELECT COUNT(*) FROM {alias}.kos_embeddings").fetchone()[0])
                        if "kos_embeddings" in tables
                        else 0
                    )

                info = AttachedPackInfo(
                    pack_id=pack_id,
                    db_alias=alias,
                    file_path=pack_path.name,
                    pack_kind=pack_kind,
                    node_count=node_count,
                    embedding_count=emb_count,
                    edge_count=edge_count,
                    has_embeddings=emb_count > 0,
                    license_spdx_list=licenses,
                    dist_tiers=tiers,
                    share_alike=share_alike,
                    local_only=local_only,
                )
                self._attached[pack_id] = info
                return info
            except Exception:
                self._con.execute(f"DETACH DATABASE {alias}")
                raise

    def detach_extension(self, pack_id: str) -> None:
        with self._lock:
            info = self._attached.pop(pack_id, None)
            if info is None:
                return
            for key in [k for k in self._vec_cache if k[0] == pack_id]:
                self._vec_cache.pop(key, None)
            # Clear cached statements before DETACH so SQLite releases schema locks cleanly
            self._con.execute("PRAGMA shrink_memory;")
            self._con.execute(f"DETACH DATABASE {info.db_alias}")

    def get_attached_packs(self) -> Dict[str, AttachedPackInfo]:
        with self._lock:
            return dict(self._attached)

    def _schema_prefix(self, pack_id: str) -> str:
        if pack_id == "core":
            return "main"
        info = self._attached.get(pack_id)
        if info is None:
            info = self.attach_extension(pack_id)
        return info.db_alias

    def get_node(self, node_id: str) -> Optional[Dict]:
        with self._lock:
            schemas = [("core", "main")] + [
                (pid, info.db_alias) for pid, info in self._attached.items() if info.pack_kind == "standard"
            ]
            for pid, sch in schemas:
                row = self._con.execute(
                    f"""
                    SELECT n.*, pr.source_name, pr.license_spdx, pr.dist_tier, pr.attribution_text
                    FROM {sch}.kos_nodes n
                    JOIN {sch}.kos_provenance pr ON pr.source_id = n.source_id
                    WHERE n.node_id = ?
                    """,
                    (node_id,),
                ).fetchone()
                if row is not None:
                    d = dict(row)
                    d["pack_id"] = pid
                    return d
            return None

    # ---- Delegated Adapter Contract v1.0 Domains ----

    def search_facet(
        self,
        query_text: str,
        facet: FacetType,
        *,
        mode: RetrievalMode = "hybrid",
        top_k: int = 20,
        ext_packs: Optional[Sequence[str]] = None,
        use_cn_alias_bridge: bool = False,
        zscore_normalize: bool = True,
    ) -> List[FacetCandidate]:
        from kos_engine.core.retrieval import search_facet

        return search_facet(
            self,
            query_text=query_text,
            facet=facet,
            mode=mode,
            top_k=top_k,
            ext_packs=ext_packs,
            use_cn_alias_bridge=use_cn_alias_bridge,
            zscore_normalize=zscore_normalize,
        )

    def search_all_facets(
        self,
        query_text: str,
        facets: Sequence[FacetType] = ALL_FACETS,
        *,
        mode: RetrievalMode = "hybrid",
        top_k: int = 10,
        ext_packs: Optional[Sequence[str]] = None,
        use_cn_alias_bridge: bool = False,
        zscore_normalize: bool = True,
    ) -> Dict[FacetType, List[FacetCandidate]]:
        from kos_engine.core.retrieval import search_all_facets

        return search_all_facets(
            self,
            query_text=query_text,
            facets=facets,
            mode=mode,
            top_k=top_k,
            ext_packs=ext_packs,
            use_cn_alias_bridge=use_cn_alias_bridge,
            zscore_normalize=zscore_normalize,
        )

    def get_aei_calibration(self, axis_type: str, axis_key: str) -> Optional[AeiDistribution]:
        from kos_engine.core.retrieval import get_aei_calibration

        return get_aei_calibration(self, axis_type=axis_type, axis_key=axis_key)

    def list_aei_calibration(self, axis_type: str = "onet_task", limit: int = 20) -> List[AeiDistribution]:
        from kos_engine.core.retrieval import list_aei_calibration

        return list_aei_calibration(self, axis_type=axis_type, limit=limit)

    def get_neighbors(
        self,
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
        from kos_engine.core.traversal import get_neighbors

        return get_neighbors(
            self,
            node_id=node_id,
            relations=relations,
            direction=direction,
            polarity=polarity,
            min_weight=min_weight,
            min_ic=min_ic,
            exclude_roots=exclude_roots,
            limit=limit,
        )

    def traverse_multi_hop(
        self,
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
        from kos_engine.core.traversal import traverse_multi_hop

        return traverse_multi_hop(
            self,
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

    def get_ancestry(self, node_id: str) -> List[BreadcrumbNode]:
        from kos_engine.core.traversal import get_ancestry

        return get_ancestry(self, node_id=node_id)

    def inspect_license_boundary(
        self,
        *,
        node_ids: Optional[Sequence[str]] = None,
        pack_ids: Optional[Sequence[str]] = None,
    ) -> LicenseBoundaryReport:
        from kos_engine.core.provenance import inspect_license_boundary

        return inspect_license_boundary(self, node_ids=node_ids, pack_ids=pack_ids)

    def query_viewport(
        self,
        bbox: Tuple[float, float, float, float],
        zoom_tier: int = 1,
        *,
        facets: Optional[Sequence[FacetType]] = None,
        limit: int = 2000,
        include_edges: bool = True,
    ) -> ViewportResponse:
        from kos_engine.core.spatial import query_viewport

        return query_viewport(
            self,
            bbox=bbox,
            zoom_tier=zoom_tier,
            facets=facets,
            limit=limit,
            include_edges=include_edges,
        )

    def get_map_partitions(self, facet: Optional[FacetType] = None) -> List[MapPartitionGeoJSON]:
        from kos_engine.core.spatial import get_map_partitions

        return get_map_partitions(self, facet=facet)
