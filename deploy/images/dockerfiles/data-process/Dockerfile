ARG DATA_PROCESS_DEPENDENCY_VARIANT=cpu

FROM python:3.11-slim AS data-process-base
ARG MIRROR
ARG APT_MIRROR
ARG TARGETARCH
LABEL authors="nexent"

# Set correct permissions as root
USER root

# Configure apt sources based on build argument
RUN --mount=type=cache,id=nexent-data-process-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-data-process-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
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
    apt-get install -y --no-install-recommends --fix-missing \
        curl \
        postgresql-client \
        libmagic1 \
        libmagic-dev \
        libgl1 \
        coreutils && \
    apt-get autoremove -y && \
    rm -rf /tmp/* /var/tmp/*

FROM data-process-base AS data-process-deps
ARG MIRROR
ARG TARGETARCH
ARG DATA_PROCESS_DEPENDENCY_VARIANT

RUN --mount=type=cache,id=nexent-data-process-pip-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    pip install uv $(test -n "$MIRROR" && echo "-i $MIRROR")
WORKDIR /opt/backend
# Layer 1: install base dependencies
COPY backend/pyproject.toml /opt/backend/pyproject.toml
COPY sdk /opt/sdk
RUN --mount=type=cache,id=nexent-data-process-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    printf '%s\n' \
        cuda-bindings \
        cuda-pathfinder \
        cuda-toolkit \
        nvidia-cublas \
        nvidia-cublas-cu11 \
        nvidia-cublas-cu12 \
        nvidia-cublas-cu13 \
        nvidia-cuda-cccl \
        nvidia-cuda-crt \
        nvidia-cuda-culibos \
        nvidia-cuda-cupti \
        nvidia-cuda-cupti-cu11 \
        nvidia-cuda-cupti-cu12 \
        nvidia-cuda-cupti-cu13 \
        nvidia-cuda-cuxxfilt \
        nvidia-cuda-nvcc \
        nvidia-cuda-nvrtc \
        nvidia-cuda-nvrtc-cu11 \
        nvidia-cuda-nvrtc-cu12 \
        nvidia-cuda-nvrtc-cu13 \
        nvidia-cuda-opencl \
        nvidia-cuda-profiler-api \
        nvidia-cuda-runtime \
        nvidia-cuda-runtime-cu11 \
        nvidia-cuda-runtime-cu12 \
        nvidia-cuda-runtime-cu13 \
        nvidia-cuda-sanitizer-api \
        nvidia-cudnn \
        nvidia-cudnn-cu11 \
        nvidia-cudnn-cu12 \
        nvidia-cudnn-cu13 \
        nvidia-cufft \
        nvidia-cufft-cu11 \
        nvidia-cufft-cu12 \
        nvidia-cufft-cu13 \
        nvidia-cufile \
        nvidia-cufile-cu11 \
        nvidia-cufile-cu12 \
        nvidia-cufile-cu13 \
        nvidia-curand \
        nvidia-curand-cu11 \
        nvidia-curand-cu12 \
        nvidia-curand-cu13 \
        nvidia-cusolver \
        nvidia-cusolver-cu11 \
        nvidia-cusolver-cu12 \
        nvidia-cusolver-cu13 \
        nvidia-cusparse \
        nvidia-cusparse-cu11 \
        nvidia-cusparse-cu12 \
        nvidia-cusparse-cu13 \
        nvidia-cusparselt \
        nvidia-cusparselt-cu12 \
        nvidia-cusparselt-cu13 \
        nvidia-nccl \
        nvidia-nccl-cu11 \
        nvidia-nccl-cu12 \
        nvidia-nccl-cu13 \
        nvidia-npp \
        nvidia-nvfatbin \
        nvidia-nvjitlink \
        nvidia-nvjitlink-cu11 \
        nvidia-nvjitlink-cu12 \
        nvidia-nvjitlink-cu13 \
        nvidia-nvjpeg \
        nvidia-nvml-dev \
        nvidia-nvptxcompiler \
        nvidia-nvshmem \
        nvidia-nvshmem-cu12 \
        nvidia-nvshmem-cu13 \
        nvidia-nvtx \
        nvidia-nvtx-cu11 \
        nvidia-nvtx-cu12 \
        nvidia-nvtx-cu13 \
        nvidia-nvvm \
        triton \
        > /tmp/nvidia-excludes.txt && \
    mirror_index_args="" && \
    if [ -n "$MIRROR" ]; then \
        mirror_index_args="--default-index ${MIRROR}"; \
    fi && \
    if [ "$DATA_PROCESS_DEPENDENCY_VARIANT" = "cpu" ]; then \
        torch_args="--torch-backend cpu --excludes /tmp/nvidia-excludes.txt"; \
    elif [ "$DATA_PROCESS_DEPENDENCY_VARIANT" = "gpu" ]; then \
        torch_args=""; \
    else \
        echo "Unsupported DATA_PROCESS_DEPENDENCY_VARIANT: ${DATA_PROCESS_DEPENDENCY_VARIANT}" >&2; \
        exit 1; \
    fi && \
    uv venv .venv && \
    uv pip install --python .venv/bin/python --link-mode copy $mirror_index_args $torch_args ".[data-process]" && \
    uv pip install --python .venv/bin/python --link-mode copy $mirror_index_args $torch_args "/opt/sdk[data-process]" && \
    if [ "$DATA_PROCESS_DEPENDENCY_VARIANT" = "cpu" ]; then \
        .venv/bin/python -c 'import importlib.metadata as metadata, importlib.util, sys; blocked = sorted(name for name in ((dist.metadata.get("Name") or "").lower() for dist in metadata.distributions()) if name == "triton" or name.startswith("nvidia-") or name.startswith("cuda-")); blocked and sys.exit("CPU data-process image must not install CUDA packages: " + ", ".join(blocked)); spec = importlib.util.find_spec("torch"); torch = __import__("torch") if spec else None; torch is not None and torch.cuda.is_available() and sys.exit("CPU data-process image unexpectedly reports CUDA availability"); print(f"Using CPU PyTorch {torch.__version__}") if torch else None'; \
    fi

FROM data-process-base AS final
ARG TARGETARCH

ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:/usr/bin:/bin:/usr/local/bin:$PATH"
WORKDIR /opt/backend

RUN --mount=type=cache,id=nexent-data-process-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-data-process-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    apt-get update && \
    apt-get install -y --no-install-recommends --fix-missing \
        libreoffice \
        pandoc \
        fontconfig \
        fonts-noto-cjk && \
    fc-cache -fv && \
    apt-get autoremove -y && \
    rm -rf /tmp/* /var/tmp/*

RUN --mount=type=bind,source=model-assets,target=/tmp/model-assets,readonly \
    mkdir -p /opt/models && \
    cp -a /tmp/model-assets/clip-vit-base-patch32 /opt/models/clip-vit-base-patch32 && \
    cp -a /tmp/model-assets/nltk_data /opt/models/nltk_data && \
    cp -a /tmp/model-assets/table-transformer-structure-recognition /opt/models/table-transformer-structure-recognition && \
    cp -a /tmp/model-assets/yolox /opt/models/yolox

COPY --from=data-process-deps /opt/backend/.venv /opt/backend/.venv
COPY --from=data-process-deps /opt/sdk /opt/sdk

# Pre-download tiktoken cl100k_base model to avoid network issues during runtime.
RUN python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base')"

# Layer 3: copy backend code
COPY backend /opt/backend
COPY VERSION /opt/nexent/VERSION
COPY deploy/common/run-sql-migrations.sh deploy/common/start-backend.sh /opt/nexent/scripts/
RUN chmod +x /opt/nexent/scripts/run-sql-migrations.sh /opt/nexent/scripts/start-backend.sh

WORKDIR /opt

# Expose the service port
EXPOSE 5012
