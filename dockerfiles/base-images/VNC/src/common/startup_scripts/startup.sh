#!/bin/bash
# Bureau distant LabOnDemand : Xvnc (TigerVNC) -> XFCE -> noVNC (websockify).
#
# Optimisations clés :
#  - redimensionnement automatique de l'écran à la taille du navigateur
#    (noVNC resize=remote + RandR intégré à Xvnc) ;
#  - mots de passe transmis via fichier (jamais visibles dans "ps") avec
#    support d'un mot de passe lecture seule (VNC_VIEW_ONLY_PW) ;
#  - presse-papiers partagé navigateur <-> bureau (vncconfig) ;
#  - attente des services au lieu de "sleep" arbitraires ;
#  - arrêt propre des processus enfant à la réception de SIGTERM (Kubernetes).
set -euo pipefail

# --- Configuration ------------------------------------------------------------
: "${VNC_RESOLUTION:=1600x900}"   # résolution initiale (s'adapte au navigateur)
: "${VNC_DEPTH:=24}"
: "${VNC_PW:=changeme}"
: "${VNC_VIEW_ONLY_PW:=}"         # mot de passe lecture seule (optionnel)
: "${NOVNC_PORT:=6901}"           # port web noVNC (HTTP + WebSocket)
DISPLAY_NUM="${DISPLAY_NUM:-1}"
RFB_PORT="$((5900 + DISPLAY_NUM))"  # port VNC classique (5901 par défaut)
NOVNC_ROOT="${NOVNC_ROOT:-/usr/share/novnc}"
PASSWD_FILE="${HOME}/.vnc/passwd"

export DISPLAY=":${DISPLAY_NUM}"

# --- Arrêt propre des processus enfant ----------------------------------------
cleanup() {
    trap - TERM INT EXIT
    kill 0 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup TERM INT EXIT

# --- Mots de passe VNC --------------------------------------------------------
# vncpasswd -f lit jusqu'à 2 mots de passe : contrôle total puis lecture seule.
mkdir -p "${HOME}/.vnc"
chmod 700 "${HOME}/.vnc"
if [ -n "${VNC_VIEW_ONLY_PW}" ]; then
    printf '%s\n%s\n' "${VNC_PW}" "${VNC_VIEW_ONLY_PW}" | vncpasswd -f > "${PASSWD_FILE}"
else
    printf '%s\n' "${VNC_PW}" | vncpasswd -f > "${PASSWD_FILE}"
fi
chmod 600 "${PASSWD_FILE}"

# --- Serveur X + VNC ----------------------------------------------------------
# +extension RANDR : noVNC peut redimensionner l'écran distant à la demande.
Xvnc ":${DISPLAY_NUM}" \
    -geometry "${VNC_RESOLUTION}" \
    -depth "${VNC_DEPTH}" \
    -rfbport "${RFB_PORT}" \
    -rfbauth "${PASSWD_FILE}" \
    -SecurityTypes VncAuth \
    -localhost no \
    -AlwaysShared \
    -DisconnectClients 0 \
    +extension RANDR \
    -desktop "LabOnDemand" &

# Attente de la socket X avant de lancer la session
for _ in $(seq 1 100); do
    [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ] && break
    sleep 0.1
done

# --- Bureau XFCE (avec session D-Bus) -----------------------------------------
dbus-launch --exit-with-session startxfce4 &

# --- Presse-papiers partagé navigateur <-> bureau -----------------------------
vncconfig -nowin &

# --- Pont web noVNC -----------------------------------------------------------
websockify --web="${NOVNC_ROOT}" "${NOVNC_PORT}" "localhost:${RFB_PORT}" &
WEBSOCKIFY_PID=$!

wait "${WEBSOCKIFY_PID}"
