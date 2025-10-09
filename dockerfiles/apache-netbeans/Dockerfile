FROM tutanka01/labondemand:base-ubuntu24

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root

ARG PROXY_URL=http://cache.univ-pau.fr:3128

ENV HOME=/home/kasm-default-profile \
    STARTUPDIR=/dockerstartup \
    INST_SCRIPTS=/dockerstartup/install \
    PROXY_URL=${PROXY_URL} \
    http_proxy=${PROXY_URL} \
    https_proxy=${PROXY_URL} \
    HTTP_PROXY=${PROXY_URL} \
    HTTPS_PROXY=${PROXY_URL} \
    all_proxy=${PROXY_URL} \
    ALL_PROXY=${PROXY_URL} \
    ftp_proxy=${PROXY_URL} \
    FTP_PROXY=${PROXY_URL} \
    no_proxy=localhost,127.0.0.1,::1 \
    NO_PROXY=localhost,127.0.0.1,::1

WORKDIR $HOME

# Configuration proxy pour apt et wget
RUN set -eux; \
    printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\nAcquire::ftp::Proxy "%s";\n' "$PROXY_URL" "$PROXY_URL" "$PROXY_URL" >/etc/apt/apt.conf.d/80proxy; \
    printf 'use_proxy=yes\nhttp_proxy=%s\nhttps_proxy=%s\nftp_proxy=%s\n' "$PROXY_URL" "$PROXY_URL" "$PROXY_URL" >/etc/wgetrc

# Paramètres d'installation NetBeans (le paquet inclut un JDK mais nous installerons Oracle JDK 25 séparément)
ARG NB_VERSION=27-1
ARG NB_DEB_URL=https://github.com/Friends-of-Apache-NetBeans/netbeans-installers/releases/download/v27-build1/apache-netbeans_27-1_amd64.deb
ARG NB_DEB_SHA256=""

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
    tmp_deb="/tmp/netbeans_${NB_VERSION}.deb"; \
    wget -q "${NB_DEB_URL}" -O "$tmp_deb"; \
    if [ -n "${NB_DEB_SHA256}" ]; then echo "${NB_DEB_SHA256}  $tmp_deb" | sha256sum -c -; fi; \
    apt-get install -y --no-install-recommends "$tmp_deb"; \
    rm -f "$tmp_deb"; \
    rm -rf /var/lib/apt/lists/*

# Configurer le proxy pour Apache NetBeans
RUN set -eux; \
    conf_file="/usr/share/netbeans/etc/netbeans.conf"; \
    proxy_host_port="${PROXY_URL#*://}"; \
    proxy_host="${proxy_host_port%%:*}"; \
    proxy_port="${proxy_host_port##*:}"; \
    mkdir -p "$(dirname "$conf_file")"; \
    if [ ! -f "$conf_file" ]; then \
        echo '# NetBeans configuration file' > "$conf_file"; \
        echo 'netbeans_default_options="-J-client -J-Xss2m -J-Xms32m -J-Dapple.laf.useScreenMenuBar=true -J-Dapple.awt.graphics.UseQuartz=true -J-Dsun.java2d.noddraw=true -J-Dsun.zip.disableMemoryMapping=true"' >> "$conf_file"; \
    fi; \
    grep -q "http.proxyHost" "$conf_file" || \
    printf '\n# Proxy configuration ajoutée via Docker build\nnetbeans_default_options="$netbeans_default_options \\\\n  -J-Djava.net.useSystemProxies=true \\\\n  -J-Dhttp.proxyHost=%s \\\\n  -J-Dhttp.proxyPort=%s \\\\n  -J-Dhttps.proxyHost=%s \\\\n  -J-Dhttps.proxyPort=%s \\\\n  -J-Dhttp.nonProxyHosts=localhost\\\\|127.0.0.1\\\\|::1"\n' \
        "$proxy_host" "$proxy_port" "$proxy_host" "$proxy_port" >>"$conf_file"

# Installer Oracle JDK 25
RUN set -euxo pipefail; \
    apt-get update; \
    tmp_jdk_deb="/tmp/oracle-jdk25.deb"; \
    wget -q "${ORACLE_JDK_DEB_URL}" -O "$tmp_jdk_deb"; \
    if [ -n "${ORACLE_JDK_DEB_SHA256}" ]; then echo "${ORACLE_JDK_DEB_SHA256}  $tmp_jdk_deb" | sha256sum -c -; fi; \
    apt-get install -y --no-install-recommends "$tmp_jdk_deb"; \
    rm -f "$tmp_jdk_deb"; \
    ln -s /usr/lib/jvm/jdk-25-oracle-x64 /usr/lib/jvm/jdk-25; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/jdk-25-oracle-x64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Desktop integration
RUN cat >/usr/share/applications/netbeans.desktop <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Apache NetBeans 27
Comment=Apache NetBeans IDE
Exec=/usr/bin/netbeans
Icon=/usr/share/netbeans/nb/netbeans.png
Terminal=false
Categories=Development;IDE;Java;
StartupWMClass=netbeans
EOF

# Copier le raccourci sur le Desktop du profil par défaut
RUN mkdir -p "$HOME/Desktop" \
    && cp /usr/share/applications/netbeans.desktop "$HOME/Desktop/Apache NetBeans.desktop"

# Exemple de fichier custom
RUN touch "$HOME/Desktop/hello.txt"

# Permissions
#RUN chown 1000:0 $HOME && $STARTUPDIR/set_user_permission.sh $HOME

# Passer à l’utilisateur final
ENV HOME=/home/uppa-user
WORKDIR $HOME
RUN mkdir -p $HOME && chown -R 1000:0 $HOME

USER 1000