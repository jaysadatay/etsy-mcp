"""etsy-mcp server entry point.

Responsibilities:
- Initialize the FastMCP server via runtime.get_server()
- Install the permissioned_tool decorator from etsy-mcp-shared
- Import all tool modules (triggers @server.tool() registration)
- Run either stdio or Streamable HTTP transport

For the CLI auth subcommand, see etsy_mcp/cli/auth.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_server() -> None:
    """Start the MCP server using the configured transport."""
    from etsy_mcp.runtime import get_auth, get_client, get_config, get_server

    cfg = get_config()
    get_auth()

    transport = str(getattr(cfg.server, "transport", "stdio")).strip().lower()
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("ETSY_MCP_TRANSPORT must be 'stdio' or 'streamable-http'.")

    server = get_server()
    logger.info(
        "Starting etsy-mcp server (transport=%s, log_level=%s)",
        transport,
        getattr(cfg.server, "log_level", "INFO"),
    )

    _install_permissioned_tool(server)
    _register_tools()

    try:
        if transport == "stdio":
            logger.info("etsy-mcp server ready. Listening on stdio.")
            await server.run_stdio_async()
        else:
            logger.info(
                "etsy-mcp server ready. Listening on http://%s:%s%s",
                server.settings.host,
                server.settings.port,
                server.settings.streamable_http_path,
            )
            await server.run_streamable_http_async()
    finally:
        await get_client().close()


def _install_permissioned_tool(server) -> None:
    """Install the permissioned_tool decorator + policy gate checker."""
    try:
        from etsy_mcp_shared.diagnostics import wrap_tool
        from etsy_mcp_shared.permissioned_tool import setup_permissioned_tool
        from etsy_mcp_shared.tool_index import register_tool
        from etsy_mcp.categories import ETSY_CATEGORY_MAP

        setup_permissioned_tool(
            server=server,
            category_map=ETSY_CATEGORY_MAP,
            server_prefix="ETSY",
            register_tool_fn=register_tool,
            diagnostics_enabled_fn=lambda: False,
            wrap_tool_fn=wrap_tool,
            logger=logger,
        )
        logger.info("permissioned_tool decorator installed with %d categories", len(ETSY_CATEGORY_MAP))
    except ImportError:
        logger.error(
            "Failed to import etsy-mcp-shared — running without permissioned_tool wrapper. "
            "Tools will work but policy gates are disabled. See traceback for root cause:",
            exc_info=True,
        )


def _register_tools() -> None:
    """Import every tool module to trigger @server.tool() decorators."""
    categories = [
        "shops", "listings", "listing_images", "listing_videos",
        "listing_inventory", "listing_properties", "listing_translations",
        "listing_digital_files", "receipts", "payments", "shipping",
        "reviews", "taxonomy", "users", "buyer",
    ]
    registered = 0
    for name in categories:
        try:
            __import__(f"etsy_mcp.tools.{name}")
            registered += 1
        except ImportError:
            logger.error("Tool module etsy_mcp.tools.%s failed to import:", name, exc_info=True)
        except Exception as exc:
            logger.error("Failed to import etsy_mcp.tools.%s: %s", name, exc, exc_info=True)
    logger.info("Tool modules registered: %d / %d", registered, len(categories))
