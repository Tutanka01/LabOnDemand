#!/bin/bash

# Stop on first error and fail on unset vars/pipes
set -euo pipefail

apt-get update

# Installe le serveur VNC et le client web
apt-get install -y --no-install-recommends \
	x11vnc \
	novnc \
	python3-websockify

# Crée le lien symbolique pour noVNC (force si déjà présent)
ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html