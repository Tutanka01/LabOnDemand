#!/bin/bash

# Stop on first error and fail on unset vars/pipes
set -euo pipefail

apt-get update
apt-get install -y --no-install-recommends \
    xfce4 \
    xfce4-goodies \
    xfce4-terminal \
    dbus-x11 \
    xinit \
    xorg \
    xvfb