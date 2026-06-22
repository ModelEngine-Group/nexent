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

# Using root user - no additional user creation needed

# Configure SSH - enable root login + enable password authentication
RUN mkdir /var/run/sshd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Install Miniconda
ARG TARGETARCH
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-$(if [ "$TARGETARCH" = "amd64" ]; then echo "x86_64"; elif [ "$TARGETARCH" = "arm64" ]; then echo "aarch64"; else echo "$TARGETARCH"; fi).sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p $CONDA_DIR && \
    rm /tmp/miniconda.sh

# Conda permissions - root owns everything by default

# Add conda to PATH and initialize
ENV PATH="$CONDA_DIR/bin:$PATH"
RUN conda init

# Create .ssh directory for root
RUN mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh

# Create default working directory
RUN mkdir -p /opt/terminal

# Set working directory
WORKDIR /opt

# Entrypoint script
COPY deploy/images/dockerfiles/terminal/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
