FROM codercom/code-server:4.121.0-39

# Proxy configurable via build args (laisser vide pour ne pas utiliser de proxy)
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV HTTP_PROXY="${HTTP_PROXY}" \
    HTTPS_PROXY="${HTTPS_PROXY}" \
    http_proxy="${HTTP_PROXY}" \
    https_proxy="${HTTPS_PROXY}"

USER root

# Installer des extensions VS Code populaires
RUN code-server --install-extension ms-python.python \
    && code-server --install-extension ms-azuretools.vscode-docker \
    && code-server --install-extension redhat.vscode-yaml \
    && code-server --install-extension esbenp.prettier-vscode \
    && code-server --install-extension eamodio.gitlens

# Exposer le port
EXPOSE 8080

# Point d'entrée: le mot de passe est fourni par PASSWORD, injecté depuis un Secret Kubernetes.
ENTRYPOINT ["/bin/sh", "-c", "mkdir -p /root/.config/code-server && printf 'bind-addr: 0.0.0.0:8080\\nauth: password\\npassword: %s\\ncert: false\\n' \"${PASSWORD:-labondemand}\" > /root/.config/code-server/config.yaml && exec /usr/bin/entrypoint.sh --config /root/.config/code-server/config.yaml"]
