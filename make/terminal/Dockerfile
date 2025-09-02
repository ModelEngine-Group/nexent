FROM ubuntu:24.04

# Set environment variables
ENV CONDA_DIR=/opt/conda

# Install base tools and dependencies with retry mechanism and network optimization
RUN apt-get clean && \
    apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
        openssh-server \
        curl \
        wget \
        git \
        vim \
        build-essential \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

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
ARG TARGETARCH
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-$(if [ "$TARGETARCH" = "amd64" ]; then echo "x86_64"; elif [ "$TARGETARCH" = "arm64" ]; then echo "aarch64"; else echo "$TARGETARCH"; fi).sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p $CONDA_DIR && \
    rm /tmp/miniconda.sh

# Set conda permissions
RUN chown -R $DEV_USER:$DEV_USER $CONDA_DIR

# Add conda to PATH and initialize
ENV PATH="$CONDA_DIR/bin:$PATH"
RUN conda init

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
