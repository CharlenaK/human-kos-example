"""
title: Human KOS Topological Explore Action
author: Human KOS Phase 3 Reference Adapter
version: 0.1.0
license: MIT
description: Zero-fork Open WebUI v0.13.4 Action Function that runs 5-facet grounding and bounded 2-hop edge traversal via kos-engine and emits a structured exploration card linking to the 2D Knowledge World Map.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field


class Action:
    class Valves(BaseModel):
        kos_api_url: str = Field(
            default="http://127.0.0.1:8787",
            description="Local kos-engine HTTP API base URL",
        )
        max_hops: int = Field(default=2, ge=1, le=3)
        min_ic: float = Field(default=1.5, ge=0.0, le=10.0)
        timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self.valves = self.Valves()
        self._injected_client = http_client

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

    async def action(
        self,
        body: Dict[str, Any],
        __user__: Optional[Dict[str, Any]] = None,
        __event_emitter__: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        messages = body.get("messages") or []
        seed_text = ""
        for m in reversed(messages):
            if isinstance(m.get("content"), str) and m["content"].strip():
                seed_text = m["content"].strip()[:500]
                break
        if not seed_text:
            return {"status": "empty", "message": "未找到可供拓扑探索的消息正文。"}

        prop = await self._post_json(
            "/v1/bridge/attach/propose",
            {"query_text": seed_text, "mode": "hybrid", "top_k_per_facet": 3},
        )
        by_facet = prop.get("candidates_by_facet", {})
        seed_ids: List[str] = []
        for facet in ("DOMAIN", "PROCESS", "ARTIFACT"):
            cands = by_facet.get(facet) or []
            if cands:
                seed_ids.append(cands[0]["node_id"])

        subgraph: Dict[str, Any] = {"nodes": [], "edges": [], "license_boundary": {}}
        if seed_ids:
            subgraph = await self._post_json(
                "/v1/traverse",
                {
                    "seed_node_ids": seed_ids,
                    "max_hops": self.valves.max_hops,
                    "include_negative": False,
                    "min_ic": self.valves.min_ic,
                    "exclude_roots": True,
                    "max_nodes": 30,
                },
            )

        map_url = f"{self.valves.kos_api_url.rstrip('/')}/map"
        lines = [
            "### Human KOS 沿边拓扑探索摘要",
            f"- 种子节点：{', '.join(f'`{sid}`' for sid in seed_ids) or '无'}",
            f"- 展开子图：{len(subgraph.get('nodes', []))} 节点 / {len(subgraph.get('edges', []))} 正向边（`polarity=1`, `IC >= {self.valves.min_ic}`）",
            f"- 2D 知识世界地图：<{map_url}>",
        ]
        for node in subgraph.get("nodes", [])[:8]:
            if node.get("hop", 0) > 0:
                lbl = node.get("canonical_label_zh") or node.get("canonical_label_en") or node.get("node_id")
                lines.append(
                    f"  - `[hop {node['hop']} · {node.get('facet_type')}]` **{lbl}** (`{node['node_id']}`)"
                )

        content = "\n".join(lines)
        if __event_emitter__ is not None:
            await __event_emitter__({"type": "message", "data": {"content": content}})
        return {
            "status": "ok",
            "seed_node_ids": seed_ids,
            "node_count": len(subgraph.get("nodes", [])),
            "edge_count": len(subgraph.get("edges", [])),
            "map_url": map_url,
            "markdown": content,
        }
