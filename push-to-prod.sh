#!/usr/bin/env bash
# push-to-prod.sh — copia DB e attachments do ambiente local para o VPS.
#
# Inverso do pull-from-prod.sh. Usado em situações onde o local é a
# source of truth (ex: backfill grande, correções em massa antes do
# usuário tocar prod).
#
# USO:
#   bash push-to-prod.sh                       # interativo (recomendado)
#   bash push-to-prod.sh --yes                 # sem confirmação
#   bash push-to-prod.sh --db-only             # só DB, pula attachments
#   bash push-to-prod.sh --attachments-only    # só attachments, pula DB
#
# FLUXO DE SEGURANÇA:
#   1. Checkpoint WAL local pra DB consistente.
#   2. Mostra diff de contagens (movements, snapshots, items) entre
#      local e prod pra você confirmar que faz sentido.
#   3. Para o container do VPS antes de sobrescrever (sqlite + WAL não
#      tolera escrita externa).
#   4. Backup do DB prod (`.bak-before-push-TS`).
#   5. Backup dos attachments prod via rsync hardlink (rápido).
#   6. scp/rsync local → VPS.
#   7. Sobe o container, roda health check.
#   8. Em caso de falha: restaura DB do backup e sobe o container.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DB="$SCRIPT_DIR/numis_geek.db"
LOCAL_ATTACHMENTS="$SCRIPT_DIR/data/attachments"
VPS="vps1-hostinger"
VPS_APP="/opt/infra/apps/numis-geek"
VPS_DB="$VPS_APP/data/numis_geek.db"
VPS_ATTACHMENTS="$VPS_APP/data/attachments"
VPS_COMPOSE_DIR="$VPS_APP"
HEALTH_URL="http://localhost:8100/health"

# ── Args ─────────────────────────────────────────────────────────────────────
ASSUME_YES=0
PUSH_DB=1
PUSH_ATT=1
for arg in "$@"; do
  case "$arg" in
    --yes) ASSUME_YES=1 ;;
    --db-only) PUSH_ATT=0 ;;
    --attachments-only) PUSH_DB=0 ;;
    *) echo "uso: $0 [--yes] [--db-only|--attachments-only]"; exit 2 ;;
  esac
done

# ── Sanity ───────────────────────────────────────────────────────────────────
[ "$PUSH_DB" = "1" ] && [ ! -f "$LOCAL_DB" ] && { echo "Local DB ausente: $LOCAL_DB"; exit 1; }
[ "$PUSH_ATT" = "1" ] && [ ! -d "$LOCAL_ATTACHMENTS" ] && {
  echo "Local attachments ausente: $LOCAL_ATTACHMENTS"; exit 1;
}

echo "═══════════════════════════════════════════════════════════════"
echo "  PUSH-TO-PROD  ·  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"
[ "$PUSH_DB" = "1" ]  && echo "  DB          : $LOCAL_DB"
[ "$PUSH_DB" = "1" ]  && echo "             → $VPS:$VPS_DB"
[ "$PUSH_ATT" = "1" ] && echo "  Attachments : $LOCAL_ATTACHMENTS/"
[ "$PUSH_ATT" = "1" ] && echo "             → $VPS:$VPS_ATTACHMENTS/"
echo "  VPS         : $VPS"
echo ""

# ── 1. Checkpoint WAL local ──────────────────────────────────────────────────
if [ "$PUSH_DB" = "1" ]; then
  echo "→ checkpoint WAL local..."
  sqlite3 "$LOCAL_DB" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
fi

# ── 2. Diff de contagens local vs prod (read-only) ───────────────────────────
if [ "$PUSH_DB" = "1" ]; then
  echo "→ contagens local vs prod (sanidade pré-overwrite):"
  COUNT_SQL="
    SELECT 'asset', COUNT(*) FROM asset WHERE is_active=1
    UNION ALL SELECT 'asset_movement', COUNT(*) FROM asset_movement WHERE is_active=1
    UNION ALL SELECT 'distribution', COUNT(*) FROM distribution WHERE is_active=1
    UNION ALL SELECT 'portfolio_snapshot', COUNT(*) FROM portfolio_snapshot WHERE is_active=1
    UNION ALL SELECT 'portfolio_snapshot_item', COUNT(*) FROM portfolio_snapshot_item;
  "
  LOCAL_COUNTS=$(sqlite3 "$LOCAL_DB" "$COUNT_SQL")
  PROD_COUNTS=$(ssh "$VPS" "sqlite3 $VPS_DB \"$COUNT_SQL\"" 2>/dev/null || echo "ERROR")

  printf "    %-25s %12s %12s\n" "tabela" "local" "prod"
  printf "    %-25s %12s %12s\n" "──────" "─────" "────"
  if [ "$PROD_COUNTS" = "ERROR" ]; then
    echo "    (prod inacessível, continuando sem diff)"
  else
    paste <(echo "$LOCAL_COUNTS") <(echo "$PROD_COUNTS") | \
      while IFS=$'\t' read -r l p; do
        T=$(echo "$l" | cut -d'|' -f1)
        LC=$(echo "$l" | cut -d'|' -f2)
        PC=$(echo "$p" | cut -d'|' -f2)
        MARK=""
        [ "$LC" != "$PC" ] && MARK="  ⟵ DIFF"
        printf "    %-25s %12s %12s%s\n" "$T" "$LC" "$PC" "$MARK"
      done
  fi
  echo ""
fi

# ── 3. Confirmação ───────────────────────────────────────────────────────────
if [ "$ASSUME_YES" != "1" ]; then
  echo "⚠  Isso vai SOBRESCREVER dados em prod. Não tem desfazer (só restore do backup)."
  read -r -p "Continuar? [s/N] " resp
  [[ "$resp" =~ ^[sS]$ ]] || { echo "Abortado."; exit 0; }
fi

# ── 4. Para o container ──────────────────────────────────────────────────────
echo "→ parando container no VPS..."
ssh "$VPS" "cd $VPS_COMPOSE_DIR && docker compose stop numis-geek" >/dev/null

cleanup_resume_container() {
  echo "→ tentando subir container de novo após erro..."
  ssh "$VPS" "cd $VPS_COMPOSE_DIR && docker compose up -d numis-geek" >/dev/null || true
}
trap cleanup_resume_container ERR

# ── 5. Backup prod (DB + attachments) ───────────────────────────────────────
TS=$(date '+%Y%m%d-%H%M%S')
DB_BACKUP="$VPS_DB.bak-before-push-$TS"
ATT_BACKUP="$VPS_ATTACHMENTS.bak-before-push-$TS"

if [ "$PUSH_DB" = "1" ]; then
  echo "→ backup DB prod → $(basename "$DB_BACKUP")"
  ssh "$VPS" "sqlite3 $VPS_DB \"PRAGMA wal_checkpoint(TRUNCATE);\" >/dev/null && cp $VPS_DB $DB_BACKUP"
fi

if [ "$PUSH_ATT" = "1" ]; then
  echo "→ backup attachments prod (hardlink, rápido) → $(basename "$ATT_BACKUP")"
  ssh "$VPS" "cp -al $VPS_ATTACHMENTS $ATT_BACKUP"
fi

# ── 6. Push DB ───────────────────────────────────────────────────────────────
if [ "$PUSH_DB" = "1" ]; then
  echo "→ enviando DB ($(du -h "$LOCAL_DB" | cut -f1))..."
  scp -q "$LOCAL_DB" "$VPS:$VPS_DB"
  # SQLite WAL pode ficar dessincronizado se houver -wal/-shm antigos no destino.
  ssh "$VPS" "rm -f ${VPS_DB}-wal ${VPS_DB}-shm"
fi

# ── 7. Push attachments ──────────────────────────────────────────────────────
if [ "$PUSH_ATT" = "1" ]; then
  echo "→ sincronizando attachments (--delete)..."
  rsync -a --delete "$LOCAL_ATTACHMENTS/" "$VPS:$VPS_ATTACHMENTS/"
fi

# ── 8. Sobe container + health ───────────────────────────────────────────────
trap - ERR
echo "→ subindo container..."
ssh "$VPS" "cd $VPS_COMPOSE_DIR && docker compose up -d numis-geek" >/dev/null

echo "→ health check (até ~48s)..."
HEALTHY=0
for i in 1 2 3 4 5 6; do
  sleep 8
  if ssh "$VPS" "curl -sf $HEALTH_URL" >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
  echo "    tentativa $i/6 falhou, retrying..."
done

if [ "$HEALTHY" = "1" ]; then
  echo ""
  echo "✅ push concluído. Backup do prod anterior:"
  [ "$PUSH_DB" = "1" ]  && echo "   DB:          $DB_BACKUP"
  [ "$PUSH_ATT" = "1" ] && echo "   Attachments: $ATT_BACKUP"
  exit 0
fi

# ── 9. Rollback ──────────────────────────────────────────────────────────────
echo ""
echo "❌ health check FAILED — fazendo rollback do DB e attachments."
ssh "$VPS" "cd $VPS_COMPOSE_DIR && docker compose stop numis-geek" >/dev/null || true
if [ "$PUSH_DB" = "1" ]; then
  ssh "$VPS" "cp $DB_BACKUP $VPS_DB && rm -f ${VPS_DB}-wal ${VPS_DB}-shm"
  echo "   DB restaurado de $DB_BACKUP"
fi
if [ "$PUSH_ATT" = "1" ]; then
  ssh "$VPS" "rm -rf $VPS_ATTACHMENTS && mv $ATT_BACKUP $VPS_ATTACHMENTS"
  echo "   Attachments restaurados de $ATT_BACKUP"
fi
ssh "$VPS" "cd $VPS_COMPOSE_DIR && docker compose up -d numis-geek" >/dev/null || true
sleep 10
if ssh "$VPS" "curl -sf $HEALTH_URL" >/dev/null 2>&1; then
  echo "✅ rollback OK — prod voltou ao estado anterior."
else
  echo "🚨 rollback falhou. SSH manual necessário."
fi
exit 1
