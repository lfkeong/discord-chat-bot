# EC2 Deployment Guide

This guide will help you deploy the Discord bot to your EC2 Ubuntu instance.

## Prerequisites

- EC2 instance running Ubuntu
- Code cloned to the instance (you've already done this)
- SSH access to the instance

## Deployment Steps

### 1. Update System Packages

```bash
sudo apt update
sudo apt upgrade -y
```

### 2. Install Python and pip

```bash
sudo apt install python3 python3-pip python3-venv -y
```

### 3. Navigate to Project Directory

```bash
cd ~/discord-chat-bot
```

(Adjust the path if you cloned it to a different location)

### 4. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 5. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Set Up Environment Variables

Create a `.env` file in the project directory:

```bash
nano .env
```

Add the following (replace with your actual values):

```
DISCORD_TOKEN=your_discord_bot_token_here
GUILD_ID=your_guild_id_here
```

Save and exit (Ctrl+X, then Y, then Enter).

**Important:** Make sure your `.env` file is in `.gitignore` (it already is) to avoid committing secrets.

### 7. Test the Bot (Optional)

Before setting up as a service, test that it runs:

```bash
source venv/bin/activate
python bot.py
```

If it connects successfully, press Ctrl+C to stop it.

### 8. Set Up Systemd Service

Copy the service file to systemd directory:

```bash
sudo cp discord-bot.service /etc/systemd/system/
```

Reload systemd to recognize the new service:

```bash
sudo systemctl daemon-reload
```

Enable the service to start on boot:

```bash
sudo systemctl enable discord-bot.service
```

Start the service:

```bash
sudo systemctl start discord-bot.service
```

### 9. Check Service Status

Check if the bot is running:

```bash
sudo systemctl status discord-bot.service
```

View logs:

```bash
sudo journalctl -u discord-bot.service -f
```

### 10. Useful Commands

**Stop the bot:**
```bash
sudo systemctl stop discord-bot.service
```

**Restart the bot:**
```bash
sudo systemctl restart discord-bot.service
```

**View recent logs:**
```bash
sudo journalctl -u discord-bot.service -n 50
```

**Disable auto-start on boot:**
```bash
sudo systemctl disable discord-bot.service
```

## Troubleshooting

### Bot not starting

1. Check the service status: `sudo systemctl status discord-bot.service`
2. Check logs: `sudo journalctl -u discord-bot.service -n 100`
3. Verify `.env` file exists and has correct values
4. Make sure virtual environment is activated when testing manually
5. Check that Python path in service file matches your venv location

### Permission issues

If you get permission errors, make sure:
- The service file has correct user (`ubuntu`)
- The working directory path is correct
- The `.env` file has correct permissions (should be readable by the ubuntu user)

### SSL Certificate Issues

The bot includes SSL certificate fixes for macOS. On Ubuntu, these should work fine, but if you encounter SSL issues, you may need to update certificates:

```bash
sudo apt update && sudo apt install ca-certificates -y
```

## Updating the Bot

When you make changes to the code:

1. Pull the latest changes (if using git):
   ```bash
   cd ~/discord-chat-bot
   git pull
   ```

2. If dependencies changed:
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Restart the service:
   ```bash
   sudo systemctl restart discord-bot.service
   ```

4. Check status:
   ```bash
   sudo systemctl status discord-bot.service
   ```
