#!/bin/bash
set -e
apt-get update
apt-get install -y --no-install-recommends \
    firefox \
    mousepad \
    gnome-terminal \
    wget \
    curl \
    unzip