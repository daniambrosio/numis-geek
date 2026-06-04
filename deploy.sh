#!/usr/bin/env bash
# deploy.sh — smart deploy for numis-geek on vps1-hostinger
#
# Usage:
#   bash /opt/infra/apps/numis-geek/deploy.sh              # normal deploy
#   bash /opt/infra/apps/numis-geek/deploy.sh --force-rebuild  # force image rebuild
#
# What it does:
#   1. git pull from origin/main
#   2. alembic check — detects pending migrations
#   3. sqlite3 .backup before any migration (safe copy while app is running)
#   4. docker compose build only when pyproject.toml / uv.lock / Dockerfile / frontend/ changed
#   5. alembic upgrade head (if needed)
#   6. docker compose up -d + health check
#   7. rollback on failure (restores old image tag + DB backup if migration was involved)
#
# Logs: /opt/infra/apps/numis-geek/data/deploy.log

set -euo pipefail
export TZ=America/Sao_Paulo

APP=/opt/infra/apps/numis-geek
CF="$APP/docker-compose.yml"
LOG="$APP/data/deploy.log"
DB="$APP/data/numis_geek.db"
FORCE_REBUILD=${1:-}
BACKUP=""

mkdir -p "$APP/data"

log()  { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
fail() { log "ERROR: $*"; exit 1; }

exec 9>"$APP/data/.deploy.lock"
flock -n 9 || fail "another deploy already running"

log "=== deploy start ==="

# ── 1. Pull ───────────────────────────────────────────────────────────────────
OLD_HEAD=$(git -C "$APP" rev-parse HEAD)
OLD_SHORT=$(git -C "$APP" rev-parse --short HEAD)

git -C "$APP" fetch origin main 2>&1 | grep -v "^$" | tee -a "$LOG" || true
NEW_HEAD=$(git -C "$APP" rev-parse origin/main)
NEW_SHORT=$(git -C "$APP" rev-parse --short origin/main)

if [ "$OLD_HEAD" = "$NEW_HEAD" ] && [ -z "$FORCE_REBUILD" ]; then
  log "already at $OLD_SHORT — nothing to do"
  exit 0
fi

git -C "$APP" pull origin main 2>&1 | tee -a "$LOG"
log "pulled: $OLD_SHORT → $NEW_SHORT"

# Detect changed files between old and new HEAD
CHANGED=$(git -C "$APP" diff --name-only "$OLD_HEAD" "$NEW_HEAD" 2>/dev/null || true)

# ── 2. Check for pending migrations ───────────────────────────────────────────
MIGRATIONS_PENDING=false
ALEMBIC_OUT=$(docker compose -f "$CF" run --rm -T numis-geek uv run alembic check 2>&1 || true)
if echo "$ALEMBIC_OUT" | grep -qi "outstanding"; then
  MIGRATIONS_PENDING=true
  log "migrations pending"
elif echo "$ALEMBIC_OUT" | grep -qi "up to date"; then
  log "schema up to date"
else
  # Unexpected output — treat as pending to be safe
  MIGRATIONS_PENDING=true
  log "WARN alembic check output unclear, treating as pending: $ALEMBIC_OUT"
fi

# ── 3. Backup DB before any migration ─────────────────────────────────────────
if [ "$MIGRATIONS_PENDING" = "true" ]; then
  TS=$(date '+%Y%m%d-%H%M%S')
  BACKUP="$DB.pre-deploy-$TS"
  sqlite3 "$DB" ".backup '$BACKUP'" \
    && log "DB backup OK: $(basename "$BACKUP")" \
    || fail "DB backup failed — aborting (no changes applied yet)"
fi

# ── 4. Detect if image rebuild needed ─────────────────────────────────────────
REBUILD=false
if [ -n "$FORCE_REBUILD" ]; then
  REBUILD=true
  log "rebuild: forced via --force-rebuild"
elif echo "$CHANGED" | grep -qE "^(pyproject\.toml|uv\.lock|Dockerfile|frontend/)"; then
  REBUILD=true
  TRIGGERS=$(echo "$CHANGED" | grep -E "^(pyproject\.toml|uv\.lock|Dockerfile|frontend/)" | head -5 | tr '\n' ' ')
  log "rebuild: triggered by $TRIGGERS"
else
  log "rebuild: skipped (code-only change)"
fi

# ── 5. Tag current image as rollback before overwriting ───────────────────────
if [ "$REBUILD" = "true" ]; then
  docker tag numis-geek:latest numis-geek:rollback 2>/dev/null \
    && log "tagged numis-geek:rollback" || log "WARN could not tag rollback image"
  log "building image..."
  docker compose -f "$CF" build 2>&1 | tail -5 | tee -a "$LOG"
fi

# ── 6. Run migrations ─────────────────────────────────────────────────────────
if [ "$MIGRATIONS_PENDING" = "true" ]; then
  log "running alembic upgrade head"
  docker compose -f "$CF" run --rm -T numis-geek uv run alembic upgrade head 2>&1 | tee -a "$LOG"
fi

# ── 7. Restart ────────────────────────────────────────────────────────────────
log "restarting container"
docker compose -f "$CF" up -d 2>&1 | tee -a "$LOG"

# ── 8. Health check (6 attempts × 8 s = 48 s total) ──────────────────────────
HEALTHY=false
for i in 1 2 3 4 5 6; do
  sleep 8
  if curl -sf http://localhost:8100/health >/dev/null 2>&1; then
    HEALTHY=true
    break
  fi
  log "health check $i/6 failed, retrying..."
done

if [ "$HEALTHY" = "true" ]; then
  log "health check OK"
  log "=== deploy done | $OLD_SHORT→$NEW_SHORT | migrations=$MIGRATIONS_PENDING | rebuild=$REBUILD ==="
  exit 0
fi

# ── 9. Rollback ───────────────────────────────────────────────────────────────
log "health check FAILED — rolling back to $OLD_SHORT"

# Restore DB if we ran a migration and have a backup
if [ "$MIGRATIONS_PENDING" = "true" ] && [ -n "$BACKUP" ] && [ -f "$BACKUP" ]; then
  docker compose -f "$CF" stop numis-geek 2>/dev/null || true
  cp "$BACKUP" "$DB" && log "DB restored from backup" || log "WARN DB restore failed"
fi

# Restore git working tree
git -C "$APP" checkout "$OLD_HEAD" -- . 2>&1 | tee -a "$LOG"

# Restore image if we rebuilt
if [ "$REBUILD" = "true" ] && docker images numis-geek:rollback -q 2>/dev/null | grep -q .; then
  docker tag numis-geek:rollback numis-geek:latest
  log "image restored from numis-geek:rollback"
fi

docker compose -f "$CF" up -d 2>&1 | tee -a "$LOG"
sleep 10
if curl -sf http://localhost:8100/health >/dev/null 2>&1; then
  log "=== ROLLBACK OK: running $OLD_SHORT ==="
else
  log "=== ROLLBACK ALSO FAILED — manual intervention required ==="
fi
exit 1
