"""CLI entrypoint for `kos-engine` (HTTP/Viewport server, MCP server, importers, and probe)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, Sequence

from kos_engine.bridge.db import PersonalBridgeDB
from kos_engine.bridge.importers.cherry_studio import import_cherry_studio_backup
from kos_engine.bridge.importers.open_webui import import_open_webui_export
from kos_engine.config import EngineConfig
from kos_engine.core.workspace import KosWorkspace


def _transport_security(args: argparse.Namespace):
    """Build FastMCP transport-security settings for `--transport streamable-http`.

    Returns ``None`` to keep the SDK default (loopback-only Host allowlist) when the
    caller did not ask for anything. Docker Desktop users forward traffic with the
    ``host.docker.internal`` Host header, which the default allowlist rejects with
    HTTP 421, so ``--allow-host host.docker.internal:8788`` is the supported knob.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    if args.no_dns_rebinding_protection:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    extra_hosts = [h.strip() for h in (getattr(args, "allow_host", None) or []) if h and h.strip()]
    if not extra_hosts:
        return None

    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for host in extra_hosts:
        allowed_hosts.append(host)
        if not re.fullmatch(r"(?:\[[0-9a-fA-F:]+\]|[^:\[\]]+):\d{1,5}", host):
            allowed_hosts.append(f"{host}:*")
        allowed_origins.append(f"http://{host}")
        allowed_origins.append(f"https://{host}")

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(set(allowed_hosts)),
        allowed_origins=sorted(set(allowed_origins)),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kos-engine", description="Human KOS L2/L3 Standalone Engine CLI")
    parser.add_argument("--core", type=str, default=None, help="Path to L1 human_kos_core.sqlite")
    parser.add_argument("--ext-dir", type=str, default=None, help="Path to L1 human_kos_ext directory")
    parser.add_argument("--model-dir", type=str, default=None, help="Path to ONNX multilingual-e5-small directory")
    parser.add_argument("--bridge-db", type=str, default=None, help="Path to writable DB III personal_bridge.sqlite")
    parser.add_argument("--allow-local-only", action="store_true", help="Explicitly allow local_only L1 sources")

    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run local FastAPI HTTP/Viewport API + hosted 2D Knowledge World Map")
    p_serve.add_argument("--host", type=str, default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8787)

    p_mcp = sub.add_parser("mcp", help="Run FastMCP Server (stdio or streamable-http)")
    p_mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    p_mcp.add_argument("--api-origin", type=str, default="http://127.0.0.1:8787")
    p_mcp.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind address for --transport streamable-http (default: 127.0.0.1; use 0.0.0.0 to accept LAN/Docker traffic)",
    )
    p_mcp.add_argument(
        "--port",
        type=int,
        default=8788,
        help="TCP port for --transport streamable-http (default: 8788, matching mcp_server_config.json)",
    )
    p_mcp.add_argument(
        "--allow-host",
        action="append",
        default=None,
        metavar="HOST[:PORT]",
        help=(
            "Extra Host header value accepted by the streamable-http server, repeatable. "
            "Docker Desktop users normally need: --allow-host host.docker.internal:8788"
        ),
    )
    p_mcp.add_argument(
        "--no-dns-rebinding-protection",
        action="store_true",
        help="Disable the Host-header allowlist entirely (only for trusted local/LAN setups)",
    )

    p_cherry = sub.add_parser(
        "import-cherry",
        help="Import an explicitly specified Cherry Studio SQLite/JSON backup into DB III (dry-run by default)",
    )
    p_cherry.add_argument("--backup", required=True, type=str, help="Explicit backup file path (.sqlite/.db/.json)")
    p_cherry.add_argument("--commit", action="store_true", help="Actually write to DB III (default is dry-run)")
    p_cherry.add_argument("--no-secret-filter", action="store_true", help="Disable secret/key regex filtering")

    p_owui = sub.add_parser("import-owui", help="Import an Open WebUI JSON export into DB III (dry-run by default)")
    p_owui.add_argument("--export", required=True, type=str, help="Path to Open WebUI JSON export file")
    p_owui.add_argument("--commit", action="store_true", help="Actually write to DB III (default is dry-run)")

    sub.add_parser("probe", help="Run quick L1 read-only + DB III health probe")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    cfg = EngineConfig.from_env(
        core_path=args.core,
        ext_dir=args.ext_dir,
        model_dir=args.model_dir,
        bridge_db_path=args.bridge_db,
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
        allow_local_only=args.allow_local_only,
    )

    if args.command == "serve":
        import uvicorn

        from kos_engine.api.http_app import create_app

        ws = KosWorkspace.open_workspace(
            cfg.core_path, cfg.ext_dir, model_dir=cfg.model_dir, allow_local_only=cfg.allow_local_only
        )
        bridge = PersonalBridgeDB(cfg.bridge_db_path)
        app = create_app(ws, bridge, static_map_dir=cfg.static_map_dir)
        try:
            uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
        finally:
            bridge.close()
            ws.close()
        return 0

    if args.command == "mcp":
        from kos_engine.api.mcp_server import create_mcp_server

        ws = KosWorkspace.open_workspace(
            cfg.core_path, cfg.ext_dir, model_dir=cfg.model_dir, allow_local_only=cfg.allow_local_only
        )
        bridge = PersonalBridgeDB(cfg.bridge_db_path)
        mcp = create_mcp_server(
            ws, bridge, api_origin=args.api_origin, static_map_dir=cfg.static_map_dir
        )
        run_kwargs: dict = {}
        if args.transport == "streamable-http":
            run_kwargs["host"] = args.host
            run_kwargs["port"] = args.port
            transport_security = _transport_security(args)
            if transport_security is not None:
                run_kwargs["transport_security"] = transport_security
        try:
            mcp.run(transport=args.transport, **run_kwargs)
        finally:
            bridge.close()
            ws.close()
        return 0

    if args.command == "import-cherry":
        with PersonalBridgeDB(cfg.bridge_db_path) as bridge:
            res = import_cherry_studio_backup(
                bridge,
                backup_path=Path(args.backup),
                dry_run=not args.commit,
                filter_secrets=not args.no_secret_filter,
            )
            print(res.model_dump_json(indent=2))
        return 0

    if args.command == "import-owui":
        with PersonalBridgeDB(cfg.bridge_db_path) as bridge:
            res = import_open_webui_export(
                bridge,
                payload_or_path=Path(args.export),
                dry_run=not args.commit,
            )
            print(res.model_dump_json(indent=2))
        return 0

    if args.command == "probe":
        with KosWorkspace.open_workspace(
            cfg.core_path, cfg.ext_dir, model_dir=cfg.model_dir, allow_local_only=cfg.allow_local_only
        ) as ws, PersonalBridgeDB(cfg.bridge_db_path) as bridge:
            meta = ws.get_meta()
            vp = ws.query_viewport((0, 0, 10000, 10000), zoom_tier=0, limit=50)
            out = {
                "ok": True,
                "schema_version": meta.schema_version,
                "core_nodes": meta.core_node_count,
                "available_extensions": ws.list_available_extensions(),
                "encoder_available": ws.encoder.available,
                "viewport_tier0_nodes": vp.total_returned,
                "bridge_stats": bridge.get_stats(),
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
