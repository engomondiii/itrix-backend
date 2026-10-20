#!/bin/sh
# Run as root on the droplet after both A records resolve to its reserved IPv4.
set -eu
cd "$(dirname "$0")"
email=${1:-}
case "$email" in *@*.*) ;; *) echo 'Usage: sh init-tls.sh certificate-operations@example.com' >&2; exit 1;; esac
if [ -f letsencrypt/live/itrix.co.kr/fullchain.pem ]; then
    echo 'Certificate already exists. Use docker compose up -d nginx-proxy and renew.sh.' >&2
    exit 1
fi
host=${RAILWAY_WEB_HOST:-}
if [ -z "$host" ] && [ -f .env ]; then
    host=$(sed -n 's/^RAILWAY_WEB_HOST=//p' .env | tail -n 1)
fi
host=${host:-itrix-web-production.up.railway.app}
case "$host" in *[!a-zA-Z0-9.-]*|'') echo 'RAILWAY_WEB_HOST must be a bare hostname.' >&2; exit 1;; esac
# Fail before changing services if Railway would serve a fallback/error page.
curl --fail --silent --show-error --head --max-time 20 "https://$host/" >/dev/null
umask 077
mkdir -p letsencrypt acme
# Nginx workers need to traverse the public ACME webroot.
chmod 755 acme
docker compose config --quiet
docker compose build --pull nginx-proxy
docker compose -p itrix-edge-bootstrap -f bootstrap.compose.yml up -d
cleanup() { docker compose -p itrix-edge-bootstrap -f bootstrap.compose.yml down; }
trap cleanup EXIT
# Running this script accepts Let's Encrypt's subscriber agreement.
docker compose run --rm certbot certonly --webroot -w /var/www/certbot     --cert-name itrix.co.kr -d itrix.co.kr -d www.itrix.co.kr     --email "$email" --agree-tos --non-interactive
docker compose run --rm nginx-proxy nginx -t
cleanup
trap - EXIT
docker compose up -d nginx-proxy
docker compose ps
