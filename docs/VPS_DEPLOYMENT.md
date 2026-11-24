# EduNexa VPS Docker Deployment Guide

**Target Environment:** Ubuntu 22.04 LTS (1 vCPU, 4 GB RAM) with Host Nginx & Cloudflare (Full Strict)  
**Host IP:** `103.86.177.229`  
**Internal Port:** `127.0.0.1:8002`  
**Domain Example:** `edunexa.sandeepwebsolutions.in`

---

## 1. Architecture Overview

Host Nginx manages incoming traffic on ports 80 and 443, routing traffic for each subdomain to isolated Docker stacks listening exclusively on local loopback (`127.0.0.1`):

```
[ User Browser / Mobile App ]
             │
             ▼ (HTTPS)
   [ Cloudflare CDN (Full Strict) ]
             │
             ▼ (HTTPS Port 443)
[ Host Nginx on VPS ] (Listens on 80 & 443)
             │
   ┌─────────┼─────────────────────────┐
   ▼         ▼                         ▼
(studio)   (app2)             (edunexa.sandeepwebsolutions.in)
 :8788     :8001                       │
                                       ▼
                              Proxy: 127.0.0.1:8002
                                       │
                                       ▼
                         [ EduNexa Docker Stack ]
                         - web (Gunicorn 2 workers, :8000)
                         - worker (Celery, concurrency 1)
                         - beat (Celery beat)
                         - db (PostgreSQL 17)
                         - redis (Redis 7.4, 128MB max)
```

---

## 2. Step-by-Step Deployment Instructions

### Step 1: Verify Port 8002 Availability

Connect to your VPS via PuTTY / SSH and verify port 8002 is not in use:

```bash
sudo ss -tulpn | grep 8002
```
*(If no output appears, port 8002 is free).*

---

### Step 2: Configure Cloudflare DNS

1. Log into your **Cloudflare Dashboard** -> Select `sandeepwebsolutions.in` -> **DNS** -> **Records**.
2. Click **Add record**:
   - **Type:** `A`
   - **Name:** `edunexa` (creates `edunexa.sandeepwebsolutions.in`)
   - **IPv4 address:** `103.86.177.229`
   - **Proxy status:** Proxied (Orange cloud enabled)
3. Click **Save**.
4. In **SSL/TLS** -> **Overview**, ensure encryption mode is set to **Full (strict)**.

---

### Step 3: Clone Repository & Configure Environment

In your VPS terminal:

```bash
# 1. Navigate to home directory and clone
cd ~
git clone https://github.com/Sandeepjanjirala/edunexa.git
cd edunexa

# 2. Create production .env file
cp .env.production.example .env
chmod 600 .env
```

Generate secure secrets for Django and PostgreSQL:

```bash
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(60))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))"
```

Edit `.env` using nano:

```bash
nano .env
```

Ensure the following variables are configured:
```ini
PORT=8002
SITE_DOMAIN=edunexa.sandeepwebsolutions.in
SITE_URL=https://edunexa.sandeepwebsolutions.in
ALLOWED_HOSTS=edunexa.sandeepwebsolutions.in,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://edunexa.sandeepwebsolutions.in
TRUST_PROXY=1

DJANGO_SECRET_KEY=<your_generated_secret_key>
POSTGRES_PASSWORD=<your_generated_postgres_password>

# Set DEMO_MODE=1 to evaluate with one-click logins and synthetic data
# Set DEMO_MODE=0 for live school usage (requires SMTP EMAIL_HOST)
DEMO_MODE=1

WEB_CONCURRENCY=2
WORKER_CONCURRENCY=1
```

Save and exit (`Ctrl + O`, `Enter`, `Ctrl + X`).

---

### Step 4: Build and Launch Docker Stack

Launch the containers in detached mode:

```bash
# 1. Build and start stack
docker compose -f docker-compose.prod.yml up -d --build

# 2. Run database migrations
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput

# 3. Create initial administrator OR seed demo data
# If DEMO_MODE=1:
docker compose -f docker-compose.prod.yml exec web python manage.py seed_demo

# If DEMO_MODE=0:
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# 4. Verify deployment checks
docker compose -f docker-compose.prod.yml exec web python manage.py check --deploy

# 5. Check container status
docker compose -f docker-compose.prod.yml ps
```

---

### Step 5: Configure Host Nginx Reverse Proxy

Create the virtual host configuration file:

```bash
sudo tee /etc/nginx/sites-available/edunexa.sandeepwebsolutions.in << 'EOF'
server {
    listen 80;
    server_name edunexa.sandeepwebsolutions.in;

    # Maximum file upload size
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket & long-lived connection support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
        proxy_connect_timeout 60s;
    }
}
EOF
```

Link into `sites-enabled` and test Nginx:

```bash
sudo ln -sf /etc/nginx/sites-available/edunexa.sandeepwebsolutions.in /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

### Step 6: Issue SSL Certificate with Certbot

Obtain the Let's Encrypt SSL certificate for Nginx:

```bash
sudo certbot --nginx -d edunexa.sandeepwebsolutions.in
```

Certbot will automatically install the certificate block on port 443 and configure the HTTP-to-HTTPS redirect.

Reload Nginx:

```bash
sudo systemctl reload nginx
```

Your app is now live at: **`https://edunexa.sandeepwebsolutions.in`**

---

## 3. Maintenance & Monitoring Cheatsheet

```bash
# View container resource utilization (RAM / CPU)
docker stats --no-stream

# View real-time web logs
cd ~/edunexa
docker compose -f docker-compose.prod.yml logs -f web

# View Celery worker logs
docker compose -f docker-compose.prod.yml logs -f worker

# Pull latest updates and redeploy
cd ~/edunexa
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput

# Graceful stop
docker compose -f docker-compose.prod.yml down
# (WARNING: NEVER use 'docker compose down -v' as that deletes postgres_data)
```
