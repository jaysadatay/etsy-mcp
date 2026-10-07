"""Transport configuration tests for stdio and Streamable HTTP serving."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from etsy_mcp import main as server_main
from etsy_mcp import runtime
from etsy_mcp.__main__ import _apply_serve_overrides


@pytest.fixture(autouse=True)
def isolated_transport_config(monkeypatch):
    for name in ("ETSY_MCP_TRANSPORT", "ETSY_MCP_HOST", "ETSY_MCP_PORT", "ETSY_MCP_PATH"):
        monkeypatch.delenv(name, raising=False)
    runtime.get_config.cache_clear()
    runtime.get_server.cache_clear()
    yield
    runtime.get_server.cache_clear()
    runtime.get_config.cache_clear()


def test_defaults_keep_stdio_and_local_http_settings():
    cfg = runtime.get_config().server
    server = runtime.get_server()

    assert cfg.transport == "stdio"
    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 8000
    assert server.settings.streamable_http_path == "/mcp"


def test_http_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("ETSY_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("ETSY_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("ETSY_MCP_PORT", "8765")
    monkeypatch.setenv("ETSY_MCP_PATH", "/etsy")
    runtime.get_config.cache_clear()
    runtime.get_server.cache_clear()

    cfg = runtime.get_config().server
    server = runtime.get_server()

    assert cfg.transport == "streamable-http"
    assert server.settings.host == "0.0.0.0"
    assert server.settings.port == 8765
    assert server.settings.streamable_http_path == "/etsy"


def test_serve_cli_overrides_use_env_backed_config():
    _apply_serve_overrides(
        ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000", "--path", "/mcp"]
    )

    assert os.environ["ETSY_MCP_TRANSPORT"] == "streamable-http"
    assert os.environ["ETSY_MCP_HOST"] == "0.0.0.0"
    assert os.environ["ETSY_MCP_PORT"] == "9000"
    assert os.environ["ETSY_MCP_PATH"] == "/mcp"


@pytest.mark.parametrize("port", [0, 65536, "not-a-port"])
def test_invalid_http_port_fails_fast(port):
    cfg = SimpleNamespace(host="127.0.0.1", port=port, streamable_http_path="/mcp", log_level="INFO")
    with pytest.raises(ValueError, match="ETSY_MCP_PORT"):
        runtime._server_http_settings(cfg)


@pytest.mark.parametrize("path", ["mcp", "", "/bad path"])
def test_invalid_http_path_fails_fast(path):
    cfg = SimpleNamespace(host="127.0.0.1", port=8000, streamable_http_path=path, log_level="INFO")
    with pytest.raises(ValueError, match="ETSY_MCP_PATH"):
        runtime._server_http_settings(cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "method_name"),
    [("stdio", "run_stdio_async"), ("streamable-http", "run_streamable_http_async")],
)
async def test_run_server_dispatches_configured_transport(monkeypatch, transport, method_name):
    monkeypatch.setenv("ETSY_MCP_TRANSPORT", transport)
    runtime.get_config.cache_clear()

    fake_server = MagicMock()
    fake_server.settings.host = "127.0.0.1"
    fake_server.settings.port = 8000
    fake_server.settings.streamable_http_path = "/mcp"
    fake_server.run_stdio_async = AsyncMock()
    fake_server.run_streamable_http_async = AsyncMock()

    fake_client = MagicMock()
    fake_client.close = AsyncMock()

    monkeypatch.setattr(runtime, "get_auth", lambda: object())
    monkeypatch.setattr(runtime, "get_server", lambda: fake_server)
    monkeypatch.setattr(runtime, "get_client", lambda: fake_client)
    monkeypatch.setattr(server_main, "_install_permissioned_tool", lambda server: None)
    monkeypatch.setattr(server_main, "_register_tools", lambda: None)

    await server_main.run_server()

    getattr(fake_server, method_name).assert_awaited_once_with()
    other = "run_streamable_http_async" if method_name == "run_stdio_async" else "run_stdio_async"
    getattr(fake_server, other).assert_not_awaited()
    fake_client.close.assert_awaited_once_with()
