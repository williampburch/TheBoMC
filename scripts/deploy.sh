#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing .env file in ${APP_DIR}."
  echo "Create it from .env.example before deploying."
  exit 1
fi

echo "Pulling latest changes..."
git pull --ff-only

echo "Building and starting containers..."
docker compose up -d --build

echo "Running database migrations..."
docker compose exec -T web flask --app app:app db upgrade

echo "Current container status:"
docker compose ps

echo
echo "Deployment complete."
