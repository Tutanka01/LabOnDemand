# LabOnDemand - Bureau distant Java EE : Eclipse for Enterprise Java and Web
# Developers + Tomcat + MariaDB/PostgreSQL, sur la base VNC (XFCE + TigerVNC +
# noVNC avec redimensionnement auto de l'écran selon la fenêtre du navigateur).
FROM tutanka01/labondemand:base-ubuntu24

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER root

ENV HOME=/home/lod-user \
    STARTUPDIR=/dockerstartup \
    INST_SCRIPTS=/dockerstartup/install

WORKDIR $HOME

# --- Versions (surchargeables avec --build-arg) -------------------------------
# Eclipse IDE for Enterprise Java and Web Developers (Jakarta EE, JSP/Servlet,
# JPA, Web Tools Platform), JDK Oracle 25, Maven, Gradle, Tomcat 10.0,
# serveurs MariaDB (MySQL) et PostgreSQL locaux, pilotes JDBC.
ARG ECLIPSE_PACKAGE=eclipse-jee
ARG ECLIPSE_VERSION=2026-06
ARG ECLIPSE_BUILD=R
ARG ECLIPSE_SHA512=""
ARG ORACLE_JDK_DEB_URL=https://download.oracle.com/java/25/latest/jdk-25_linux-x64_bin.deb
ARG ORACLE_JDK_DEB_SHA256=""
ARG MAVEN_VERSION=3.9.16
ARG GRADLE_VERSION=9.7.1
ARG TOMCAT_VERSION=10.0.27
ARG TOMCAT_SHA512=""
ARG MARIADB_JDBC_VERSION=3.5.10
ARG POSTGRESQL_JDBC_VERSION=42.7.13

ENV JAVA_HOME=/usr/lib/jvm/oracle-jdk-25 \
    ECLIPSE_HOME=/opt/eclipse \
    MAVEN_HOME=/opt/maven \
    GRADLE_HOME=/opt/gradle \
    TOMCAT_HOME=/opt/tomcat \
    CATALINA_HOME=/opt/tomcat \
    JDBC_DRIVERS_DIR=/opt/jdbc
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

# --- SGBD locaux : MariaDB (compatible MySQL) + PostgreSQL --------------------
# Les serveurs ne sont pas lancés à la construction (policy-rc.d bloque les
# services) : le script de démarrage les initialise dans le home persistant.
RUN set -euxo pipefail; \
    printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; \
    chmod +x /usr/sbin/policy-rc.d; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        mariadb-server mariadb-client postgresql postgresql-client; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/lib/postgresql/*/main /var/lib/mysql

# --- Eclipse IDE for Enterprise Java and Web Developers -----------------------
RUN set -euxo pipefail; \
    eclipse_archive="/tmp/eclipse.tar.gz"; \
    eclipse_url="https://download.eclipse.org/technology/epp/downloads/release/${ECLIPSE_VERSION}/${ECLIPSE_BUILD}/${ECLIPSE_PACKAGE}-${ECLIPSE_VERSION}-${ECLIPSE_BUILD}-linux-gtk-x86_64.tar.gz"; \
    wget -q "${eclipse_url}" -O "$eclipse_archive"; \
    if [ -n "${ECLIPSE_SHA512}" ]; then echo "${ECLIPSE_SHA512}  $eclipse_archive" | sha512sum -c -; fi; \
    tar -xzf "$eclipse_archive" -C /opt; \
    rm -f "$eclipse_archive"; \
    ln -sf "${ECLIPSE_HOME}/eclipse" /usr/local/bin/eclipse; \
    # Utiliser le JDK 25 (et non le JRE JustJ embarqué). Le heap n'est pas figé ici :
    # -XX:MaxRAMPercentage fait calculer -Xmx par le JVM d'après la limite mémoire du
    # conteneur (50 % -> 2 Gi de heap sur la limite de 4 Gi du RuntimeConfig, la
    # marge restante allant à Xvnc + XFCE + Firefox + Tomcat + MariaDB/PostgreSQL).
    # Un -Xmx en dur dépassait la limite -> OOMKilled (137). La présence d'un -Xmx
    # explicite ferait ignorer MaxRAMPercentage, donc on retire tout -Xm[sx] hérité
    # de l'ini d'origine.
    # MaxMetaspaceSize borne le métaspace (plugins JDT/WTP) pour qu'il ne puisse pas
    # ronger la marge native du conteneur.
    ini="${ECLIPSE_HOME}/eclipse.ini"; \
    awk 'BEGIN { skip=0; done=0 } \
        skip { skip=0; next } \
        /^-vm$/ { if (!done) { print "-vm"; print "'"${JAVA_HOME}"'/bin"; done=1 }; skip=1; next } \
        /^-vmargs/ && !done { print "-vm"; print "'"${JAVA_HOME}"'/bin"; done=1 } \
        { print }' "$ini" > "$ini.new"; \
    mv "$ini.new" "$ini"; \
    sed -i -E '/^-Xm[sx]/d; /^-XX:MaxRAMPercentage/d; /^-XX:MaxMetaspaceSize/d' "$ini"; \
    printf '%s\n' '-Xms256m' '-XX:MaxRAMPercentage=50' '-XX:MaxMetaspaceSize=512m' '-Dfile.encoding=UTF-8' >> "$ini"
# --- Apache Maven ------------------------------------------------------------
RUN set -euxo pipefail; \
    tmp_maven="/tmp/maven.tar.gz"; \
    wget -q "https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" -O "$tmp_maven"; \
    tar -xzf "$tmp_maven" -C /opt; \
    rm -f "$tmp_maven"; \
    ln -s "/opt/apache-maven-${MAVEN_VERSION}" "${MAVEN_HOME}"; \
    ln -sf "${MAVEN_HOME}/bin/mvn" /usr/local/bin/mvn

# Borne la JVM Maven : sans cela, un `mvn package` ajoute une JVM non plafonnée
# à côté d'Eclipse et peut faire dépasser la limite mémoire du conteneur.
ENV MAVEN_OPTS="-Xmx512m -XX:MaxMetaspaceSize=256m"

# --- Gradle ------------------------------------------------------------------
RUN set -euxo pipefail; \
    tmp_gradle="/tmp/gradle.zip"; \
    wget -q "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" -O "$tmp_gradle"; \
    unzip -q "$tmp_gradle" -d /opt; \
    rm -f "$tmp_gradle"; \
    ln -s "/opt/gradle-${GRADLE_VERSION}" "${GRADLE_HOME}"; \
    ln -sf "${GRADLE_HOME}/bin/gradle" /usr/local/bin/gradle

# Même logique que Maven pour Gradle : borne la JVM cliente (GRADLE_OPTS) et le
# daemon (org.gradle.jvmargs). Le daemon garde la même limite haute, il ne peut
# donc pas manger la marge d'Eclipse + Firefox. Écrit dans le profil par défaut,
# recopié dans le home persistant au premier démarrage (seed-home).
ENV GRADLE_OPTS="-Xmx512m -Dorg.gradle.jvmargs=-Xmx512m"
RUN mkdir -p "$HOME/.gradle"; \
    printf '%s\n' 'org.gradle.jvmargs=-Xmx512m -XX:MaxMetaspaceSize=256m' > "$HOME/.gradle/gradle.properties"; \
    chown -R 1000:0 "$HOME/.gradle"

# --- Apache Tomcat 10.0 ------------------------------------------------------
# Tomcat autonome sur 8081 : l'instance gérée par Eclipse WTP (Run on Server)
# utilise 8080, exposée par LabOnDemand. Les deux peuvent tourner ensemble.
RUN set -euxo pipefail; \
    tomcat_archive="/tmp/tomcat.tar.gz"; \
    wget -q "https://archive.apache.org/dist/tomcat/tomcat-10/v${TOMCAT_VERSION}/bin/apache-tomcat-${TOMCAT_VERSION}.tar.gz" -O "$tomcat_archive"; \
    if [ -n "${TOMCAT_SHA512}" ]; then echo "${TOMCAT_SHA512}  $tomcat_archive" | sha512sum -c -; fi; \
    tar -xzf "$tomcat_archive" -C /opt; \
    rm -f "$tomcat_archive"; \
    ln -sfn "/opt/apache-tomcat-${TOMCAT_VERSION}" "${TOMCAT_HOME}"; \
    sed -i 's/port="8080"/port="8081"/' "${TOMCAT_HOME}/conf/server.xml"; \
    printf '%s\n' \
        'export CATALINA_OPTS="$CATALINA_OPTS -Xmx512m -XX:MaxMetaspaceSize=256m"' \
        'export CATALINA_PID="/tmp/tomcat.pid"' > "${TOMCAT_HOME}/bin/setenv.sh"; \
    chmod +x "${TOMCAT_HOME}/bin/setenv.sh"; \
    # L'archive Tomcat crée des répertoires en 750 root:root : lod-user doit
    # pouvoir écrire dans logs/temp/work/webapps et exécuter bin/.
    chown -R 1000:0 "/opt/apache-tomcat-${TOMCAT_VERSION}"

# --- Pilotes JDBC MySQL/MariaDB + PostgreSQL ----------------------------------
# Disponibles dans /opt/jdbc (à ajouter au Build Path dans Eclipse) et déjà
# présents dans /opt/tomcat/lib (utilisables par les applications déployées).
RUN set -euxo pipefail; \
    mkdir -p "${JDBC_DRIVERS_DIR}"; \
    wget -q "https://repo1.maven.org/maven2/org/mariadb/jdbc/mariadb-java-client/${MARIADB_JDBC_VERSION}/mariadb-java-client-${MARIADB_JDBC_VERSION}.jar" \
        -O "${JDBC_DRIVERS_DIR}/mariadb-java-client-${MARIADB_JDBC_VERSION}.jar"; \
    wget -q "https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRESQL_JDBC_VERSION}/postgresql-${POSTGRESQL_JDBC_VERSION}.jar" \
        -O "${JDBC_DRIVERS_DIR}/postgresql-${POSTGRESQL_JDBC_VERSION}.jar"; \
    cp "${JDBC_DRIVERS_DIR}"/*.jar "${TOMCAT_HOME}/lib/"; \
    chmod 644 "${JDBC_DRIVERS_DIR}"/*.jar

# --- Lanceur Tomcat (autonome, port 8081) -------------------------------------
RUN cat > /usr/local/bin/labondemand-tomcat <<'EOF'
#!/bin/bash
set -euo pipefail
PID_FILE="/tmp/tomcat.pid"
is_running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }
case "${1:-}" in
  start)
    if is_running; then echo "Tomcat est déjà démarré : http://localhost:8081"; exit 0; fi
    /opt/tomcat/bin/startup.sh >/dev/null
    echo "Tomcat démarré : http://localhost:8081 (déposez vos WAR dans /opt/tomcat/webapps)"
    ;;
  stop)
    /opt/tomcat/bin/shutdown.sh >/dev/null 2>&1 || true
    echo "Tomcat arrêté."
    ;;
  status)
    if is_running; then echo "Tomcat en cours : http://localhost:8081"; else echo "Tomcat arrêté."; fi
    ;;
  *) echo "Usage: labondemand-tomcat {start|stop|status}"; exit 2 ;;
esac
EOF
RUN chmod +x /usr/local/bin/labondemand-tomcat

# --- Intégration bureau ------------------------------------------------------
RUN cat > /usr/share/applications/eclipse.desktop <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Eclipse IDE for Enterprise Java and Web Developers
Comment=Eclipse IDE for Enterprise Java and Web Developers ${ECLIPSE_VERSION}
Exec=/usr/local/bin/eclipse
Icon=${ECLIPSE_HOME}/icon.xpm
Terminal=false
Categories=Development;IDE;Java;
StartupWMClass=eclipse
EOF

RUN cat > /usr/share/applications/labondemand-tomcat-start.desktop <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Démarrer Tomcat 10
Comment=Tomcat autonome sur http://localhost:8081 (WAR dans /opt/tomcat/webapps)
Exec=/usr/local/bin/labondemand-tomcat start
Icon=applications-internet
Terminal=true
Categories=Development;
EOF

RUN cat > /usr/share/applications/labondemand-tomcat-stop.desktop <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Arrêter Tomcat 10
Comment=Arrêter le Tomcat autonome (port 8081)
Exec=/usr/local/bin/labondemand-tomcat stop
Icon=applications-internet
Terminal=true
Categories=Development;
EOF

# Raccourcis sur le menu et sur le Bureau du profil utilisateur par défaut
RUN mkdir -p "$HOME/Desktop" "$HOME/workspace"; \
    cp /usr/share/applications/eclipse.desktop "$HOME/Desktop/Eclipse.desktop"; \
    chmod +x "$HOME/Desktop/Eclipse.desktop"; \
    chown -R 1000:0 "$HOME"

# Script d'entrée : initialise/démarre MariaDB + PostgreSQL dans le home
# persistant, copie les raccourcis manquants, puis lance le bureau VNC.
COPY startup-eclipse.sh /usr/local/bin/startup-eclipse.sh
RUN chmod +x /usr/local/bin/startup-eclipse.sh

USER 1000
WORKDIR $HOME

ENTRYPOINT [ "/usr/local/bin/startup-eclipse.sh" ]
