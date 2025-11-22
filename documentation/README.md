# Documentation LabOnDemand

Ce fichier est le point d'entrée unique pour la documentation du projet. Il donne la marche à suivre pour lancer LabOnDemand en local et réoriente vers les guides spécialisés.

## Démarrage express (≈10 minutes)

1. **Prérequis**
   - Docker Desktop + Docker Compose Plugin
   - `kubectl` pointant vers votre cluster (k3s, kind, Minikube, ou cluster distant)
   - Helm (requis si vous devez installer l'Ingress Controller)
   - Python 3.11+ (uniquement si vous souhaitez exécuter les scripts hors conteneur)
2. **Préparer la configuration**
   - Copier l'exemple d'environnement : `cp .env.exemple .env`
   - Renseigner les secrets DB (`DB_PASSWORD`, `DB_ROOT_PASSWORD`), le domaine (`COOKIE_DOMAIN`) et les options Ingress (`INGRESS_*`)
   - Placer votre kubeconfig actuel dans `kubeconfig.yaml` (ou adapter le bind-volume de `compose.yaml`)
3. **Lancer l'infrastructure locale**
   ```bash
   docker compose up -d --build
   docker compose logs -f api
   ```
   Attendez que FastAPI affiche `Application startup complete`.
4. **Initialiser les données**
   ```bash
   docker exec -it labondemand-api python backend/init_db.py
   docker exec -it labondemand-api python backend/test_connection.py
   ```
   Un administrateur `admin / admin123` est créé si nécessaire.
5. **Sanity check**
   - Ouvrir http://localhost:80/login.html
   - Se connecter avec `admin / admin123`
   - Déployer un VS Code ou une stack LAMP depuis le catalogue et vérifier les URLs exposées
6. **Nettoyer / arrêter**
   ```bash
   docker compose down -v
   ```

> Besoin de préparer un cluster k3s + Ingress + MetalLB avant d'y connecter LabOnDemand ? Voir `documentation/platform-setup.md`.

## Mode pause

Le mode pause permet de couper temporairement une application sans la détruire.

1. Dans `Déploiements actifs`, cliquer sur `Pause` ; l'API force les réplicas à 0 et stocke l'état désiré dans les annotations `labondemand.io/paused-*`.
2. Le dashboard affiche un badge gris *Pause* et la carte de coût bascule en mode économie.
3. Cliquer sur `Reprendre` pour restaurer les réplicas mémorisés. Les labels/verrous sont supprimés automatiquement.
4. Si un composant est exclu (quota ou label `pause-disabled=true`), la requête échoue explicitement sans modifier les autres services.

## Scripts et commandes utiles

| Objectif | Commande |
| --- | --- |
| Initialiser la base | `docker exec -it labondemand-api python backend/init_db.py` |
| Vérifier la connectivité DB | `docker exec -it labondemand-api python backend/test_connection.py` |
| Réinitialiser le compte admin | `docker exec -it labondemand-api python backend/reset_admin.py` |
| Healthcheck API | `curl http://localhost:8000/api/v1/health` |
| Lancer tous les tests | `python backend/tests/run_tests.py --all` |
| Tests backend uniquement | `python backend/tests/run_tests.py --backend` |
| Tests UI (Selenium) | `python backend/tests/run_tests.py --ui --skip-server-check` |

Les logs JSON (`app.log`, `access.log`, `audit.log`) sont montés dans `./logs`. Pour tracer un bug, taillez `docker compose logs -f api` tout en surveillant `logs/audit.log` pour les actions sensibles.

## Où continuer ?

- **Plateforme & réseau** : `documentation/platform-setup.md` explique comment préparer k3s, ingress-nginx, MetalLB, DNS et TLS.
- **Authentification & rôles** : `documentation/authentication.md` couvre l'architecture et l'API `/api/v1/auth/*` (diagramme Mermaid inclus).
- **Observabilité** : `documentation/logging.md` détaille les flux JSON, variables d'environnement et recommandations de collecte.
- **Ressources & quotas** : `documentation/resource-limits.md` centralise les LimitRange, ResourceQuota et clamps côté API.
- **Stockage persistant** : `documentation/storage.md` décrit la mise à disposition des StorageClass/PVC et l'intégration à l'UI.
- **Stacks prêtes à l'emploi** : `documentation/lamp.md` et `documentation/wordpress.md` listent la topologie, les secrets et les URL générées.
- **Terminal Web** : `documentation/terminal.md` explique le WebSocket exec sécurisé et les restrictions par rôle.

Ces documents sont volontairement courts mais complémentaires : commencez par ce README, puis creusez uniquement les sections nécessaires à votre profil (ops, dev, enseignants).
