"""Independent writable DB III (`personal_bridge.sqlite`) persistence manager.

Hard architectural invariant (DEC-02 / DEC-20):
DB III is strictly separate from L1 DB II (`kos_build/release/human_kos_*.sqlite`).
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kos_engine.bridge.models import (
    FacetBinding,
    NodeActivationRecord,
    SessionInput,
    SessionRecord,
)

_BRIDGE_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS bridge_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bridge_sessions (
    session_uid         TEXT PRIMARY KEY,
    source_client       TEXT NOT NULL,
    external_session_id TEXT NOT NULL,
    content_sha256      TEXT NOT NULL,
    title               TEXT NOT NULL,
    excerpt             TEXT NOT NULL DEFAULT '',
    turn_count          INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    imported_at         TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    UNIQUE (source_client, external_session_id)
);

CREATE INDEX IF NOT EXISTS idx_bridge_sessions_sha ON bridge_sessions(content_sha256);
CREATE INDEX IF NOT EXISTS idx_bridge_sessions_updated ON bridge_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS bridge_mappings (
    mapping_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uid     TEXT NOT NULL REFERENCES bridge_sessions(session_uid) ON DELETE CASCADE,
    facet_type      TEXT NOT NULL CHECK (facet_type IN ('DOMAIN', 'ACTIVITY', 'PROCESS', 'ARTIFACT', 'STANCE')),
    node_id         TEXT NOT NULL,
    pack_id         TEXT NOT NULL DEFAULT 'core',
    canonical_label TEXT NOT NULL DEFAULT '',
    breadcrumb_path TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 1.0,
    binding_source  TEXT NOT NULL DEFAULT 'user_attach',
    attached_at     TEXT NOT NULL,
    UNIQUE (session_uid, facet_type, node_id)
);

CREATE INDEX IF NOT EXISTS idx_bridge_mappings_node ON bridge_mappings(node_id);
CREATE INDEX IF NOT EXISTS idx_bridge_mappings_facet ON bridge_mappings(facet_type, node_id);

CREATE TABLE IF NOT EXISTS bridge_node_activation (
    node_id         TEXT PRIMARY KEY,
    facet_type      TEXT NOT NULL CHECK (facet_type IN ('DOMAIN', 'ACTIVITY', 'PROCESS', 'ARTIFACT', 'STANCE')),
    pack_id         TEXT NOT NULL DEFAULT 'core',
    canonical_label TEXT NOT NULL DEFAULT '',
    touch_count     INTEGER NOT NULL DEFAULT 1,
    base_activation REAL NOT NULL DEFAULT 1.0,
    last_touched_at TEXT NOT NULL,
    half_life_days  REAL NOT NULL DEFAULT 14.0
);

CREATE TABLE IF NOT EXISTS bridge_briefings (
    briefing_id           TEXT PRIMARY KEY,
    generated_at          TEXT NOT NULL,
    seed_count            INTEGER NOT NULL DEFAULT 0,
    item_count            INTEGER NOT NULL DEFAULT 0,
    share_alike_triggered INTEGER NOT NULL DEFAULT 0,
    local_only_triggered  INTEGER NOT NULL DEFAULT 0,
    briefing_json         TEXT NOT NULL,
    briefing_markdown     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bridge_import_receipts (
    receipt_id             TEXT PRIMARY KEY,
    source_client          TEXT NOT NULL,
    input_sha256           TEXT NOT NULL,
    dry_run                INTEGER NOT NULL DEFAULT 0,
    total_seen             INTEGER NOT NULL DEFAULT 0,
    inserted_count         INTEGER NOT NULL DEFAULT 0,
    updated_count          INTEGER NOT NULL DEFAULT 0,
    skipped_count          INTEGER NOT NULL DEFAULT 0,
    private_filtered_count INTEGER NOT NULL DEFAULT 0,
    imported_at            TEXT NOT NULL
);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: str) -> datetime:
    cleaned = ts.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def compute_content_sha256(title: str, content_text: str) -> str:
    payload = f"{(title or '').strip()}\n---\n{(content_text or '').strip()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_effective_activation(
    base_activation: float,
    last_touched_at: str,
    half_life_days: float = 14.0,
    now: Optional[datetime] = None,
) -> float:
    ref = now or datetime.now(timezone.utc)
    dt = _parse_iso(last_touched_at)
    age_days = max(0.0, (ref - dt).total_seconds() / 86400.0)
    hl = max(0.5, float(half_life_days))
    return round(float(base_activation) * math.pow(0.5, age_days / hl), 6)


class PersonalBridgeDB:
    """Writable personal mapping ledger (DB III: `personal_bridge.sqlite`)."""

    SCHEMA_VERSION = "1.0.0"

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).resolve()
        # Hard guard: never write DB III into L1 release artifacts
        lower_parts = [p.lower() for p in self.db_path.parts]
        if "human_kos_core.sqlite" in lower_parts or "human_kos_ext" in lower_parts:
            raise ValueError(f"Refusing to place DB III inside L1 database path: {self.db_path}")
        if self.db_path.name.lower().startswith("human_kos_"):
            raise ValueError(f"DB III filename must not collide with L1 DB II naming: {self.db_path.name}")

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._con.executescript(_BRIDGE_DDL)
            now = _utcnow_iso()
            self._con.execute(
                """
                INSERT INTO bridge_meta (key, value, updated_at)
                VALUES ('schema_version', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (self.SCHEMA_VERSION, now),
            )
            self._con.commit()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def __enter__(self) -> "PersonalBridgeDB":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def upsert_session(self, session: SessionInput) -> Tuple[SessionRecord, bool, str]:
        """Insert or update a session using dual-key idempotency (`source_client`+`external_id` & `content_sha256`).

        Returns `(record, reconnected_by_fingerprint, action)` where action is 'inserted' | 'updated' | 'unchanged'.
        """
        now = _utcnow_iso()
        content_sha = compute_content_sha256(session.title, session.content_text)
        excerpt = (session.excerpt or session.content_text or session.title).strip()[:280]
        created_at = session.created_at or now
        updated_at = session.updated_at or now
        meta_json = json.dumps(session.metadata or {}, ensure_ascii=False)

        with self._lock:
            existing = self._con.execute(
                """
                SELECT * FROM bridge_sessions
                WHERE source_client = ? AND external_session_id = ?
                """,
                (session.source_client, session.external_session_id),
            ).fetchone()

            if existing is not None:
                if (
                    existing["content_sha256"] == content_sha
                    and existing["title"] == session.title
                    and int(existing["turn_count"]) == int(session.turn_count)
                ):
                    return self.get_session(str(existing["session_uid"])), False, "unchanged"
                self._con.execute(
                    """
                    UPDATE bridge_sessions
                    SET content_sha256 = ?, title = ?, excerpt = ?, turn_count = ?,
                        updated_at = ?, metadata_json = ?
                    WHERE session_uid = ?
                    """,
                    (
                        content_sha,
                        session.title,
                        excerpt,
                        int(session.turn_count),
                        updated_at,
                        meta_json,
                        existing["session_uid"],
                    ),
                )
                self._con.commit()
                return self.get_session(str(existing["session_uid"])), False, "updated"

            # R4 cross-client migration reconnection by content_sha256 fingerprint
            fp_match = self._con.execute(
                "SELECT * FROM bridge_sessions WHERE content_sha256 = ? LIMIT 1",
                (content_sha,),
            ).fetchone()
            reconnected = False
            if fp_match is not None:
                reconnected = True
                session_uid = str(fp_match["session_uid"])
                # Merge alias info into metadata rather than duplicating mappings
                old_meta = json.loads(fp_match["metadata_json"] or "{}")
                aliases = list(old_meta.get("client_aliases", []))
                alias_entry = {
                    "source_client": session.source_client,
                    "external_session_id": session.external_session_id,
                }
                if alias_entry not in aliases:
                    aliases.append(alias_entry)
                old_meta["client_aliases"] = aliases
                self._con.execute(
                    """
                    UPDATE bridge_sessions
                    SET updated_at = ?, metadata_json = ?
                    WHERE session_uid = ?
                    """,
                    (updated_at, json.dumps(old_meta, ensure_ascii=False), session_uid),
                )
                self._con.commit()
                return self.get_session(session_uid), reconnected, "updated"

            session_uid = f"sess_{uuid.uuid4().hex[:16]}"
            self._con.execute(
                """
                INSERT INTO bridge_sessions (
                    session_uid, source_client, external_session_id, content_sha256,
                    title, excerpt, turn_count, created_at, updated_at, imported_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_uid,
                    session.source_client,
                    session.external_session_id,
                    content_sha,
                    session.title,
                    excerpt,
                    int(session.turn_count),
                    created_at,
                    updated_at,
                    now,
                    meta_json,
                ),
            )
            self._con.commit()
            return self.get_session(session_uid), False, "inserted"

    def get_session(self, session_uid: str) -> Optional[SessionRecord]:
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM bridge_sessions WHERE session_uid = ?",
                (session_uid,),
            ).fetchone()
            if row is None:
                return None
            mrows = self._con.execute(
                """
                SELECT facet_type, node_id, pack_id, canonical_label, breadcrumb_path,
                       confidence, binding_source, attached_at
                FROM bridge_mappings
                WHERE session_uid = ?
                ORDER BY facet_type, attached_at DESC
                """,
                (session_uid,),
            ).fetchall()
            mappings = [FacetBinding(**dict(m)) for m in mrows]
            return SessionRecord(
                session_uid=str(row["session_uid"]),
                source_client=str(row["source_client"]),
                external_session_id=str(row["external_session_id"]),
                content_sha256=str(row["content_sha256"]),
                title=str(row["title"]),
                excerpt=str(row["excerpt"]),
                turn_count=int(row["turn_count"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                imported_at=str(row["imported_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
                mappings=mappings,
            )

    def list_sessions(self, limit: int = 50, source_client: Optional[str] = None) -> List[SessionRecord]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            if source_client:
                rows = self._con.execute(
                    """
                    SELECT session_uid FROM bridge_sessions
                    WHERE source_client = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (source_client, limit),
                ).fetchall()
            else:
                rows = self._con.execute(
                    "SELECT session_uid FROM bridge_sessions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [s for r in rows if (s := self.get_session(str(r["session_uid"]))) is not None]

    def add_mappings(self, session_uid: str, bindings: List[FacetBinding], *, half_life_days: float = 14.0) -> List[FacetBinding]:
        now = _utcnow_iso()
        applied: List[FacetBinding] = []
        with self._lock:
            for b in bindings:
                self._con.execute(
                    """
                    INSERT INTO bridge_mappings (
                        session_uid, facet_type, node_id, pack_id,
                        canonical_label, breadcrumb_path, confidence, binding_source, attached_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_uid, facet_type, node_id) DO UPDATE SET
                        confidence = excluded.confidence,
                        canonical_label = excluded.canonical_label,
                        breadcrumb_path = excluded.breadcrumb_path,
                        attached_at = excluded.attached_at
                    """,
                    (
                        session_uid,
                        b.facet_type,
                        b.node_id,
                        b.pack_id,
                        b.canonical_label,
                        b.breadcrumb_path,
                        float(b.confidence),
                        b.binding_source,
                        now,
                    ),
                )
                # Update node activation ledger with decay-aware accumulation
                act = self._con.execute(
                    "SELECT touch_count, base_activation, last_touched_at, half_life_days FROM bridge_node_activation WHERE node_id = ?",
                    (b.node_id,),
                ).fetchone()
                if act is None:
                    self._con.execute(
                        """
                        INSERT INTO bridge_node_activation (
                            node_id, facet_type, pack_id, canonical_label,
                            touch_count, base_activation, last_touched_at, half_life_days
                        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                        """,
                        (b.node_id, b.facet_type, b.pack_id, b.canonical_label, float(b.confidence), now, half_life_days),
                    )
                else:
                    decayed = compute_effective_activation(
                        float(act["base_activation"]),
                        str(act["last_touched_at"]),
                        float(act["half_life_days"]),
                    )
                    new_base = round(decayed + float(b.confidence), 6)
                    self._con.execute(
                        """
                        UPDATE bridge_node_activation
                        SET touch_count = touch_count + 1,
                            base_activation = ?,
                            last_touched_at = ?,
                            canonical_label = ?
                        WHERE node_id = ?
                        """,
                        (new_base, now, b.canonical_label, b.node_id),
                    )
                applied.append(b.model_copy(update={"attached_at": now}))
            self._con.commit()
        return applied

    def list_activations(self, limit: int = 100, now: Optional[datetime] = None) -> List[NodeActivationRecord]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._con.execute(
                """
                SELECT node_id, facet_type, pack_id, canonical_label,
                       touch_count, base_activation, last_touched_at, half_life_days
                FROM bridge_node_activation
                """
            ).fetchall()
        out = [
            NodeActivationRecord(
                node_id=str(r["node_id"]),
                facet_type=r["facet_type"],
                pack_id=str(r["pack_id"]),
                canonical_label=str(r["canonical_label"]),
                touch_count=int(r["touch_count"]),
                base_activation=float(r["base_activation"]),
                effective_activation=compute_effective_activation(
                    float(r["base_activation"]),
                    str(r["last_touched_at"]),
                    float(r["half_life_days"]),
                    now=now,
                ),
                last_touched_at=str(r["last_touched_at"]),
                half_life_days=float(r["half_life_days"]),
            )
            for r in rows
        ]
        out.sort(key=lambda r: (r.effective_activation, r.touch_count), reverse=True)
        return out[:limit]

    def save_briefing(self, briefing_id: str, generated_at: str, seed_count: int, item_count: int, share_alike: bool, local_only: bool, briefing_json: str, briefing_markdown: str) -> None:
        with self._lock:
            self._con.execute(
                """
                INSERT OR REPLACE INTO bridge_briefings (
                    briefing_id, generated_at, seed_count, item_count,
                    share_alike_triggered, local_only_triggered, briefing_json, briefing_markdown
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    briefing_id,
                    generated_at,
                    int(seed_count),
                    int(item_count),
                    1 if share_alike else 0,
                    1 if local_only else 0,
                    briefing_json,
                    briefing_markdown,
                ),
            )
            self._con.commit()

    def list_briefings(self, limit: int = 20) -> List[Dict]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._con.execute(
                """
                SELECT briefing_id, generated_at, seed_count, item_count,
                       share_alike_triggered, local_only_triggered, briefing_json, briefing_markdown
                FROM bridge_briefings
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [json.loads(r["briefing_json"]) for r in rows]

    def record_import_receipt(
        self,
        source_client: str,
        input_sha256: str,
        dry_run: bool,
        total_seen: int,
        inserted_count: int,
        updated_count: int,
        skipped_count: int,
        private_filtered_count: int = 0,
    ) -> str:
        receipt_id = f"imp_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._con.execute(
                """
                INSERT INTO bridge_import_receipts (
                    receipt_id, source_client, input_sha256, dry_run,
                    total_seen, inserted_count, updated_count, skipped_count,
                    private_filtered_count, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    source_client,
                    input_sha256,
                    1 if dry_run else 0,
                    int(total_seen),
                    int(inserted_count),
                    int(updated_count),
                    int(skipped_count),
                    int(private_filtered_count),
                    _utcnow_iso(),
                ),
            )
            self._con.commit()
        return receipt_id

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "sessions": int(self._con.execute("SELECT COUNT(*) FROM bridge_sessions").fetchone()[0]),
                "mappings": int(self._con.execute("SELECT COUNT(*) FROM bridge_mappings").fetchone()[0]),
                "active_nodes": int(self._con.execute("SELECT COUNT(*) FROM bridge_node_activation").fetchone()[0]),
                "briefings": int(self._con.execute("SELECT COUNT(*) FROM bridge_briefings").fetchone()[0]),
                "import_receipts": int(self._con.execute("SELECT COUNT(*) FROM bridge_import_receipts").fetchone()[0]),
            }
