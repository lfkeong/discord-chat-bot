#!/bin/bash
# Simple deployment script for Discord bot on EC2 with Docker
#
# What it does:
# 1) SSH into EC2
# 2) cd into project directory
# 3) git pull latest changes
# 4) build Docker image
# 5) recreate & restart container
#
# Usage (from your local machine, in project root):
#   bash scripts/deploy-docker.sh
#
# Prerequisites on EC2:
# - repo already cloned to REPO_DIR
# - Docker installed and running
# - .env file present in REPO_DIR with DISCORD_TOKEN, etc.

set -e

# ----- CONFIG -----
EC2_IP="18.138.236.195"
EC2_USER="ubuntu"
KEY_FILE="./discord-chat-bot.pem"          # path relative to project root
REPO_DIR="/home/ubuntu/discord-chat-bot"   # directory on EC2 where repo is cloned
DOCKER_IMAGE_NAME="discord-bot"
DOCKER_CONTAINER_NAME="discord-bot"
GIT_BRANCH="main"                          # change if you use a different branch
# -------------------

if [ ! -f "$KEY_FILE" ]; then
  echo "Error: Key file not found at $KEY_FILE"
  echo "Make sure your PEM file is in the project root and KEY_FILE path is correct."
  exit 1
fi

# Ensure correct key permissions
if [ "$(stat -f %A "$KEY_FILE" 2>/dev/null || stat -c %a "$KEY_FILE" 2>/dev/null)" != "400" ]; then
  echo "Setting correct permissions for key file..."
  chmod 400 "$KEY_FILE"
fi

echo "Deploying to EC2 $EC2_USER@$EC2_IP ..."

ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP" bash -s <<EOF
set -e

echo ">>> Switching to repo directory: $REPO_DIR"
cd "$REPO_DIR"

echo ">>> Fetching latest code..."
git fetch origin
git checkout "$GIT_BRANCH"
git pull origin "$GIT_BRANCH"

echo ">>> Building Docker image: $DOCKER_IMAGE_NAME"
docker build -t "$DOCKER_IMAGE_NAME" .

echo ">>> Stopping old container (if exists)..."
docker rm -f "$DOCKER_CONTAINER_NAME" 2>/dev/null || true

echo ">>> Starting new container..."
docker run -d --name "$DOCKER_CONTAINER_NAME" \\
  --env-file .env \\
  "$DOCKER_IMAGE_NAME"

echo ">>> Deployment complete. Showing last 20 log lines:"
docker logs --tail 20 "$DOCKER_CONTAINER_NAME" || true
EOF

echo "Done."

