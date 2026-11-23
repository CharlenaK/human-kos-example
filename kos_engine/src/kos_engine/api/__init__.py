"""HTTP/Viewport API and MCP Server (with MCP Apps) transport projections."""

from kos_engine.api.http_app import create_app
from kos_engine.api.mcp_server import MCP_APP_MIME_TYPE, MCP_APP_RESOURCE_URI, create_mcp_server

__all__ = [
    "MCP_APP_MIME_TYPE",
    "MCP_APP_RESOURCE_URI",
    "create_app",
    "create_mcp_server",
]
