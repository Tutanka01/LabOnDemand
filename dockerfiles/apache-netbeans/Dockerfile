FROM tutanka01/labondemand:base-ubuntu24

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root

ENV HOME=/home/lod-user \
    STARTUPDIR=/dockerstartup \
    INST_SCRIPTS=/dockerstartup/install

WORKDIR $HOME

# Paramètres d'installation NetBeans (le paquet inclut un JDK Temurin mais nous
# installons Oracle JDK 25 séparément, comme sur l'image Eclipse)
ARG NB_VERSION=31-1
ARG NB_DEB_URL=https://github.com/Friends-of-Apache-NetBeans/netbeans-installers/releases/download/nb31/apache-netbeans_31-1_amd64.deb
ARG NB_DEB_SHA256=329ba92c4aa87bcd2814a800f6cc2d29083d7b00434f1e7e42249221986e6e78

# Paramètres d'installation Oracle JDK 25
ARG ORACLE_JDK_DEB_URL=https://download.oracle.com/java/25/latest/jdk-25_linux-x64_bin.deb
ARG ORACLE_JDK_DEB_SHA256=""

# Dépendances légères pour NetBeans + téléchargement
RUN set -euxo pipefail; \
        apt-get update; \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            wget ca-certificates xdg-utils \
            libxext6 libxrender1 libxtst6 libxi6 libgtk-3-0 libnss3 libgtk-3-0t64 fonts-dejavu; \
        update-ca-certificates

# Installer NetBeans (le JDK fourni par le .deb sera utilisé par défaut)
RUN set -euxo pipefail; \
    apt-get update; \
    tmp_deb="/tmp/netbeans_${NB_VERSION}.deb"; \
    wget -q "${NB_DEB_URL}" -O "$tmp_deb"; \
    if [ -n "${NB_DEB_SHA256}" ]; then echo "${NB_DEB_SHA256}  $tmp_deb" | sha256sum -c -; fi; \
    # Installe les dépendances éventuelles et réessaie si dpkg échoue
    dpkg -i "$tmp_deb" || { apt-get -f install -y; dpkg -i "$tmp_deb"; }; \
    rm -f "$tmp_deb"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Installer Oracle JDK 25
RUN set -euxo pipefail; \
    apt-get update; \
    tmp_jdk_deb="/tmp/oracle-jdk25.deb"; \
    wget -q "${ORACLE_JDK_DEB_URL}" -O "$tmp_jdk_deb"; \
    if [ -n "${ORACLE_JDK_DEB_SHA256}" ]; then echo "${ORACLE_JDK_DEB_SHA256}  $tmp_jdk_deb" | sha256sum -c -; fi; \
    apt-get install -y --no-install-recommends "$tmp_jdk_deb"; \
    rm -f "$tmp_jdk_deb"; \
    # Lien stable: le répertoire du JDK est versionné (ex: jdk-25.0.4.1-oracle-x64)
    real_jdk="$(ls -d /usr/lib/jvm/jdk-*-oracle-x64 | sort | tail -1)"; \
    ln -sfn "$real_jdk" /usr/lib/jvm/oracle-jdk-25; \
    ln -sfn /usr/lib/jvm/oracle-jdk-25 /usr/lib/jvm/jdk-25; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/oracle-jdk-25
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Desktop integration
RUN cat >/usr/share/applications/netbeans.desktop <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Apache NetBeans 31
Comment=Apache NetBeans IDE
Exec=/usr/bin/netbeans
Icon=/usr/share/netbeans/nb/netbeans.png
Terminal=false
Categories=Development;IDE;Java;
StartupWMClass=netbeans
EOF

# Copier le raccourci sur le Desktop du profil par défaut
RUN mkdir -p "$HOME/Desktop" \
    && cp /usr/share/applications/netbeans.desktop "$HOME/Desktop/Apache NetBeans.desktop" \
    && chmod +x "$HOME/Desktop/Apache NetBeans.desktop"

# Permissions
#RUN chown 1000:0 $HOME && $STARTUPDIR/set_user_permission.sh $HOME

# Passer à l'utilisateur final
ENV HOME=/home/lod-user
WORKDIR $HOME
RUN mkdir -p $HOME && chown -R 1000:0 $HOME

USER 1000
