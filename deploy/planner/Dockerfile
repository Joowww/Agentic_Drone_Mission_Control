# syntax=docker/dockerfile:1.7
#
# Planning profile image: Hermes (the project's agent runtime) + the project's MCP server, validation and stores.
# Plans and validates only: Hermes runs with the project's MCP server restricted to the planning tools
# (deploy/planner/hermes_home.py); no simulator, vehicle, Docker socket or ROS. No model, credential or
# provider configuration is inside the image (HERMES_HOME is a volume; login with `hermes auth`).
#
#   python3 deploy/planner/hermes_source.py fetch --out deploy/planner/vendor/hermes-agent-d923a5eb.tar
#       (or `export --repo <a clone holding the commit>`; both verify the commit's tree)
#   docker build -f deploy/planner/Dockerfile --build-context hermes_src=deploy/planner/vendor \
#       -t tfg/planner:2026.10.28 .                                                (context: repository root)
#
# Hermes: NousResearch/hermes-agent at d923a5eb487a17c0a68801bba9ef0f56c81040a8 (the commit of the executed H1 turn
# and of the capture runner's verified sources), installed like Joel's install record: its uv.lock, extra "all",
# with the uv and CPython builds pinned in its own pm/lock.json (uv 0.12.3, CPython 3.14.7+20260901).

ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c

# ---- certs: TLS trust anchors only for reaching snapshot.ubuntu.com (https-only); never copied ----
FROM ${UBUNTU_IMAGE} AS certs
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates

# ---- base: Python 3.12 (project) and CA certificates from the pinned Ubuntu snapshot ----
FROM ${UBUNTU_IMAGE} AS base
ARG APT_SNAPSHOT=20261024T000000Z
RUN --mount=type=bind,from=certs,source=/etc/ssl/certs/ca-certificates.crt,target=/run/tfg-ca.crt \
    sed -i -E "s#^URIs: .*#URIs: https://snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}/#" \
        /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::https::CaInfo=/run/tfg-ca.crt -o APT::Update::Error-Mode=any update \
    && apt-get -o Acquire::https::CaInfo=/run/tfg-ca.crt install -y --no-install-recommends \
        python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- deps: the project's verified versions (same as deploy/app) ----
FROM base AS deps
COPY requirements.txt requirements-observability.txt constraints-verified.txt /opt/tfg-build/
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check \
        --report /opt/tfg-build/pip-install-report.json \
        -r /opt/tfg-build/requirements.txt -r /opt/tfg-build/requirements-observability.txt \
        -c /opt/tfg-build/constraints-verified.txt \
    && /opt/venv/bin/pip freeze --all > /opt/tfg-build/pip-freeze.txt

# ---- hermes: pinned checkout, uv and CPython from Hermes' own lock, environment from its uv.lock ----
FROM base AS hermes
ADD --checksum=sha256:600cf9a742aca00d292673b16b5acffaa7b8c269a364ad0c2e79498dcb1fe101 \
    https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-unknown-linux-gnu.tar.gz /tmp/uv.tar.gz
ADD --checksum=sha256:0ab3305457051cd3e7c031857e005f1bda17c218a1990567dacaaac6dd1d14f0 \
    https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.14.7+20260901-x86_64-unknown-linux-gnu-install_only.tar.gz \
    /tmp/python.tar.gz
# Frozen Hermes source (build context `hermes_src` = deploy/planner/vendor, produced by
# deploy/planner/hermes_source.py export|fetch): raw blobs of the commit's tree, verified here twice, by its sha256
# and by recomputing the git tree hash 5a064077... of commit d923a5eb (no git fetch at build time).
COPY --from=hermes_src hermes-agent-d923a5eb.tar /tmp/hermes-agent.tar
COPY deploy/planner/hermes_source.py /tmp/hermes_source.py
RUN echo "5b668df1d429ab315e1ba857a9ffa00898b5cf066b6d9304b8698d5d300fa7c0  /tmp/hermes-agent.tar" | sha256sum -c - \
    && python3 /tmp/hermes_source.py verify /tmp/hermes-agent.tar \
    && mkdir -p /opt/hermes/agent && tar -xf /tmp/hermes-agent.tar -C /opt/hermes/agent --no-same-owner \
    && rm /tmp/hermes-agent.tar /tmp/hermes_source.py
RUN mkdir -p /opt/hermes/python /tmp/uv \
    && tar -xzf /tmp/uv.tar.gz -C /tmp/uv --strip-components=1 \
    && tar -xzf /tmp/python.tar.gz -C /opt/hermes/python --strip-components=1 \
    && cd /opt/hermes/agent \
    && UV_PYTHON=/opt/hermes/python/bin/python3 UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 UV_LINK_MODE=copy \
       /tmp/uv/uv sync --frozen --no-dev --extra all \
    && /opt/hermes/agent/.venv/bin/python -c "import hermes_cli" \
    && (cd /opt/hermes/agent && find . -path ./.venv -prune -o -type f -print0 | sort -z | xargs -0 sha256sum) \
        > /opt/hermes/agent-files.sha256 \
    && rm -rf /tmp/uv /tmp/uv.tar.gz /tmp/python.tar.gz

# ---- runtime ----
FROM base
COPY --from=deps /opt/venv /opt/venv
COPY --from=deps /opt/tfg-build/pip-install-report.json /opt/tfg-build/pip-freeze.txt /opt/tfg-provenance/
COPY --from=hermes /opt/hermes /opt/hermes
COPY . /opt/tfg/
RUN cd /opt/tfg && find . -type f -print0 | sort -z | xargs -0 sha256sum > /opt/tfg-provenance/files.sha256 \
    && ln -s /opt/venv /opt/tfg/.venv \
    && install -d -m 0755 /opt/tfg/missions/generated /work \
    && install -d -o 1000 -g 1000 -m 0700 /hermes /hermes/planning \
    && chmod -R a+rX,go-w /opt/tfg /opt/tfg-provenance /opt/hermes

LABEL org.opencontainers.image.title="tfg-planner" \
      org.opencontainers.image.version="2026.10.28" \
      org.opencontainers.image.description="Planning profile: Hermes + project MCP server restricted to planning tools" \
      tfg.hermes.commit="d923a5eb487a17c0a68801bba9ef0f56c81040a8" \
      tfg.apt.snapshot="20261024T000000Z"

ENV PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/home \
    HERMES_HOME=/hermes/planning \
    TFG_PROFILE=planning
WORKDIR /opt/tfg
USER 1000:1000
ENTRYPOINT ["python3", "/opt/tfg/deploy/app/entry.py"]
CMD ["/opt/tfg/deploy/planner/hermes_home.py", "status"]
