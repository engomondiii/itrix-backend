#!/bin/sh
set -eu
cd "$(dirname "$0")"
docker compose run --rm certbot renew --webroot --webroot-path /var/www/certbot --quiet
docker compose exec -T nginx-proxy nginx -t
docker compose exec -T nginx-proxy nginx -s reload
