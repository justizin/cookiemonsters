# cookiemonsters grading server, standalone (SQLite) — see docs/DEPLOY.md#container
#
#   podman build -t cookiemonsters .                       # podman / buildah find this file by default
#   docker build -f Containerfile -t cookiemonsters .      # docker needs -f
#
#   podman run -d --name cookiemonsters -p 127.0.0.1:8787:8787 -v cookiemonsters-data:/data cookiemonsters
#   (docker run takes the same arguments)

ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# ---- build: turn ./api into a wheel ------------------------------------------
FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src
COPY api/ ./api/
RUN python -m pip wheel --wheel-dir /wheels "./api[standalone]"

# ---- runtime -------------------------------------------------------------------
FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="cookiemonsters" \
      org.opencontainers.image.description="Grades websites on how hard they make refusing tracking cookies (standalone server)" \
      org.opencontainers.image.source="https://github.com/justizin/cookiemonsters" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    CM_CONTAINER=1 \
    CM_HOST=0.0.0.0 \
    CM_PORT=8787 \
    CM_DB_PATH=/data/cookiemonsters.sqlite3

COPY --from=build /wheels /tmp/wheels
RUN python -m pip install --no-index --find-links /tmp/wheels "cookiemonsters[standalone]" \
 && rm -rf /tmp/wheels \
 && useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin cookiemonsters \
 && mkdir -p /data && chown cookiemonsters /data

USER 10001
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('CM_PORT', '8787'), timeout=2)"]

ENTRYPOINT ["cookiemonsters"]
CMD ["serve"]
