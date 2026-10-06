# Shared authentication with the Etsy token service

Use this mode when n8n and MCP share one Etsy OAuth authorization. The private
service owns the access/refresh token pair and its persistent SQLite database.
MCP requests access tokens; it never receives, stores or refreshes the shared
refresh token. Existing tool permissions and confirmation rules are unchanged.

## Configure this checkout

Run the version of this repository containing the integration. Installing the
upstream `uvx etsy-mcp@latest` package does not install changes from your fork.

```bash
uv sync --all-packages
```

Set these variables in the MCP process environment or your MCP client's `env`
configuration. The server does not automatically load a `.env` file: export the
values, or supply the file through your process/container launcher.

```dotenv
ETSY_KEYSTRING=your_etsy_app_keystring
ETSY_SHARED_SECRET=your_etsy_app_shared_secret
ETSY_BROKER_URL=http://etsy-token:8080
ETSY_BROKER_KEY=the_token_services_client_keys_mcp_value
ETSY_BROKER_TIMEOUT_SECONDS=60
```

- The keystring/shared secret must match the token service's Etsy application.
  MCP still sends Etsy's `x-api-key: keystring:shared_secret` header.
- The broker key is **`client_keys.mcp`** from the service's private
  `secrets/config.json`. It is not an Etsy token. Do not copy the service's full
  config or encryption key into the MCP repository/configuration.
- Either broker variable selects broker mode. Both must be valid. Partial
  configuration fails instead of silently falling back to local OAuth.
- `ETSY_TOKEN_STORE` and `ETSY_REFRESH_TOKEN` are ignored in broker mode. Remove
  stale values from deployment configuration to avoid confusion.

```bash
uv run --package etsy-mcp etsy-mcp auth info
uv run --package etsy-mcp etsy-mcp
```

`auth info` calls `GET /etsy/status` and displays only state, version, expiry and
retry delay. It does not fetch tokens or force a refresh. The second command starts the default stdio transport. For a permanently running
remote MCP endpoint, use the included Docker Compose deployment or start
`streamable-http` explicitly. The HTTP endpoint defaults to `/mcp`.

A host-based MCP client configuration for this checkout:

```json
{
  "mcpServers": {
    "etsy": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/etsy-mcp", "run", "--package", "etsy-mcp", "etsy-mcp"],
      "env": {
        "ETSY_KEYSTRING": "your_etsy_app_keystring",
        "ETSY_SHARED_SECRET": "your_etsy_app_shared_secret",
        "ETSY_BROKER_URL": "http://127.0.0.1:8787",
        "ETSY_BROKER_KEY": "the_token_services_client_keys_mcp_value"
      }
    }
  }
}
```

All credential values above are placeholders. Choose the URL for the actual
location of the MCP process, as described below.

## Same-host networking

**MCP in Docker:** the repository's `docker-compose.yml` already attaches the MCP
container to the external `etsy-auth` network and starts Streamable HTTP. The host
port is loopback-only by default; place your authenticated HTTPS reverse proxy in
front of it. A minimal equivalent configuration is:

```yaml
services:
  etsy-mcp:  # replace with your existing service name
    environment:
      ETSY_KEYSTRING: ${ETSY_KEYSTRING:?Set the Etsy app keystring}
      ETSY_SHARED_SECRET: ${ETSY_SHARED_SECRET:?Set the Etsy app shared secret}
      ETSY_BROKER_URL: http://etsy-token:8080
      ETSY_BROKER_KEY: ${ETSY_BROKER_KEY:?Set the broker client_keys.mcp value}
      ETSY_BROKER_TIMEOUT_SECONDS: "60"
    networks:
      - default
      - etsy-auth
networks:
  default: {}
  etsy-auth:
    external: true
    name: etsy-auth
```

**MCP directly on the host:** enable the token service's supplied loopback-only
override in the token service project:

```bash
docker compose -f compose.yaml -f compose.host.yaml up -d
```

Use `ETSY_BROKER_URL=http://127.0.0.1:8787`. Inside another container, `127.0.0.1`
refers to that container; use the shared Docker network instead. For another
machine, use private routing and HTTPS. Do not publicly expose the token service.
Broker requests disable redirects and environment proxies.

## Migrate from local OAuth

1. Pause processes currently refreshing the shared authorization. Let in-progress
   refreshes finish and take the latest token pair.
2. In the token service project, import it with
   `docker compose exec etsy-token python -m broker.manage seed` (or `seed --replace`
   if initialized). If the service already has the current pair, leave it there;
   do not replace it with an old MCP token file.
3. Configure the variables above. Make both n8n and MCP use the service, and
   disable all other refresh branches for this authorization.
4. Run `etsy-mcp auth info` and check for `state: active`, then perform a read-only
   shop/listing request through your MCP client.

Old token files are ignored, not deleted. `auth login` and `auth logout` refuse to
operate in broker mode and explain that administration belongs to the service.
To disconnect only MCP, remove/rotate its broker client key. Revoking the shared
Etsy authorization also affects n8n.

For reauthorization, use your existing OAuth consent setup and import the new
pair on the service. Broker mode does not add a second browser OAuth flow.

## Request and recovery behavior

Before each logical Etsy API request, MCP sends `POST /etsy/token` with `{}` and
its broker bearer key. It uses the returned access token and keeps the token's
version local to that request.

On an explicit access-token rejection (401 `invalid_token`, a matching bearer
challenge, or an expired/invalid token message), MCP sends:

```json
{"rejected_version": 17}
```

The version belongs to the token actually rejected, not a concurrent request's
token. The service decides whether to refresh or reuse a newer token from n8n.

- GET and explicitly idempotent PUT requests may retry once after recovery.
  There is at most one broker recovery per logical request.
- POST, PATCH, DELETE and ordinary PUT notify the broker but are **never replayed
  automatically**. MCP returns an actionable error; verify Etsy state before
  deciding whether to submit the write again.
- Generic 401 errors, invalid app keys and 403 scope errors do not trigger token
  recovery. Existing idempotent retries for Etsy 429/5xx/timeouts still apply.
- Broker failures never fall back to a token file or Etsy's refresh endpoint.
  Broker 429 errors retain their `Retry-After` delay in the rate-limit exception.
- Broker errors use fixed explanations, not raw response bodies. Tokens and keys
  are not exposed as MCP tools or tool results.

For `refresh_uncertain` or `reauthorization_required`, recover the authorization
on the token service. A refresh cannot add scopes: reauthorize with the union of
the scopes n8n/MCP need, then import the new pair.

## Standalone compatibility

When both broker variables are absent, the existing local `EtsyAuth` flow remains
available. Use that for an independently managed authorization. Do not run local
and broker refresh against the same shared token pair.
