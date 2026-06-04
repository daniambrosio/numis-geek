#!/usr/bin/env bash
# deploy.sh — smart deploy for numis-geek on vps1-hostinger
#
# Usage:
#   bash /opt/infra/apps/numis-geek/deploy.sh              # normal deploy
#   bash /opt/infra/apps/numis-geek/deploy.sh --force-rebuild  # force image rebuild
#
# What it does:
#   1. git pull from origin/main
#   2. Rebuild image when code/deps/migrations/frontend changed (baked into image)
#      Skip rebuild only for pure docs/tests/spec changes
#   3. Compare DB revision against heads in the NEW image to detect pending migrations
#   4. sqlite3 .backup before any migration (safe copy while app is running)
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

# Changed files between old and new HEAD
CHANGED=$(git -C "$APP" diff --name-only "$OLD_HEAD" "$NEW_HEAD" 2>/dev/null || true)

# ── 2. Detect if image rebuild needed ─────────────────────────────────────────
# Rebuild unless ALL changes are pure docs/tests/specs (nothing baked into the image)
INFRA_ONLY=$(echo "$CHANGED" | grep -cvE "^(docs/|tests/|specs/|assets/|.*\.md$|deploy\.sh$|\.gitignore$)" || true)
REBUILD=false
if [ -n "$FORCE_REBUILD" ]; then
  REBUILD=true
  log "rebuild: forced"
elif [ "$INFRA_ONLY" -gt 0 ]; then
  REBUILD=true
  TRIGGERS=$(echo "$CHANGED" | grep -vE "^(docs/|tests/|specs/|assets/|.*\.md$|deploy\.sh$|\.gitignore$)" | head -5 | tr '\n' ' ')
  log "rebuild: triggered by $TRIGGERS"
else
  log "rebuild: skipped (docs/tests only)"
fi

# Tag current image as rollback target before overwriting
if [ "$REBUILD" = "true" ]; then
  docker tag numis-geek:latest numis-geek:rollback 2>/dev/null \
    && log "tagged numis-geek:rollback" || log "WARN could not tag rollback image"
  # Spec 54 — injeta versão pra exibir no UI + detectar mismatch.
  export GIT_SHA="$(git -C "$APP" rev-parse --short HEAD)"
  export BUILD_DATE="$(date +%F)"
  log "building image (GIT_SHA=$GIT_SHA BUILD_DATE=$BUILD_DATE)..."
  docker compose -f "$CF" build \
    --build-arg "GIT_SHA=$GIT_SHA" --build-arg "BUILD_DATE=$BUILD_DATE" \
    2>&1 | tail -5 | tee -a "$LOG"
fi

# ── 3. Check for pending migrations (against the NEW image) ───────────────────
# Compare DB current revision against the heads known to the (now rebuilt) image.
CURRENT_REV=$(docker compose -f "$CF" run --rm -T numis-geek \
  uv run alembic current 2>/dev/null | grep -oE '[a-f0-9]{12}' | head -1 || true)
HEAD_REV=$(docker compose -f "$CF" run --rm -T numis-geek \
  uv run alembic heads 2>/dev/null | grep -oE '[a-f0-9]{12}' | head -1 || true)

log "schema: current=$CURRENT_REV head=$HEAD_REV"

MIGRATIONS_PENDING=false
if [ -n "$HEAD_REV" ] && [ "$CURRENT_REV" != "$HEAD_REV" ]; then
  MIGRATIONS_PENDING=true
  log "migrations pending ($CURRENT_REV → $HEAD_REV)"
fi

# ── 4. Backup DB before any migration ─────────────────────────────────────────
if [ "$MIGRATIONS_PENDING" = "true" ]; then
  TS=$(date '+%Y%m%d-%H%M%S')
  BACKUP="$DB.pre-deploy-$TS"
  sqlite3 "$DB" ".backup '$BACKUP'" \
    && log "DB backup OK: $(basename "$BACKUP")" \
    || fail "DB backup failed — aborting (no changes applied to DB yet)"
fi

# ── 5. Run migrations ─────────────────────────────────────────────────────────
if [ "$MIGRATIONS_PENDING" = "true" ]; then
  log "running alembic upgrade head"
  docker compose -f "$CF" run --rm -T numis-geek uv run alembic upgrade head 2>&1 | tee -a "$LOG"
fi

# ── 6. Restart container ──────────────────────────────────────────────────────
log "restarting container"
docker compose -f "$CF" up -d 2>&1 | tee -a "$LOG"

# ── 7. Health check (6 attempts × 8 s = 48 s window) ─────────────────────────
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

# ── 8. Rollback ───────────────────────────────────────────────────────────────
log "health check FAILED — rolling back to $OLD_SHORT"

# Restore DB if we ran a migration
if [ "$MIGRATIONS_PENDING" = "true" ] && [ -n "$BACKUP" ] && [ -f "$BACKUP" ]; then
  docker compose -f "$CF" stop numis-geek 2>/dev/null || true
  cp "$BACKUP" "$DB" && log "DB restored from backup" || log "WARN DB restore failed"
fi

git -C "$APP" checkout "$OLD_HEAD" -- . 2>&1 | tee -a "$LOG"

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
