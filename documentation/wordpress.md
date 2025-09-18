# Application WordPress (Web + Base de données)

Cette fonctionnalité permet à chaque utilisateur de déployer une instance WordPress isolée avec sa base MariaDB dans son propre namespace Kubernetes géré par LabOnDemand.

## Vue d’ensemble

- Composants créés automatiquement:
  - Secret (mots de passe auto-générés)
  - PVC 1Gi pour la base de données
  - Service + Deployment MariaDB
  - Service + Deployment WordPress (image bitnami/wordpress)
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
- Images: `bitnami/wordpress:latest` (HTTP sur 8080), `bitnami/mariadb:latest`.
- Probes HTTP prêtes/vivantes configurées sur `/` port 8080 pour WordPress.
- Le Service WordPress respecte le type choisi (NodePort par défaut).
