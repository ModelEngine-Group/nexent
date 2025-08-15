#!/bin/bash
set -e

# Get user name
DEV_USER=${DEV_USER:-linuxserver.io}
USER_HOME="/home/$DEV_USER"

# Allow login (unlock)
passwd -u "$DEV_USER" 2>/dev/null || true

# Ensure shell is available
usermod -s /bin/bash "$DEV_USER" 2>/dev/null || true

# Ensure user .ssh directory exists
mkdir -p "$USER_HOME/.ssh"
chown $DEV_USER:$DEV_USER "$USER_HOME/.ssh"
chmod 700 "$USER_HOME/.ssh"

# Configure public key authentication (Ed25519)
if [ -f /tmp/ssh_keys/openssh_server_key.pub ]; then
    cp /tmp/ssh_keys/openssh_server_key.pub "$USER_HOME/.ssh/authorized_keys"
    chown $DEV_USER:$DEV_USER "$USER_HOME/.ssh/authorized_keys"
    chmod 600 "$USER_HOME/.ssh/authorized_keys"
    echo "✅ SSH public key successfully configured (Ed25519)"
else
    echo "⚠️ Warning: SSH public key file not found /tmp/ssh_keys/openssh_server_key.pub"
    echo "⚠️ Unable to connect to container via SSH"
fi

# Configure SSH timeout settings
echo "Configuring SSH timeout settings (60 minutes)..."
cat >> /etc/ssh/sshd_config << 'SSHD_EOF'

# Nexent Terminal Tool - Session timeout configuration (60 minutes = 3600 seconds)
ClientAliveInterval 300
ClientAliveCountMax 12
SSHD_EOF

echo "SSH timeout configuration applied successfully"

# Start SSH service
if [ $# -gt 0 ]; then
    exec "$@"
else
    exec /usr/sbin/sshd -D -d
fi
