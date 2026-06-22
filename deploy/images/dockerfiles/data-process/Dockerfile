ARG DATA_PROCESS_VARIANT=full

FROM python:3.11-slim AS data-process-base
ARG MIRROR
ARG APT_MIRROR
LABEL authors="nexent"

# Set correct permissions as root
USER root

# Configure apt sources based on build argument
RUN if [ "$APT_MIRROR" = "tsinghua" ]; then \
    rm -f /etc/apt/sources.list.d/* && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends curl postgresql-client && rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y --no-install-recommends --fix-missing \
    libmagic1 \
    libmagic-dev \
    libgl1 \
    coreutils \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

FROM data-process-base AS data-process-runtime-full
RUN apt-get update && \
    apt-get install -y --no-install-recommends --fix-missing \
    libreoffice \
    fontconfig \
    fonts-noto-cjk \
    && fc-cache -fv \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY model-assets/clip-vit-base-patch32 /opt/models/clip-vit-base-patch32
COPY model-assets/nltk_data /opt/models/nltk_data
COPY model-assets/table-transformer-structure-recognition /opt/models/table-transformer-structure-recognition
COPY model-assets/yolox /opt/models/yolox

FROM data-process-base AS data-process-runtime-slim
RUN mkdir -p /opt/models

FROM data-process-runtime-${DATA_PROCESS_VARIANT} AS final
ARG MIRROR

RUN pip install --no-cache-dir uv $(test -n "$MIRROR" && echo "-i $MIRROR")
WORKDIR /opt/backend
# Layer 1: install base dependencies
COPY backend/pyproject.toml /opt/backend/pyproject.toml
RUN uv sync --no-cache-dir --extra data-process $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv cache clean
# Layer 2: install sdk in link mode
COPY sdk /opt/sdk
RUN uv pip install --no-cache-dir "/opt/sdk[performance]" $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv cache clean

# Pre-download tiktoken cl100k_base model to avoid network issues during runtime
RUN uv run python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base')"

# Layer 3: copy backend code
COPY backend /opt/backend
COPY VERSION /opt/nexent/VERSION
COPY deploy/sql/migrations /opt/nexent/sql
COPY deploy/common/run-sql-migrations.sh deploy/common/start-backend.sh /opt/nexent/scripts/
RUN chmod +x /opt/nexent/scripts/run-sql-migrations.sh /opt/nexent/scripts/start-backend.sh

ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:/usr/bin:/bin:/usr/local/bin:$PATH"

WORKDIR /opt

# Expose the service port
EXPOSE 5012
