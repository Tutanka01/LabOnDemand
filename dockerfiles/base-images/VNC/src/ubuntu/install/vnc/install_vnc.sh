#!/bin/bash

# Stop on first error and fail on unset vars/pipes
set -euo pipefail

apt-get update

# Serveur VNC TigerVNC (Xvnc = serveur X + VNC avec encodages Tight/ZRLE et
# redimensionnement dynamique de l'écran via RFB DesktopSize / RandR),
# le client web noVNC et son pont WebSocket.
apt-get install -y --no-install-recommends \
	tigervnc-standalone-server \
	tigervnc-common \
	tigervnc-tools \
	novnc \
	python3-websockify \
	x11-xserver-utils \
	xclip \
	xsel

apt-get clean
rm -rf /var/lib/apt/lists/*

# Page d'accueil noVNC : connexion automatique + redimensionnement automatique
# de l'écran distant à la taille de la fenêtre du navigateur (resize=remote),
# avec reconnexion automatique en cas de coupure réseau.
NOVNC_LAUNCH="vnc.html?autoconnect=true&resize=remote&reconnect=true&reconnect_delay=3"
cat > /usr/share/novnc/index.html <<EOF
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="0; url=${NOVNC_LAUNCH}" />
  <title>Bureau distant LabOnDemand</title>
  <script>window.location.replace("${NOVNC_LAUNCH}");</script>
</head>
<body>
  <p><a href="${NOVNC_LAUNCH}">Ouvrir le bureau distant</a></p>
</body>
</html>
EOF
