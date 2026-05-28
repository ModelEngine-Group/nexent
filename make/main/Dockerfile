FROM python:3.11-slim
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
RUN uv pip install --no-cache-dir "/opt/sdk[performance]" $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv cache clean

# Layer 1.5: install openjiuwen without its heavyweight transitive deps (transformers, etc.)
# openjiuwen's prompt_builder only needs pydantic, openai, httpx, tiktoken — all already in sdk/base
# Using --no-deps then installing only what's needed avoids pulling in transformers (~2GB) etc.
# pymilvus IS needed — openjiuwen's import chain references it and the real module must exist
# dashscope/pdfplumber remain stubbed since they are never called at runtime
RUN uv pip install --no-cache-dir --no-deps openjiuwen $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv pip install --no-cache-dir pymilvus $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv pip install --no-cache-dir pydantic openai tiktoken httpx $(test -n "$MIRROR" && echo "-i $MIRROR") && \
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
