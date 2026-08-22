#!/usr/bin/with-contenv bash

# Set error handling
set -e

# Install required packages
echo "Installing required packages..."
apk update
apk add --no-cache \
  python3 \
  py3-pip \
  py3-virtualenv \
  curl \
  vim \
  git \
  wget

echo "Package installation completed successfully!"

# Configure SSH timeout settings for nexent terminal tool
echo "Configuring SSH timeout settings (60 minutes)..."

# Fix SSH host key permissions (must be 600 for private keys)
echo "Fixing SSH host key permissions..."
find /config -name "*_key" -type f -exec chmod 600 {} \; 2>/dev/null || true
find /config/ssh_host_keys -name "*_key" -type f -exec chmod 600 {} \; 2>/dev/null || true
echo "SSH host key permissions fixed"

# Append timeout configuration to sshd_config
cat >> /config/sshd/sshd_config << 'SSHD_EOF'

# Nexent Terminal Tool - Session timeout configuration (60 minutes = 3600 seconds)
ClientAliveInterval 300
ClientAliveCountMax 12
SSHD_EOF

echo "SSH timeout configuration applied successfully"
