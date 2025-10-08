#!/bin/bash
set -e
apt-get update

# Installe le nouveau serveur VNC (x11vnc) et le client web
apt-get install -y --no-install-recommends x11vnc novnc websockify

# Crée le lien symbolique pour noVNC
ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html