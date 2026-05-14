#!/bin/bash
set -e

echo "=== Deploying Telegram NFT Minter Bot ==="

# Install dependencies
apt update
apt install -y python3 python3-pip git

# Clone repo
cd /root
if [ -d telegram-nft-minter ]; then
    cd telegram-nft-minter
    git pull
else
    git clone https://github.com/PIANOMUG/telegram-nft-minter.git
    cd telegram-nft-minter
fi

# Install Python packages
pip3 install -r requirements.txt

# Create .env from example if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "=== IMPORTANT ==="
    echo "Edit /root/telegram-nft-minter/.env with your settings"
    echo "Then run: systemctl start telegram-nft-minter"
    exit 1
fi

# Install systemd service
cp telegram-nft-minter.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable telegram-nft-minter
systemctl restart telegram-nft-minter

echo ""
echo "=== DONE ==="
echo "Status: systemctl status telegram-nft-minter"
echo "Logs:   journalctl -u telegram-nft-minter -f"
