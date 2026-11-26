#!/usr/bin/env bash
set -Eeuo pipefail
# This is a separate, explicit host operation. deploy.sh never invokes it.
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
apply=0 obtain=0 email=''
while (( $# )); do
    case "$1" in
        --apply) apply=1 ;;
        --obtain-certificate) obtain=1 ;;
        --email) shift; email=${1:?Supply an ACME contact email} ;;
        *) die 'Usage: bash scripts/nginx.sh [--apply] [--obtain-certificate --email you@example.com]' ;;
    esac
    shift
done
load_env
lock
limit=${UPLOAD_LIMIT:-10m}
[[ $limit =~ ^[1-9][0-9]*[mk]$ ]] || die 'UPLOAD_LIMIT must be like 10m or 512k.'
site="/etc/nginx/sites-available/edunexa-$SITE_DOMAIN.conf"
enabled="/etc/nginx/sites-enabled/edunexa-$SITE_DOMAIN.conf"
cert="/etc/letsencrypt/live/$SITE_DOMAIN"
webroot="/var/www/edunexa-acme-$SITE_DOMAIN"
candidate="$STATE/nginx.conf"
render() {
    cat > "$candidate" <<EOF
# Managed by EduNexa scripts/nginx.sh for $SITE_DOMAIN
server {
    listen 80;
    server_name $SITE_DOMAIN;
    location ^~ /.well-known/acme-challenge/ { root $webroot; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF
    if [[ $1 == tls ]]; then
        cat >> "$candidate" <<EOF
server {
    listen 443 ssl;
    server_name $SITE_DOMAIN;
    ssl_certificate $cert/fullchain.pem;
    ssl_certificate_key $cert/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size $limit;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_connect_timeout 10s;
        proxy_read_timeout 65s;
        proxy_send_timeout 65s;
    }
}
EOF
    fi
}
render tls
if [[ $apply == 0 ]]; then
    log "Review $candidate. No host configuration changed. Explicit --apply is required."
    exit 0
fi
[[ $EUID == 0 ]] || die 'Host changes need root: sudo bash scripts/nginx.sh --apply [certificate options].'
for tool in nginx certbot openssl curl; do need "$tool"; done
nginx -t
[[ ! -L "$site" ]] || die 'Refusing a symlink in sites-available.'
if [[ -e "$site" ]] && ! grep -Fqx "# Managed by EduNexa scripts/nginx.sh for $SITE_DOMAIN" "$site"; then
    die 'Existing unmanaged EduNexa configuration: retain it or manually migrate after review. It was not overwritten.'
fi
[[ ! -e "$enabled" && ! -L "$enabled" || ( -L "$enabled" && $(readlink "$enabled") == "$site" ) ]] || die 'Enabled-site path belongs to another configuration.'
# Refuse duplicate domains in other enabled files rather than disabling any existing vhost.
for other in /etc/nginx/sites-enabled/*; do
    [[ -f "$other" && "$other" != "$enabled" ]] || continue
    if grep -Fq "$SITE_DOMAIN" "$other"; then die "Domain already appears in $other. Keep that existing vhost or migrate manually."; fi
done
snapshot=$(mktemp -d "$STATE/nginx-backup.XXXXXX")
had_site=0 had_link=0
if [[ -e "$site" ]]; then cp -p "$site" "$snapshot/site"; had_site=1; fi
[[ ! -L "$enabled" ]] || had_link=1
restore_config() {
    if (( had_site )); then cp -p "$snapshot/site" "$site"; else rm -f -- "$site"; fi
    if (( ! had_link )); then rm -f -- "$enabled"; fi
    nginx -t && systemctl reload nginx
}
trap 'code=$?; if (( code != 0 )); then restore_config || true; printf "[FAIL] Nginx operation failed; previous EduNexa configuration restored.\n" >&2; fi' EXIT
install_candidate() {
    install -m 644 "$candidate" "$site"
    [[ -L "$enabled" ]] || ln -s "$site" "$enabled"
    nginx -t
    systemctl reload nginx
}
if ! [[ -f "$cert/fullchain.pem" && -f "$cert/privkey.pem" ]] ||
   ! openssl x509 -in "$cert/fullchain.pem" -noout -checkend 604800 >/dev/null ||
   ! openssl x509 -in "$cert/fullchain.pem" -noout -checkhost "$SITE_DOMAIN" >/dev/null; then
    (( obtain )) || die 'No suitable certificate. Authorize issuance with --obtain-certificate --email ADDRESS, or install a valid certificate manually.'
    [[ $email == *@* ]] || die 'Supply --email for certificate issuance and ACME registration.'
    install -d -m 755 "$webroot"
    render http
    install_candidate
    certbot certonly --webroot -w "$webroot" -d "$SITE_DOMAIN" --cert-name "$SITE_DOMAIN" \
        --non-interactive --agree-tos --email "$email" \
        --deploy-hook 'nginx -t && systemctl reload nginx'
fi
render tls
install_candidate
http_check --resolve "$SITE_DOMAIN:443:127.0.0.1" "https://$SITE_DOMAIN/health/"
http_check "https://$SITE_DOMAIN/health/"
[[ -f "/etc/letsencrypt/renewal/$SITE_DOMAIN.conf" ]] || warn 'Certificate renewal configuration missing; configure renewal before expiry.'
if ! systemctl is-enabled certbot.timer >/dev/null 2>&1 && ! systemctl is-enabled snap.certbot.renew.timer >/dev/null 2>&1; then
    warn 'No recognized Certbot timer enabled. Check your existing cron/timer; no global schedule was modified.'
fi
log "Nginx and HTTPS verified. Snapshot: $snapshot. Run the documented certificate-specific renewal dry run."
