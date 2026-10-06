"""Async access-token provider for the private Etsy token service.

The service alone owns refresh tokens and persistence. There is deliberately no
fallback to EtsyAuth, a local token file, or Etsy's OAuth endpoint on failure.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from etsy_core.exceptions import EtsyAuthError, EtsyRateLimitError

_ERROR_HELP = {
    "unauthorized": "Check ETSY_BROKER_KEY against the service's client_keys.mcp.",
    "not_initialized": "Import the current tokens using the token service's local seed command.",
    "refresh_uncertain": "Recover known-current tokens on the token service; do not retry an old refresh token.",
    "reauthorization_required": "Reauthorize Etsy and import the new tokens on the token service.",
    "oauth_configuration_error": "Check the token service's Etsy app credentials and imported authorization.",
    "refresh_busy": "The token service is busy; wait before requesting a token again.",
    "refresh_rate_limited": "The token service is rate limited; respect Retry-After.",
    "recovery_rate_limited": "Repeated token recovery was throttled; check Etsy application credentials.",
    "unknown_token_version": "Fetch a token normally before attempting recovery again.",
    "client_id_mismatch": "The token service's database and application configuration do not match.",
    "storage_decryption_failed": "Restore the token service's correct encryption key.",
}
_STATES = {"uninitialized", "active", "refresh_pending", "reauthorization_required", "oauth_configuration_error"}


@dataclass(frozen=True)
class BrokerToken:
    """Per-request snapshot: concurrent calls must never share a mutable version."""

    access_token: str = field(repr=False)
    version: int
    expires_at: int


class TokenServiceAuth:
    """Same-server HTTP or private HTTPS broker client; no refresh-token access."""

    def __init__(
        self, *, broker_url: str, broker_key: str, keystring: str, shared_secret: str, timeout: float = 60.0
    ) -> None:
        try:
            url = httpx.URL(broker_url)
            valid_url = (
                url.scheme in {"http", "https"}
                and bool(url.host)
                and not url.userinfo
                and not url.query
                and not url.fragment
            )
        except (httpx.InvalidURL, ValueError):
            valid_url = False
        if not broker_url or broker_url != broker_url.strip() or not valid_url:
            raise EtsyAuthError("ETSY_BROKER_URL must be an HTTP(S) base URL without credentials, query or fragment.")
        for name, value in (
            ("ETSY_BROKER_KEY", broker_key),
            ("ETSY_KEYSTRING", keystring),
            ("ETSY_SHARED_SECRET", shared_secret),
        ):
            if not value or not value.isascii() or any(c.isspace() or ord(c) < 32 for c in value):
                raise EtsyAuthError(f"{name} is required in token-service mode and must not contain whitespace.")
        if not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise EtsyAuthError("ETSY_BROKER_TIMEOUT_SECONDS must be greater than zero and at most 300.")
        self._url = broker_url.rstrip("/")
        self._key = broker_key
        self._api_key = f"{keystring}:{shared_secret}"
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False, trust_env=False)
        try:
            response = await self._http.request(
                method,
                f"{self._url}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError:
            # Suppress exception chains: transport errors can contain URLs/headers.
            raise EtsyAuthError("Cannot reach the Etsy token service; check its health and private network.") from None
        if response.status_code != 200:
            try:
                payload = response.json()
                code = payload.get("error") if isinstance(payload, dict) else None
                help_text = (
                    _ERROR_HELP.get(code, "Check the token service's status and configuration.")
                    if isinstance(code, str)
                    else "Check the token service's status and configuration."
                )
            except ValueError:
                help_text = "Check the token service's status and configuration."
            message = f"Etsy token service returned HTTP {response.status_code}. {help_text}"
            if response.status_code == 429:
                try:
                    seconds = int(response.headers.get("Retry-After", ""))
                    seconds = seconds if seconds >= 0 else None
                except ValueError:
                    seconds = None
                raise EtsyRateLimitError(message, status=429, retry_after_seconds=seconds)
            raise EtsyAuthError(message, status=response.status_code)
        try:
            payload = response.json()
        except ValueError:
            raise EtsyAuthError("Etsy token service returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise EtsyAuthError("Etsy token service returned an invalid response object.")
        return payload

    async def get_token(self, rejected_version: int | None = None) -> BrokerToken:
        body = {} if rejected_version is None else {"rejected_version": rejected_version}
        data = await self._request("POST", "/etsy/token", body)
        access, version, expiry = data.get("access_token"), data.get("version"), data.get("expires_at")
        if (
            not isinstance(access, str)
            or not access
            or not access.isascii()
            or any(c.isspace() or ord(c) < 32 for c in access)
            or type(version) is not int
            or version < 1
            or type(expiry) is not int
            or expiry <= time.time()
            or data.get("token_type") != "Bearer"
        ):
            raise EtsyAuthError("Etsy token service returned invalid or expired access-token metadata.")
        return BrokerToken(access, version, expiry)

    async def get_access_token(self) -> str:
        return (await self.get_token()).access_token

    def get_keystring(self) -> str:
        """Return Etsy's application header value: keystring:shared_secret."""
        return self._api_key

    async def get_status(self) -> dict[str, Any]:
        """Allowlist metadata for the CLI; never echo arbitrary service fields."""
        data = await self._request("GET", "/etsy/status")
        state = data.get("state")
        if not isinstance(state, str) or state not in _STATES:
            raise EtsyAuthError("Etsy token service returned invalid status metadata.")
        result: dict[str, Any] = {"state": state}
        for key in ("version", "expires_at", "retry_after"):
            if key in data:
                if type(data[key]) is not int or data[key] < 0:
                    raise EtsyAuthError("Etsy token service returned invalid status metadata.")
                result[key] = data[key]
        return result

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


def is_access_token_rejection(response: httpx.Response) -> bool:
    """Recover only explicit bearer-token failures, never arbitrary 401/403 errors."""
    if response.status_code != 401:
        return False
    challenge = response.headers.get("WWW-Authenticate", "").lower()
    if challenge.startswith("bearer ") and "invalid_token" in challenge:
        return True
    try:
        data = response.json()
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    for key in ("error", "error_description", "message"):
        value = data.get(key)
        if not isinstance(value, str):
            continue
        value = value.lower()
        if value in {"invalid_token", "invalid_access_token", "token_expired", "expired_token"}:
            return True
        if ("access token" in value or "oauth token" in value) and any(
            marker in value for marker in ("expired", "invalid", "revoked")
        ):
            return True
    return False
