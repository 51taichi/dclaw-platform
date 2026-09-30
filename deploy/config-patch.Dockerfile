FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONFIG_PATCH_HOST=0.0.0.0 \
    CONFIG_PATCH_PORT=8788 \
    CONFIG_PATCH_DATA_DIR=/var/lib/dclaw-config-patch

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system configpatch \
    && useradd --system --gid configpatch --home-dir /nonexistent --shell /usr/sbin/nologin configpatch \
    && install -d -o configpatch -g configpatch -m 0700 /var/lib/dclaw-config-patch

WORKDIR /app

COPY pyproject.toml setup.py README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir \
      "fastapi>=0.115,<1" \
      "httpx>=0.27,<1" \
      "pydantic>=2,<3" \
      "uvicorn>=0.40,<1" \
    && python -m pip install --no-cache-dir --no-deps .

COPY --chmod=755 deploy/config-patch-entrypoint.sh /usr/local/bin/config-patch-entrypoint.sh

USER configpatch
EXPOSE 8788
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl --fail --silent --show-error http://127.0.0.1:8788/health || exit 1

ENTRYPOINT ["/usr/local/bin/config-patch-entrypoint.sh"]
