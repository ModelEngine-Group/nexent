FROM python:3.10-slim
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
    apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y --no-install-recommends --fix-missing \
        curl \
        libmagic1 \
        libmagic-dev \
        libreoffice \
        libgl1 \
        coreutils \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN pip install --no-cache-dir uv $(test -n "$MIRROR" && echo "-i $MIRROR")
# Layer 0: copy model assets
COPY model-assets/clip-vit-base-patch32 /opt/models/clip-vit-base-patch32
COPY model-assets/nltk_data /opt/models/nltk_data

WORKDIR /opt/backend
# Layer 1: install base dependencies
COPY backend/pyproject.toml /opt/backend/pyproject.toml
RUN uv sync --no-cache-dir --extra data-process $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv cache clean
# Layer 2: install sdk in link mode
COPY sdk /opt/sdk
RUN uv pip install --no-cache-dir /opt/sdk $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv cache clean

# Pre-download tiktoken cl100k_base model to avoid network issues during runtime
RUN uv run python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base')"
# Layer 3: copy backend code
COPY backend /opt/backend

ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:/usr/bin:/bin:/usr/local/bin:$PATH"

WORKDIR /opt

# Expose the service port
EXPOSE 5012
