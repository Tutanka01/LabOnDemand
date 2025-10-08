#!/bin/bash
set -e

# --- DEBUT DE LA MODIFICATION FINALE ---
# Définit la résolution et la profondeur de couleur correctement
# VNC_RESOLUTION est "1600x900" (par défaut), on ajoute juste "x24" pour la couleur
GEOMETRY="${VNC_RESOLUTION}x24"
# --- FIN DE LA MODIFICATION FINALE ---

DISPLAY_NUM="0"
WEBSOCKET_PORT="6901"

# Lance le serveur d'affichage virtuel Xvfb en arrière-plan
# Il crée l'écran virtuel :0 avec la bonne géométrie
Xvfb :${DISPLAY_NUM} -screen 0 ${GEOMETRY} &

# Exporte la variable DISPLAY
export DISPLAY=:${DISPLAY_NUM}

# Attend une seconde que Xvfb soit prêt
sleep 1

# Démarre le bureau XFCE sur l'écran virtuel, en arrière-plan
startxfce4 &

# Attend une seconde que XFCE soit prêt
sleep 1

# Démarre le serveur VNC x11vnc, attaché à notre écran virtuel
x11vnc -forever -passwd "$VNC_PW" -display :${DISPLAY_NUM} &

# Lance le pont web noVNC (c'est le processus qui restera au premier plan)
websockify -v --web=/usr/share/novnc/ ${WEBSOCKET_PORT} localhost:5900