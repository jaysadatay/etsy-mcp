FROM python:3.13-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages

RUN uv sync \
    --locked \
    --package etsy-mcp \
    --no-dev \
    --no-editable


FROM python:3.13-slim-trixie AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/etsy-mcp \
    XDG_CONFIG_HOME=/home/etsy-mcp/.config

RUN groupadd --system --gid 10001 etsy-mcp \
    && useradd \
        --system \
        --uid 10001 \
        --gid 10001 \
        --create-home \
        --home-dir /home/etsy-mcp \
        etsy-mcp \
    && mkdir -p /home/etsy-mcp/.config/etsy-mcp \
    && chown -R etsy-mcp:etsy-mcp /home/etsy-mcp

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

USER etsy-mcp

EXPOSE 8000

ENTRYPOINT ["etsy-mcp"]
CMD ["serve"]
