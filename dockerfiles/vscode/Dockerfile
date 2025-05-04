FROM codercom/code-server:latest

USER root

# Installer les dépendances de base
RUN apt-get update && apt-get install -y \
    curl \
    git \
    python3 \
    python3-pip \
    nodejs \
    npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Installer des extensions VS Code populaires
RUN code-server --install-extension ms-python.python \
    && code-server --install-extension ms-azuretools.vscode-docker \
    && code-server --install-extension redhat.vscode-yaml \
    && code-server --install-extension esbenp.prettier-vscode \
    && code-server --install-extension eamodio.gitlens

# Configurer le mot de passe dans le fichier de configuration approprié
RUN mkdir -p /root/.config/code-server && \
    echo "bind-addr: 0.0.0.0:8080\nauth: password\npassword: labondemand\ncert: false" > /root/.config/code-server/config.yaml

# Exposer le port
EXPOSE 8080

# Point d'entrée - utiliser le fichier de configuration par défaut
ENTRYPOINT ["/usr/bin/entrypoint.sh", "--config", "/root/.config/code-server/config.yaml"]