# =====================================================================
# Sandbox runtime image for LLM-generated Python execution.
#
# Design reference: doc/docs/zh/backend/sandbox-design.md#6-docker镜像设计
# This image is consumed by smolagents DockerExecutor; it is NOT a
# long-running service and is created/destroyed per agent run.
# =====================================================================

# ---------------------------------------------------------------------
# Stage 1: builder - install uv and the Nexent SDK with all of its
# tool-side dependencies so the runtime stage can copy them in as a
# pre-built artifact (no `pip install` happens at sandbox startup).
# ---------------------------------------------------------------------
FROM python:3.11-slim AS builder

ARG MIRROR
ARG APT_MIRROR
ARG TARGETARCH
LABEL authors="nexent"

USER root
RUN umask 0022

# Configure apt sources based on build argument (mirrors main/Dockerfile).
RUN --mount=type=cache,id=nexent-sandbox-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-sandbox-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    if [ "$APT_MIRROR" = "tsinghua" ]; then \
        for apt_source in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
            [ -f "$apt_source" ] || continue; \
            sed -i \
                -e 's|https\?://deb.debian.org/debian-security|http://security.debian.org/debian-security|g' \
                -e 's|https\?://security.debian.org/debian-security|http://security.debian.org/debian-security|g' \
                -e 's|https\?://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g' \
                "$apt_source"; \
        done; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl build-essential

RUN --mount=type=cache,id=nexent-sandbox-pip-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    pip install uv $(test -n "$MIRROR" && echo "-i $MIRROR")

WORKDIR /opt

# Copy SDK source first (and pyproject.toml) so uv can resolve deps.
# The sandbox does not run `pip install` at startup; everything here is
# pre-installed in the image so that DockerExecutor.start_kernel_gateway
# can hand control to a Jupyter kernel immediately.
COPY sdk/pyproject.toml /opt/sdk/pyproject.toml
COPY sdk/nexent /opt/sdk/nexent

# Install SDK into the system site-packages with link-mode copy so the
# runtime stage can COPY the site-packages wholesale. `--system` matches
# the python:3.11-slim base layout; no venv is created.
RUN --mount=type=cache,id=nexent-sandbox-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    uv pip install --system --link-mode copy "/opt/sdk" $(test -n "$MIRROR" && echo "-i $MIRROR")

# ---------------------------------------------------------------------
# Stage 2: runtime - minimal Python image with Jupyter Kernel Gateway
# (smolagents DockerExecutor's default IPC channel) and a non-root
# `sandbox` user. The DockerExecutor will run this image with
# network_mode=none and per-run resource limits; the image itself only
# enforces the in-container invariants (non-root, workdir, libs).
# ---------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ARG APT_MIRROR
ARG TARGETARCH
LABEL authors="nexent"

USER root
RUN umask 0022

# Minimal apt surface: curl is required by some tools to fetch the
# /files endpoints; libgomp1 is needed by numpy/scipy wheels.
RUN --mount=type=cache,id=nexent-sandbox-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-sandbox-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    if [ "$APT_MIRROR" = "tsinghua" ]; then \
        for apt_source in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
            [ -f "$apt_source" ] || continue; \
            sed -i \
                -e 's|https\?://deb.debian.org/debian-security|http://security.debian.org/debian-security|g' \
                -e 's|https\?://security.debian.org/debian-security|http://security.debian.org/debian-security|g' \
                -e 's|https\?://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g' \
                "$apt_source"; \
        done; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Jupyter Kernel Gateway - the IPC channel smolagents DockerExecutor
# uses to send code actions and stream back observations.
RUN --mount=type=cache,id=nexent-sandbox-pip-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    pip install --no-cache-dir \
        jupyter_kernel_gateway \
        jupyter_client \
        ipykernel

# Bring in the pre-built SDK (source tree) and its resolved dependencies
# from the builder. /usr/local/lib/python3.11/site-packages is the install
# target of `uv pip install --system` on python:3.11-slim.
COPY --from=builder /opt/sdk /opt/sdk
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# ---------------------------------------------------------------------
# Stage 2.5: pre-install the LLM-friendly Python library whitelist
# (design doc §6.4). Versions are pinned with upper bounds so upstream
# releases do not silently break reproducibility. No auto-`pip install`
# happens at sandbox execution time; missing imports return a structured
# diagnostic that nudges the LLM toward supported packages.
# ---------------------------------------------------------------------
FROM runtime AS with-libs

ARG MIRROR

RUN --mount=type=cache,id=nexent-sandbox-pip-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    pip install --no-cache-dir \
        "numpy>=1.26.4,<2.0" \
        "pandas>=2.0,<3.0" \
        "requests>=2.31,<3.0" \
        "pillow>=10.0,<11.0" \
        "beautifulsoup4>=4.12,<5.0" \
        "lxml>=4.9,<5.0" \
        "openpyxl>=3.1,<4.0" \
        "matplotlib>=3.7,<4.0" \
        "scipy>=1.11,<2.0" \
        "scikit-learn>=1.3,<2.0" \
        "pydantic>=2.0,<3.0" \
        "sympy>=1.12,<2.0" \
        "statsmodels>=0.14,<1.0" \
        "tabulate>=0.9,<1.0" \
        "python-dateutil>=2.8,<3.0" \
    $(test -n "$MIRROR" && echo "-i $MIRROR") \
    && python -c "import numpy, pandas, requests, PIL, bs4, lxml, openpyxl, matplotlib, scipy, sklearn, pydantic, sympy, statsmodels, tabulate, dateutil; print('OK')"

# Create a non-root user so the LLM code cannot write outside /home/sandbox
# (combined with network_mode=none + run-scoped resource limits, this is
# the in-container half of the security boundary; the host-side halves
# are enforced by the DockerExecutor at run start).
RUN useradd --uid 1000 --create-home --shell /bin/bash sandbox && \
    mkdir -p /home/sandbox/workdir/input \
             /home/sandbox/workdir/output \
             /home/sandbox/workdir/tmp && \
    chown -R sandbox:sandbox /home/sandbox

WORKDIR /home/sandbox/workdir
USER sandbox

# Jupyter Kernel Gateway is the IPC channel required by smolagents
# DockerExecutor. The Executor passes --gateway-url pointing at this port.
EXPOSE 8888
CMD ["jupyter", "kernelgateway", \
     "--KernelGatewayApp.ip=0.0.0.0", \
     "--KernelGatewayApp.port=8888", \
     "--KernelGatewayApp.allow_origin=*", \
     "--ServerApp.allow_remote_access=True", \
     "--JupyterWebsocketPersonality.list_kernels=True"]