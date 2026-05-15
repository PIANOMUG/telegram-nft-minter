#!/bin/bash
set -e

echo "=== Deploying Discord AI Bot ==="
apt update && apt install -y python3 python3-pip git

cd /root
if [ -d discord-ai-bot ]; then
    cd discord-ai-bot && git pull
else
    git clone https://github.com/PIANOMUG/telegram-nft-minter.git
    cp -r telegram-nft-minter/discord-ai-bot .
fi

pip3 install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Edit /root/discord-ai-bot/.env and run: systemctl start discord-ai-bot"
    exit 1
fi

cp discord-ai-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable discord-ai-bot
systemctl restart discord-ai-bot

echo "Done! Status: systemctl status discord-ai-bot"
