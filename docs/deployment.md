# Deployment — Numis-Geek on a VPS

Target stack: **single VPS** (e.g., Hetzner CX22, DigitalOcean droplet, etc) with **Ubuntu 22.04+**, **nginx reverse-proxying uvicorn**, **systemd** for uptime, **SQLite for now → PostgreSQL later**. Attachments on disk. Backups daily via the existing `Makefile backup` target + `restic` snapshots to off-site object storage.

Optimized for **single-user / personal use**. Multi-user/heavy-traffic concerns (gunicorn workers, etc.) are deferred — see "Known blockers" below.

---

## 0. Pre-flight — blockers to clear BEFORE going live

These items are tracked but not implemented yet. **Don't go to prod without addressing them.**

| Blocker | Severity | Where it surfaces | Fix path |
|---|---|---|---|
| **IntegrationCredential.secret_value stored in plaintext** | 🔴 high | Anthropic key, brapi/finnhub tokens, Notion token. Anyone with file access to the DB reads them. | Future spec ([[pending_security_spec]]): Fernet symmetric encryption with key in `.env`. Migration re-encrypts existing rows. |
| **APScheduler fires once per worker** | 🟡 medium | If you ever switch from uvicorn-single-process to gunicorn-N-workers, the price refresh + ptax sync + snapshot job fire N times. Single-process uvicorn is safe. | Spec 24 docstring lists 3 options: gunicorn preload + worker 0 guard, systemd timer + endpoint, or APScheduler with DB jobstore. |
| **`docs/`, backups and `data/attachments/` not in repo** | 🟢 low | Gitignored on purpose. On the VPS, mount/bind them under `/var/numis/` and configure backups separately. | This guide §5. |
| **No PDF→image pipeline yet** | 🟢 low | Spec 38 V1 only handles PNG/JPG; PDF extracts ship raw bytes to Anthropic which usually fails. | When relevant, install `pypdfium2` and pre-render to image in `_read_attachment_payload`. |

---

## 1. Provision the VPS

Minimum spec for personal use: **2 vCPU / 2 GB RAM / 40 GB SSD**. Heavier RAM only matters if you push lots of huge images through Anthropic (Pillow can spike).

```bash
# Create non-root user
adduser numis
usermod -aG sudo numis
ssh-copy-id numis@VPS_IP
ssh numis@VPS_IP

sudo apt update && sudo apt -y upgrade
sudo apt -y install python3.12 python3.12-venv build-essential nginx \
                    sqlite3 git curl ufw fail2ban
# Node 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt -y install nodejs

# Firewall
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

---

## 2. Layout

```
/var/numis/
├── repo/                          # git clone of numis-geek
├── data/
│   ├── numis_geek.db              # SQLite (until migrated to Postgres)
│   ├── attachments/{ws}/{uuid}.{ext}
│   └── backups/
└── .env                           # secrets, env vars
```

Symlinks back into the repo so the running code reads the right paths:

```bash
sudo mkdir -p /var/numis/{data/attachments,data/backups}
sudo chown -R numis:numis /var/numis
cd /var/numis && git clone https://github.com/daniambrosio/numis-geek.git repo
cd repo
ln -s /var/numis/data/numis_geek.db numis_geek.db
ln -s /var/numis/data/attachments data/attachments  # ensure parent exists
ln -s /var/numis/.env .env
```

> The Attachment service writes to `./data/attachments/` relative to cwd (see `services/attachment_storage.py:16`). Keep cwd as the repo root in the systemd unit so the relative path resolves correctly.

---

## 3. Install + migrate

```bash
cd /var/numis/repo
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,llm]"   # llm extra pulls anthropic + Pillow
npm --prefix frontend ci
npm --prefix frontend run build         # → frontend/dist/

.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed.py        # only first time; idempotent-ish
```

`.env` template:

```dotenv
DATABASE_URL=sqlite:////var/numis/data/numis_geek.db
SECRET_KEY=<generate with `openssl rand -hex 32`>
SYSADMIN_PASSWORD=<long random>
# DISABLE_SCHEDULER=true  # uncomment to skip price refresh cron on restart
```

---

## 4. systemd unit for the backend

`/etc/systemd/system/numis-backend.service`:

```ini
[Unit]
Description=Numis-Geek FastAPI backend
After=network.target

[Service]
Type=simple
User=numis
Group=numis
WorkingDirectory=/var/numis/repo
EnvironmentFile=/var/numis/.env
ExecStart=/var/numis/repo/.venv/bin/uvicorn numis_geek.api.app:app \
          --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now numis-backend
sudo systemctl status numis-backend       # check it stayed up
journalctl -u numis-backend -f            # tail logs
```

Note: **no `--reload`**. Production wants a stable process. Restart manually after each deploy.

---

## 5. nginx — TLS + SPA + API proxy

Get a cert: `sudo apt -y install certbot python3-certbot-nginx && sudo certbot --nginx -d numis.example.com`.

`/etc/nginx/sites-available/numis`:

```nginx
server {
  listen 443 ssl http2;
  server_name numis.example.com;
  ssl_certificate     /etc/letsencrypt/live/numis.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/numis.example.com/privkey.pem;

  client_max_body_size 25M;        # attachments can be a few MB

  # Frontend SPA
  root /var/numis/repo/frontend/dist;
  index index.html;
  location / {
    try_files $uri /index.html;
  }

  # Backend API
  location /api/ {
    rewrite ^/api/(.*) /$1 break;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 90s;        # LLM extract can take ~30s
  }
}

server {
  listen 80;
  server_name numis.example.com;
  return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/numis /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

> **Frontend API base URL**: the dev config proxies `/api/*`. For prod, the frontend either calls `/api/*` (same origin) or you set `VITE_API_BASE_URL=https://numis.example.com/api` at build time. Confirm `frontend/src/lib/api.ts` uses the right BASE constant.

---

## 6. Backups

Two layers — **don't skip either**.

### 6.1 Local rotation (already in repo)

Spec 39 ships a daily SQLite snapshot job (`run_daily_backup` in `scheduler.py`) that writes to `data/backups/` and rotates (latest 7 days + last-of-month for 12 months). Confirm by `ls /var/numis/data/backups/` after 24h.

For ad-hoc text dumps:

```bash
cd /var/numis/repo && make backup       # writes data/backups/numis_geek-YYYYMMDD-HHMMSS.sql.gz
```

### 6.2 Off-site (restic → object storage)

Recommended target: **Backblaze B2** (~$0.005/GB/month) or any S3-compatible.

```bash
sudo apt -y install restic
restic -r b2:bucket-name:numis init       # one-time
```

Daily cron at /etc/cron.d/numis-restic:

```cron
0 4 * * * numis BASH_ENV=/var/numis/.env restic -r b2:bucket-name:numis backup /var/numis/data --tag daily && \
          restic -r b2:bucket-name:numis forget --tag daily --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune
```

`/var/numis/.env` carries `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`, `RESTIC_PASSWORD`.

---

## 7. Anthropic + integration keys

The bulk extract feature (Spec 48) needs an **active Anthropic credential** in the DB.

1. Login at `https://numis.example.com` as sysadmin.
2. Navigate `/sysadmin/integrations`.
3. Add credential: **Anthropic Claude (LLM extraction)** + paste `sk-ant-…`.
4. Click "Test" — should return `OK` (pings POST /v1/messages with max_tokens=1, cost ~$0.0001).

Same path for brapi / finnhub / Notion tokens.

⚠️ **`secret_value` is stored unencrypted** in the SQLite DB until the security spec lands. Restrict access to `/var/numis/data/numis_geek.db` (only the `numis` user reads it). Anyone with SSH + permission to read that file gets all API keys.

---

## 8. Deploy a new version (zero-downtime-ish)

```bash
ssh numis@VPS
cd /var/numis/repo
git pull
.venv/bin/alembic upgrade head           # if there are new migrations
.venv/bin/pip install -e ".[dev,llm]"    # if deps changed
npm --prefix frontend ci
npm --prefix frontend run build
sudo systemctl restart numis-backend     # ~2s downtime
```

For production-grade zero downtime, you'd front the backend with two systemd units and swap them, or move to gunicorn + multi-worker (with the scheduler fix mentioned above).

---

## 9. Migrating SQLite → Postgres

The models are SQLAlchemy-portable. Steps when load justifies the switch:

1. Provision Postgres (managed: DigitalOcean / Neon / Supabase free tier).
2. `pip install psycopg[binary]`.
3. Dump SQLite: `sqlite3 numis_geek.db .dump > dump.sql` (you'll need to tweak the AUTOINCREMENT lines and a few type casts — pgloader handles most of it).
4. Easier path: `pgloader sqlite:///numis_geek.db postgresql://user:pass@host/numis`.
5. Update `.env` with `DATABASE_URL=postgresql+psycopg://...`.
6. Run `alembic upgrade head` — should be no-op if SQLite was caught up.
7. Restart systemd unit.

Things to revisit after the move:
- `SnapshotPendency` enum behavior (Postgres enforces enums strictly; SQLite stored as VARCHAR — should still parse).
- Concurrent migrations (Postgres handles concurrent transactions cleanly; SQLite limitation was single-writer).
- `op.batch_alter_table` calls in migrations were SQLite workarounds; Postgres doesn't need them but they don't hurt.

---

## 10. Monitoring

Minimum: `journalctl -u numis-backend -f` + log into the VPS once a day. Nice-to-haves:

- **Uptime**: free tier at uptimerobot.com pings `https://numis.example.com/api/health` every 5 min.
- **Logs**: tail to a file via systemd `StandardOutput=append:/var/log/numis-backend.log` + logrotate.
- **Cost watch**: Anthropic dashboard, B2 dashboard.

---

## 11. Recovery

| Scenario | Recovery |
|---|---|
| Corrupted DB | Restore latest `data/backups/numis_geek-*.db` over the live file, then restart. |
| Lost VPS | New VPS → install steps → restic restore `/var/numis/data` from B2 → `alembic upgrade head` → restart. |
| Anthropic key compromised | Revoke at console.anthropic.com → `/sysadmin/integrations` → soft-delete the row → create new. |
| Bad migration | `alembic downgrade -1`. If destructive, restore from backup. |
