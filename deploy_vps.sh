#!/bin/bash
# Autonomous Podcast Shorts Deploy Script for Linux VPS

echo "Setting up Autonomous Publisher for VPS..."

# 1. Update and install FFmpeg and Python if not present
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg

# 2. Set up virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the daemon in the background (nohup)
echo "Starting daemon and dashboard in the background..."
nohup python auto_publisher.py > daemon_output.log 2>&1 &
nohup python dashboard.py > dashboard.log 2>&1 &

echo "Deployment complete! The bot is now running autonomously in the background."
echo "Your monitoring dashboard is live at: http://<YOUR_VPS_IP>:5000"
echo "You can check the raw logs anytime by running: tail -f daemon_output.log"
