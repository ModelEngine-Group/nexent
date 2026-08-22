#!/bin/bash
set -e

# Get user name and password
DEV_USER=${DEV_USER:-linuxserver.io}
DEV_PASSWORD=${DEV_PASSWORD:-nexent123}

# Set correct home directory based on user
if [ "$DEV_USER" = "root" ]; then
    USER_HOME="/root"
else
    USER_HOME="/home/$DEV_USER"
fi

# Create user if it doesn't exist (except for root)
if [ "$DEV_USER" != "root" ] && ! id "$DEV_USER" &>/dev/null; then
    echo "Creating user: $DEV_USER"
    useradd -m -s /bin/bash -G sudo "$DEV_USER" 2>/dev/null || useradd -m -s /bin/bash "$DEV_USER"
    echo "✅ User $DEV_USER created"
    
    # Ensure user has proper permissions
    chown -R "$DEV_USER:$DEV_USER" "$USER_HOME" 2>/dev/null || true
fi

# Set user password for SSH authentication
if echo "$DEV_USER:$DEV_PASSWORD" | chpasswd; then
    echo "✅ User password set for SSH authentication"
else
    echo "❌ Failed to set password for user $DEV_USER"
    echo "   This might be due to password policy restrictions"
    echo "   Trying alternative method..."
    
    # Try using passwd command as fallback
    echo -e "$DEV_PASSWORD\n$DEV_PASSWORD" | passwd "$DEV_USER" 2>/dev/null || {
        echo "❌ Alternative password setting also failed"
        echo "   Please check password complexity requirements"
        exit 1
    }
    echo "✅ Password set using alternative method"
fi

# Allow login (unlock)
passwd -u "$DEV_USER" 2>/dev/null || true

# Ensure shell is available
usermod -s /bin/bash "$DEV_USER" 2>/dev/null || true

# Configure conda auto-activation for development user
echo "Configuring conda auto-activation for user $DEV_USER..."
echo 'export PATH="/opt/conda/bin:$PATH"' >> "$USER_HOME/.bashrc"
echo 'source /opt/conda/etc/profile.d/conda.sh' >> "$USER_HOME/.bashrc"
echo 'conda activate base' >> "$USER_HOME/.bashrc"
chown $DEV_USER:$DEV_USER "$USER_HOME/.bashrc"

# Configure SSH timeout settings
echo "Configuring SSH timeout settings (60 minutes)..."
cat >> /etc/ssh/sshd_config << 'SSHD_EOF'

# Nexent Terminal Tool - Session timeout configuration (60 minutes = 3600 seconds)
ClientAliveInterval 300
ClientAliveCountMax 12
SSHD_EOF

echo "SSH timeout configuration applied successfully"

# Fix terminal directory permissions if mounted from host
echo "Fixing terminal directory permissions..."
if [ -d "/opt/terminal" ]; then
    chown -R $DEV_USER:$DEV_USER /opt/terminal 2>/dev/null || true
    chmod 755 /opt/terminal 2>/dev/null || true
    echo "✅ Terminal directory permissions fixed"
else
    echo "⚠️ Terminal directory not found"
fi

# Start SSH service
if [ $# -gt 0 ]; then
    exec "$@"
else
    exec /usr/sbin/sshd -D
fi
