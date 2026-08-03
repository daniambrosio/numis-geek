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
# Rollback AFTER the fact (hours/days later): the `numis-geek:rollback` tag is gone
# by morning (nightly image prune), so use the saved image —
#   docker load -i /opt/infra/backups/rollback/numis-geek-<sha>.tar.gz
#   docker tag numis-geek:latest numis-geek:latest && docker compose up -d
# Last 3 deploys are kept there. Older than that: the nightly full-*.tgz backup.
#
# Logs: /opt/infra/apps/numis-geek/data/deploy.log

set -euo pipefail
export TZ=America/Sao_Paulo

APP=/opt/infra/apps/numis-geek
CF="$APP/docker-compose.yml"
LOG="$APP/data/deploy.log"
DB="$APP/data/numis_geek.db"
ROLLBACK_DIR=/opt/infra/backups/rollback   # own dir: backup-all.sh globs full-*.tgz only
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

  # The tag above only covers THIS run's failure path. /etc/cron.d/docker-image-prune
  # runs `docker image prune -af --filter until=24h` nightly, so any rollback tag is
  # gone by morning — "roll back to what ran last Tuesday" was never actually possible.
  # Save the image to disk instead. Keep 3: the box hit 76% full on 2026-08-01.
  if docker image inspect numis-geek:latest >/dev/null 2>&1; then
    mkdir -p "$ROLLBACK_DIR"
    SAVE="$ROLLBACK_DIR/numis-geek-$OLD_SHORT.tar.gz"
    if [ -f "$SAVE" ]; then
      log "rollback image for $OLD_SHORT already saved"
    elif docker save numis-geek:latest | gzip -1 > "$SAVE.part" 2>>"$LOG"; then
      mv "$SAVE.part" "$SAVE"
      log "rollback image saved: $(basename "$SAVE") ($(du -h "$SAVE" | cut -f1))"
    else
      rm -f "$SAVE.part"
      log "WARN docker save failed — rollback limited to this run's tag"
    fi
    ls -1t "$ROLLBACK_DIR"/numis-geek-*.tar.gz 2>/dev/null | tail -n +4 | while read -r old; do
      rm -f "$old" && log "pruned old rollback image: $(basename "$old")"
    done
  fi
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
# Parses the alembic output by skipping INFO/blank lines and grabbing the first
# token of the first remaining line (the revision ID, optionally followed by
# " (head)"). Earlier this used a `[a-f0-9]{12}` regex that silently skipped
# textual revision IDs like `notion_removal`, leaving migrations un-applied.
CURRENT_REV=$(docker compose -f "$CF" run --rm -T numis-geek \
  uv run alembic current 2>/dev/null \
  | grep -vE '^(INFO|$)' | awk '{print $1; exit}' || true)
HEAD_REV=$(docker compose -f "$CF" run --rm -T numis-geek \
  uv run alembic heads 2>/dev/null \
  | grep -vE '^(INFO|$)' | awk '{print $1; exit}' || true)

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
