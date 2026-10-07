FROM python:3.13-slim-trixie AS builder

# Pin uv for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy only what is required for the workspace.
# This deliberately avoids copying .env, .git, etc. into the image.
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages

# Install only the etsy-mcp package and its workspace dependencies.
# --no-editable lets us copy only the finished virtualenv into the runtime image.
RUN uv sync \
    --locked \
    --package etsy-mcp \
    --no-dev \
    --no-editable


# ---------------------------------------------------------------------------
# Runtime image
# ---------------------------------------------------------------------------
FROM python:3.13-slim-trixie AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/etsy-mcp

# Run the MCP server as an unprivileged user.
RUN groupadd --system --gid 10001 etsy-mcp \
    && useradd \
        --system \
        --uid 10001 \
        --gid 10001 \
        --create-home \
        --home-dir /home/etsy-mcp \
        etsy-mcp

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

USER etsy-mcp

# This project currently uses MCP stdio transport.
ENTRYPOINT ["etsy-mcp"]
CMD ["serve"]