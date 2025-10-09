# ÉTAPE 1: Construction de la base
ARG BASE_IMAGE="ubuntu:24.04"
FROM $BASE_IMAGE AS base_layer

# Arguments de construction pour la personnalisation
ARG BG_IMG=bg_uppa.png

# Variables d'environnement
ENV DEBIAN_FRONTEND=noninteractive \
    LANG='fr_FR.UTF-8' \
    LANGUAGE='fr_FR:fr' \
    LC_ALL='fr_FR.UTF-8' \
    TZ='Europe/Paris' \
    HOME=/home/uppa-user \
    STARTUPDIR=/dockerstartup \
    INST_SCRIPTS=/dockerstartup/install

# Création de l'utilisateur
RUN groupmod -n uppa-user $(getent group 1000 | cut -d: -f1) && \
    usermod -l uppa-user -d /home/uppa-user -m $(getent passwd 1000 | cut -d: -f1) && \
    mkdir -p ${HOME}/Desktop && \
    chown -R uppa-user:uppa-user ${HOME}

WORKDIR $HOME

# Installation des dépendances et locales
RUN apt-get update && \
    apt-get install -y --no-install-recommends locales && \
    locale-gen fr_FR.UTF-8

# Installation des outils et du bureau XFCE
COPY src/ubuntu/install/xfce/ $INST_SCRIPTS/xfce/
RUN bash $INST_SCRIPTS/xfce/install_xfce_ui.sh && rm -rf $INST_SCRIPTS/xfce/

# --- MODIFIÉ : Installation de TigerVNC et noVNC ---
COPY src/ubuntu/install/vnc/ $INST_SCRIPTS/vnc/
RUN bash $INST_SCRIPTS/vnc/install_vnc.sh && rm -rf $INST_SCRIPTS/vnc/

# Configuration du bureau et des icônes
COPY src/common/resources/config/ $HOME/.config/
RUN chown -R uppa-user:uppa-user $HOME/.config
ADD src/common/resources/images/$BG_IMG /usr/share/backgrounds/bg_default.png
ADD src/common/resources/images/icon_uppa.png /usr/share/icons/icon_default.png

# Configuration des scripts de démarrage
COPY src/common/startup_scripts/ $STARTUPDIR/
RUN chmod +x -R $STARTUPDIR && \
    chown -R uppa-user:uppa-user $STARTUPDIR

# Script de nettoyage final
COPY src/ubuntu/install/cleanup/ $INST_SCRIPTS/cleanup/
RUN bash $INST_SCRIPTS/cleanup/cleanup.sh && rm -rf $INST_SCRIPTS/cleanup/

# ---
# ÉTAPE 2: Création de l'image finale
FROM scratch
COPY --from=base_layer / /

# Labels de l'image
LABEL org.opencontainers.image.authors="univ-pau.fr" \
      org.opencontainers.image.title="Desktop UPPA" \
      org.opencontainers.image.description="Environnement de bureau distant pour l'Université de Pau."

# Variables d'environnement pour l'exécution
ENV HOME=/home/uppa-user \
    VNC_PW=password \
    VNC_RESOLUTION=1600x900 \
    LANG='fr_FR.UTF-8' \
    TZ='Europe/Paris'

EXPOSE 6901

USER uppa-user
WORKDIR $HOME

ENTRYPOINT [ "/dockerstartup/startup.sh" ]