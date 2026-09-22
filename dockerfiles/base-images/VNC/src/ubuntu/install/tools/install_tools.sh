#!/bin/bash
set -euo pipefail

apt-get update

# Outils du bureau (éditeur, archiveur, réseau, Git)
apt-get install -y --no-install-recommends \
    mousepad \
    wget \
    curl \
    ca-certificates \
    zip \
    unzip \
    git \
    xdg-utils

# Firefox : le paquet d'Ubuntu 24.04 est une coquille Snap inutilisable dans un
# conteneur. On installe le paquet .deb officiel du dépôt Mozilla à la place.
install -d -m 0755 /etc/apt/keyrings
wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg \
    -O /etc/apt/keyrings/packages.mozilla.org.asc
echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
    > /etc/apt/sources.list.d/mozilla.list
# Priorité haute pour ne jamais retomber sur le paquet Snap d'Ubuntu
cat > /etc/apt/preferences.d/mozilla <<'EOF'
Package: *
Pin: origin packages.mozilla.org
Pin-Priority: 1000
EOF

apt-get update
apt-get install -y --no-install-recommends firefox

apt-get clean
rm -rf /var/lib/apt/lists/*
