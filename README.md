# etsy-mcp

Professional-grade Model Context Protocol server wrapping the [Etsy Open API v3](https://developers.etsy.com/documentation/) as **pure capability primitives**. Built so AI agents (Claude, ChatGPT, Gemini, local Llama) can manage Etsy shops at scale without baked-in heuristics getting in their way.

[![CI](https://img.shields.io/github/actions/workflow/status/mofiaboss/etsy-mcp/ci.yml?branch=main)](https://github.com/mofiaboss/etsy-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/etsy-mcp)](https://pypi.org/project/etsy-mcp/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## What this is

90 tools across 13 categories — every endpoint your agent needs to:

- Read shops, listings, listing images/videos/inventory/properties/translations/digital files
- Manage receipts, payments, shipping profiles
- Walk the seller taxonomy and read reviews
- Look up users and buyer addresses
- Bulk create / update listings from templates (rate-limit-friendly)
- Bulk update image alt_text across an entire shop

Every tool is a thin wrapper around an Etsy API endpoint. **No scoring algorithms. No SEO heuristics. No tag generators. No "AI search readiness" judgments.** The MCP is a capability layer; your model is the reasoning layer.

## Why pure primitives

A baked-in `seo_score_listing` heuristic goes stale the day it ships. AI ranking algorithms change constantly, and Claude/GPT/Gemini/Llama all reason differently about SEO. By keeping every judgment inside the model, the MCP works identically across every agent today and continues to work as both Etsy's algorithms and your model evolve. Less code, lower test surface, no hidden intelligence to debug. See [docs/WORKFLOWS.md](docs/WORKFLOWS.md) for end-to-end LLM-driven workflow examples that prove the model alone is enough.

## How we compare

| Project | Tools | Reasoning baked in? |
|---|---|---|
| [aserper/etsy-mcp](https://github.com/aserper/etsy-mcp) | 37 | partial |
| [profplum700/etsy-mcp](https://github.com/profplum700/etsy-mcp) | 10 | partial |
| **etsy-mcp (this project)** | **90** | **none — pure primitives** |

## Quick start

### Install

```bash
uvx etsy-mcp@latest --help
```

Or install into a project:
```bash
uv add etsy-mcp
```

### Authenticate

For shared n8n/MCP authentication, configure the private Etsy token service:

```dotenv
ETSY_KEYSTRING=your_etsy_app_keystring
ETSY_SHARED_SECRET=your_etsy_app_shared_secret
ETSY_BROKER_URL=http://etsy-token:8080
ETSY_BROKER_KEY=the_token_services_client_keys_mcp_value
```

Pass these variables to the MCP process. From this checkout, run
`uv run --package etsy-mcp etsy-mcp auth info` to inspect the service. MCP ignores
local tokens in this mode; only the service refreshes them. See
[docs/TOKEN_SERVICE.md](docs/TOKEN_SERVICE.md) for migration and Docker/host setup.
Run this checkout containing the change; the upstream PyPI package does not
automatically include changes from this fork.

For standalone authentication without broker variables:

```bash
etsy-mcp auth login
```

This walks you through the OAuth 2.0 + PKCE flow, opens your browser, captures the callback on `localhost:3456`, and writes tokens to `~/.config/etsy-mcp/tokens.json` (mode 0600). Refresh tokens rotate automatically; you only re-auth if your refresh token is invalidated.

### Register with Claude Code

```bash
claude mcp add etsy -- uvx etsy-mcp@latest
```

Or in `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "etsy": {
      "command": "uvx",
      "args": ["etsy-mcp@latest"],
      "env": {
        "ETSY_KEYSTRING": "your-app-keystring",
        "ETSY_SHARED_SECRET": "your-app-shared-secret"
      }
    }
  }
}
```

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `ETSY_KEYSTRING` | Yes | Etsy application keystring |
| `ETSY_SHARED_SECRET` | In broker mode | Etsy application shared secret |
| `ETSY_BROKER_URL` | With broker key | Service base URL, e.g. `http://etsy-token:8080` |
| `ETSY_BROKER_KEY` | With broker URL | Token service `client_keys.mcp`, not an Etsy token |
| `ETSY_BROKER_TIMEOUT_SECONDS` | No | Broker timeout; default 60 seconds |
| `ETSY_TOKEN_STORE` | Standalone only | Local token file override |
| `ETSY_REFRESH_TOKEN` | Standalone only | Bootstrap from an existing refresh token |

Either broker variable selects broker mode; incomplete configuration fails instead
of using local OAuth. See `.env.example` for other server settings.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — package layering and responsibilities
- [docs/OAUTH.md](docs/OAUTH.md) — full PKCE flow and token rotation
- [docs/TOKEN_SERVICE.md](docs/TOKEN_SERVICE.md) — shared n8n/MCP token-service authentication
- [docs/RATE_LIMITS.md](docs/RATE_LIMITS.md) — token bucket, daily counter, backoff
- [docs/ERROR_HANDLING.md](docs/ERROR_HANDLING.md) — exception hierarchy and envelope shapes
- [docs/TESTING.md](docs/TESTING.md) — unit and integration test strategy
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md) — **end-to-end LLM workflows using only primitives**
- [docs/permissions.md](docs/permissions.md) — policy gates and confirmation modes
- [SECURITY.md](SECURITY.md), [PRIVACY.md](PRIVACY.md)

## Security notice

In token-service mode, refresh tokens stay on the private service; MCP obtains access tokens in memory and never falls back to local OAuth. In standalone mode, tokens are stored at `~/.config/etsy-mcp/tokens.json` with mode `0600`, and the latest refresh response is persisted. The F3 redaction layer scrubs OAuth tokens, broker keys, buyer PII and shop credentials. Report vulnerabilities per [SECURITY.md](SECURITY.md) — never via public issues.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, golden paths, and PR conventions. The full project rules live in [AGENTS.md](AGENTS.md) — read them before opening a PR.

## License

[MIT](LICENSE) — copyright 2026 Rick Villucci
