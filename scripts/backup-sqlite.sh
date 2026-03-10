#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${APP_DIR}/backups"
TIMESTAMP="$(date +%F_%H-%M-%S)"
KEEP_DAYS="${KEEP_DAYS:-14}"

cd "${APP_DIR}"

mkdir -p "${BACKUP_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing .env file in ${APP_DIR}."
  exit 1
fi

echo "Creating SQLite backup..."
docker compose exec -T -e BACKUP_TIMESTAMP="${TIMESTAMP}" web python -c "import os, sqlite3; source='/app/instance/buffet_club.db'; dest=f'/backups/buffet_club_{os.environ[\"BACKUP_TIMESTAMP\"]}.sqlite3'; src=sqlite3.connect(f'file:{source}?mode=ro', uri=True); dst=sqlite3.connect(dest); src.backup(dst); dst.close(); src.close(); print(dest)"

echo "Pruning backups older than ${KEEP_DAYS} days..."
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'buffet_club_*.sqlite3' -mtime +"${KEEP_DAYS}" -delete

echo "Current backups:"
ls -lh "${BACKUP_DIR}"
