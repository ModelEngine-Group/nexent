# syntax=docker/dockerfile:1.7

FROM ubuntu:24.04

ARG TERMINAL_VARIANT=slim
ARG TARGETARCH

ENV CONDA_DIR=/opt/conda

RUN --mount=type=cache,id=nexent-terminal-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-terminal-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    if [ "$TERMINAL_VARIANT" != "slim" ] && [ "$TERMINAL_VARIANT" != "conda" ]; then \
        echo "Unsupported TERMINAL_VARIANT: ${TERMINAL_VARIANT}" >&2; \
        exit 1; \
    fi && \
    apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        openssh-server \
        curl \
        wget \
        git \
        python3 \
        python3-pip \
        python3-venv && \
    if [ "$TERMINAL_VARIANT" = "conda" ]; then \
        apt-get install -y --no-install-recommends vim build-essential; \
    fi

# Configure SSH - enable root login + enable password authentication.
RUN mkdir /var/run/sshd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config

RUN --mount=type=cache,id=nexent-terminal-miniconda-${TARGETARCH},target=/var/cache/miniconda,sharing=locked \
    if [ "$TERMINAL_VARIANT" = "conda" ]; then \
        arch="${TARGETARCH:-$(dpkg --print-architecture)}" && \
        case "$arch" in \
            amd64|x86_64) conda_arch="x86_64" ;; \
            arm64|aarch64) conda_arch="aarch64" ;; \
            *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
        esac && \
        miniconda_installer="/var/cache/miniconda/Miniconda3-latest-Linux-${conda_arch}.sh" && \
        if [ ! -f "$miniconda_installer" ]; then \
            wget "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-${conda_arch}.sh" -O "$miniconda_installer"; \
        fi && \
        bash "$miniconda_installer" -b -p "$CONDA_DIR" && \
        "$CONDA_DIR/bin/conda" init; \
    else \
        mkdir -p "$CONDA_DIR"; \
    fi

ENV PATH="$CONDA_DIR/bin:$PATH"

RUN mkdir -p /root/.ssh /opt/terminal && \
    chmod 700 /root/.ssh

WORKDIR /opt

COPY --chmod=755 deploy/images/dockerfiles/terminal/entrypoint.sh /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
