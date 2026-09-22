# Eclipse Desktop (LabOnDemand)

Bureau distant XFCE + **Eclipse IDE for Java Developers** accessible depuis le
navigateur via noVNC, sur la base VNC LabOnDemand
(`dockerfiles/base-images/VNC`, tag `tutanka01/labondemand:base-ubuntu24`).

## Contenu

| Composant | Version (par défaut) | Emplacement |
|-----------|----------------------|-------------|
| Eclipse IDE for Java | 2026-06 R | `/opt/eclipse` (`eclipse`) |
| Oracle JDK | 25 | `/usr/lib/jvm/jdk-25-oracle-x64` |
| Apache Maven | 3.9.16 | `/opt/maven` (`mvn`) |
| Gradle | 9.7.1 | `/opt/gradle` (`gradle`) |

En plus du bureau de la base : Firefox, Git, éditeur de texte, archiveurs.
L'écran suit automatiquement la taille de la fenêtre du navigateur.

## Construction

```bash
# 1. (une fois) Construire et publier la base VNC
docker build -t tutanka01/labondemand:base-ubuntu24 dockerfiles/base-images/VNC

# 2. Construire l'image Eclipse
docker build -t tutanka01/labondemand:eclipsejava dockerfiles/eclipse
```

Versions surchargeables :

```bash
docker build -t tutanka01/labondemand:eclipsejava \
  --build-arg ECLIPSE_VERSION=2026-06 --build-arg MAVEN_VERSION=3.9.16 \
  --build-arg GRADLE_VERSION=9.7.1 dockerfiles/eclipse
```

## Exécution locale (test)

```bash
docker run --rm -p 6901:6901 -e VNC_PW=secret tutanka01/labondemand:eclipsejava
# puis ouvrir http://localhost:6901/ (connexion automatique, resize automatique)
```

| Port | Usage |
|------|-------|
| 6901 | noVNC (HTTP + WebSocket) |
| 5901 | VNC classique (optionnel) |

Variables : `VNC_PW` (mot de passe), `VNC_VIEW_ONLY_PW` (accès lecture seule),
`VNC_RESOLUTION` (résolution initiale, défaut `1600x900`).
