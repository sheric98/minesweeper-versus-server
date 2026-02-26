#!/bin/bash
set -euo pipefail

### --- FILL THESE IN BEFORE LAUNCH --- ###
GIT_REPO="https://github.com/sheric98/minesweeper-web-server.git"
DOMAIN="api.minesweeper-versus.com"
JWT_SECRET="<generate-with: python3 -c 'import secrets;print(secrets.token_hex(32))'>"
CORS_ORIGINS="https://minesweeper-versus.com"
CERTBOT_EMAIL="<your-email>"
### ----------------------------------- ###

apt-get update && apt-get upgrade -y
apt-get install -y docker.io nginx certbot python3-certbot-nginx git

systemctl enable docker && systemctl start docker

# Save secrets
cat > /home/ubuntu/.env.minesweeper <<EOF
JWT_SECRET=$JWT_SECRET
CORS_ORIGINS=$CORS_ORIGINS
EOF
chown ubuntu:ubuntu /home/ubuntu/.env.minesweeper
chmod 600 /home/ubuntu/.env.minesweeper

# Clone and build
cd /home/ubuntu
git clone "$GIT_REPO" minesweeper-web-server
chown -R ubuntu:ubuntu minesweeper-web-server
cd minesweeper-web-server
docker build -t minesweeper-backend .
docker run -d \
  --name minesweeper-backend \
  --restart unless-stopped \
  -p 5000:5000 \
  -e JWT_SECRET="$JWT_SECRET" \
  -e CORS_ORIGINS="$CORS_ORIGINS" \
  minesweeper-backend

# Nginx config
cat > /etc/nginx/sites-available/$DOMAIN <<'NGINX'
server {
    listen 80;
    server_name DOMAIN_PLACEHOLDER;

    location /ws {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" /etc/nginx/sites-available/$DOMAIN
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# SSL (requires DNS A record to already point to this instance)
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$CERTBOT_EMAIL"
