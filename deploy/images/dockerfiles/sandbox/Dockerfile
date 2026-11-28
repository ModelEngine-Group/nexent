# =====================================================================
# Sandbox runtime image for LLM-generated Python execution.
#
# Design reference: doc/docs/zh/backend/sandbox-design.md#6-docker镜像设计
# This image is consumed by smolagents DockerExecutor. Depending on the
# configured sandbox scope, it either serves one agent run or hosts isolated
# per-run Jupyter kernels in a long-running system container.
# =====================================================================

# ---------------------------------------------------------------------
# Stage 1: builder - install uv and the Nexent SDK with all of its
# tool-side dependencies so the runtime stage can copy them in as a
# pre-built artifact (no package installation happens at sandbox startup).
# ---------------------------------------------------------------------
FROM python:3.11-slim AS debian-base

ARG APT_MIRROR=""

# Use the signed Debian repositories over HTTPS and retry transient download failures.
RUN set -eu; \
    for apt_source in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
        [ -f "$apt_source" ] || continue; \
        sed -i 's|http://deb.debian.org/|https://deb.debian.org/|g; s|http://security.debian.org/|https://security.debian.org/|g' "$apt_source"; \
        if [ "$APT_MIRROR" = "tsinghua" ]; then \
            sed -i \
                -e 's|https://deb.debian.org/debian-security|https://security.debian.org/debian-security|g' \
                -e 's|https://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' \
                "$apt_source"; \
        fi; \
    done; \
    printf '%s\n' 'Acquire::Retries "4";' 'Acquire::https::Timeout "30";' > /etc/apt/apt.conf.d/80-nexent-downloads

FROM debian-base AS builder

ARG MIRROR
ARG TARGETARCH
LABEL authors="nexent"

USER root
RUN umask 0022

# Install the build tools.
RUN --mount=type=cache,id=nexent-sandbox-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-sandbox-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    apt-get update --error-on=any && \
    apt-get install -y --no-install-recommends curl build-essential

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

WORKDIR /opt

# Copy SDK source first (and pyproject.toml) so uv can resolve deps.
# The sandbox does not install packages at startup; everything here is
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
# the configured network mode and per-run resource limits; the image itself
# enforces the in-container invariants (non-root, workdir, libs).
# ---------------------------------------------------------------------
FROM debian-base AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

ARG TARGETARCH
LABEL authors="nexent"
LABEL org.opencontainers.image.title="Nexent Sandbox" \
      org.opencontainers.image.description="Default lightweight Nexent sandbox runtime" \
      io.nexent.sandbox.variant="lightweight"

USER root
RUN umask 0022

# Install runtime utilities, a TrueType CJK font for ReportLab, and libgomp1 for numpy/scipy wheels.
RUN --mount=type=cache,id=nexent-sandbox-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-sandbox-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    apt-get update --error-on=any && \
    apt-get install -y --no-install-recommends \
        curl \
        vim \
        procps \
        wget \
        less \
        fonts-wqy-zenhei \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Jupyter Kernel Gateway - the IPC channel smolagents DockerExecutor
# uses to send code actions and stream back observations.
RUN --mount=type=cache,id=nexent-sandbox-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    uv pip install --system --link-mode copy \
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
# releases do not silently break reproducibility. No automatic package installation
# happens at sandbox execution time; missing imports return a structured
# diagnostic that nudges the LLM toward supported packages.
# ---------------------------------------------------------------------
FROM runtime AS with-libs

ARG MIRROR

RUN --mount=type=cache,id=nexent-sandbox-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    uv pip install --system --link-mode copy \
        "numpy>=1.26.4,<2.0" \
        "pandas>=2.0,<3.0" \
        "requests>=2.31,<3.0" \
        "pillow>=10.0,<11.0" \
        "beautifulsoup4>=4.12,<5.0" \
        "lxml>=4.9,<5.0" \
        "openpyxl>=3.1,<4.0" \
        "xlsxwriter>=3.2,<4.0" \
        "xlrd>=2.0,<3.0" \
        "pyxlsb>=1.0,<2.0" \
        "python-docx>=1.1,<2.0" \
        "docx2txt>=0.9,<1.0" \
        "python-pptx>=1.0,<2.0" \
        "pypdf>=6.0,<7.0" \
        "pdfplumber>=0.11,<1.0" \
        "reportlab>=4.2,<5.1" \
        "odfpy>=1.4,<2.0" \
        "defusedxml>=0.7,<1.0" \
        "matplotlib>=3.7,<4.0" \
        "scipy>=1.11,<2.0" \
        "scikit-learn>=1.3,<2.0" \
        "pydantic>=2.0,<3.0" \
        "sympy>=1.12,<2.0" \
        "statsmodels>=0.14,<1.0" \
        "tabulate>=0.9,<1.0" \
        "python-dateutil>=2.8,<3.0" \
    $(test -n "$MIRROR" && echo "-i $MIRROR") \
    && python -c "import numpy, pandas, requests, PIL, bs4, lxml, openpyxl, xlsxwriter, xlrd, pyxlsb, docx, docx2txt, pptx, pypdf, pdfplumber, reportlab, odf, defusedxml, matplotlib, scipy, sklearn, pydantic, sympy, statsmodels, tabulate, dateutil; print('OK')" \
    && python -c "from reportlab.pdfbase.ttfonts import TTFont; face = TTFont('SandboxCJK', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc').face; assert all(face.charToGlyph.get(codepoint) for codepoint in (0x4E2D, 0x6587))" \
    && pip check

# Create a non-root user and the fixed workspace mount root. Runtime creates
# /mnt/nexent/workdir/<user_id>/<run_id> for each run and grants access only
# after mounting or copying that run's workspace into the container. Keep a
# private home workdir as the kernel's neutral default cwd; a Dockerfile cannot
# select a dynamic per-run directory as WORKDIR.
RUN useradd --uid 1000 --create-home --shell /bin/bash sandbox && \
    mkdir -p /home/sandbox/workdir/input \
             /home/sandbox/workdir/output \
             /home/sandbox/workdir/tmp \
             /mnt/nexent/workdir && \
    chown -R sandbox:sandbox /home/sandbox /mnt/nexent

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
