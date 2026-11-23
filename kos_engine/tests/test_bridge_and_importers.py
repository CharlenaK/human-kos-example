"""Tests for DB III (personal_bridge.sqlite), /attach, serendipity, and DB I importers (P3-A3 & P3-A4)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kos_engine.bridge.attach import confirm_attach, propose_attach
from kos_engine.bridge.db import PersonalBridgeDB, compute_effective_activation
from kos_engine.bridge.importers.cherry_studio import import_cherry_studio_backup
from kos_engine.bridge.importers.open_webui import import_open_webui_export
from kos_engine.bridge.models import AttachConfirmRequest, FacetBinding, SessionInput
from kos_engine.bridge.serendipity import compute_topic_collections, generate_serendipity_briefing
from kos_engine.core.workspace import KosWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
L1_CORE = Path(
    os.environ.get("KOS_CORE_DB")
    or next(
        (
            str(b / r)
            for b in (REPO_ROOT, REPO_ROOT.parent)
            for r in ("kos_build/release/human_kos_core.sqlite", "data/human_kos_core.sqlite")
            if (b / r).is_file()
        ),
        str(REPO_ROOT / "data" / "human_kos_core.sqlite"),
    )
)
L1_EXT_DIR = Path(os.environ.get("KOS_EXT_DIR") or (L1_CORE.parent / "human_kos_ext"))


@pytest.fixture(scope="module")
def ws() -> KosWorkspace:
    w = KosWorkspace.open_workspace(L1_CORE, L1_EXT_DIR, model_dir=None)
    yield w
    w.close()


def test_db3_rejects_l1_collision(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        PersonalBridgeDB(tmp_path / "human_kos_core.sqlite")
    with pytest.raises(ValueError):
        PersonalBridgeDB(tmp_path / "human_kos_ext" / "personal_bridge.sqlite")


def test_attach_propose_confirm_decay_and_collections(ws: KosWorkspace, tmp_path: Path) -> None:
    db = PersonalBridgeDB(tmp_path / "personal_bridge.sqlite")
    try:
        proposal = propose_attach(ws, "知识图谱与大语言模型智能体系统架构", mode="bm25", top_k_per_facet=5)
        assert set(proposal.candidates_by_facet.keys()) == {"DOMAIN", "ACTIVITY", "PROCESS", "ARTIFACT", "STANCE"}

        # Pick real verified nodes from L1 (ensure at least one OA_TREE node with cooccur edges for serendipity)
        oa_row = ws._con.execute(
            """
            SELECT e.source_id, n.facet_type
            FROM kos_edges e
            JOIN kos_nodes n ON n.node_id = e.source_id
            WHERE e.relation_type = 'oa:cooccur' AND n.info_content >= 1.5 AND n.is_root = 0
            LIMIT 1
            """
        ).fetchone()
        assert oa_row is not None
        proc_cand = proposal.candidates_by_facet["PROCESS"][0]
        stance_row = ws._con.execute("SELECT node_id FROM kos_nodes WHERE facet_type = 'STANCE' LIMIT 1").fetchone()
        assert stance_row is not None

        bindings = [
            FacetBinding(facet_type=oa_row["facet_type"], node_id=str(oa_row["source_id"]), confidence=0.95),
            FacetBinding(facet_type="PROCESS", node_id=proc_cand.node_id, confidence=0.9),
            FacetBinding(facet_type="STANCE", node_id=str(stance_row["node_id"]), confidence=0.85),
        ]

        req = AttachConfirmRequest(
            session=SessionInput(
                source_client="open_webui",
                external_session_id="owui-chat-001",
                title="知识图谱与认知辅助系统架构探讨",
                content_text="讨论如何用五维正交分面与沿边遍历构建个人认知辅助系统。",
                turn_count=6,
            ),
            bindings=bindings,
        )
        res = confirm_attach(ws, db, req)
        assert len(res.applied_bindings) == 3
        assert res.reconnected_by_fingerprint is False
        assert res.session.session_uid.startswith("sess_")

        # Verify facet mismatch rejection
        with pytest.raises(ValueError, match="Facet mismatch"):
            confirm_attach(
                ws,
                db,
                AttachConfirmRequest(
                    session=req.session,
                    bindings=[FacetBinding(facet_type="ARTIFACT", node_id=proc_cand.node_id)],
                ),
            )

        # R4 cross-client migration reconnection via content_sha256
        migrated_req = AttachConfirmRequest(
            session=SessionInput(
                source_client="cherry_studio",
                external_session_id="cherry-topic-999",
                title=req.session.title,
                content_text=req.session.content_text,
                turn_count=6,
            ),
            bindings=[bindings[0]],
        )
        res2 = confirm_attach(ws, db, migrated_req)
        assert res2.reconnected_by_fingerprint is True
        assert res2.session.session_uid == res.session.session_uid

        # Activation decay math check
        past = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat().replace("+00:00", "Z")
        decayed = compute_effective_activation(2.0, past, half_life_days=14.0)
        assert 0.95 <= decayed <= 1.05

        # Dynamic Named Topic Collections
        collections = compute_topic_collections(db)
        assert len(collections) >= 1
        assert collections[0].session_count >= 1

        # Controlled Serendipity Briefing (deterministic, zero external LLM API)
        briefing = generate_serendipity_briefing(ws, db, max_hops=2, min_ic=1.5, top_k=6)
        assert briefing.seed_node_count >= 1
        assert len(briefing.items) >= 1
        assert all(it.info_content >= 1.5 for it in briefing.items)
        assert all(len(it.evidence_paths) >= 1 for it in briefing.items)
        assert "# 受控漫游简报" in briefing.markdown
        assert db.get_stats()["briefings"] == 1
    finally:
        db.close()


def test_open_webui_export_import_idempotent(tmp_path: Path) -> None:
    db = PersonalBridgeDB(tmp_path / "bridge.sqlite")
    export_data = [
        {
            "id": "chat-alpha",
            "title": "哲学认识论与形式化方法",
            "created_at": 1760000000,
            "updated_at": 1760003600,
            "chat": {
                "messages": [
                    {"role": "user", "content": "认识论中的基础主义与融贯论有什么区别？"},
                    {"role": "assistant", "content": "基础主义依赖自明信念，融贯论强调信念网络的一致性。"},
                ]
            },
        },
        {
            "id": "chat-beta",
            "title": "SQLite R-Tree 视口索引优化",
            "created_at": 1760010000,
            "chat": {
                "messages": [
                    {"role": "user", "content": "如何结合 R*Tree 和 LoD 分级加载 8 万个节点？"}
                ]
            },
        },
    ]
    export_file = tmp_path / "open_webui_export.json"
    export_file.write_text(json.dumps(export_data, ensure_ascii=False), encoding="utf-8")

    try:
        preview = import_open_webui_export(db, export_file, dry_run=True)
        assert preview.dry_run is True
        assert preview.inserted_count == 2
        assert db.get_stats()["sessions"] == 0

        committed = import_open_webui_export(db, export_file, dry_run=False)
        assert committed.inserted_count == 2
        assert db.get_stats()["sessions"] == 2

        # Re-importing the exact same file must produce 0 duplicates
        rerun = import_open_webui_export(db, export_file, dry_run=False)
        assert rerun.inserted_count == 0
        assert rerun.skipped_count == 2
        assert db.get_stats()["sessions"] == 2
    finally:
        db.close()


def test_cherry_studio_synthetic_sqlite_and_json_import(tmp_path: Path) -> None:
    """P3-A4: Verify synthetic Cherry Studio SQLite & JSON backup import + zero real-path scanning."""
    # Static check: cherry_studio.py must never scan user home / AppData
    importer_src = (
        REPO_ROOT / "kos_engine" / "src" / "kos_engine" / "bridge" / "importers" / "cherry_studio.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("AppData", "expanduser", "Path.home()", "USERPROFILE"):
        assert forbidden not in importer_src

    # Build synthetic Cherry Studio v2 SQLite fixture
    cherry_db = tmp_path / "synthetic_cherry_backup.sqlite"
    con = sqlite3.connect(cherry_db)
    con.executescript(
        """
        CREATE TABLE assistants (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE topics (id TEXT PRIMARY KEY, assistant_id TEXT, name TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE messages (id TEXT PRIMARY KEY, topic_id TEXT, role TEXT, searchable_text TEXT, data_json TEXT, created_at TEXT);
        INSERT INTO assistants VALUES ('asst-1', '研究助手');
        INSERT INTO topics VALUES
            ('topic-syn-1', 'asst-1', '计算神经科学与预测编码', '2026-10-01T10:00:00Z', '2026-10-01T10:30:00Z'),
            ('topic-syn-secret', 'asst-1', '密钥泄露测试样例', '2026-10-02T10:00:00Z', '2026-10-02T10:30:00Z');
        INSERT INTO messages VALUES
            ('m1', 'topic-syn-1', 'user', '预测编码框架如何解释视觉皮层的层级反馈？', NULL, '2026-10-01T10:00:00Z'),
            ('m2', 'topic-syn-1', 'assistant', '高层皮层向低层发送预测信号，低层仅上传预测误差。', NULL, '2026-10-01T10:05:00Z'),
            ('m3', 'topic-syn-secret', 'user', '测试过滤 sk-1234567890abcdef1234567890', NULL, '2026-10-02T10:00:00Z');
        """
    )
    con.commit()
    con.close()

    # Build synthetic Cherry Studio JSON fixture
    cherry_json = tmp_path / "synthetic_cherry_backup.json"
    cherry_json.write_text(
        json.dumps(
            {
                "indexedDB": {
                    "topics": [
                        {
                            "id": "topic-json-1",
                            "name": "宋代陶瓷釉色与窑变机理",
                            "createdAt": "2026-10-03T08:00:00Z",
                            "messages": [
                                {"role": "user", "content": "钧窑铜红釉在还原气氛中的呈色机理是什么？"}
                            ],
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = PersonalBridgeDB(tmp_path / "bridge.sqlite")
    try:
        # 1. SQLite backup dry-run (default)
        dry = import_cherry_studio_backup(db, cherry_db)
        assert dry.dry_run is True
        assert dry.inserted_count == 1
        assert dry.private_filtered_count == 1
        assert db.get_stats()["sessions"] == 0

        # 2. SQLite backup commit + idempotent rerun
        res = import_cherry_studio_backup(db, cherry_db, dry_run=False)
        assert res.inserted_count == 1
        assert res.private_filtered_count == 1
        assert db.get_stats()["sessions"] == 1

        rerun = import_cherry_studio_backup(db, cherry_db, dry_run=False)
        assert rerun.inserted_count == 0
        assert rerun.skipped_count == 1

        # 3. JSON backup commit
        res_json = import_cherry_studio_backup(db, cherry_json, dry_run=False)
        assert res_json.inserted_count == 1
        assert db.get_stats()["sessions"] == 2
    finally:
        db.close()
