# Stack LAMP (Apache + PHP + MySQL + phpMyAdmin)

Cette stack fournit un environnement LAMP prêt à l’emploi pour les travaux pratiques: un serveur web Apache+PHP, une base MySQL, et une interface phpMyAdmin. Elle est déployée et gérée automatiquement par LabOnDemand avec des bonnes pratiques de sécurité et de persistance.

## Composants déployés

- Secret Kubernetes: identifiants MySQL (générés si absent), réutilisés entre redéploiements
- MySQL (Deployment + Service ClusterIP)
- phpMyAdmin (Deployment + Service NodePort)
- Web Apache+PHP (Deployment + Service NodePort)
- Volumes:
  - DB: PVC 1Gi (best-effort; fallback emptyDir si StorageClass indisponible)
  - Web: PVC best-effort monté sur /var/www/html (fallback emptyDir)

## Accès et URLs

Une fois l’application prête, les détails du déploiement affichent plusieurs URLs:
- Web (Apache+PHP): http://<NODE_IP>:<NODE_PORT>/
- phpMyAdmin: http://<NODE_IP>:<NODE_PORT>/

Astuce: utilisez kubectl get svc -n <namespace> pour retrouver le NodePort si besoin.

## Identifiants & Secrets

- MySQL:
  - hôte: <name>-mysql-service (ClusterIP)
  - port: 3306
  - utilisateur: app_user
  - mot de passe: généré et stocké dans le Secret <name>-secret
  - base: app_db
- phpMyAdmin: se connecter avec les identifiants MySQL ci-dessus.

Les secrets sont idempotents: s’ils existent déjà, ils sont réutilisés et leurs labels sont corrigés au besoin.

## Sécurité

- Conteneur web non-root (runAsUser/runAsGroup), capabilities ALL drop + NET_BIND_SERVICE ajoutée, seccomp=RuntimeDefault
- Restrictions terminal: les étudiants ne peuvent pas ouvrir de terminal sur les pods de base de données
- Services exposés en NodePort par défaut; vous pouvez basculer vers un Ingress en prod

## Fichiers et contenu par défaut

Le pod web initialise un fichier index.php par défaut (style by makhal) via un initContainer si le volume est vide. Vous pouvez ensuite modifier les fichiers sous /var/www/html via le terminal web ou en déployant vos sources.

## Persistance

- Web: best-effort PVC monté à /var/www/html. Si aucune StorageClass par défaut n’est disponible, un emptyDir est utilisé (pas de persistance au redémarrage)
- DB: PVC 1Gi. Les paramètres de suppression contrôlent la conservation ou non des données (voir suppression ci-dessous)

## Suppression de la stack

La suppression via l’UI supprime les Deployments et Services. Par défaut, le Secret et le PVC de la DB peuvent être supprimés pour éviter les conflits lors d’une réinstallation (AlreadyExists). Un paramètre delete_persistent=false peut être fourni via l’API pour garder ces ressources.

## Dépannage

- Page web 403/404 au premier démarrage: attendez la fin de l’initContainer (création de index.php)
- Pas de persistance: vérifiez qu’une StorageClass par défaut est définie dans le cluster
- Terminal indisponible sur la DB: comportement attendu pour les rôles étudiants
- Performance terminal: WebGL est activé si possible; sinon, fallback canvas/DOM
