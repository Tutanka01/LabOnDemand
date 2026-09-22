#!/bin/bash
# LabOnDemand - Eclipse Java EE : démarre les services de développement
# (MariaDB, PostgreSQL) puis le bureau VNC (Xvnc + XFCE + noVNC).
#
# Les données sont stockées dans le home persistant (~/.local/share/labondemand),
# monté sur le PVC utilisateur : elles survivent aux redémarrages du lab.
# Les serveurs sont initialisés au premier démarrage, puis simplement relancés.
# Un échec SGBD n'empêche jamais le bureau de démarrer (dégradation contrôlée).
set -euo pipefail

DATA_ROOT="${HOME}/.local/share/labondemand"
RUN_DIR="${DATA_ROOT}/run"
LOG_DIR="${DATA_ROOT}/logs"
MARIADB_DATA="${DATA_ROOT}/mariadb"
MARIADB_CNF="${DATA_ROOT}/mariadb.cnf"
POSTGRES_DATA="${DATA_ROOT}/postgresql"
mkdir -p "${RUN_DIR}" "${LOG_DIR}" "${MARIADB_DATA}" "${POSTGRES_DATA}"

# --- MariaDB (compatible MySQL, port 3306) -----------------------------------
# Fichier de configuration dédié : --defaults-file ignore la configuration
# Debian (datadir /run/mysqld, user=mysql) inadaptée à un conteneur non-root.
cat > "${MARIADB_CNF}" <<EOF
[mariadbd]
datadir=${MARIADB_DATA}
socket=${RUN_DIR}/mysqld.sock
pid-file=${RUN_DIR}/mysqld.pid
port=3306
bind-address=127.0.0.1
innodb_buffer_pool_size=64M
skip_name_resolve

[client]
socket=${RUN_DIR}/mysqld.sock
EOF

# Initialisation unique du répertoire de données (compte root sans mot de passe,
# usage local uniquement : le conteneur est dédié à un seul utilisateur).
if [ ! -d "${MARIADB_DATA}/mysql" ]; then
    echo "[labondemand] Initialisation de MariaDB..."
    mariadb-install-db \
        --defaults-file="${MARIADB_CNF}" \
        --datadir="${MARIADB_DATA}" \
        --auth-root-authentication-method=normal \
        --skip-test-db >"${LOG_DIR}/mariadb-init.log" 2>&1 || \
        echo "[labondemand] ERREUR initialisation MariaDB (voir ${LOG_DIR}/mariadb-init.log)"
fi

if ! mariadb-admin --defaults-file="${MARIADB_CNF}" -u root ping >/dev/null 2>&1; then
    echo "[labondemand] Démarrage de MariaDB..."
    nohup mariadbd --defaults-file="${MARIADB_CNF}" \
        >"${LOG_DIR}/mariadb.log" 2>&1 &
    for _ in $(seq 1 60); do
        mariadb-admin --defaults-file="${MARIADB_CNF}" -u root ping >/dev/null 2>&1 && break
        sleep 0.5
    done
fi

# Base de TP et compte applicatif (idempotent).
mariadb --defaults-file="${MARIADB_CNF}" -u root >/dev/null 2>&1 <<'SQL' || true
CREATE DATABASE IF NOT EXISTS tp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'etudiant'@'localhost' IDENTIFIED BY 'etudiant';
CREATE USER IF NOT EXISTS 'etudiant'@'127.0.0.1' IDENTIFIED BY 'etudiant';
GRANT ALL PRIVILEGES ON *.* TO 'etudiant'@'localhost' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON *.* TO 'etudiant'@'127.0.0.1' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL

# --- PostgreSQL (port 5432) --------------------------------------------------
PG_BIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort | tail -1)"
if [ -n "${PG_BIN}" ]; then
    # Connexions locales en trust (socket), connexions TCP avec mot de passe.
    if [ ! -f "${POSTGRES_DATA}/PG_VERSION" ]; then
        echo "[labondemand] Initialisation de PostgreSQL..."
        "${PG_BIN}/initdb" -D "${POSTGRES_DATA}" -U postgres \
            --encoding=UTF8 --auth-local=trust --auth-host=scram-sha-256 \
            >"${LOG_DIR}/postgresql-init.log" 2>&1 || \
            echo "[labondemand] ERREUR initialisation PostgreSQL (voir ${LOG_DIR}/postgresql-init.log)"
    fi

    if ! "${PG_BIN}/pg_ctl" -D "${POSTGRES_DATA}" status >/dev/null 2>&1; then
        echo "[labondemand] Démarrage de PostgreSQL..."
        "${PG_BIN}/pg_ctl" -D "${POSTGRES_DATA}" -l "${LOG_DIR}/postgresql.log" \
            -o "-p 5432 -h 127.0.0.1 -k ${RUN_DIR}" -w start >/dev/null 2>&1 || true
    fi

    PSQL=( "${PG_BIN}/psql" -h "${RUN_DIR}" -p 5432 -U postgres -d postgres -qtA )
    "${PSQL[@]}" -c "ALTER USER postgres PASSWORD 'postgres';" >/dev/null 2>&1 || true
    if ! "${PSQL[@]}" -c "SELECT 1 FROM pg_roles WHERE rolname='etudiant'" 2>/dev/null | grep -q 1; then
        "${PSQL[@]}" -c "CREATE ROLE etudiant LOGIN PASSWORD 'etudiant' SUPERUSER;" >/dev/null 2>&1 || true
    fi
    if ! "${PSQL[@]}" -c "SELECT 1 FROM pg_database WHERE datname='tp'" 2>/dev/null | grep -q 1; then
        "${PSQL[@]}" -c "CREATE DATABASE tp OWNER etudiant;" >/dev/null 2>&1 || true
    fi
else
    echo "[labondemand] PostgreSQL introuvable, service ignoré."
fi

# --- Raccourcis bureau (couvre aussi les PVC déjà initialisés) ----------------
mkdir -p "${HOME}/Desktop"
copy_shortcut() {
    local src="/usr/share/applications/$1" dst="${HOME}/Desktop/$2"
    if [ -f "${src}" ] && [ ! -f "${dst}" ]; then
        cp "${src}" "${dst}"
        chmod +x "${dst}"
    fi
}
copy_shortcut eclipse.desktop "Eclipse.desktop"
copy_shortcut labondemand-tomcat-start.desktop "Démarrer Tomcat 10.desktop"
copy_shortcut labondemand-tomcat-stop.desktop "Arrêter Tomcat 10.desktop"

# Laisse la main au script du bureau VNC (Xvnc, XFCE, noVNC).
exec bash /dockerstartup/startup.sh
