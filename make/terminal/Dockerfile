FROM ubuntu:24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV CONDA_DIR=/opt/conda
ENV PATH=$CONDA_DIR/bin:$PATH

# Install base tools and dependencies
RUN apt-get update && apt-get install -y \
    openssh-server \
    sudo \
    curl \
    wget \
    git \
    vim \
    nano \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Create development user
ARG DEV_USER=linuxserver.io
RUN useradd -m -s /bin/bash $DEV_USER && \
    usermod -aG sudo $DEV_USER && \
    echo "$DEV_USER ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Configure SSH - disable root login + disable password authentication
RUN mkdir /var/run/sshd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config

# Install Miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p $CONDA_DIR && \
    rm /tmp/miniconda.sh

# Set conda permissions
RUN chown -R $DEV_USER:$DEV_USER $CONDA_DIR

# Create .ssh directory
RUN mkdir -p /home/$DEV_USER/.ssh && \
    chown $DEV_USER:$DEV_USER /home/$DEV_USER/.ssh && \
    chmod 700 /home/$DEV_USER/.ssh

# Create default working directory
RUN mkdir -p /opt/terminal && \
    chown $DEV_USER:$DEV_USER /opt/terminal

# Set working directory
WORKDIR /opt

# Entrypoint script
COPY make/terminal/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"] 