FROM codercom/code-server:latest

# Proxy configurable via build args (laisser vide pour ne pas utiliser de proxy)
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV HTTP_PROXY="${HTTP_PROXY}" \
    HTTPS_PROXY="${HTTPS_PROXY}" \
    http_proxy="${HTTP_PROXY}" \
    https_proxy="${HTTPS_PROXY}"

USER root

# Configurer le proxy pour APT (uniquement si défini)
RUN if [ -n "$HTTP_PROXY" ]; then \
      printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$HTTP_PROXY" "$HTTP_PROXY" > /etc/apt/apt.conf.d/01proxy; \
    fi

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

# Configurer npm, git et pip pour utiliser le proxy (uniquement si défini)
RUN if [ -n "$HTTP_PROXY" ]; then \
      npm config set proxy "$HTTP_PROXY" \
      && npm config set https-proxy "$HTTPS_PROXY" \
      && git config --system http.proxy "$HTTP_PROXY" \
      && git config --system https.proxy "$HTTPS_PROXY" \
      && printf '[global]\nproxy = %s\n' "$HTTP_PROXY" > /etc/pip.conf; \
    fi

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