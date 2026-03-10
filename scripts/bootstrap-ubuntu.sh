#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this script as your normal sudo-capable user, not as root."
  exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/williampburch/TheBoMC.git}"
APP_DIR="${APP_DIR:-$HOME/TheBoMC}"
APP_USER="${APP_USER:-$USER}"

echo "Updating apt package index..."
sudo apt-get update

echo "Installing base packages..."
sudo apt-get install -y ca-certificates curl git

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker Engine..."
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg

  source /etc/os-release
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    ${VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

echo "Ensuring Docker starts on boot..."
sudo systemctl enable docker
sudo systemctl start docker

echo "Adding ${APP_USER} to the docker group..."
sudo usermod -aG docker "${APP_USER}"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Cloning repository to ${APP_DIR}..."
  git clone "${REPO_URL}" "${APP_DIR}"
else
  echo "Repository already exists at ${APP_DIR}, skipping clone."
fi

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
  echo "Edit ${APP_DIR}/.env before running deploy.sh."
else
  echo ".env already exists, leaving it unchanged."
fi

echo
echo "Bootstrap complete."
echo "Next steps:"
echo "1. Log out and back in so docker group membership applies."
echo "2. Edit ${APP_DIR}/.env with production values."
echo "3. Run: cd ${APP_DIR} && ./scripts/deploy.sh"
