#!/bin/bash
set -e

GEOMETRY="${VNC_RESOLUTION}x24"
DISPLAY_NUM="0"
WEBSOCKET_PORT="6901"

# Lance le serveur d'affichage virtuel Xvfb
Xvfb :${DISPLAY_NUM} -screen 0 ${GEOMETRY} &
export DISPLAY=:${DISPLAY_NUM}
sleep 1

# Démarre le bureau XFCE en arrière-plan
startxfce4 &
sleep 2

# --- DÉBUT DE LA MODIFICATION FINALE ---
# On force le fond d'écran de manière robuste.
WALLPAPER_PATH="/usr/share/backgrounds/bg_default.png"

# Trouve TOUTES les propriétés de fond d'écran et boucle dessus
xfconf-query -c xfce4-desktop -l | grep 'last-image$' | while read -r PROPERTY; do
  # Applique notre fond d'écran à chaque propriété trouvée (monitor0, monitorscreen, etc.)
  echo "Définition du fond d'écran pour la propriété : $PROPERTY"
  xfconf-query -c xfce4-desktop -p "$PROPERTY" -s "$WALLPAPER_PATH"
done
# --- FIN DE LA MODIFICATION FINALE ---

# Démarre le serveur VNC x11vnc
x11vnc -forever -passwd "$VNC_PW" -display :${DISPLAY_NUM} &
sleep 2

# Lance le pont web noVNC
websockify -v --web=/usr/share/novnc/ ${WEBSOCKET_PORT} localhost:5900