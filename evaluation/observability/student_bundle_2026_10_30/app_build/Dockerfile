# syntax=docker/dockerfile:1.7
#
# Offline application image: scenario query over conserved evidence, synthetic demo, site validation,
# instantiation, package export/verification, .plan comparison and the existing reports.
#
#   docker build -f deploy/app/Dockerfile -t tfg/app:2026.10.30 .        (context: repository root, or the frozen copy of the evidence)
#
# Contents come ONLY from the build-context allowlist deploy/app/Dockerfile.dockerignore, generated from the
# app_image set of tools/agri_scenario_distribution.py (static import closure + inputs + evidence). No ROS, Gazebo,
# simulator, Docker socket or LLM provider. Python 3.12.3 from Ubuntu 24.04 is the version under which
# constraints-verified.txt was verified.

ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c

# ---- certs: TLS trust anchors only for reaching snapshot.ubuntu.com (https-only) ----
# From the live archive, NOT pinned; bind-mounted into the apt step and never copied into the image.
FROM ${UBUNTU_IMAGE} AS certs
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates

# ---- base: Python from the pinned Ubuntu snapshot ----
FROM ${UBUNTU_IMAGE} AS base
ARG APT_SNAPSHOT=20261024T000000Z
RUN --mount=type=bind,from=certs,source=/etc/ssl/certs/ca-certificates.crt,target=/run/tfg-ca.crt \
    sed -i -E "s#^URIs: .*#URIs: https://snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}/#" \
        /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::https::CaInfo=/run/tfg-ca.crt -o APT::Update::Error-Mode=any update \
    && apt-get -o Acquire::https::CaInfo=/run/tfg-ca.crt install -y --no-install-recommends \
        python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ---- deps: the project's verified versions (requirements + constraints-verified.txt), from PyPI ----
FROM base AS deps
COPY requirements.txt requirements-observability.txt constraints-verified.txt /opt/tfg-build/
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check \
        --report /opt/tfg-build/pip-install-report.json \
        -r /opt/tfg-build/requirements.txt -r /opt/tfg-build/requirements-observability.txt \
        -c /opt/tfg-build/constraints-verified.txt \
    && /opt/venv/bin/pip freeze --all > /opt/tfg-build/pip-freeze.txt

# ---- runtime ----
FROM base
COPY --from=deps /opt/venv /opt/venv
COPY --from=deps /opt/tfg-build/pip-install-report.json /opt/tfg-build/pip-freeze.txt /opt/tfg-provenance/
COPY . /opt/tfg/
RUN cd /opt/tfg && find . -type f -print0 | sort -z | xargs -0 sha256sum > /opt/tfg-provenance/files.sha256 \
    && chmod -R a+rX,go-w /opt/tfg /opt/tfg-provenance

LABEL org.opencontainers.image.title="tfg-app" \
      org.opencontainers.image.version="2026.10.30" \
      org.opencontainers.image.description="Offline agri_demo_001 scenario tools (no simulator, no LLM provider)" \
      tfg.apt.snapshot="20261024T000000Z" \
      tfg.python.constraints="constraints-verified.txt"

# HOME and caches go to tmpfs at run time (read-only root filesystem); no .pyc is written into /opt/tfg.
ENV PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/home \
    TFG_PROFILE=offline
WORKDIR /opt/tfg
USER 1000:1000
# Same arguments as python3 (-m MODULE / -c CODE / SCRIPT); an early Ctrl+C ends with a message, not a traceback.
ENTRYPOINT ["python3", "/opt/tfg/deploy/app/entry.py"]
CMD ["main.py"]
