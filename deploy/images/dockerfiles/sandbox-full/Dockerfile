# =====================================================================
# Full sandbox runtime for the supported Anthropic document, design, web, and MCP skills.
#
# Design reference: doc/docs/zh/backend/sandbox-design.md#6-docker镜像设计
# This image is consumed by smolagents DockerExecutor. Depending on the
# configured sandbox scope, it either serves one agent run or hosts isolated
# per-run Jupyter kernels in a long-running system container.
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

# Node is copied into the Python runtime image instead of installed from a
# distribution repository so workspace scripts can rely on the Node 20
# permission model on every supported architecture.
FROM node:20-bookworm-slim AS node-builder

ARG NPM_MIRROR

RUN if [ -n "$NPM_MIRROR" ]; then npm config set registry "$NPM_MIRROR"; fi

RUN npm install --global "pnpm@9.15.9"

WORKDIR /opt/nexent
RUN npm init -y && npm install --save-exact \
        "docx@9.5.1" \
        "pdf-lib@1.17.1" \
        "pdfjs-dist@4.10.38" \
        "pptxgenjs@3.12.0" \
        "react@18.3.1" \
        "react-dom@18.3.1" \
        "react-icons@5.5.0" \
        "sharp@0.33.5"

# Prime pnpm's content-addressed store during the image build. Runtime package
# installs are forced offline and can only resolve content already present here.
WORKDIR /opt/nexent/web-cache
RUN pnpm init && pnpm add \
        "vite@5.4.21" "typescript@5.7.3" "@vitejs/plugin-react@4.3.4" \
        "tailwindcss@3.4.17" "postcss@8.5.3" "autoprefixer@10.4.21" \
        "tailwindcss-animate@1.0.7" "@types/node@22.13.10" \
        "@types/react@18.3.18" "@types/react-dom@18.3.5" \
        "class-variance-authority@0.7.1" "clsx@2.1.1" "tailwind-merge@2.6.0" \
        "lucide-react@0.468.0" "next-themes@0.4.4" \
        "sonner@1.7.4" "cmdk@1.1.1" "vaul@1.1.2" \
        "embla-carousel-react@8.5.2" "react-day-picker@9.5.1" \
        "react-resizable-panels@2.1.7" "date-fns@4.1.0" \
        "react-hook-form@7.54.2" "@hookform/resolvers@3.10.0" "zod@3.24.2" \
        "parcel@2.13.3" "@parcel/config-default@2.13.3" \
        "parcel-resolver-tspaths@0.0.9" "html-inline@1.2.0" \
        "@radix-ui/react-accordion@1.2.3" "@radix-ui/react-avatar@1.1.3" \
        "@radix-ui/react-checkbox@1.3.1" "@radix-ui/react-dialog@1.1.6" \
        "@radix-ui/react-dropdown-menu@2.1.6" "@radix-ui/react-label@2.1.2" \
        "@radix-ui/react-popover@1.1.6" "@radix-ui/react-progress@1.1.2" \
        "@radix-ui/react-radio-group@1.3.2" "@radix-ui/react-scroll-area@1.2.3" \
        "@radix-ui/react-select@2.1.6" "@radix-ui/react-separator@1.1.2" \
        "@radix-ui/react-slider@1.3.1" "@radix-ui/react-slot@1.2.0" \
        "@radix-ui/react-switch@1.2.1" "@radix-ui/react-tabs@1.1.3" \
        "@radix-ui/react-toast@1.2.6" "@radix-ui/react-tooltip@1.2.8"
RUN pnpm add \
        @radix-ui/react-aspect-ratio @radix-ui/react-collapsible \
        @radix-ui/react-context-menu @radix-ui/react-hover-card \
        @radix-ui/react-menubar @radix-ui/react-navigation-menu \
        @radix-ui/react-toggle @radix-ui/react-toggle-group

# `pnpm create vite` uses pnpm's separate dlx metadata/cache in addition to
# the content-addressed store. Prime that exact workflow and every unpinned
# dependency installed by Anthropic's web-artifacts-builder scripts so the
# same commands work with DNS and outbound traffic disabled at runtime.
RUN pnpm create vite nexent-vite-template --template react-ts && \
    cd /opt/nexent/web-cache/nexent-vite-template && \
    pnpm install && \
    pnpm add -D tailwindcss@3.4.1 postcss autoprefixer @types/node tailwindcss-animate && \
    pnpm add class-variance-authority clsx tailwind-merge lucide-react next-themes && \
    pnpm add \
        @radix-ui/react-accordion @radix-ui/react-aspect-ratio @radix-ui/react-avatar \
        @radix-ui/react-checkbox @radix-ui/react-collapsible @radix-ui/react-context-menu \
        @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-hover-card \
        @radix-ui/react-label @radix-ui/react-menubar @radix-ui/react-navigation-menu \
        @radix-ui/react-popover @radix-ui/react-progress @radix-ui/react-radio-group \
        @radix-ui/react-scroll-area @radix-ui/react-select @radix-ui/react-separator \
        @radix-ui/react-slider @radix-ui/react-slot @radix-ui/react-switch \
        @radix-ui/react-tabs @radix-ui/react-toast @radix-ui/react-toggle \
        @radix-ui/react-toggle-group @radix-ui/react-tooltip && \
    pnpm add @hookform/resolvers cmdk date-fns embla-carousel-react react-day-picker \
        react-hook-form react-resizable-panels sonner vaul zod && \
    pnpm add -D parcel @parcel/config-default parcel-resolver-tspaths html-inline && \
    rm -rf /opt/nexent/web-cache/nexent-vite-template

# ---------------------------------------------------------------------
# Stage 2: runtime - minimal Python image with Jupyter Kernel Gateway
# (smolagents DockerExecutor's default IPC channel) and a non-root
# `sandbox` user. The DockerExecutor will run this image with
# the configured network mode and per-run resource limits; the image itself
# enforces the in-container invariants (non-root, workdir, libs).
# ---------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ARG APT_MIRROR
ARG TARGETARCH
LABEL authors="nexent"
LABEL org.opencontainers.image.title="Nexent Sandbox Full" \
      org.opencontainers.image.description="Nexent sandbox for 10 supported Anthropic skills" \
      io.nexent.sandbox.variant="full" \
      io.nexent.sandbox.skills="docx,pdf,pptx,xlsx,canvas-design,frontend-design,slack-gif-creator,mcp-builder,web-artifacts-builder,skill-creator"

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
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation \
        libgomp1 \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-writer \
        pandoc \
        poppler-utils \
        tesseract-ocr \
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
COPY --from=node-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=node-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node-builder /opt/nexent/node_modules /opt/nexent/node_modules
COPY --from=node-builder /root/.local/share/pnpm/store /opt/nexent/pnpm-store
COPY --from=node-builder --chown=1000:1000 /root/.cache/pnpm /home/sandbox/.cache/pnpm

RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    ln -s /usr/local/lib/node_modules/pnpm/bin/pnpm.cjs /usr/local/bin/pnpm

ENV NODE_PATH=/opt/nexent/node_modules:/usr/local/lib/node_modules \
    PNPM_CONFIG_OFFLINE=true \
    PNPM_CONFIG_STORE_DIR=/mnt/nexent/workdir/.pnpm-store \
    npm_config_offline=true \
    npm_config_store_dir=/mnt/nexent/workdir/.pnpm-store \
    COREPACK_ENABLE_NETWORK=0

# ---------------------------------------------------------------------
# Stage 2.5: install only the Python dependencies used by the supported skills.
# ---------------------------------------------------------------------
FROM runtime AS with-libs

ARG MIRROR
ARG TARGETARCH

RUN --mount=type=cache,id=nexent-sandbox-pip-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    pip install --no-cache-dir \
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
        "tabulate>=0.9,<1.0" \
        "python-dateutil>=2.8,<3.0" \
        "anthropic>=0.39,<1.0" \
        "imageio>=2.31,<3.0" \
        "imageio-ffmpeg>=0.4.9,<1.0" \
        "markitdown[pptx]>=0.1,<1.0" \
        "pdf2image>=1.17,<2.0" \
        "pytesseract>=0.3.13,<1.0" \
    $(test -n "$MIRROR" && echo "-i $MIRROR") \
    && python -c "import anthropic, imageio, numpy, pandas, pdf2image, pytesseract, requests, PIL, bs4, lxml, openpyxl, xlsxwriter, xlrd, pyxlsb, docx, docx2txt, pptx, pypdf, pdfplumber, reportlab, odf, defusedxml, tabulate, dateutil, yaml; print('OK')" \
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
    mkdir -p /home/sandbox/.cache && \
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
