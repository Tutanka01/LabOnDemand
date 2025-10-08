#!/bin/bash
set -e
apt-get update
apt-get install -y --no-install-recommends \
    xfce4 \
    xfce4-goodies \
    xfce4-terminal \
    dbus-x11 \
    xinit \
    xorg \
    xvfb # MODIFIÉ : Ajout du serveur d'affichage virtuel