"""Broker configuration selection and CLI ownership boundaries."""

from unittest.mock import AsyncMock

import pytest
from etsy_core.auth import EtsyAuth
from etsy_core.exceptions import EtsyAuthError
from etsy_core.token_service import TokenServiceAuth
from etsy_mcp import runtime
from etsy_mcp.cli.auth import auth_cli


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    for name in ("ETSY_BROKER_URL", "ETSY_BROKER_KEY", "ETSY_BROKER_TIMEOUT_SECONDS", "ETSY_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ETSY_KEYSTRING", "test-app")
    monkeypatch.setenv("ETSY_SHARED_SECRET", "test-secret")
    monkeypatch.setenv("ETSY_TOKEN_STORE", str(tmp_path / "tokens.json"))
    runtime.get_config.cache_clear()
    runtime.get_auth.cache_clear()
    yield
    runtime.get_config.cache_clear()
    runtime.get_auth.cache_clear()


def enable_broker(monkeypatch):
    monkeypatch.setenv("ETSY_BROKER_URL", "http://etsy-token:8080")
    monkeypatch.setenv("ETSY_BROKER_KEY", "broker-test-key")


def test_broker_selected_and_local_token_file_untouched(monkeypatch, tmp_path):
    enable_broker(monkeypatch)
    monkeypatch.setenv("ETSY_REFRESH_TOKEN", "DO-NOT-USE")
    auth = runtime.get_auth()
    assert isinstance(auth, TokenServiceAuth)
    assert runtime.get_auth() is auth
    assert not (tmp_path / "tokens.json").exists()


def test_standalone_still_available():
    assert isinstance(runtime.get_auth(), EtsyAuth)


@pytest.mark.parametrize("name,value", [("ETSY_BROKER_URL", "http://etsy-token:8080"), ("ETSY_BROKER_KEY", "secret")])
def test_partial_configuration_never_falls_back(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(EtsyAuthError):
        runtime.get_auth()


@pytest.mark.parametrize("value", ["invalid", "nan", "0"])
def test_invalid_timeout_fails_with_safe_message(monkeypatch, value):
    enable_broker(monkeypatch)
    monkeypatch.setenv("ETSY_BROKER_TIMEOUT_SECONDS", value)
    with pytest.raises(EtsyAuthError, match="ETSY_BROKER_TIMEOUT_SECONDS"):
        runtime.get_auth()


@pytest.mark.parametrize("command", ["login", "logout"])
def test_broker_cli_cannot_mutate_local_tokens(monkeypatch, tmp_path, capsys, command):
    enable_broker(monkeypatch)
    file = tmp_path / "tokens.json"
    file.write_text("local-secret")
    with pytest.raises(SystemExit) as caught:
        auth_cli([command])
    assert caught.value.code == 1
    assert file.read_text() == "local-secret"
    assert "token service" in capsys.readouterr().err


def test_broker_info_only_fetches_status(monkeypatch, capsys):
    enable_broker(monkeypatch)
    auth = runtime.get_auth()
    monkeypatch.setattr(auth, "get_status", AsyncMock(return_value={"state": "active", "version": 2}))
    monkeypatch.setattr(auth, "get_token", AsyncMock(side_effect=AssertionError("must not request tokens")))
    monkeypatch.setattr(auth, "close", AsyncMock())
    auth_cli(["info"])
    assert "version: 2" in capsys.readouterr().out
    auth.get_status.assert_awaited_once()
    auth.get_token.assert_not_awaited()
    auth.close.assert_awaited_once()
