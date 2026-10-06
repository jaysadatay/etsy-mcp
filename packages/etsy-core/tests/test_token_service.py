"""Contract and request-flow tests for the private token service integration."""

from __future__ import annotations

import asyncio
import json
import time
import traceback

import httpx
import pytest
import respx
from etsy_core.client import DEFAULT_BASE_URL, EtsyClient
from etsy_core.exceptions import EtsyAuthError, EtsyPossiblyCompletedError, EtsyRateLimitError
from etsy_core.redaction import REDACTED_PLACEHOLDER, redact_sensitive
from etsy_core.token_service import TokenServiceAuth

BROKER = "http://etsy-token:8080"


def token(version=1):
    return {
        "access_token": f"123.token-{version}",
        "version": version,
        "expires_at": int(time.time()) + 3600,
        "token_type": "Bearer",
    }


@pytest.fixture
def auth():
    return TokenServiceAuth(
        broker_url=BROKER, broker_key="broker-secret", keystring="app-key", shared_secret="app-secret"
    )


@pytest.fixture
async def client(auth, tmp_path):
    client = EtsyClient(auth, rate_limit_per_second=100, daily_counter_path=tmp_path / "daily.json")
    yield client
    await client.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("broker_url", ""),
        ("broker_key", ""),
        ("keystring", ""),
        ("shared_secret", ""),
        ("broker_url", "ftp://host"),
        ("broker_url", "http://key@host"),
        ("broker_url", "http://host?key=secret"),
        ("broker_url", "http://host#secret"),
        ("broker_key", "secret\nheader"),
        ("timeout", float("nan")),
        ("timeout", 0),
    ],
)
def test_rejects_invalid_configuration_without_echoing_values(field, value):
    kwargs = dict(broker_url=BROKER, broker_key="broker-secret", keystring="app-key", shared_secret="app-secret")
    kwargs[field] = value
    with pytest.raises(EtsyAuthError):
        TokenServiceAuth(**kwargs)


@pytest.mark.asyncio
async def test_contract_no_local_tokens_or_direct_refresh(auth, tmp_path, monkeypatch, mock_httpx):
    store = tmp_path / "tokens.json"
    store.write_text('{"refresh_token": "DO-NOT-USE"}')
    monkeypatch.setenv("ETSY_REFRESH_TOKEN", "DO-NOT-USE")
    monkeypatch.setenv("ETSY_TOKEN_STORE", str(store))
    broker = mock_httpx.post(BROKER + "/etsy/token").respond(200, json=token())
    direct = mock_httpx.post("https://api.etsy.com/v3/public/oauth/token").respond(500)
    result = await auth.get_token()
    assert result.version == 1 and "123.token-1" not in repr(result)
    request = broker.calls[0].request
    assert json.loads(request.content) == {}
    assert request.headers["Authorization"] == "Bearer broker-secret"
    assert "x-api-key" not in request.headers
    assert auth.get_keystring() == "app-key:app-secret"
    assert direct.call_count == 0 and store.read_text() == '{"refresh_token": "DO-NOT-USE"}'
    await auth.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {**token(), "access_token": ""},
        {**token(), "version": True},
        {**token(), "expires_at": 1},
        {**token(), "expires_at": "100000000000"},
        {**token(), "access_token": "token\r\nheader"},
        {**token(), "token_type": "Basic"},
    ],
)
async def test_bad_token_response_fails_closed(auth, mock_httpx, data):
    mock_httpx.post(BROKER + "/etsy/token").respond(200, json=data)
    with pytest.raises(EtsyAuthError, match="invalid"):
        await auth.get_token()
    await auth.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["refresh_uncertain", "reauthorization_required", "not_initialized", "SECRET-RAW-BODY"]
)
async def test_broker_failure_never_calls_etsy_or_echoes_body(client, mock_httpx, caplog, code):
    route = mock_httpx.post(BROKER + "/etsy/token").respond(
        503, json={"error": code, "refresh_token": "PRIVATE", "message": "PRIVATE"}
    )
    with pytest.raises(EtsyAuthError) as caught:
        await client.get("/listings/1")
    output = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert "PRIVATE" not in output and "SECRET-RAW-BODY" not in output
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_broker_network_errors_are_not_retried_or_leaked(client, mock_httpx):
    route = mock_httpx.post(BROKER + "/etsy/token").mock(side_effect=httpx.ReadTimeout("PRIVATE-KEY"))
    with pytest.raises(EtsyAuthError) as caught:
        await client.get("/listings/1")
    assert "PRIVATE-KEY" not in "".join(traceback.format_exception(caught.value))
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_broker_rate_limit_is_not_wrapped_or_retried(client, mock_httpx):
    route = mock_httpx.post(BROKER + "/etsy/token").respond(429, headers={"Retry-After": "120"})
    with pytest.raises(EtsyRateLimitError) as caught:
        await client.get("/listings/1")
    assert caught.value.retry_after_seconds == 120 and route.call_count == 1


@pytest.mark.asyncio
async def test_get_recovers_exact_rejected_version_once(client, mock_httpx):
    broker = mock_httpx.post(BROKER + "/etsy/token").mock(
        side_effect=[httpx.Response(200, json=token(5)), httpx.Response(200, json=token(6))]
    )
    etsy = mock_httpx.get(DEFAULT_BASE_URL + "/listings/1").mock(
        side_effect=[httpx.Response(401, json={"error": "invalid_token"}), httpx.Response(200, json={"listing_id": 1})]
    )
    assert await client.get("/listings/1") == {"listing_id": 1}
    assert json.loads(broker.calls[1].request.content) == {"rejected_version": 5}
    assert etsy.calls[1].request.headers["Authorization"] == "Bearer 123.token-6"
    assert etsy.calls[1].request.headers["x-api-key"] == "app-key:app-secret"
    assert "broker-secret" not in str(etsy.calls[1].request.headers)
    assert client.rate_limit_status()["remaining_today"] == 9998


@pytest.mark.asyncio
async def test_second_401_does_not_create_refresh_loop(client, mock_httpx):
    broker = mock_httpx.post(BROKER + "/etsy/token").respond(200, json=token())
    etsy = mock_httpx.get(DEFAULT_BASE_URL + "/listings/1").respond(401, json={"error": "invalid_token"})
    with pytest.raises(EtsyAuthError):
        await client.get("/listings/1")
    assert broker.call_count == 2 and etsy.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [(401, "invalid_api_key"), (401, "unauthorized"), (403, "invalid_token")])
async def test_unrelated_auth_errors_do_not_trigger_refresh(client, mock_httpx, status, error):
    broker = mock_httpx.post(BROKER + "/etsy/token").respond(200, json=token())
    etsy = mock_httpx.get(DEFAULT_BASE_URL + "/listings/1").respond(status, json={"error": error})
    with pytest.raises(EtsyAuthError):
        await client.get("/listings/1")
    assert broker.call_count == 1 and etsy.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["post", "patch", "put", "delete"])
async def test_write_401_notifies_broker_without_replaying_write(client, mock_httpx, method):
    broker = mock_httpx.post(BROKER + "/etsy/token").respond(200, json=token())
    etsy = mock_httpx.route(method=method.upper(), url=DEFAULT_BASE_URL + "/listings/1").respond(
        401, json={"error": "invalid_token"}
    )
    with pytest.raises(EtsyAuthError, match="write was not retried"):
        await getattr(client, method)("/listings/1")
    assert etsy.call_count == 1 and broker.call_count == 2


@pytest.mark.asyncio
async def test_write_timeout_is_not_replayed_or_refreshed(client, mock_httpx):
    broker = mock_httpx.post(BROKER + "/etsy/token").respond(200, json=token())
    etsy = mock_httpx.post(DEFAULT_BASE_URL + "/listings").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(EtsyPossiblyCompletedError):
        await client.post("/listings", json={"title": "test"})
    assert etsy.call_count == 1 and broker.call_count == 1


@pytest.mark.asyncio
async def test_concurrent_requests_keep_their_own_versions(client, mock_httpx):
    normals = 0
    rejected = []
    waiting = 0
    both_waiting = asyncio.Event()

    def broker(request):
        nonlocal normals
        data = json.loads(request.content)
        if "rejected_version" in data:
            rejected.append(data["rejected_version"])
            return httpx.Response(200, json=token(data["rejected_version"] + 10))
        normals += 1
        return httpx.Response(200, json=token(normals))

    async def etsy(request):
        nonlocal waiting
        if request.headers["Authorization"] in {"Bearer 123.token-1", "Bearer 123.token-2"}:
            waiting += 1
            if waiting == 2:
                both_waiting.set()
            await asyncio.wait_for(both_waiting.wait(), 2)
            return httpx.Response(401, json={"error": "invalid_token"})
        return httpx.Response(200, json={"ok": True})

    mock_httpx.post(BROKER + "/etsy/token").mock(side_effect=broker)
    mock_httpx.get(DEFAULT_BASE_URL + "/listings/1").mock(side_effect=etsy)
    results = await asyncio.gather(client.get("/listings/1"), client.get("/listings/1"))
    assert results == [{"ok": True}, {"ok": True}]
    assert sorted(rejected) == [1, 2]


@pytest.mark.asyncio
async def test_redirects_do_not_forward_credentials(client, mock_httpx):
    broker = mock_httpx.post(BROKER + "/etsy/token").respond(
        307, headers={"Location": "https://elsewhere.example/token"}
    )
    with pytest.raises(EtsyAuthError):
        await client.get("/listings/1")
    assert broker.call_count == 1


@pytest.mark.asyncio
async def test_status_allowlists_only_nonsecret_fields(auth):
    with respx.mock as router:
        router.get(BROKER + "/etsy/status").respond(
            200,
            json={
                "state": "active",
                "version": 2,
                "expires_at": 1234,
                "retry_after": 0,
                "access_token": "PRIVATE",
                "refresh_token": "PRIVATE",
                "unexpected": "PRIVATE",
            },
        )
        assert await auth.get_status() == {"state": "active", "version": 2, "expires_at": 1234, "retry_after": 0}
    await auth.close()


def test_broker_key_redacted():
    assert redact_sensitive({"broker_key": "PRIVATE", "ETSY_BROKER_KEY": "PRIVATE"}) == {
        "broker_key": REDACTED_PLACEHOLDER,
        "ETSY_BROKER_KEY": REDACTED_PLACEHOLDER,
    }
