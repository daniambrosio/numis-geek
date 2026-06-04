#!/usr/bin/env bash
# pull-from-prod.sh — traz DB e attachments do VPS para o ambiente local.
#
# USO:
#   bash pull-from-prod.sh          # interativo: confirma antes de sobrescrever
#   bash pull-from-prod.sh --yes    # sem confirmação (útil em scripts)
#
# ATENÇÃO: sobrescreve numis_geek.db e data/attachments/ locais.
# Sempre faz backup do DB local antes de substituir.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DB="$SCRIPT_DIR/numis_geek.db"
LOCAL_ATTACHMENTS="$SCRIPT_DIR/data/attachments"
VPS="vps1-hostinger"
VPS_DB="/opt/infra/apps/numis-geek/data/numis_geek.db"
VPS_ATTACHMENTS="/opt/infra/apps/numis-geek/data/attachments/"

# ── Confirmação ───────────────────────────────────────────────────────────────
if [ "${1:-}" != "--yes" ]; then
  echo "Isso vai SOBRESCREVER:"
  echo "  $LOCAL_DB"
  echo "  $LOCAL_ATTACHMENTS/"
  echo ""
  read -r -p "Continuar? [s/N] " resp
  [[ "$resp" =~ ^[sS]$ ]] || { echo "Abortado."; exit 0; }
fi

# ── Backup do DB local antes de tudo ─────────────────────────────────────────
if [ -f "$LOCAL_DB" ]; then
  TS=$(date '+%Y%m%d-%H%M%S')
  BACKUP="$LOCAL_DB.bak-before-pull-$TS"
  cp "$LOCAL_DB" "$BACKUP"
  echo "backup local: $(basename "$BACKUP")"
fi

# ── Checkpoint WAL no VPS (garante DB consistente) ───────────────────────────
echo "checkpoint WAL no VPS..."
ssh "$VPS" "sqlite3 $VPS_DB 'PRAGMA wal_checkpoint(TRUNCATE);'" >/dev/null

# ── Copia DB ──────────────────────────────────────────────────────────────────
echo "copiando DB..."
scp "$VPS:$VPS_DB" "$LOCAL_DB"
echo "DB ok: $(du -h "$LOCAL_DB" | cut -f1)"

# ── Sincroniza attachments ────────────────────────────────────────────────────
echo "sincronizando attachments..."
mkdir -p "$LOCAL_ATTACHMENTS"
rsync -av --delete "$VPS:$VPS_ATTACHMENTS" "$LOCAL_ATTACHMENTS/"

echo ""
echo "done — prod → local sincronizado."
echo "Reinicie o backend local para usar o novo banco."
