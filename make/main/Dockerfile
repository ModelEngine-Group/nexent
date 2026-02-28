FROM python:3.10-slim
ARG MIRROR
ARG APT_MIRROR
LABEL authors="nexent"

# Set correct permissions as root
USER root
RUN umask 0022

# Configure apt sources based on build argument
RUN if [ "$APT_MIRROR" = "tsinghua" ]; then \
        rm -f /etc/apt/sources.list.d/* && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv $(test -n "$MIRROR" && echo "-i $MIRROR")
WORKDIR /opt/backend

# Layer 0: install base dependencies
COPY backend/pyproject.toml /opt/backend/pyproject.toml
RUN uv sync --no-cache-dir $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv cache clean
# Layer 1: install sdk in link mode
COPY sdk /opt/sdk
RUN uv pip install --no-cache-dir /opt/sdk $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv cache clean

# Pre-download tiktoken cl100k_base model to avoid network issues during runtime
RUN uv run python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base')"
# Layer 2: copy backend code
COPY backend /opt/backend

# Create SSH key directory for Terminal tool
RUN mkdir -p /opt/ssh-keys
VOLUME ["/opt/ssh-keys"]

ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /opt

# Expose the service port
EXPOSE 5010
