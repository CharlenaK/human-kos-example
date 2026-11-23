"""Adapter Contract v1.0 Conformance Tests for kos-engine (P3-A1 & P3-A2)."""

from __future__ import annotations

import os
import sqlite3
import statistics
import time
from pathlib import Path

import pytest

from kos_engine.core.models import ALL_FACETS
from kos_engine.core.workspace import (
    KosLicenseBoundaryError,
    KosSchemaVersionError,
    KosWorkspace,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_l1_core() -> Path:
    env_p = os.environ.get("KOS_CORE_DB")
    if env_p:
        return Path(env_p).resolve()
    for base in (REPO_ROOT, REPO_ROOT.parent):
        for rel in ("kos_build/release/human_kos_core.sqlite", "data/human_kos_core.sqlite"):
            cand = base / rel
            if cand.is_file():
                return cand
    return REPO_ROOT / "data" / "human_kos_core.sqlite"


L1_CORE = _resolve_l1_core()
L1_EXT_DIR = Path(os.environ.get("KOS_EXT_DIR") or (L1_CORE.parent / "human_kos_ext"))
E5_MODEL_DIR = Path(
    os.environ.get("KOS_E5_MODEL_DIR")
    or (REPO_ROOT.parent / "Data Repository" / "_derived" / "models" / "multilingual-e5-small")
)


@pytest.fixture(scope="module")
def workspace() -> KosWorkspace:
    ws = KosWorkspace.open_workspace(
        core_path=L1_CORE,
        ext_dir=L1_EXT_DIR,
        model_dir=E5_MODEL_DIR if E5_MODEL_DIR.is_dir() else None,
        verify_sha256=True,
    )
    yield ws
    ws.close()


def test_readonly_hard_constraint(workspace: KosWorkspace) -> None:
    """P3-A1: DB II must be strictly read-only (mode=ro + PRAGMA query_only=ON)."""
    with pytest.raises(sqlite3.OperationalError):
        workspace._con.execute("CREATE TABLE should_fail (id INT)")
    with pytest.raises(sqlite3.OperationalError):
        workspace._con.execute("DELETE FROM kos_meta WHERE key = 'schema_version'")


def test_meta_handshake_and_sha256(workspace: KosWorkspace) -> None:
    """Contract §1.1(6): kos_meta handshake + MANIFEST SHA-256 verification."""
    meta = workspace.get_meta()
    assert meta.schema_version == "1.0.0"
    assert meta.embedding_version == "e5-small-int8-v1"
    assert meta.layout_version == "umap-n15-d01-cos-s42-v1"
    assert meta.embedding_dim == 384
    assert meta.embedding_quant == "int8"
    assert meta.core_node_count > 80_000
    assert meta.sha256_verified is True


def test_schema_version_incompatibility_rejected(tmp_path: Path) -> None:
    bad_db = tmp_path / "bad_v2.sqlite"
    con = sqlite3.connect(bad_db)
    con.execute("CREATE TABLE kos_meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    con.execute("INSERT INTO kos_meta VALUES ('schema_version', '2.0.0', '2026-01-01')")
    con.commit()
    con.close()

    with pytest.raises(KosSchemaVersionError):
        KosWorkspace.open_workspace(bad_db)


def test_local_only_guard(tmp_path: Path) -> None:
    local_db = tmp_path / "local_only.sqlite"
    con = sqlite3.connect(local_db)
    con.executescript(
        """
        CREATE TABLE kos_meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        INSERT INTO kos_meta VALUES ('schema_version', '1.0.0', '2026-01-01');
        CREATE TABLE kos_provenance (
            source_id TEXT PRIMARY KEY, source_name TEXT, version TEXT,
            license_spdx TEXT, dist_tier TEXT, attribution_text TEXT,
            homepage_url TEXT, fetched_at TEXT, notes TEXT
        );
        INSERT INTO kos_provenance VALUES (
            'LOCAL_SRC', 'Local Only Source', '1.0', 'NOASSERTION',
            'local_only', 'Local only notice', NULL, '2026-01-01', NULL
        );
        CREATE TABLE kos_nodes (node_id TEXT PRIMARY KEY);
        """
    )
    con.commit()
    con.close()

    with pytest.raises(KosLicenseBoundaryError):
        KosWorkspace.open_workspace(local_db, allow_local_only=False)

    with KosWorkspace.open_workspace(local_db, allow_local_only=True) as ws:
        report = ws.inspect_license_boundary(pack_ids=["core"])
        assert report.local_only_triggered is True


def test_on_demand_attach_detach_and_zero_vector_pack_fallback(workspace: KosWorkspace) -> None:
    """Contract §1.1(1) & (2): on-demand ATTACH/DETACH + zero-embedding pack graceful fallback."""
    info_lcsh = workspace.attach_extension("lcsh")
    assert info_lcsh.pack_id == "lcsh"
    assert info_lcsh.has_embeddings is False
    assert "lcsh" in workspace.active_packages

    # Hybrid query with zero-embedding lcsh pack must not fail
    cands = workspace.search_facet(
        "epistemology philosophy", "DOMAIN", mode="hybrid", top_k=10, ext_packs=["lcsh"]
    )
    assert len(cands) > 0
    assert all(c.facet_type == "DOMAIN" for c in cands)

    workspace.detach_extension("lcsh")
    assert "lcsh" not in workspace.active_packages


def test_facet_isolation_zero_mixing(workspace: KosWorkspace) -> None:
    """Contract §1.1(3) / A6: ambiguous words must stay strictly isolated per facet."""
    for term in ("test", "model", "agent"):
        by_facet = workspace.search_all_facets(term, mode="bm25", top_k=10)
        assert set(by_facet.keys()) == set(ALL_FACETS)
        for facet, cands in by_facet.items():
            assert all(c.facet_type == facet for c in cands), f"Cross-facet leak on {term}/{facet}"


def test_fts5_chinese_bm25_p95_under_20ms(workspace: KosWorkspace) -> None:
    """Contract §1.1(2) / A3: Chinese FTS5 BM25 P95 latency < 20 ms."""
    queries = [
        ("大语言模型与智能体系统", "PROCESS"),
        ("知识图谱构建与本体工程", "PROCESS"),
        ("认知心理学与哲学认识论", "DOMAIN"),
        ("青铜器与宋代瓷器美学", "ARTIFACT"),
        ("软件架构设计与项目管理", "ACTIVITY"),
        ("人工智能伦理与社会治理", "DOMAIN"),
        ("机器学习强化学习算法", "PROCESS"),
        ("建筑历史与文艺复兴雕塑", "ARTIFACT"),
        ("临床诊断与健康管理活动", "ACTIVITY"),
        ("批判性辩论与思想实验", "STANCE"),
    ]
    # Warm SQLite page cache once
    for q, f in queries[:2]:
        workspace.search_facet(q, f, mode="bm25", top_k=10)

    latencies_ms = []
    for _ in range(3):
        for q, f in queries:
            t0 = time.perf_counter()
            res = workspace.search_facet(q, f, mode="bm25", top_k=10)
            elapsed = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed)
            assert len(res) >= 0

    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1]
    assert p95 < 20.0, f"FTS5 BM25 P95 too slow: {p95:.2f} ms (median={statistics.median(latencies_ms):.2f} ms)"


def test_onnx_e5_hybrid_zscore_and_fallback(workspace: KosWorkspace) -> None:
    """Contract §1.1(2): ONNX e5-small int8 dequantization + per-facet z-score + fallback."""
    if workspace.encoder.available:
        vec = workspace.encoder.encode_query("大语言模型推理优化")
        assert vec is not None
        assert vec.shape == (384,)
        cands = workspace.search_facet("大语言模型推理优化", "PROCESS", mode="hybrid", top_k=10, zscore_normalize=True)
        assert len(cands) > 0
        assert any(c.cosine_score is not None for c in cands)
        assert any(c.z_score is not None for c in cands)

    # Graceful FTS5 fallback when model_dir=None
    with KosWorkspace.open_workspace(L1_CORE, L1_EXT_DIR, model_dir=None) as ws_no_vec:
        assert ws_no_vec.encoder.available is False
        fallback = ws_no_vec.search_facet("大语言模型", "PROCESS", mode="vector", top_k=5)
        assert len(fallback) > 0
        assert all("bm25_fallback" in c.matched_via for c in fallback)


def test_cn_rel_alias_bridge_and_share_alike_guard(workspace: KosWorkspace) -> None:
    """Contract §1.1(2) & (5): cn_rel zh->en alias bridge + ShareAlike provenance guard."""
    info = workspace.attach_extension("cn_rel")
    assert info.pack_kind == "cn_rel"
    assert info.share_alike is True

    cands = workspace.search_facet(
        "哲学认识论", "DOMAIN", mode="bm25", top_k=10, use_cn_alias_bridge=True
    )
    assert len(cands) > 0

    report = workspace.inspect_license_boundary(pack_ids=["core", "cn_rel"])
    assert report.share_alike_triggered is True
    assert report.local_only_triggered is False
    assert any("CC-BY-SA" in n for n in report.required_notices)

    workspace.detach_extension("cn_rel")


def test_aei_calibration_lookup(workspace: KosWorkspace) -> None:
    items = workspace.list_aei_calibration("onet_task", limit=5)
    assert len(items) == 5
    first = workspace.get_aei_calibration(items[0].axis_type, items[0].axis_key)
    assert first is not None
    assert first.total_pct > 90.0


def test_multi_hop_traversal_ic_root_and_unesco_bridge(workspace: KosWorkspace) -> None:
    """Contract §1.1(4): multi-hop traversal with IC>=1.5, exclude_roots, and unesco bridge."""
    seed_row = workspace._con.execute(
        """
        SELECT e.source_id
        FROM kos_edges e
        JOIN kos_nodes n ON n.node_id = e.source_id
        WHERE e.relation_type = 'oa:cooccur' AND n.info_content >= 1.5 AND n.is_root = 0
        LIMIT 1
        """
    ).fetchone()
    assert seed_row is not None
    seed_id = str(seed_row[0])

    subgraph = workspace.traverse_multi_hop(
        [seed_id],
        max_hops=2,
        relations=["oa:cooccur", "skos:broader", "skos:related", "skos:closeMatch"],
        include_negative=False,
        min_ic=1.5,
        exclude_roots=True,
        max_nodes=40,
    )
    assert len(subgraph.nodes) >= 2
    assert len(subgraph.edges) >= 1
    assert all(e.polarity == 1 for e in subgraph.edges)
    # Non-seed nodes must satisfy IC >= 1.5 and is_root == False
    for node in subgraph.nodes:
        if node.hop > 0:
            assert node.info_content >= 1.5
            assert node.is_root is False

    ancestry = workspace.get_ancestry(seed_id)
    assert len(ancestry) >= 1
    assert ancestry[-1].node_id == seed_id

    # Cross-pack unesco skos:related + SA provenance
    unesco_info = workspace.attach_extension("unesco")
    assert unesco_info.share_alike is True
    unesco_report = workspace.inspect_license_boundary(pack_ids=["unesco"])
    assert unesco_report.share_alike_triggered is True
    workspace.detach_extension("unesco")


def test_negative_edge_guard_explicit_opt_in(tmp_path: Path) -> None:
    """Contract §1.1(4): polarity=-1 edges excluded by default, returned only with include_negative=True."""
    db_path = tmp_path / "neg_edge_test.sqlite"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE kos_meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        INSERT INTO kos_meta VALUES ('schema_version', '1.0.0', '2026-01-01');
        CREATE TABLE kos_provenance (
            source_id TEXT PRIMARY KEY, source_name TEXT, version TEXT,
            license_spdx TEXT, dist_tier TEXT, attribution_text TEXT,
            homepage_url TEXT, fetched_at TEXT, notes TEXT
        );
        INSERT INTO kos_provenance VALUES ('TEST', 'Test', '1.0', 'CC0-1.0', 'dist_core', 'Test notice', NULL, '2026-01-01', NULL);
        CREATE TABLE kos_nodes (
            node_id TEXT PRIMARY KEY, spatial_id INTEGER, canonical_label_en TEXT, canonical_label_zh TEXT,
            label_zh_status TEXT, facet_type TEXT, source_id TEXT, source_code TEXT, wikidata_qid TEXT,
            parent_id TEXT, depth INTEGER, is_root INTEGER, breadcrumb_path TEXT, definition_summary TEXT,
            definition_status TEXT, info_content REAL, map_x REAL, map_y REAL, domain_partition_id TEXT,
            min_zoom_tier INTEGER, met_value REAL, geo_lat REAL, geo_lon REAL, extra_json TEXT
        );
        INSERT INTO kos_nodes VALUES
            ('n1', 1, 'Walking', '步行', 'native', 'ACTIVITY', 'TEST', '1', NULL, NULL, 1, 0, 'Act > Walking', NULL, 'missing', 3.0, 100, 100, 'p1', 1, NULL, NULL, NULL, NULL),
            ('n2', 2, 'Running', '跑步', 'native', 'ACTIVITY', 'TEST', '2', NULL, NULL, 1, 0, 'Act > Running', NULL, 'missing', 3.0, 120, 120, 'p1', 1, NULL, NULL, NULL, NULL),
            ('n3', 3, 'Wheelchair Exclusion', '轮椅排除项', 'native', 'ACTIVITY', 'TEST', '3', NULL, NULL, 1, 0, 'Act > Wheelchair', NULL, 'missing', 3.0, 140, 140, 'p1', 1, NULL, NULL, NULL, NULL);
        CREATE TABLE kos_edges (
            source_id TEXT, target_id TEXT, relation_type TEXT, weight REAL,
            polarity INTEGER, provenance_source_id TEXT, evidence_json TEXT
        );
        INSERT INTO kos_edges VALUES
            ('n1', 'n2', 'skos:related', 0.9, 1, 'TEST', NULL),
            ('n1', 'n3', 'icf:excludes', 1.0, -1, 'TEST', '{"note": "negative exclusion"}');
        """
    )
    con.commit()
    con.close()

    with KosWorkspace.open_workspace(db_path) as ws:
        sub_default = ws.traverse_multi_hop(["n1"], max_hops=1, include_negative=False, min_ic=1.5)
        assert {e.target_id for e in sub_default.edges} == {"n2"}

        sub_with_neg = ws.traverse_multi_hop(["n1"], max_hops=1, include_negative=True, min_ic=1.5)
        assert {e.target_id for e in sub_with_neg.edges} == {"n2", "n3"}
        neg_edges = [e for e in sub_with_neg.edges if e.polarity == -1]
        assert len(neg_edges) == 1
        assert neg_edges[0].relation_type == "icf:excludes"


def test_spatial_viewport_and_voronoi_partitions(workspace: KosWorkspace) -> None:
    """Contract §1.1(6): R*Tree 4-tier LoD viewport capped <= 5000 + Voronoi GeoJSON polygons."""
    vp0 = workspace.query_viewport((0, 0, 10000, 10000), zoom_tier=0, limit=5000)
    assert 0 < vp0.total_returned <= 50
    assert all(n.min_zoom_tier == 0 for n in vp0.nodes)

    vp3 = workspace.query_viewport((0, 0, 10000, 10000), zoom_tier=3, limit=99999)
    assert vp3.total_returned == 5000
    assert vp3.truncated is True

    parts = workspace.get_map_partitions()
    assert len(parts) > 5
    for p in parts[:5]:
        assert p.geometry.get("type") in ("Polygon", "MultiPolygon")
        assert len(p.geometry.get("coordinates", [])) > 0
