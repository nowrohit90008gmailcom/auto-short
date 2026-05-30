#!/bin/bash

# ==============================================================================
# Honeygain Passive Income Setup Script
# Automatically installs Docker and runs the headless Honeygain container.
# ==============================================================================

echo "Starting Honeygain Passive Income Setup..."

# 1. Update and install Docker if it doesn't exist
if ! command -v docker &> /dev/null
then
    echo "Docker not found. Installing Docker..."
    sudo apt update
    sudo apt install -y docker.io
    sudo systemctl enable docker
    sudo systemctl start docker
else
    echo "Docker is already installed."
fi

# 2. Run the Honeygain Node
# The --restart unless-stopped flag ensures it starts up automatically if the VPS reboots.
echo "Launching Honeygain Node..."

sudo docker run -d \
    --restart unless-stopped \
    --name honeygain \
    honeygain/honeygain \
    -tou-accept \
    -email nowrohit90008@gmail.com \
    -pass Sakshi2307@ \
    -device UbuntuVPS

echo "====================================================================="
echo "SUCCESS: Honeygain is now running silently in the background!"
echo "It will automatically start earning passive income using idle bandwidth."
echo "You can view your earnings on the Honeygain web dashboard."
echo "====================================================================="
