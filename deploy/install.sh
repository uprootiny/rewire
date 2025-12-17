#!/bin/bash
set -euo pipefail

# Rewire installation script
# Usage: sudo ./install.sh

INSTALL_DIR=/opt/rewire
SERVICE_FILE=/etc/systemd/system/rewire.service
ENV_FILE=/etc/rewire.env

echo "Installing Rewire to $INSTALL_DIR"

# Create directory
mkdir -p "$INSTALL_DIR"
cp -r python/rewire "$INSTALL_DIR/"
cp python/pyproject.toml "$INSTALL_DIR/"

# Initialize database
cd "$INSTALL_DIR"
python3 -m rewire.server --db rewire.db --init-db --base-url http://localhost:8080 || true

# Create env file if not exists
if [ ! -f "$ENV_FILE" ]; then
    ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    cat > "$ENV_FILE" << EOF
REWIRE_BASE_URL=http://localhost:8080
REWIRE_ADMIN_TOKEN=$ADMIN_TOKEN
EOF
    chmod 600 "$ENV_FILE"
    echo "Created $ENV_FILE with generated admin token"
    echo "Admin token: $ADMIN_TOKEN"
fi

# Install systemd service
cp deploy/rewire.service "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable rewire

echo ""
echo "Installation complete."
echo "Start with: systemctl start rewire"
echo "Check status: systemctl status rewire"
echo "View logs: journalctl -u rewire -f"
