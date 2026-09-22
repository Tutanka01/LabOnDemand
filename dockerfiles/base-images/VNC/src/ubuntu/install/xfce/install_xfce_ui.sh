#!/bin/bash

# Stop on first error and fail on unset vars/pipes
set -euo pipefail

apt-get update

# Bureau XFCE. Le serveur X est fourni par Xvnc (TigerVNC) :
# pas besoin du paquet "xorg" (trop lourd) ni de "xvfb".
apt-get install -y --no-install-recommends \
	xfce4 \
	xfce4-goodies \
	xfce4-terminal \
	xinit \
	dbus-x11 \
	x11-utils \
	fonts-dejavu \
	fonts-liberation

apt-get clean
rm -rf /var/lib/apt/lists/*
