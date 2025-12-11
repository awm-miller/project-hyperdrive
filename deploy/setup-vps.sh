#!/bin/bash
# Hyperdrive VPS Setup Script
# Run this on a fresh Ubuntu VPS (22.04 or later)

set -e

echo "=========================================="
echo "Hyperdrive VPS Setup"
echo "=========================================="

# Update system
echo "[1/6] Updating system..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
fi

# Install Docker Compose
echo "[3/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo apt-get install -y docker-compose
fi

# Install Mullvad (optional - for VPN rotation)
echo "[4/6] Installing Mullvad VPN (optional)..."
if ! command -v mullvad &> /dev/null; then
    # Add Mullvad repo
    sudo curl -fsSLo /usr/share/keyrings/mullvad-keyring.asc https://repository.mullvad.net/deb/mullvad-keyring.asc
    echo "deb [signed-by=/usr/share/keyrings/mullvad-keyring.asc arch=$( dpkg --print-architecture )] https://repository.mullvad.net/deb/stable $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/mullvad.list
    sudo apt-get update
    sudo apt-get install -y mullvad-vpn
    echo "  -> Mullvad installed. Run 'mullvad account login YOUR_ACCOUNT' to set up."
fi

# Create app directory
echo "[5/6] Setting up application directory..."
APP_DIR="/opt/hyperdrive"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Copy your project files to $APP_DIR:"
echo "   scp -r ./* your-vps:$APP_DIR/"
echo ""
echo "2. Create your .env file:"
echo "   nano $APP_DIR/.env"
echo "   Add: GEMINI_API_KEY=your_key_here"
echo ""
echo "3. Add your Twitter session:"
echo "   nano $APP_DIR/sessions.jsonl"
echo ""
echo "4. (Optional) Set up Mullvad VPN:"
echo "   mullvad account login YOUR_ACCOUNT"
echo "   mullvad connect"
echo ""
echo "5. Start the application:"
echo "   cd $APP_DIR/deploy"
echo "   docker-compose -f docker-compose.prod.yml up -d"
echo ""
echo "6. (Optional) Set up Nginx reverse proxy + SSL:"
echo "   See: deploy/nginx-example.conf"
echo ""

