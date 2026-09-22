# LabOnDemand - Bureau distant Eclipse IDE for Java
# Hérite de la base VNC (XFCE + TigerVNC + noVNC avec redimensionnement auto
# de l'écran selon la fenêtre du navigateur).
FROM tutanka01/labondemand:base-ubuntu24

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root

ENV HOME=/home/lod-user \
    STARTUPDIR=/dockerstartup \
    INST_SCRIPTS=/dockerstartup/install

WORKDIR $HOME

# --- Versions (surchargeables avec --build-arg) -------------------------------
# Eclipse IDE for Java Developers, JDK Oracle 25 (aligné sur l'image NetBeans),
# Maven et Gradle : l'environnement Java complet pour les TP.
ARG ECLIPSE_VERSION=2026-06
ARG ECLIPSE_BUILD=R
ARG ECLIPSE_SHA512=""
ARG ORACLE_JDK_DEB_URL=https://download.oracle.com/java/25/latest/jdk-25_linux-x64_bin.deb
ARG ORACLE_JDK_DEB_SHA256=""
ARG MAVEN_VERSION=3.9.16
ARG GRADLE_VERSION=9.7.1

ENV JAVA_HOME=/usr/lib/jvm/oracle-jdk-25 \
    ECLIPSE_HOME=/opt/eclipse \
    MAVEN_HOME=/opt/maven \
    GRADLE_HOME=/opt/gradle
ENV PATH="${JAVA_HOME}/bin:${MAVEN_HOME}/bin:${GRADLE_HOME}/bin:${ECLIPSE_HOME}:${PATH}"

# --- Dépendances système (SWT/GTK, outils d'archive et Git) -------------------
RUN set -euxo pipefail; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        wget ca-certificates xdg-utils zip unzip git \
        libxext6 libxrender1 libxtst6 libxi6 libgtk-3-0t64 libnss3 \
        fonts-dejavu fonts-liberation; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# --- Oracle JDK 25 -----------------------------------------------------------
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

# --- Eclipse IDE for Java Developers -----------------------------------------
RUN set -euxo pipefail; \
    eclipse_archive="/tmp/eclipse.tar.gz"; \
    eclipse_url="https://download.eclipse.org/technology/epp/downloads/release/${ECLIPSE_VERSION}/${ECLIPSE_BUILD}/eclipse-java-${ECLIPSE_VERSION}-${ECLIPSE_BUILD}-linux-gtk-x86_64.tar.gz"; \
    wget -q "${eclipse_url}" -O "$eclipse_archive"; \
    if [ -n "${ECLIPSE_SHA512}" ]; then echo "${ECLIPSE_SHA512}  $eclipse_archive" | sha512sum -c -; fi; \
    tar -xzf "$eclipse_archive" -C /opt; \
    rm -f "$eclipse_archive"; \
    ln -sf "${ECLIPSE_HOME}/eclipse" /usr/local/bin/eclipse; \
    # Utiliser le JDK 25 (et non le JRE JustJ embarqué) avec un heap raisonnable
    ini="${ECLIPSE_HOME}/eclipse.ini"; \
    awk 'BEGIN { skip=0; done=0 } \
        skip { skip=0; next } \
        /^-vm$/ { if (!done) { print "-vm"; print "'"${JAVA_HOME}"'/bin"; done=1 }; skip=1; next } \
        /^-vmargs/ && !done { print "-vm"; print "'"${JAVA_HOME}"'/bin"; done=1 } \
        { print }' "$ini" > "$ini.new"; \
    mv "$ini.new" "$ini"; \
    printf '%s\n' '-Xms256m' '-Xmx2048m' '-Dfile.encoding=UTF-8' >> "$ini"
# --- Apache Maven ------------------------------------------------------------
RUN set -euxo pipefail; \
    tmp_maven="/tmp/maven.tar.gz"; \
    wget -q "https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" -O "$tmp_maven"; \
    tar -xzf "$tmp_maven" -C /opt; \
    rm -f "$tmp_maven"; \
    ln -s "/opt/apache-maven-${MAVEN_VERSION}" "${MAVEN_HOME}"; \
    ln -sf "${MAVEN_HOME}/bin/mvn" /usr/local/bin/mvn

# --- Gradle ------------------------------------------------------------------
RUN set -euxo pipefail; \
    tmp_gradle="/tmp/gradle.zip"; \
    wget -q "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" -O "$tmp_gradle"; \
    unzip -q "$tmp_gradle" -d /opt; \
    rm -f "$tmp_gradle"; \
    ln -s "/opt/gradle-${GRADLE_VERSION}" "${GRADLE_HOME}"; \
    ln -sf "${GRADLE_HOME}/bin/gradle" /usr/local/bin/gradle

# --- Intégration bureau ------------------------------------------------------
RUN cat > /usr/share/applications/eclipse.desktop <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Eclipse IDE for Java
Comment=Eclipse IDE for Java Developers ${ECLIPSE_VERSION}
Exec=/usr/local/bin/eclipse
Icon=${ECLIPSE_HOME}/icon.xpm
Terminal=false
Categories=Development;IDE;Java;
StartupWMClass=eclipse
EOF

# Raccourcis sur le menu et sur le Bureau du profil utilisateur par défaut
RUN mkdir -p "$HOME/Desktop" "$HOME/workspace"; \
    cp /usr/share/applications/eclipse.desktop "$HOME/Desktop/Eclipse.desktop"; \
    chmod +x "$HOME/Desktop/Eclipse.desktop"; \
    chown -R 1000:0 "$HOME"

USER 1000
WORKDIR $HOME
