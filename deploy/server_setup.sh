#!/usr/bin/env bash
# =============================================================================
# One-time setup of a fresh Ubuntu 24.04 server for ResearchFlow.
#
#   sudo bash server_setup.sh <domain> "<deploy public key>"
#
#   <domain>             e.g. myteam.duckdns.org (its DNS must point at this server)
#   <deploy public key>  the one-line contents of researchflow_deploy.pub
#
# Safe to run again: it keeps existing settings, secrets and data.
# After this, every push to main on GitHub deploys automatically.
# =============================================================================
set -euo pipefail

DOMAIN=${1:-}
PUBKEY=${2:-}
if [ -z "$DOMAIN" ] || [ -z "$PUBKEY" ]; then
  echo "Usage: sudo bash server_setup.sh <domain> \"<deploy public key>\"" >&2
  exit 1
fi
case "$PUBKEY" in
  ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*) ;;
  *) echo "The second argument must be a public key line starting with ssh-ed25519." >&2; exit 1 ;;
esac
if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo." >&2
  exit 1
fi

echo "== Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip rsync curl sqlite3 cron
if ! apt-get install -y -q caddy; then
  # Caddy's official repository, for Ubuntu releases that do not ship it.
  apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https gnupg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi

echo "== Firewall (ports 80 and 443)"
if command -v netfilter-persistent >/dev/null 2>&1; then
  # Oracle Cloud images ship iptables rules that reject everything except SSH.
  for port in 443 80; do
    if ! iptables -C INPUT -p tcp -m state --state NEW --dport "$port" -j ACCEPT 2>/dev/null; then
      reject=$(iptables -L INPUT --line-numbers -n | awk '$2 == "REJECT" { print $1; exit }')
      if [ -n "$reject" ]; then
        iptables -I INPUT "$reject" -p tcp -m state --state NEW --dport "$port" -j ACCEPT
      else
        iptables -A INPUT -p tcp -m state --state NEW --dport "$port" -j ACCEPT
      fi
    fi
  done
  netfilter-persistent save
elif command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH
  ufw allow 80,443/tcp
  ufw --force enable
fi

echo "== Accounts and folders"
# "researchflow" runs the API and owns the data; "deploy" receives releases from GitHub.
id researchflow >/dev/null 2>&1 || useradd --system --home-dir /var/lib/researchflow --shell /usr/sbin/nologin researchflow
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
grep -qxF "$PUBKEY" /home/deploy/.ssh/authorized_keys || printf '%s\n' "$PUBKEY" >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

install -d -o deploy -g deploy -m 755 /opt/researchflow
install -d -o researchflow -g researchflow -m 750 /var/lib/researchflow /var/lib/researchflow/uploads
install -d -o root -g researchflow -m 750 /etc/researchflow

# The deploy account may restart the API and nothing else as root.
cat > /etc/sudoers.d/researchflow-deploy <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart researchflow
EOF
chmod 440 /etc/sudoers.d/researchflow-deploy
visudo -cf /etc/sudoers.d/researchflow-deploy >/dev/null

echo "== Settings and secrets"
ENV_FILE=/etc/researchflow/backend.env
if [ ! -f "$ENV_FILE" ]; then
  secret() { python3 -c "import secrets; print(secrets.token_urlsafe(48))"; }
  cat > "$ENV_FILE" <<EOF
# ResearchFlow production settings (created by server_setup.sh). Keep private.
APP_ENV=production
DEBUG=false
FRONTEND_ORIGIN=https://$DOMAIN
BACKEND_ORIGIN=https://$DOMAIN
SESSION_COOKIE_SECURE=true

DATABASE_PATH=/var/lib/researchflow/researchflow.sqlite3
PRIVATE_STORAGE_DIR=/var/lib/researchflow/uploads
MAX_UPLOAD_SIZE_BYTES=104857600
PROJECT_STORAGE_QUOTA_BYTES=2147483648

SESSION_SECRET_KEY=$(secret)
CSRF_SECRET_KEY=$(secret)
TOKEN_HASH_PEPPER=$(secret)

# Email. "console" sends nothing: people can still register and sign in, and
# passwords are reset with scripts/admin.py. For real email set EMAIL_BACKEND=smtp
# and fill in the lines below (port 587 uses STARTTLS, 465 uses SSL).
EMAIL_BACKEND=console
# SMTP_HOST=smtp.your-provider.com
# SMTP_PORT=587
# SMTP_USERNAME=
# SMTP_PASSWORD=
# SMTP_USE_TLS=true
# EMAIL_FROM_ADDRESS=noreply@$DOMAIN

# Optional: only let addresses at these domains sign up, e.g. ALLOWED_EMAIL_DOMAINS=uni.edu,lab.org
# ALLOWED_EMAIL_DOMAINS=

DOI_LOOKUP_ENABLED=false
EOF
fi
chown root:researchflow "$ENV_FILE"
chmod 640 "$ENV_FILE"

echo "== API service"
cat > /etc/systemd/system/researchflow.service <<'EOF'
[Unit]
Description=ResearchFlow API
After=network.target

[Service]
User=researchflow
Group=researchflow
WorkingDirectory=/opt/researchflow/backend
# One worker on purpose: SQLite and the in-memory rate limiter assume one process.
ExecStart=/opt/researchflow/venv/bin/uvicorn app.main:app --env-file /etc/researchflow/backend.env --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ReadWritePaths=/var/lib/researchflow
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable researchflow >/dev/null

echo "== HTTPS (Caddy)"
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
	encode zstd gzip

	# Big files upload in chunks; this only has to exceed MAX_UPLOAD_SIZE_BYTES.
	request_body {
		max_size 110MB
	}

	handle /api/* {
		reverse_proxy 127.0.0.1:8000
	}

	handle {
		root * /opt/researchflow/web
		try_files {path} /index.html
		file_server

		header {
			Strict-Transport-Security "max-age=63072000; includeSubDomains"
			X-Content-Type-Options "nosniff"
			X-Frame-Options "DENY"
			Referrer-Policy "strict-origin-when-cross-origin"
			Permissions-Policy "geolocation=(), microphone=(), camera=()"
			Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; frame-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
			-Server
		}
		@html path / /index.html
		header @html Cache-Control "no-cache"
		header /assets/* Cache-Control "public, max-age=31536000, immutable"
	}
}
EOF
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl enable caddy >/dev/null
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "== Nightly backup"
cat > /usr/local/bin/researchflow-backup <<'EOF'
#!/usr/bin/env bash
# Consistent copy of the database (safe while the app runs) plus uploaded files; keeps 14 days.
set -euo pipefail
DATA=/var/lib/researchflow
DEST=/var/backups/researchflow
STAMP=$(date +%Y%m%d-%H%M%S)
install -d -m 700 "$DEST"
[ -f "$DATA/researchflow.sqlite3" ] || { echo "No database yet."; exit 0; }
sqlite3 "$DATA/researchflow.sqlite3" ".backup '$DEST/db-$STAMP.sqlite3'"
gzip "$DEST/db-$STAMP.sqlite3"
tar -czf "$DEST/uploads-$STAMP.tar.gz" -C "$DATA" uploads
find "$DEST" -type f -name '*.gz' -mtime +14 -delete
echo "Backup written to $DEST ($STAMP)"
EOF
chmod 755 /usr/local/bin/researchflow-backup
echo '30 2 * * * root /usr/local/bin/researchflow-backup >/dev/null' > /etc/cron.d/researchflow-backup

echo
echo "============================================================================"
echo " Server ready. Add these in GitHub > Settings > Secrets and variables > Actions"
echo
echo " Variables tab:  DEPLOY_HOST = $DOMAIN"
echo " Secrets tab:    DEPLOY_SSH_KEY = (contents of researchflow_deploy, the private key)"
echo "                 DEPLOY_KNOWN_HOSTS = the line below"
echo
for f in /etc/ssh/ssh_host_ed25519_key.pub /etc/ssh/ssh_host_ecdsa_key.pub; do
  [ -f "$f" ] && echo "$DOMAIN $(cut -d' ' -f1,2 "$f")"
done
echo
echo " Then run the Deploy workflow (Actions tab) or push to main."
echo "============================================================================"
