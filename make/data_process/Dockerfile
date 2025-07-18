FROM python:3.10-slim
LABEL authors="nexent"

# Set correct permissions as root
USER root

RUN echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

RUN apt-get update && \
    apt-get install -y --no-install-recommends --fix-missing \
        libmagic1 \
        libmagic-dev \
        libreoffice \
        libgl1 \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY backend /opt/backend
COPY sdk /opt/sdk
COPY model-assets/clip-vit-base-patch32 /opt/models/clip-vit-base-patch32

WORKDIR /opt/backend

RUN pip install --no-cache-dir uv
RUN uv sync --extra data-process && \
    rm -rf /home/notebook-user/.cache/uv /home/notebook-user/.cache/pip && \
    find .venv -type d -name '__pycache__' -exec rm -rf {} + && \
    find .venv -type f -name '*.pyc' -delete

ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /opt

# Expose the service port
EXPOSE 5012
