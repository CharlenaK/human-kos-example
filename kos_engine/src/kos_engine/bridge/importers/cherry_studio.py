"""Cherry Studio backup read-only importer (SQLite v2 & JSON backup formats).

Hard privacy & scope boundary (DEC-28 / G-P3-05e revised):
- Requires an EXPLICIT `backup_path` supplied by the caller.
- Never auto-discovers, scans, or reads any default user data directory.
- Opens SQLite backup files strictly in read-only mode (`mode=ro` + `PRAGMA query_only = ON`).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from kos_engine.bridge.db import PersonalBridgeDB, compute_content_sha256
from kos_engine.bridge.models import ImportPreviewItem, ImportResult, SessionInput

_SECRET_PATTERNS = [
    re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{20,})"),
    re.compile(r"BEGIN\s+(?:RSA|OPENSSH|EC)\s+PRIVATE\s+KEY"),
    re.compile(r"(?:api[_-]?key|secret[_-]?key|password)\s*[:=]\s*\S+", re.IGNORECASE),
]


def _has_secret_signal(text: str) -> bool:
    for pat in _SECRET_PATTERNS:
        if pat.search(text or ""):
            return True
    return False


def _readonly_uri(path: Path) -> str:
    posix = path.resolve().as_posix()
    encoded = quote(posix, safe="/:")
    if not encoded.startswith("/"):
        encoded = "/" + encoded
    return f"file:{encoded}?mode=ro"


def _extract_block_text(data_json: Optional[str]) -> str:
    if not data_json:
        return ""
    try:
        obj = json.loads(data_json)
    except Exception:
        return str(data_json)
    if isinstance(obj, dict):
        if isinstance(obj.get("content"), str):
            return obj["content"]
        if isinstance(obj.get("blocks"), list):
            parts = [str(b.get("content", "")) for b in obj["blocks"] if isinstance(b, dict) and b.get("content")]
            return "\n".join(parts)
        if isinstance(obj.get("messages"), list):
            parts = []
            for m in obj["messages"]:
                if isinstance(m, dict):
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    if isinstance(content, str) and content.strip():
                        parts.append(f"[{role}] {content.strip()}")
            return "\n".join(parts)
    return ""


def _parse_cherry_sqlite(backup_path: Path) -> List[SessionInput]:
    con = sqlite3.connect(_readonly_uri(backup_path), uri=True, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON;")
    try:
        tables = {str(r[0]) for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "topics" not in tables:
            raise ValueError(f"Unsupported Cherry Studio SQLite schema (missing 'topics' table): {sorted(tables)}")

        assistants: Dict[str, str] = {}
        if "assistants" in tables:
            cols = {str(r[1]) for r in con.execute("PRAGMA table_info(assistants)").fetchall()}
            name_col = "name" if "name" in cols else ("title" if "title" in cols else None)
            if name_col and "id" in cols:
                for ar in con.execute(f"SELECT id, {name_col} AS name FROM assistants").fetchall():
                    assistants[str(ar["id"])] = str(ar["name"] or "")

        topic_cols = {str(r[1]) for r in con.execute("PRAGMA table_info(topics)").fetchall()}
        msg_cols = {str(r[1]) for r in con.execute("PRAGMA table_info(messages)").fetchall()} if "messages" in tables else set()

        sessions: List[SessionInput] = []
        for tr in con.execute("SELECT * FROM topics").fetchall():
            td = dict(tr)
            tid = str(td.get("id") or td.get("topic_id") or "")
            if not tid:
                continue
            title = str(td.get("name") or td.get("title") or f"Topic {tid}").strip()
            assistant_id = str(td.get("assistant_id") or "")
            assistant_name = assistants.get(assistant_id, "")

            parts: List[str] = []
            turn_count = 0
            if "messages" in tables and "topic_id" in msg_cols:
                order_col = "created_at" if "created_at" in msg_cols else "rowid"
                mrows = con.execute(
                    f"SELECT * FROM messages WHERE topic_id = ? ORDER BY {order_col} ASC",
                    (tid,),
                ).fetchall()
                for mr in mrows:
                    md = dict(mr)
                    role = str(md.get("role") or "user")
                    txt = str(md.get("searchable_text") or md.get("content") or "").strip()
                    if not txt and md.get("data_json"):
                        txt = _extract_block_text(md.get("data_json")).strip()
                    if txt:
                        parts.append(f"[{role}] {txt}")
                        turn_count += 1
            elif "data_json" in topic_cols and td.get("data_json"):
                txt = _extract_block_text(td["data_json"]).strip()
                if txt:
                    parts.append(txt)
                    turn_count = max(1, txt.count("\n") + 1)

            full_text = "\n".join(parts)
            sessions.append(
                SessionInput(
                    source_client="cherry_studio",
                    external_session_id=tid,
                    title=title,
                    content_text=full_text,
                    excerpt=(full_text[:240] if full_text else title),
                    turn_count=max(1, turn_count),
                    created_at=str(td["created_at"]) if td.get("created_at") else None,
                    updated_at=str(td["updated_at"]) if td.get("updated_at") else None,
                    metadata={"assistant_name": assistant_name} if assistant_name else {},
                )
            )
        return sessions
    finally:
        con.close()


def _parse_cherry_json(backup_path: Path) -> List[SessionInput]:
    data = json.loads(backup_path.read_text(encoding="utf-8"))
    topics_raw: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        if isinstance(data.get("topics"), list):
            topics_raw = data["topics"]
        elif isinstance(data.get("indexedDB"), dict) and isinstance(data["indexedDB"].get("topics"), list):
            topics_raw = data["indexedDB"]["topics"]
    elif isinstance(data, list):
        topics_raw = data

    sessions: List[SessionInput] = []
    for idx, t in enumerate(topics_raw):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or f"cherry_json_{idx}")
        title = str(t.get("name") or t.get("title") or f"Topic {tid}").strip()
        msgs = t.get("messages") if isinstance(t.get("messages"), list) else []
        parts: List[str] = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "user")
            content = str(m.get("content") or "").strip()
            if not content and isinstance(m.get("blocks"), list):
                content = "\n".join(str(b.get("content", "")) for b in m["blocks"] if isinstance(b, dict))
            if content.strip():
                parts.append(f"[{role}] {content.strip()}")
        full_text = "\n".join(parts)
        sessions.append(
            SessionInput(
                source_client="cherry_studio",
                external_session_id=tid,
                title=title,
                content_text=full_text,
                excerpt=(full_text[:240] if full_text else title),
                turn_count=max(1, len(msgs)),
                created_at=str(t["createdAt"]) if t.get("createdAt") else None,
                updated_at=str(t["updatedAt"]) if t.get("updatedAt") else None,
                metadata={"format": "cherry_json_backup"},
            )
        )
    return sessions


def import_cherry_studio_backup(
    bridge_db: PersonalBridgeDB,
    backup_path: Path | str,
    *,
    dry_run: bool = True,
    filter_secrets: bool = True,
) -> ImportResult:
    """Import an explicitly provided Cherry Studio SQLite or JSON backup into DB III.

    Defaults to `dry_run=True` so callers preview changes before committing.
    """
    path = Path(backup_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Cherry Studio backup file not found: {path}")

    raw_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    suffix = path.suffix.lower()
    if suffix in (".sqlite", ".sqlite3", ".db"):
        sessions = _parse_cherry_sqlite(path)
    elif suffix == ".json":
        sessions = _parse_cherry_json(path)
    else:
        raise ValueError(f"Unsupported Cherry Studio backup extension '{suffix}'; expected .sqlite/.db or .json")

    items: List[ImportPreviewItem] = []
    inserted = updated = skipped = private_filtered = 0

    for s in sessions:
        sha = compute_content_sha256(s.title, s.content_text)
        if filter_secrets and _has_secret_signal(f"{s.title}\n{s.content_text}"):
            private_filtered += 1
            items.append(
                ImportPreviewItem(
                    external_session_id=s.external_session_id,
                    title=s.title,
                    turn_count=s.turn_count,
                    content_sha256=sha,
                    status="skip_private",
                    reason="Detected potential credential/secret pattern",
                )
            )
            continue

        if dry_run:
            existing = bridge_db._con.execute(
                "SELECT content_sha256 FROM bridge_sessions WHERE source_client = ? AND external_session_id = ?",
                (s.source_client, s.external_session_id),
            ).fetchone()
            if existing is None:
                status = "new"
                inserted += 1
            elif existing["content_sha256"] == sha:
                status = "skip_duplicate"
                skipped += 1
            else:
                status = "update"
                updated += 1
            items.append(
                ImportPreviewItem(
                    external_session_id=s.external_session_id,
                    title=s.title,
                    turn_count=s.turn_count,
                    content_sha256=sha,
                    status=status,
                )
            )
        else:
            _, _, action = bridge_db.upsert_session(s)
            if action == "inserted":
                status = "new"
                inserted += 1
            elif action == "updated":
                status = "update"
                updated += 1
            else:
                status = "skip_duplicate"
                skipped += 1
            items.append(
                ImportPreviewItem(
                    external_session_id=s.external_session_id,
                    title=s.title,
                    turn_count=s.turn_count,
                    content_sha256=sha,
                    status=status,
                )
            )

    receipt_id = bridge_db.record_import_receipt(
        source_client="cherry_studio",
        input_sha256=raw_sha,
        dry_run=dry_run,
        total_seen=len(sessions),
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
        private_filtered_count=private_filtered,
    )
    return ImportResult(
        receipt_id=receipt_id,
        source_client="cherry_studio",
        dry_run=dry_run,
        total_seen=len(sessions),
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
        private_filtered_count=private_filtered,
        items=items,
    )
