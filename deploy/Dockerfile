# -----------------------------------------------------------------------------
# Stage 1: build console frontend (dist not committed in repo).
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim AS console-builder
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
ENV NPM_CONFIG_REPLACE_REGISTRY_HOST=always
WORKDIR /app
COPY console /app/console
RUN cd /app/console && npm ci --include=dev && NODE_OPTIONS=--max-old-space-size=4096 npm run build

# -----------------------------------------------------------------------------
# Stage 2: runtime image with Python, Chromium, and app.
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g; s|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g; s|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    printf '%s\n' \
      'Acquire::Retries "5";' \
      'Acquire::http::Timeout "60";' \
      'Acquire::https::Timeout "60";' \
      'Acquire::http::Pipeline-Depth "0";' \
      'Acquire::http::No-Cache "true";' \
      > /etc/apt/apt.conf.d/80-qwenpaw-retries

# ENV variables
ENV NODE_ENV=production
ENV WORKSPACE_DIR=/app
ENV QWENPAW_WORKING_DIR=/app/working
ENV QWENPAW_SECRET_DIR=/app/working.secret
ENV QWENPAW_BACKUP_DIR=/app/working.backups
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# Channel filtering: use QWENPAW_DISABLED_CHANNELS (exclusion, recommended)
# or QWENPAW_ENABLED_CHANNELS (whitelist). Override at runtime with -e.
ARG QWENPAW_DISABLED_CHANNELS="imessage"
ENV QWENPAW_DISABLED_CHANNELS=${QWENPAW_DISABLED_CHANNELS}
ARG QWENPAW_ENABLED_CHANNELS=""
ENV QWENPAW_ENABLED_CHANNELS=${QWENPAW_ENABLED_CHANNELS}

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends --fix-missing \
    ca-certificates \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    libssl-dev \
    git \
    supervisor \
    vim \
    gettext-base \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get clean

RUN apt-get update && apt-get install -y --no-install-recommends --fix-missing \
    dbus-x11 \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    xvfb \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get clean

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing libepoxy0; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing \
      libreoffice-impress \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-chi-sim \
      tesseract-ocr-eng; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get clean

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing libcolord2; \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing \
      xfce4 \
      xfce4-terminal; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get clean

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing \
      chromium \
      chromium-sandbox \
      libx11-xcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxext6 \
      libxfixes3 \
      libxi6 \
      libxtst6 \
      libnss3 \
      libglib2.0-0 \
      libdrm2 \
      libgbm1 \
      libasound2 \
      fonts-liberation \
      libu2f-udev; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g; s|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get clean


RUN sed -i 's/^CHROMIUM_FLAGS=""/CHROMIUM_FLAGS="--no-sandbox"/' /usr/bin/chromium

# Playwright: use system Chromium (already installed above).
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
# Avoid Playwright downloading its own browser when executable_path is used.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
# Indicate running in container (used e.g. for Chromium --no-sandbox).
ENV QWENPAW_RUNNING_IN_CONTAINER=1

WORKDIR ${WORKSPACE_DIR}

RUN python3 -m venv venv
ENV PATH="/app/venv/bin:$PATH"

COPY pyproject.toml uv.lock setup.py README.md ./
COPY scripts/db ./scripts/db
COPY scripts/perf ./scripts/perf
COPY src ./src
COPY website/public/docs/ ./src/qwenpaw/docs/
# Inject console dist from build stage (repo does not commit dist). Remove any
# stale checked-in console assets first so old hashed bundles cannot linger.
RUN rm -rf ./src/qwenpaw/console
COPY --from=console-builder /app/console/dist/ ./src/qwenpaw/console/
# Speed up Python package installation with uv.
COPY --from=agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/uv:latest /uv /bin/uv
RUN uv export --frozen --no-dev --no-emit-project --no-hashes \
      --output-file /tmp/requirements.txt \
  && uv pip install --no-cache-dir \
      --index-url https://mirrors.aliyun.com/pypi/simple/ \
      --requirement /tmp/requirements.txt \
  && uv pip install --no-cache-dir --no-deps . \
  && rm -f /tmp/requirements.txt \
  && rm -rf ./build


# QwenPaw app port (default 8088). Override at runtime with -e QWENPAW_PORT=3000.
ENV QWENPAW_PORT=8088

COPY deploy/config/supervisord.conf.template /etc/supervisor/conf.d/supervisord.conf.template
COPY --chmod=755 deploy/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod 755 /entrypoint.sh

EXPOSE 8088

CMD ["/entrypoint.sh"]
