# syntax=docker/dockerfile:1.7
#
# QGroundControl v5.1.5 (official stable release) for the offline .plan import check.
#
# Self-contained: the AppImage is fetched from the immutable GitHub release and checked against the
# sha256 that GitHub publishes for that asset; base image and apt packages are pinned (digest and
# snapshot.ubuntu.com date). Nothing is read from the host, /tmp or a previous session.
#
#   docker build -t tfg/qgroundcontrol:5.1.5 deploy/qgc
#
# Provenance of the asset (consulted 27/10/2026): release v5.1.5 "QGroundControl V5.1 - Stable",
# immutable, tag object 94287222 -> commit 3a67d31f0c36bf3fe38ec52970d250a89d0aaf67 (tag unsigned),
# uploaded by DonLakeFlyer on 2026-10-01; GitHub build-provenance attestations exist for the asset.
# Upstream docs: AppImage supported on Ubuntu 24.04 / 26.04, built on ubuntu-24.04 runners.

ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c

# ---- fetch: download, check and unpack the AppImage (no FUSE needed for --appimage-extract) ----
FROM ${UBUNTU_IMAGE} AS fetch
ADD --checksum=sha256:9a47e4cf269d9e4f897f582f6b19aa7ebf1e9e67c9d68a532a45b541354bc344 \
    https://github.com/mavlink/qgroundcontrol/releases/download/v5.1.5/QGroundControl-x86_64.AppImage \
    /fetch/QGroundControl-x86_64.AppImage
RUN cd /fetch \
    && chmod 0755 QGroundControl-x86_64.AppImage \
    && ./QGroundControl-x86_64.AppImage --appimage-extract >/dev/null \
    && mv squashfs-root /opt/qgroundcontrol \
    && chmod -R a+rX,go-w /opt/qgroundcontrol

# Exported only to verify the attestation on the exact bytes used by this build:
#   docker build --target artifact --output type=local,dest=OUT deploy/qgc
FROM scratch AS artifact
COPY --from=fetch /fetch/QGroundControl-x86_64.AppImage /

# ---- certs: TLS trust anchors only for reaching snapshot.ubuntu.com (https-only) ----
# Comes from the live archive and is NOT pinned; it is bind-mounted into the apt step below and never
# copied into the image. Package integrity still rests on the signed snapshot indexes.
FROM ${UBUNTU_IMAGE} AS certs
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates

# ---- runtime ----
FROM ${UBUNTU_IMAGE}
ARG APT_SNAPSHOT=20261024T000000Z
# Runtime libraries the AppImage expects from the system (upstream docs list the xcb ones; AppRun
# preloads the system libEGL/libGLESv2). Mesa only: rendering is software (llvmpipe), no GPU device.
# Sources point only at the snapshot (no fallback to the live archive).
RUN --mount=type=bind,from=certs,source=/etc/ssl/certs/ca-certificates.crt,target=/run/tfg-ca.crt \
    sed -i -E "s#^URIs: .*#URIs: https://snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}/#" \
        /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::https::CaInfo=/run/tfg-ca.crt update \
    && apt-get -o Acquire::https::CaInfo=/run/tfg-ca.crt install -y --no-install-recommends \
        libegl1 libgles2 libgl1 libglx-mesa0 libgl1-mesa-dri \
        libxcb-xinerama0 libxkbcommon-x11-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
        libxcb-shape0 libxcb-xfixes0 libxcb-xkb1 libx11-xcb1 libxkbcommon0 \
        libfontconfig1 libfreetype6 fonts-dejavu-core libdbus-1-3 \
        libasound2t64 libfribidi0 libharfbuzz0b libxrandr2 \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o 1000 -g 1000 -m 0700 /home/qgc \
    && install -d -m 0755 /opt/tfg

COPY --from=fetch /opt/qgroundcontrol /opt/qgroundcontrol
COPY --chmod=0644 QGroundControl.ini /opt/tfg/QGroundControl.ini
COPY --chmod=0755 entrypoint.sh /opt/tfg/entrypoint.sh

LABEL org.opencontainers.image.title="tfg-qgroundcontrol" \
      org.opencontainers.image.version="5.1.5" \
      org.opencontainers.image.source="https://github.com/mavlink/qgroundcontrol/releases/tag/v5.1.5" \
      tfg.qgc.appimage.sha256="9a47e4cf269d9e4f897f582f6b19aa7ebf1e9e67c9d68a532a45b541354bc344" \
      tfg.qgc.commit="3a67d31f0c36bf3fe38ec52970d250a89d0aaf67" \
      tfg.apt.snapshot="20261024T000000Z"

# Not installed on purpose (optional Qt plugins, not needed to open/save a .plan): GTK3 platform
# theme (libqgtk3) and speech-dispatcher text-to-speech (libqtexttospeech_speechd).
ENV LANG=C.UTF-8 \
    QT_QPA_PLATFORM=xcb \
    QT_X11_NO_MITSHM=1 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    HOME=/home/qgc

# Default unprivileged user (uid 1000 already exists in ubuntu:24.04); Compose may override the uid.
USER 1000:1000
ENTRYPOINT ["/opt/tfg/entrypoint.sh"]
