
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/app.db

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY seed/ seed/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# UID/GID 1000 so the bind-mounted ./data (host user) stays writable
RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser --create-home appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

# Stay root at container start: the entrypoint fixes ownership of whatever is
# bind-mounted at /data (which Docker may auto-create as root) before dropping
# privileges to appuser itself.
VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
