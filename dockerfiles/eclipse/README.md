# Eclipse Java EE Desktop (LabOnDemand)

Bureau distant XFCE + **Eclipse IDE for Enterprise Java and Web Developers**
(Jakarta EE, JSP/Servlet, JPA, Web Tools Platform) accessible depuis le
navigateur via noVNC, sur la base VNC LabOnDemand
(`dockerfiles/base-images/VNC`, tag `tutanka01/labondemand:base-ubuntu24`).

## Contenu

| Composant | Version (par défaut) | Emplacement |
|-----------|----------------------|-------------|
| Eclipse IDE for Enterprise Java and Web Developers | 2026-06 R | `/opt/eclipse` (`eclipse`) |
| Oracle JDK | 25 | `/usr/lib/jvm/oracle-jdk-25` |
| Apache Maven | 3.9.16 | `/opt/maven` (`mvn`) |
| Gradle | 9.7.1 | `/opt/gradle` (`gradle`) |
| Apache Tomcat | 10.0.27 (`TOMCAT_VERSION`) | `/opt/tomcat` (`labondemand-tomcat start|stop|status`) |
| MariaDB (compatible MySQL) | paquet Ubuntu 24.04 | données dans `~/.local/share/labondemand/mariadb` |
| PostgreSQL | paquet Ubuntu 24.04 | données dans `~/.local/share/labondemand/postgresql` |
| Pilotes JDBC MariaDB / PostgreSQL | 3.5.10 / 42.7.13 | `/opt/jdbc` et `/opt/tomcat/lib` |
| Navigateur | Firefox (base VNC) | menu Applications |

## Services de développement

Au démarrage du conteneur, `startup-eclipse.sh` initialise (première fois) puis
lance **MariaDB** et **PostgreSQL** ; les données sont dans le home persistant
(PVC), donc conservées entre les redémarrages. Tomcat n'est **pas** lancé
automatiquement pour ne pas entrer en conflit avec l'instance gérée par Eclipse
WTP (port 8080) : le Tomcat autonome écoute sur **8081**.

| Service | Adresse | Compte | Mot de passe |
|---------|---------|--------|--------------|
| MariaDB (MySQL) | `localhost:3306`, base `tp` | `etudiant` | `etudiant` |
| MariaDB root | socket `~/.local/share/labondemand/run/mysqld.sock` | `root` | *(vide)* |
| PostgreSQL | `localhost:5432`, base `tp` | `etudiant` | `etudiant` |
| PostgreSQL superuser | `localhost:5432` | `postgres` | `postgres` |
| Tomcat autonome | http://localhost:8081 | — | — |

URLs JDBC :

```
jdbc:mariadb://localhost:3306/tp
jdbc:mysql://localhost:3306/tp          (pilote MariaDB, compatible)
jdbc:postgresql://localhost:5432/tp
```

Dans Eclipse : `Window > Preferences > Server > Runtime Environments > Add >
Apache Tomcat v10.0` puis pointer sur `/opt/tomcat` (`Run on Server`, port 8080).
L'application web déployée est aussi joignable depuis l'extérieur sur le
NodePort « tomcat » du lab (voir la fiche du déploiement).

## Mémoire et heap JVM

Le conteneur est limité à **4 Gi** par le RuntimeConfig Eclipse
(`backend/templates.py` / `backend/seed.py`). Le heap Eclipse n'est pas figé :
`eclipse.ini` utilise `-XX:MaxRAMPercentage=50` (→ 2 Gi de heap sur 4 Gi) et
`-XX:MaxMetaspaceSize=512m`. Un `-Xmx` en dur ferait ignorer `MaxRAMPercentage`
et dépasserait la limite du conteneur (OOMKilled / exit 137).

Les JVM auxiliaires sont bornées pour ne pas consommer la marge restante :

| Outil | Variable / fichier | Valeur |
|-------|--------------------|--------|
| Eclipse | `eclipse.ini` | `MaxRAMPercentage=50`, `MaxMetaspaceSize=512m` |
| Maven | `MAVEN_OPTS` | `-Xmx512m -XX:MaxMetaspaceSize=256m` |
| Gradle client | `GRADLE_OPTS` | `-Xmx512m` |
| Gradle daemon | `~/.gradle/gradle.properties` | `org.gradle.jvmargs=-Xmx512m -XX:MaxMetaspaceSize=256m` |
| Tomcat | `bin/setenv.sh` | `-Xmx512m -XX:MaxMetaspaceSize=256m` |
| MariaDB | démarrage | `--innodb-buffer-pool-size=64M` |

## Construction

Le cluster est en amd64 : construire avec buildx et pousser directement.

```bash
# 1. (une fois) Construire et publier la base VNC
docker buildx build --platform linux/amd64 \
  -t tutanka01/labondemand:base-ubuntu24 --push dockerfiles/base-images/VNC

# 2. Construire l'image Eclipse Java EE. IMPORTANT : utiliser un tag daté
#    immuable, sinon les nœuds gardent l'ancienne image en cache
#    (imagePullPolicy IfNotPresent) et ne re-téléchargent jamais le contenu.
TAG=eclipsejava-ee-$(date +%Y%m%d)
docker buildx build --platform linux/amd64 --pull \
  -t tutanka01/labondemand:$TAG \
  -t tutanka01/labondemand:eclipsejava \
  --push dockerfiles/eclipse
```

Après publication : mettre à jour `ECLIPSE_IMAGE` dans `backend/templates.py` et
`default_image` dans `backend/seed.py` avec le nouveau tag daté, puis redémarrer
l'API (le seed relève les planchers et migre les anciens tags au démarrage).

Versions surchargeables :

```bash
docker buildx build --platform linux/amd64 \
  --build-arg ECLIPSE_PACKAGE=eclipse-jee \
  --build-arg ECLIPSE_VERSION=2026-06 --build-arg TOMCAT_VERSION=10.0.27 \
  --build-arg MAVEN_VERSION=3.9.16 --build-arg GRADLE_VERSION=9.7.1 \
  -t tutanka01/labondemand:eclipsejava-ee-20260922 --push dockerfiles/eclipse
```

> Tomcat 10.0.x n'est plus maintenu en amont (fin de vie) ; la version est
> demandée par les TP. Pour passer à une version maintenue, surcharger
> `--build-arg TOMCAT_VERSION=10.1.x` (Jakarta EE 10) et vérifier les projets.

## Exécution locale (test)

```bash
docker run --rm -p 6901:6901 -p 8080:8080 -p 8081:8081 \
  -e VNC_PW=secret tutanka01/labondemand:eclipsejava-ee-20260922
# puis ouvrir http://localhost:6901/ (connexion automatique, resize automatique)
```

| Port | Usage |
|------|-------|
| 6901 | noVNC (HTTP + WebSocket) |
| 5901 | VNC classique (optionnel) |
| 8080 | Application web (instance Tomcat d'Eclipse WTP) — exposé en NodePort par LabOnDemand |
| 8081 | Tomcat autonome |
| 3306 / 5432 | MariaDB / PostgreSQL (locaux au conteneur, non exposés) |

Variables : `VNC_PW` (mot de passe), `VNC_VIEW_ONLY_PW` (accès lecture seule),
`VNC_RESOLUTION` (résolution initiale, défaut `1600x900`).
