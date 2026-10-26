ARG DATA_PROCESS_DEPENDENCY_VARIANT=cpu

FROM python:3.11-slim AS data-process-base
ARG MIRROR
ARG APT_MIRROR
ARG TARGETARCH
LABEL authors="nexent"
ENV TZ=Asia/Shanghai

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
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --fix-missing \
        curl \
        vim \
        procps \
        wget \
        less \
        tzdata \
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

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/
WORKDIR /opt/backend
# Layer 1: install base dependencies
COPY backend/pyproject.toml /opt/backend/pyproject.toml
COPY sdk /opt/sdk
RUN --mount=type=cache,id=nexent-data-process-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    if [ "$DATA_PROCESS_DEPENDENCY_VARIANT" = "cpu" ]; then \
        dependency_extra="data-process"; \
    elif [ "$DATA_PROCESS_DEPENDENCY_VARIANT" = "gpu" ]; then \
        dependency_extra="nvidia"; \
    else \
        echo "Unsupported DATA_PROCESS_DEPENDENCY_VARIANT: ${DATA_PROCESS_DEPENDENCY_VARIANT}" >&2; \
        exit 1; \
    fi && \
    uv sync --no-editable --link-mode copy --extra "$dependency_extra" \
        $(test -n "$MIRROR" && echo "--default-index $MIRROR")

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
        fontconfig \
        fonts-noto-cjk \
        libreoffice \
        pandoc \
        poppler-utils \
        tesseract-ocr && \
    fc-cache -fv && \
    apt-get autoremove -y && \
    rm -rf /tmp/* /var/tmp/*

# NLTK >= 3.10 refuses a data root that is group/world-writable or not owned by
# root. cp -a preserves the build-context mode, and on Windows/WSL the
# model-assets checkout is 777, so normalize the baked copy to match CI builds.
RUN --mount=type=bind,source=model-assets,target=/tmp/model-assets,readonly \
    mkdir -p /opt/models && \
    cp -a /tmp/model-assets/clip-vit-base-patch32 /opt/models/clip-vit-base-patch32 && \
    cp -a /tmp/model-assets/nltk_data /opt/models/nltk_data && \
    cp -a /tmp/model-assets/table-transformer-structure-recognition /opt/models/table-transformer-structure-recognition && \
    cp -a /tmp/model-assets/yolox /opt/models/yolox && \
    chown -R root:root /opt/models/nltk_data && \
    chmod -R u+rwX,go+rX,go-w /opt/models/nltk_data

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
