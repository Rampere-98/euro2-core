#!/usr/bin/env bash
# One-shot installer for a fresh Ubuntu VM (Oracle Cloud Always Free or any other):
#   curl -fsSL https://raw.githubusercontent.com/Rampere-98/euro2-core/main/deploy/install.sh | bash
# Installs Docker, downloads the production stack and starts it. Everything else is done
# from the app (Ajustes → Administración) after the first registration.
set -euo pipefail

DOMAIN="${DOMAIN:-}"
DIR="${EURO2_DIR:-$HOME/euro2}"

if ! command -v docker >/dev/null 2>&1; then
  echo "▶ Installing Docker"
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
fi

echo "▶ Preparing $DIR"
mkdir -p "$DIR/deploy/updater"
cd "$DIR"
BASE="https://raw.githubusercontent.com/Rampere-98/euro2-core/main"
curl -fsSL "$BASE/docker-compose.prod.yml" -o docker-compose.prod.yml
curl -fsSL "$BASE/deploy/Caddyfile" -o deploy/Caddyfile
curl -fsSL "$BASE/deploy/updater/Dockerfile" -o deploy/updater/Dockerfile
curl -fsSL "$BASE/deploy/updater/updater.py" -o deploy/updater/updater.py

if [ ! -f .env ]; then
  if [ -z "$DOMAIN" ]; then
    read -r -p "Dominio público (p. ej. euro2.duckdns.org) [localhost]: " DOMAIN
    DOMAIN="${DOMAIN:-localhost}"
  fi
  read -r -p "Subdominio DuckDNS (vacío si no usas DuckDNS): " DUCK_SUB || true
  read -r -p "Token DuckDNS (vacío si no usas DuckDNS): " DUCK_TOKEN || true
  cat > .env <<ENV
DOMAIN=$DOMAIN
POSTGRES_PASSWORD=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' )
DUCKDNS_SUBDOMAIN=${DUCK_SUB:-}
DUCKDNS_TOKEN=${DUCK_TOKEN:-}
ENV
fi

# open the web ports on the VM firewall (Oracle images ship with iptables rules)
if command -v ufw >/dev/null 2>&1; then sudo ufw allow 80/tcp >/dev/null; sudo ufw allow 443/tcp >/dev/null; fi
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true

PROFILES=""
grep -q '^DUCKDNS_TOKEN=.\+' .env && PROFILES="--profile duckdns"
echo "▶ Starting the stack"
sudo docker compose -f docker-compose.prod.yml $PROFILES up -d
echo
echo "✔ Euro2 is starting. In a couple of minutes open https://$(grep ^DOMAIN= .env | cut -d= -f2)/app/"
echo "  Register the first account: it becomes the administrator. Then Ajustes → Administración."
