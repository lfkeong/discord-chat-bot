#!/bin/bash
# Quick SSH connection script for EC2 trading bot instance

# EC2 instance details
EC2_IP="13.212.18.190"
EC2_USER="ubuntu"
KEY_FILE="./discord-test-bot.pem"

# Check if key file exists
if [ ! -f "$KEY_FILE" ]; then
    echo "Error: Key file not found at $KEY_FILE"
    echo "Please place your trading-bot.pem file in the project root directory"
    exit 1
fi

# Check key permissions
if [ "$(stat -f %A "$KEY_FILE" 2>/dev/null || stat -c %a "$KEY_FILE" 2>/dev/null)" != "400" ]; then
    echo "Setting correct permissions for key file..."
    chmod 400 "$KEY_FILE"
fi

# Connect to EC2
echo "Connecting to EC2 instance at $EC2_IP..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_IP"
