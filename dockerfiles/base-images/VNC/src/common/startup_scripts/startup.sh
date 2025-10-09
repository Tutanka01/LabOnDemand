#!/bin/bash
set -e

GEOMETRY="${VNC_RESOLUTION}x24"
DISPLAY_NUM="0"
WEBSOCKET_PORT="6901"

# Lance le serveur d'affichage virtuel Xvfb
Xvfb :${DISPLAY_NUM} -screen 0 ${GEOMETRY} &
export DISPLAY=:${DISPLAY_NUM}
sleep 1

# Démarre le bureau XFCE (qui lancera notre script de fond d'écran via l'autostart)
startxfce4 &
sleep 2

# Démarre le serveur VNC x11vnc
x11vnc -forever -passwd "$VNC_PW" -display :${DISPLAY_NUM} &
sleep 2

# Lance le pont web noVNC
websockify -v --web=/usr/share/novnc/ ${WEBSOCKET_PORT} localhost:5900