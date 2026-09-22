# ÉTAPE 1: Construction de la base
ARG BASE_IMAGE="ubuntu:24.04"
FROM $BASE_IMAGE AS base_layer

# Arguments de construction pour la personnalisation
ARG BG_IMG=bg_labondemand.png

# Variables d'environnement
ENV DEBIAN_FRONTEND=noninteractive \
    LANG='fr_FR.UTF-8' \
    LANGUAGE='fr_FR:fr' \
    LC_ALL='fr_FR.UTF-8' \
    TZ='Europe/Paris' \
    HOME=/home/lod-user \
    STARTUPDIR=/dockerstartup \
    INST_SCRIPTS=/dockerstartup/install

# Création de l'utilisateur
RUN groupmod -n lod-user $(getent group 1000 | cut -d: -f1) && \
    usermod -l lod-user -d /home/lod-user -m $(getent passwd 1000 | cut -d: -f1) && \
    mkdir -p ${HOME}/Desktop && \
    chown -R lod-user:lod-user ${HOME}

WORKDIR $HOME

# Installation des dépendances et locales
RUN apt-get update && \
    apt-get install -y --no-install-recommends locales && \
    locale-gen fr_FR.UTF-8

# Installation des outils et du bureau XFCE
COPY src/ubuntu/install/xfce/ $INST_SCRIPTS/xfce/
RUN sed -i 's/\r$//' $INST_SCRIPTS/xfce/install_xfce_ui.sh && \
    bash $INST_SCRIPTS/xfce/install_xfce_ui.sh && \
    rm -rf $INST_SCRIPTS/xfce/

# --- MODIFIÉ : Installation de TigerVNC et noVNC ---
COPY src/ubuntu/install/vnc/ $INST_SCRIPTS/vnc/
RUN sed -i 's/\r$//' $INST_SCRIPTS/vnc/install_vnc.sh && \
    bash $INST_SCRIPTS/vnc/install_vnc.sh && \
    rm -rf $INST_SCRIPTS/vnc/

# Installation des outils du bureau (Firefox, éditeur, Git, archiveurs)
COPY src/ubuntu/install/tools/ $INST_SCRIPTS/tools/
RUN sed -i 's/\r$//' $INST_SCRIPTS/tools/install_tools.sh && \
    bash $INST_SCRIPTS/tools/install_tools.sh && \
    rm -rf $INST_SCRIPTS/tools/

# Configuration du bureau et des icônes
COPY src/common/resources/config/ $HOME/.config/
RUN chown -R lod-user:lod-user $HOME/.config
ADD src/common/resources/images/$BG_IMG /usr/share/backgrounds/bg_default.png
ADD src/common/resources/images/icon_labondemand.png /usr/share/icons/icon_default.png

# Configuration des scripts de démarrage
COPY src/common/startup_scripts/ $STARTUPDIR/
RUN sed -i 's/\r$//' $STARTUPDIR/startup.sh && \
    chmod +x -R $STARTUPDIR && \
    chown -R lod-user:lod-user $STARTUPDIR

# Script de nettoyage final
COPY src/ubuntu/install/cleanup/ $INST_SCRIPTS/cleanup/
RUN bash $INST_SCRIPTS/cleanup/cleanup.sh && rm -rf $INST_SCRIPTS/cleanup/

# ---
# ÉTAPE 2: Création de l'image finale
FROM scratch
COPY --from=base_layer / /

# Labels de l'image
LABEL org.opencontainers.image.authors="makhal" \
    org.opencontainers.image.title="Desktop LabOnDemand" \
    org.opencontainers.image.description="Environnement de bureau distant by makhal."

# Variables d'environnement pour l'exécution
ENV HOME=/home/lod-user \
    VNC_PW=changeme \
    VNC_VIEW_ONLY_PW= \
    VNC_RESOLUTION=1600x900 \
    NOVNC_PORT=6901 \
    LANG='fr_FR.UTF-8' \
    TZ='Europe/Paris'

# 6901: bureau via navigateur (noVNC) - 5901: client VNC classique
EXPOSE 6901 5901

# Le bureau est sain quand le pont web noVNC répond
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python3 -c "import os,socket; socket.create_connection(('127.0.0.1', int(os.environ.get('NOVNC_PORT','6901'))), 3)"

USER lod-user
WORKDIR $HOME

ENTRYPOINT [ "bash", "/dockerstartup/startup.sh" ]
