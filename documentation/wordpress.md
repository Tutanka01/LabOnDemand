---
title: Application WordPress (Web + Base de données)
summary: Déploiement d'instances WordPress isolées par utilisateur avec MariaDB dans Kubernetes — composants créés, identifiants générés, accès NodePort et dépannage.
read_when: |
  - Tu travailles sur le backend de déploiement WordPress (routers, k8s_utils)
  - Tu veux connaître les identifiants générés ou l'URL d'accès à une instance WordPress
  - Tu dépannes un problème lié au pod WordPress ou MariaDB d'un utilisateur
---

# Application WordPress (Web + Base de données)

Cette fonctionnalité permet à chaque utilisateur de déployer une instance WordPress isolée avec sa base MariaDB dans son propre namespace Kubernetes géré par LabOnDemand.

## Vue d’ensemble

- Composants créés automatiquement:
  - Secret (mots de passe auto-générés)
  - PVC 1Gi pour la base de données
  - Service + Deployment MariaDB
  - Service + Deployment WordPress (image bitnamilegacy/wordpress:6.8.2-debian-12-r5)
- Accès par NodePort (par défaut): le port est assigné par Kubernetes, l’URL publique est visible dans les détails du déploiement (frontend) une fois prêt.
- Isolation par utilisateur: labels `managed-by=labondemand` et `user-id=<id>` + namespace dédié.

## Déploiement depuis l’interface

1. Ouvrez le catalogue et sélectionnez « WordPress (Web + DB) ».
2. Donnez un nom d’application (ex: `wp-<cours>-<votre-id>`).
3. Laissez le mode d’accès sur NodePort (recommandé) et validez.
4. Suivez l’état dans le tableau de bord. Quand l’app est prête, le bouton « Accéder » s’active.

## Identifiants générés

- Admin WordPress: `admin` / mot de passe unique (affiché côté backend dans le message de création et disponible via les détails du déploiement si exposé)
- Base de données:
  - hôte: `<name>-mariadb-service`
  - port: `3306`
  - utilisateur: `wp_user`
  - mot de passe: généré automatiquement
  - base: `wordpress`

Les secrets sont stockés dans un objet Secret Kubernetes nommé `<name>-secret` dans votre namespace.

Note sur la suppression: lorsque vous supprimez une stack WordPress via l'API de LabOnDemand, le Secret `<name>-secret` et le PVC de la base de données (`<name>-mariadb-pvc`) sont supprimés par défaut afin d'éviter les conflits lors d'une réinstallation (erreur AlreadyExists). Vous pouvez garder ces ressources persistantes en passant le paramètre de requête `delete_persistent=false` à l'endpoint de suppression.

Idempotence: si un Secret `<name>-secret` existe déjà (par exemple après une suppression partielle), le déploiement ne renverra plus d'erreur 409. Le Secret existant sera réutilisé et ses labels seront mis à jour si nécessaire.

## Ressources et persistance

- MariaDB utilise un `PersistentVolumeClaim` de 1Gi.
- WordPress et MariaDB sont déployés chacun dans un `Deployment` indépendant.
- Les ressources CPU/RAM utilisent les valeurs par défaut; ajustements possibles via RuntimeConfigs à l’avenir.

## Sécurité et permissions

- Étudiants, enseignants et admins peuvent créer WordPress si autorisé par la plateforme.
- Les labels garantissent l’isolation logique. Chaque utilisateur voit uniquement ses déploiements.

## Dépannage

- Si l’URL n’apparaît pas immédiatement, attendez que les pods passent à `Running` puis actualisez.
- Vérifiez les détails du déploiement pour voir les services et NodePort.
- En cas d’erreur Kubernetes (quota, storageclass), consultez les logs backend et la ressource créée.

## Suppression

- Depuis le tableau de bord, cliquez « Arrêter » sur l’application pour supprimer les déploiements WordPress et le service WordPress.
- Le PVC et le service DB seront supprimés uniquement si vous supprimez manuellement ces ressources (préservation des données). Ajout d’un bouton « suppression complète » pourra être envisagé.

---

Notes techniques:
- Images: `bitnamilegacy/wordpress:6.8.2-debian-12-r5` (HTTP sur 8080), `bitnamilegacy/mariadb:12.0.2-debian-12-r0`.
- Probes HTTP prêtes/vivantes configurées sur `/` port 8080 pour WordPress.
- Le Service WordPress respecte le type choisi (NodePort par défaut).
