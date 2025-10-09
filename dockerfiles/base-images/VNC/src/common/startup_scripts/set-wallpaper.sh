#!/bin/bash

# Attend que le processus du bureau soit bien lancé
sleep 3

WALLPAPER_PATH="/usr/share/backgrounds/bg_default.png"

# Trouve TOUTES les propriétés de fond d'écran et boucle dessus
xfconf-query -c xfce4-desktop -l | grep 'last-image$' | while read -r PROPERTY; do
  # Applique notre fond d'écran à chaque propriété trouvée
  xfconf-query -c xfce4-desktop -p "$PROPERTY" -s "$WALLPAPER_PATH"
done