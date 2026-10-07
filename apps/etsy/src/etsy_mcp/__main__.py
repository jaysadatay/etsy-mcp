"""etsy-mcp entry point.

Dispatches to:
- `etsy-mcp` — start the MCP server using configured/default transport
- `etsy-mcp serve` — start the MCP server with optional transport overrides
- `etsy-mcp auth login` — run the interactive OAuth PKCE bootstrap
- `etsy-mcp auth info` — display current token state (redacted)
- `etsy-mcp auth logout` — delete stored tokens
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure stderr-only logging per AGENTS.md rules."""
    level = os.environ.get("ETSY_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="etsy-mcp serve",
        description="Start the Etsy MCP server.",
    )
    parser.add_argument("--transport", choices=("stdio", "streamable-http"),
                        help="MCP transport. Defaults to ETSY_MCP_TRANSPORT or stdio.")
    parser.add_argument("--host", help="HTTP bind host. Defaults to ETSY_MCP_HOST or 127.0.0.1.")
    parser.add_argument("--port", type=int, help="HTTP bind port. Defaults to ETSY_MCP_PORT or 8000.")
    parser.add_argument("--path", dest="streamable_http_path",
                        help="Streamable HTTP endpoint path. Defaults to ETSY_MCP_PATH or /mcp.")
    return parser


def _apply_serve_overrides(args: list[str]) -> None:
    """Apply CLI transport options through the same env-backed config path as Docker."""
    options = _serve_parser().parse_args(args)
    overrides = {
        "ETSY_MCP_TRANSPORT": options.transport,
        "ETSY_MCP_HOST": options.host,
        "ETSY_MCP_PORT": str(options.port) if options.port is not None else None,
        "ETSY_MCP_PATH": options.streamable_http_path,
    }
    for name, value in overrides.items():
        if value is not None:
            os.environ[name] = value


def _print_help() -> None:
    print("etsy-mcp — Etsy MCP server")
    print()
    print("Usage:")
    print("  etsy-mcp                         Start server (stdio by default)")
    print("  etsy-mcp serve [options]         Start server with transport overrides")
    print("  etsy-mcp auth login              Interactive OAuth PKCE bootstrap")
    print("  etsy-mcp auth info               Show current token state (redacted)")
    print("  etsy-mcp auth logout             Delete stored tokens")
    print("  etsy-mcp --version               Show version")
    print("  etsy-mcp --help                  Show this help")
    print()
    print("Run `etsy-mcp serve --help` for HTTP transport options.")


def main() -> None:
    """CLI dispatch."""
    _configure_logging()
    args = sys.argv[1:]

    if not args:
        from etsy_mcp.main import run_server
        asyncio.run(run_server())
        return

    if args[0] in ("serve", "--serve"):
        _apply_serve_overrides(args[1:])
        from etsy_mcp.main import run_server
        asyncio.run(run_server())
        return

    if args[0] == "auth":
        from etsy_mcp.cli.auth import auth_cli
        auth_cli(args[1:])
        return

    if args[0] in ("--version", "-V"):
        from etsy_mcp import __version__
        print(f"etsy-mcp {__version__}")
        return

    if args[0] in ("--help", "-h"):
        _print_help()
        return

    print(f"Unknown command: {args[0]}", file=sys.stderr)
    print("Run `etsy-mcp --help` for usage.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
