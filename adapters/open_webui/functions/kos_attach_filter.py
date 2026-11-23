"""
title: Human KOS Five-Facet /attach Filter
author: Human KOS Phase 3 Reference Adapter
version: 0.1.0
license: MIT
description: Zero-fork Open WebUI v0.13.4 Filter Function that intercepts /attach commands, queries standalone kos-engine for strictly isolated 5-facet candidates, and writes confirmed anchors to DB III (personal_bridge.sqlite).
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

_ATTACH_CONFIRM_RE = re.compile(r"^/attach\s+confirm\s+(.+)$", re.IGNORECASE | re.DOTALL)
_ATTACH_PROPOSE_RE = re.compile(r"^/attach(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_FACET_ORDER = ("DOMAIN", "ACTIVITY", "PROCESS", "ARTIFACT", "STANCE")


def _extract_last_user_text(messages: List[Dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return "\n".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip()
    return ""


def _parse_confirm_bindings(spec: str) -> List[Dict[str, Any]]:
    """Parse `FACET:node_id` pairs separated by commas or whitespace."""
    bindings: List[Dict[str, Any]] = []
    for token in re.split(r"[\s,，;；]+", spec.strip()):
        if not token or ":" not in token:
            continue
        facet, node_id = token.split(":", 1)
        facet_up = facet.strip().upper()
        node_id = node_id.strip()
        if facet_up in _FACET_ORDER and node_id:
            bindings.append(
                {
                    "facet_type": facet_up,
                    "node_id": node_id,
                    "pack_id": "core",
                    "confidence": 0.95,
                    "binding_source": "user_attach",
                }
            )
    return bindings


def _format_proposal_context(proposal: Dict[str, Any], map_url: str) -> str:
    by_facet = proposal.get("candidates_by_facet", {})
    boundary = proposal.get("license_boundary", {})
    lines = [
        "[Human KOS /attach 五维正交分面隔离候选（来自独立只读 L1 + kos-engine）]",
        "规则：以下五个分面物理隔离，不应跨分面混排；请向用户分面呈现候选，由用户确认后使用 `/attach confirm FACET:node_id ...` 写回 DB III。",
        f"2D 知识世界地图：{map_url}",
        "",
    ]
    for facet in _FACET_ORDER:
        cands = by_facet.get(facet, [])
        lines.append(f"### {facet} ({len(cands)})")
        if not cands:
            lines.append("- （无匹配候选）")
        for c in cands[:5]:
            lbl = c.get("canonical_label_zh") or c.get("canonical_label_en") or c.get("node_id")
            lines.append(
                f"- `{facet}:{c['node_id']}` **{lbl}** — {c.get('breadcrumb_path', '')} "
                f"(IC={c.get('info_content', 0):.2f}, {c.get('license_spdx', '')})"
            )
    if boundary.get("share_alike_triggered"):
        lines.append(f"\n> ShareAlike 合规提示：{boundary.get('summary', '')}")
    return "\n".join(lines)


class Filter:
    class Valves(BaseModel):
        kos_api_url: str = Field(
            default="http://127.0.0.1:8787",
            description="Local kos-engine HTTP API base URL",
        )
        retrieval_mode: str = Field(
            default="hybrid",
            description="Retrieval mode: hybrid | bm25 | vector",
        )
        top_k_per_facet: int = Field(
            default=5,
            ge=1,
            le=20,
            description="Maximum isolated candidates returned per facet",
        )
        timeout_seconds: float = Field(
            default=10.0,
            ge=1.0,
            le=60.0,
            description="HTTP request timeout to kos-engine",
        )
        auto_premount: bool = Field(
            default=False,
            description="Optional silent read-only 5-facet grounding without /attach prefix",
        )

    class UserValves(BaseModel):
        enabled: bool = Field(default=True, description="Enable /attach filter for this user")

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.valves = self.Valves()
        self._injected_client = http_client

    async def _emit_status(
        self,
        emitter: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
        description: str,
        done: bool = True,
    ) -> None:
        if emitter is not None:
            await emitter({"type": "status", "data": {"description": description, "done": done}})

    async def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        base = self.valves.kos_api_url.rstrip("/")
        if self._injected_client is not None:
            resp = await self._injected_client.post(f"{base}{path}", json=payload)
            resp.raise_for_status()
            return resp.json()
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
            resp = await client.post(f"{base}{path}", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def inlet(
        self,
        body: Dict[str, Any],
        __user__: Optional[Dict[str, Any]] = None,
        __event_emitter__: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return body

        user_text = _extract_last_user_text(messages)
        if not user_text:
            return body

        m_confirm = _ATTACH_CONFIRM_RE.match(user_text)
        if m_confirm:
            bindings = _parse_confirm_bindings(m_confirm.group(1))
            if not bindings:
                await self._emit_status(__event_emitter__, "未解析到有效的 FACET:node_id 绑定项", done=True)
                return body
            chat_id = str(body.get("chat_id") or body.get("metadata", {}).get("chat_id") or "owui-session")
            title = str(body.get("metadata", {}).get("title") or user_text[:60])
            transcript = "\n".join(
                f"[{m.get('role', 'user')}] {m.get('content', '')}"
                for m in messages
                if isinstance(m.get("content"), str)
            )
            await self._emit_status(__event_emitter__, "正在校验 L1 节点并写入 DB III…", done=False)
            result = await self._post_json(
                "/v1/bridge/attach/confirm",
                {
                    "session": {
                        "source_client": "open_webui",
                        "external_session_id": chat_id,
                        "title": title,
                        "content_text": transcript,
                        "turn_count": len(messages),
                    },
                    "bindings": bindings,
                },
            )
            applied = result.get("applied_bindings", [])
            summary_note = (
                f"[Human KOS DB III 挂载成功] session_uid={result['session']['session_uid']}, "
                f"已绑定 {len(applied)} 个五维锚点："
                + ", ".join(f"{b['facet_type']}:{b['node_id']}({b['canonical_label']})" for b in applied)
            )
            messages.insert(0, {"role": "system", "content": summary_note})
            await self._emit_status(__event_emitter__, f"已挂载 {len(applied)} 个五维锚点至 DB III", done=True)
            return body

        m_propose = _ATTACH_PROPOSE_RE.match(user_text)
        if m_propose or self.valves.auto_premount:
            query_text = (m_propose.group(1) or "").strip() if m_propose else user_text
            if not query_text:
                # Fall back to prior conversation text when user simply types `/attach`
                query_text = " ".join(
                    str(m.get("content", ""))
                    for m in messages[-6:]
                    if isinstance(m.get("content"), str) and not str(m.get("content", "")).startswith("/attach")
                ).strip()
            if not query_text:
                return body

            await self._emit_status(__event_emitter__, "正在检索 Human KOS 五维正交分面候选…", done=False)
            proposal = await self._post_json(
                "/v1/bridge/attach/propose",
                {
                    "query_text": query_text,
                    "mode": self.valves.retrieval_mode,
                    "top_k_per_facet": self.valves.top_k_per_facet,
                },
            )
            map_url = f"{self.valves.kos_api_url.rstrip('/')}/map"
            context_block = _format_proposal_context(proposal, map_url)
            messages.insert(0, {"role": "system", "content": context_block})
            await self._emit_status(__event_emitter__, "已注入五维隔离候选池（等待人工确认挂载）", done=True)

        return body

    async def outlet(
        self,
        body: Dict[str, Any],
        __user__: Optional[Dict[str, Any]] = None,
        __event_emitter__: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        return body
