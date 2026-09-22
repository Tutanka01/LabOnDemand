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

## Mémoire et heap JVM

Le conteneur est limité à **3 Gi** par le RuntimeConfig Eclipse
(`backend/templates.py` / `backend/seed.py`). Le heap Eclipse n'est pas figé :
`eclipse.ini` utilise `-XX:MaxRAMPercentage=50` (→ 1,5 Gi de heap sur 3 Gi) et
`-XX:MaxMetaspaceSize=512m`. Un `-Xmx` en dur ferait ignorer `MaxRAMPercentage`
et dépasserait la limite du conteneur (OOMKilled / exit 137).

Les JVM auxiliaires sont bornées pour ne pas consommer la marge restante :

| Outil | Variable / fichier | Valeur |
|-------|--------------------|--------|
| Eclipse | `eclipse.ini` | `MaxRAMPercentage=50`, `MaxMetaspaceSize=512m` |
| Maven | `MAVEN_OPTS` | `-Xmx512m -XX:MaxMetaspaceSize=256m` |
| Gradle client | `GRADLE_OPTS` | `-Xmx512m` |
| Gradle daemon | `~/.gradle/gradle.properties` | `org.gradle.jvmargs=-Xmx512m -XX:MaxMetaspaceSize=256m` |

## Construction

Le cluster est en amd64 : construire avec buildx et pousser directement.

```bash
# 1. (une fois) Construire et publier la base VNC
docker buildx build --platform linux/amd64 \
  -t tutanka01/labondemand:base-ubuntu24 --push dockerfiles/base-images/VNC

# 2. Construire l'image Eclipse. IMPORTANT : utiliser un tag daté immuable,
#    sinon les nœuds gardent l'ancienne image en cache (imagePullPolicy
#    IfNotPresent) et ne re-téléchargent jamais le nouveau contenu.
TAG=eclipsejava-$(date +%Y%m%d)
docker buildx build --platform linux/amd64 --pull \
  -t tutanka01/labondemand:$TAG \
  -t tutanka01/labondemand:eclipsejava \
  --push dockerfiles/eclipse
```

Après publication : mettre à jour `ECLIPSE_IMAGE` dans `backend/templates.py` et
`default_image` dans `backend/seed.py` avec le nouveau tag daté, puis redémarrer
l'API (le seed relève les planchers et migre l'ancien tag au démarrage).

Versions surchargeables :

```bash
docker buildx build --platform linux/amd64 \
  --build-arg ECLIPSE_VERSION=2026-06 --build-arg MAVEN_VERSION=3.9.16 \
  --build-arg GRADLE_VERSION=9.7.1 \
  -t tutanka01/labondemand:eclipsejava-20260922 --push dockerfiles/eclipse
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
