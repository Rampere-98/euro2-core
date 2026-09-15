# syntax=docker/dockerfile:1.7
# Euro2 server image: API + scheduler + local models, with the Flutter web app and the public
# site baked in. Built for amd64 and arm64 (Oracle Ampere) by .github/workflows/image.yml.

# ---- Flutter web build ------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM debian:bookworm-slim AS web
ARG FLUTTER_VERSION=3.47.4
RUN apt-get update && apt-get install -y --no-install-recommends git curl unzip xz-utils ca-certificates     && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 -b ${FLUTTER_VERSION} https://github.com/flutter/flutter.git /opt/flutter
ENV PATH=/opt/flutter/bin:$PATH
RUN git config --global --add safe.directory /opt/flutter && flutter config --no-analytics --enable-web     && flutter precache --web
WORKDIR /src
COPY app/pubspec.yaml app/pubspec.lock ./app/
RUN cd app && flutter pub get
COPY app ./app
RUN cd app && flutter build web --release --base-href /app/

# ---- Python runtime ---------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HF_HOME=/data/hf-cache \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /srv/euro2
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic.ini README.md ./
COPY alembic ./alembic
COPY site ./site
COPY --from=web /src/app/build/web ./app/build/web
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
ARG IMAGE_SHA=dev
ENV EURO2_IMAGE_SHA=$IMAGE_SHA \
    DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD curl -fsS http://localhost:8000/health || exit 1
# migrate, then serve (API + scheduler); the first admin registers from the app
CMD ["sh", "-c", "alembic upgrade head && python -m euro2core serve --host 0.0.0.0 --port 8000"]
