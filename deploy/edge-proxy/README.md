# Static IPv4 edge for Gabia DNS

This optional package runs on a separate Linux VM (or the client's existing edge server) with a reserved public IPv4. It does not provision that machine. Running it as another Railway service does NOT create a static inbound IP. Railway remains the application host; do not run the root development Compose stack on this VM. No Cloudflare DNS, proxy, nameserver transfer or email-provider change is required.

Traffic: Gabia A record → reserved IPv4 VM → Nginx HTTPS → Railway web → existing backend/dashboard routes.

## Before cutover

Obtain a VM, reserved IPv4, SSH access and an operations owner. Install Docker Engine and Compose v2 using your VM provider's supported instructions. Allow inbound TCP 80/443, restrict SSH to administrators, and allow outbound DNS/HTTPS. Keep the previous DNS values for rollback. This single VM adds a failure point: monitor availability, disk, certificate expiry and updates. Use the client's redundant load balancer if they require high availability.

Verify the web service's **generated public domain** in Railway. The default here is `itrix-web-production.up.railway.app`. `plycm7lu.up.railway.app` was supplied as a custom-domain DNS target; do not assume a DNS target is a usable HTTP application origin. Set `RAILWAY_WEB_HOST` to that target only if HTTPS to it independently serves the correct application. Use a bare hostname, no scheme, port or slash. No Railway custom-domain certificate is needed by this architecture: the VM holds the public certificate and verifies the generated Railway origin certificate.

On the VM, obtain this repository after the owner merges, then:

```sh
cd itrix-backend/deploy/edge-proxy
printf '%s\n' 'RAILWAY_WEB_HOST=itrix-web-production.up.railway.app' > .env
curl --fail --show-error --head https://itrix-web-production.up.railway.app/
mkdir -p acme letsencrypt
docker compose config --quiet
docker compose build --pull nginx-proxy
```

At Gabia, set A `@` and A `www` to the VM's reserved IPv4. Remove only conflicting web-host A/CNAME/AAAA entries; an old AAAA can send IPv6 users to the wrong server. Preserve MX, mail hostnames, existing SPF/DKIM/DMARC and all unrelated records. Check any existing CAA permits your selected certificate authority. Lower TTL ahead of the agreed cutover. Do not promise zero downtime: the initial HTTP certificate bootstrap briefly serves a setup response. For uninterrupted replacement of an existing website, IT should provision the TLS certificate in advance via its approved DNS-01 or existing certificate process and skip bootstrap.

## First certificate (HTTP-01, after A records resolve to this VM)

Replace the email below with the certificate operations mailbox. Running Certbot with `--agree-tos` accepts Let's Encrypt's terms.

```sh
docker compose -f bootstrap.compose.yml up -d
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  --cert-name itrix.co.kr -d itrix.co.kr -d www.itrix.co.kr \
  --email YOUR_CERTIFICATE_OPERATIONS_EMAIL --agree-tos --non-interactive
docker compose run --rm nginx-proxy nginx -t
# Only after both preceding commands succeed:
docker compose -f bootstrap.compose.yml down
docker compose up -d nginx-proxy
docker compose ps
curl --fail --show-error --head https://itrix.co.kr/
curl --show-error --head https://www.itrix.co.kr/itx-console-7k2m
curl --fail --show-error --head https://itrix.co.kr/itx-console-7k2m
```

The www hostname redirects to the canonical apex and keeps path/query. `/itx-console-7k2m`, `/itx-console-assets`, `/ask-x` and all other paths reach the web service unchanged. TLS terminates at Nginx and is re-established with verified SNI upstream; this is not raw TLS passthrough. The upstream Host must be the Railway origin so Railway routes to the correct service. No response cache is enabled; streaming is unbuffered. The 25 MiB edge body ceiling is an upper limit, not a relaxation of application upload limits.

## Renewal and maintenance

Test renewal:

```sh
docker compose run --rm certbot renew --dry-run --webroot -w /var/www/certbot
sh ./renew.sh
```

Install a root cron entry twice daily using the **absolute** installation directory (replace `/opt/itrix-backend` if different):

```cron
17 3,15 * * * /bin/sh /opt/itrix-backend/deploy/edge-proxy/renew.sh >> /var/log/itrix-edge-renew.log 2>&1
```

Monitor failures and rotate this host log. Renewal reloads Nginx only after successful Certbot execution and syntax validation. Protect and back up `letsencrypt` with restricted access. Keys and `.env` are ignored by Git and excluded from the Docker build context. Update images on an approved schedule (`docker compose pull certbot`, rebuild with `--pull`, test and recreate Nginx). Pin tested image digests in the client's release process if required.

## Application configuration and verification

On web set both `WEBSITE_PUBLIC_URL` and `NEXT_PUBLIC_SITE_URL` to `https://itrix.co.kr`. Dashboard and backend/worker use the same `WEBSITE_PUBLIC_URL`. Backend `FRONTEND_WEB_URL`, CORS/CSRF/WebSocket origins and allowed captcha hostnames must include the public domain. Keep API/WS URLs targeting the actual backend Railway host. Do not point API_URL to the website.

Verify form submission, allowed-mailbox OTP/login, admin assets, Ask X streaming, client account actions and attachments through the public domain. Confirm how Railway overwrites/preserves `X-Real-IP`: this edge strips spoofed client forwarding headers, but cannot guarantee Railway retains the original IP. Do not disable rate limits or trust arbitrary forwarded chains to fix this. Public Railway URLs remain reachable; this package does not make the dashboard private or prevent origin bypass. Existing authentication remains required.

## Email and DNS corrections

Keep the existing approved SMTP transport and sender for the first release. The web domain does not require a new mail provider, MX edits or SPF/DKIM changes. If the client authorizes sending through its existing provider as `no-reply@itrix.co.kr`, its mail administrator must confirm the permitted submission method and From address. Existing provider authentication may already cover it; do not add duplicate SPF records or casually replace an existing policy. The current app implements username/password SMTP, not Microsoft OAuth token acquisition/refresh. A Microsoft tenant requiring OAuth needs an approved compatible relay or an OAuth mail integration before switching. Do not disable tenant security defaults to accommodate the application.

The earlier guide's claim that Gabia necessarily supports apex CNAME flattening was not established. Static IPv4 is not inherently unsafe. Railway region, dashboard private networking and a zero-disruption guarantee also cannot be inferred from this Docker configuration.

Existing form protection uses Turnstile, which is independent of Cloudflare DNS. This proxy does not require it, but the current intake implementation does. If no Cloudflare service is permitted at all, keep intake disabled until an approved alternative captcha is implemented; do not bypass verification.

References: [Railway domain requirements](https://docs.railway.com/integrations/api/manage-domains), [Nginx HTTPS proxy directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html), [Certbot](https://eff-certbot.readthedocs.io/en/stable/using.html), [Turnstile independence](https://developers.cloudflare.com/turnstile/get-started/).
