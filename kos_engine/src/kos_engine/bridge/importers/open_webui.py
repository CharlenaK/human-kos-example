"""Open WebUI v0.13.4 native chat export/API importer (DB I -> DB III)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Union

from kos_engine.bridge.db import PersonalBridgeDB, compute_content_sha256
from kos_engine.bridge.models import ImportPreviewItem, ImportResult, SessionInput


def _ts_to_iso(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        # Open WebUI stores Unix epoch seconds or milliseconds
        sec = float(val) / 1000.0 if float(val) > 1e12 else float(val)
        return datetime.fromtimestamp(sec, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return str(val)


def _extract_messages_text(chat_obj: Dict[str, Any]) -> tuple[str, int]:
    messages: List[Dict[str, Any]] = []
    if isinstance(chat_obj.get("messages"), list):
        messages = chat_obj["messages"]
    elif isinstance(chat_obj.get("history"), dict) and isinstance(chat_obj["history"].get("messages"), dict):
        messages = list(chat_obj["history"]["messages"].values())

    parts: List[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if isinstance(content, list):
            text_bits = [str(c.get("text", "")) for c in content if isinstance(c, dict) and c.get("type") == "text"]
            content = "\n".join(text_bits)
        text = str(content).strip()
        if text:
            parts.append(f"[{role}] {text}")
    return "\n".join(parts), max(1, len(messages))


def parse_open_webui_payload(payload: Union[List[Dict[str, Any]], Dict[str, Any]]) -> List[SessionInput]:
    raw_items: List[Dict[str, Any]]
    if isinstance(payload, list):
        raw_items = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        if isinstance(payload.get("chats"), list):
            raw_items = [x for x in payload["chats"] if isinstance(x, dict)]
        else:
            raw_items = [payload]
    else:
        raise ValueError("Unsupported Open WebUI export JSON structure")

    sessions: List[SessionInput] = []
    for idx, item in enumerate(raw_items):
        chat_obj = item.get("chat") if isinstance(item.get("chat"), dict) else item
        ext_id = str(item.get("id") or chat_obj.get("id") or f"owui_{idx}")
        title = str(item.get("title") or chat_obj.get("title") or f"Open WebUI Chat {ext_id}").strip()
        text, turn_count = _extract_messages_text(chat_obj)
        sessions.append(
            SessionInput(
                source_client="open_webui",
                external_session_id=ext_id,
                title=title,
                content_text=text,
                excerpt=text[:240] if text else title,
                turn_count=turn_count,
                created_at=_ts_to_iso(item.get("created_at") or chat_obj.get("timestamp")),
                updated_at=_ts_to_iso(item.get("updated_at") or chat_obj.get("timestamp")),
                metadata={"tags": item.get("meta", {}).get("tags", []) if isinstance(item.get("meta"), dict) else []},
            )
        )
    return sessions


def import_open_webui_export(
    bridge_db: PersonalBridgeDB,
    payload_or_path: Union[Path, str, List[Dict[str, Any]], Dict[str, Any]],
    *,
    dry_run: bool = False,
) -> ImportResult:
    """Import Open WebUI native chat export JSON into DB III idempotently."""
    if isinstance(payload_or_path, (Path, str)):
        p = Path(payload_or_path).resolve()
        raw_bytes = p.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
        input_sha = hashlib.sha256(raw_bytes).hexdigest()
    else:
        payload = payload_or_path
        input_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    sessions = parse_open_webui_payload(payload)
    items: List[ImportPreviewItem] = []
    inserted = updated = skipped = 0

    for s in sessions:
        sha = compute_content_sha256(s.title, s.content_text)
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
        source_client="open_webui",
        input_sha256=input_sha,
        dry_run=dry_run,
        total_seen=len(sessions),
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
    )
    return ImportResult(
        receipt_id=receipt_id,
        source_client="open_webui",
        dry_run=dry_run,
        total_seen=len(sessions),
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
        items=items,
    )
