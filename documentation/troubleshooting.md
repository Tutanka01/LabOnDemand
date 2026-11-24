---
title: Dépannage
summary: Guide de résolution des problèmes courants — API qui ne démarre pas, erreurs 403 Kubernetes, pods en Pending, problèmes de connexion SSO et de stockage.
read_when: |
  - Un composant ne démarre pas ou retourne une erreur inattendue
  - Un déploiement Kubernetes est bloqué (Forbidden, Pending, CrashLoopBackOff)
  - Tu cherches rapidement la cause d'un problème sans lire toute la documentation
---

# Dépannage

## L'API ne démarre pas

**Symptôme**: `docker compose up` échoue sur le service `api`.

**Causes courantes**:

1. **Base de données non prête** — Depuis la v2 du compose.yaml, l'API attend un
   healthcheck MariaDB sain. Si MariaDB met trop de temps à démarrer, augmenter
   `start_period` dans le healthcheck.

2. **Redis inaccessible** — Vérifier `REDIS_URL` et `REDIS_PASSWORD`. Redis
   doit rester non exposé publiquement; une URL sans mot de passe ou un mot de
   passe incorrect empêchera la création des sessions.

   Si les logs affichent
   `AuthenticationError: HELLO must be called with the client already authenticated`,
   l'API s'est connectée sans mot de passe à un Redis protégé par `requirepass`
   (typiquement une entrée `REDIS_URL=redis://redis:6379/0` obsolète restée dans
   `.env`). `compose.yaml` construit désormais `REDIS_URL` à partir de
   `REDIS_PASSWORD` et ignore cette valeur; vérifier puis recréer l'API :

   ```bash
   docker compose config | grep REDIS_URL          # doit contenir :<mot_de_passe>@
   docker compose up -d --force-recreate api
   ```

3. **Kubeconfig manquant ou illisible** — L'API lit `./kubeconfig.yaml`, monté en
   lecture seule sur `/etc/labondemand/kubeconfig` (variable `KUBECONFIG` de l'image).
   Si le fichier n'existe pas sur l'hôte, Docker crée un répertoire à sa place :
   le supprimer et créer le fichier. Le kubeconfig est un secret local et ne doit
   pas être versionné.

4. **`PermissionError` sur `/app/logs` ou sur le kubeconfig (hôte Linux)** — L'API
   tourne sous l'utilisateur non-root `app` (UID 1000 par défaut). Les fichiers de
   `./logs` créés par une ancienne image (root) ne sont pas modifiables :
   `sudo chown -R 1000:1000 logs`, ou définir `APP_UID` / `APP_GID` dans `.env`
   puis `docker compose build api`.

5. **Production : `required variable ... is missing a value`** — `compose.prod.yaml`
   refuse de démarrer sans `DB_ROOT_PASSWORD`, `DB_PASSWORD` et `REDIS_PASSWORD`
   (pas de valeur de repli). Les définir dans `.env`.

6. **MariaDB refuse de démarrer après la mise à jour** — l'image est épinglée
   (`mariadb:13.0`). Si le volume `mariadb_data` a été créé par une version plus
   récente (ancien `mariadb:latest`), définir `MARIADB_IMAGE=mariadb:<version>`
   dans `.env` (la version figure dans les logs du conteneur `db`).

## L'interface affiche une erreur « service indisponible » (HTTP 503)

**Cause** : l'API n'arrive pas à joindre le cluster Kubernetes. Les endpoints de
liste et de lecture renvoient HTTP 503 avec un message `detail` au lieu d'une liste
vide ; les pages qui ne dépendent pas de Kubernetes continuent de fonctionner.

**Diagnostic** :
```bash
curl -s http://localhost/api/v1/k8s/ping          # {"k8s": false} si le cluster est injoignable
docker compose logs api --since 10m | grep -i timeout
```

Chaque appel Kubernetes est borné par `K8S_CONNECT_TIMEOUT_SECONDS` (5 s) et
`K8S_READ_TIMEOUT_SECONDS` (30 s). Vérifier l'adresse du serveur dans
`kubeconfig.yaml`, la connectivité réseau depuis l'hôte Docker et les variables
de proxy.

## Déploiement échoue avec "Forbidden" ou 403

**Cause**: Le compte de service Kubernetes de l'API n'a pas les droits suffisants.

**Solution**: Vérifier que le ClusterRole / Role associé au ServiceAccount autorise
`create`, `get`, `list`, `delete` sur `deployments`, `services`, `pods`, `secrets`,
`persistentvolumeclaims`, et `namespaces`.

## Déploiement créé mais pod en `Pending`

**Causes possibles**:
- Ressources insuffisantes sur les nodes (CPU/RAM)
- `PersistentVolumeClaim` en attente (pas de StorageClass par défaut)
- Image Docker non disponible (vérifier le registre)

**Diagnostic**:
```bash
kubectl describe pod <pod-name> -n <namespace>
kubectl get events -n <namespace> --sort-by='.lastTimestamp'
```

## PVC non créé / erreur StorageClass

Si le cluster n'a pas de StorageClass par défaut, le service tombe automatiquement
en mode `emptyDir` (données perdues au redémarrage du pod). Pour activer le stockage
persistant, configurer une StorageClass par défaut:

```bash
kubectl patch storageclass <name> -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```

## Ingress ne répond pas

1. Vérifier que `INGRESS_ENABLED=true` et `INGRESS_BASE_DOMAIN` est configuré.
2. Vérifier que l'IngressClass `INGRESS_CLASS_NAME` (défaut: `traefik`) existe:
   ```bash
   kubectl get ingressclass
   ```
3. Vérifier que le DNS `*.{INGRESS_BASE_DOMAIN}` pointe vers l'IP de l'Ingress Controller.
4. Inspecter la ressource Ingress créée:
   ```bash
   kubectl get ingress -A | grep labondemand
   kubectl describe ingress <name> -n <namespace>
   ```

## Labs SSO qui disparaissent après quelque temps

**Symptôme** : un utilisateur SSO crée un déploiement, il est visible, puis
disparaît après le prochain cycle de nettoyage (toutes les `CLEANUP_INTERVAL_MINUTES`
minutes, défaut 60 min) sans que l'utilisateur l'ait supprimé.

**Causes possibles** :

1. **Changement d'email côté IdP** — si l'email de l'utilisateur a changé au niveau
   de l'IdP et qu'aucune ligne `users` ne correspond à `external_id = sub`, un
   nouveau compte est créé avec un nouvel `id`. L'ancien namespace
   `labondemand-user-<OLD_ID>` n'a plus de correspondance en base et peut être
   détecté comme orphelin.

2. **`external_id` absent au premier login** — si la migration
   `add_users_external_id` n'a pas encore rempli le champ `external_id` pour un
   utilisateur existant, la recherche par `sub` échoue et un doublon peut être créé.

**Protection en place** : la tâche de nettoyage applique deux garde-fous avant
de supprimer un namespace orphelin :
- Présence de déploiements actifs en DB rattachés à ce `user_id` → suppression différée
- Âge du namespace < `ORPHAN_NS_GRACE_DAYS` jours (défaut : 7) → suppression différée

**Diagnostic** :
```bash
# Vérifier si des namespaces ont été ignorés par les garde-fous
grep orphan_namespace_skipped logs/app.log

# Vérifier si des namespaces ont été supprimés
grep orphan_namespace_deleted logs/app.log

# Vérifier l'external_id de l'utilisateur SSO en base
# (doit correspondre au claim 'sub' de l'IdP)
SELECT id, username, external_id FROM users WHERE auth_provider = 'oidc';
```

**Solution** : si un utilisateur SSO a perdu ses déploiements à cause d'un doublon
de compte, fusionner manuellement les deux lignes en base et remettre à jour
`external_id` avec la valeur `sub` correcte :

```sql
-- Identifier les doublons SSO
SELECT external_id, COUNT(*) FROM users WHERE auth_provider='oidc' GROUP BY external_id HAVING COUNT(*) > 1;

-- Corriger : mettre à jour le user_id dans deployments puis supprimer l'ancien compte
UPDATE deployments SET user_id = <NEW_ID> WHERE user_id = <OLD_ID>;
DELETE FROM users WHERE id = <OLD_ID>;
```

## SSO ne fonctionne pas

1. Vérifier `SSO_ENABLED=true` et toutes les variables `OIDC_*`.
2. L'`OIDC_REDIRECT_URI` doit correspondre exactement à ce qui est enregistré
   auprès de l'IdP.
3. Vérifier que `FRONTEND_BASE_URL` est défini (utilisé pour les redirections).
4. Consulter `logs/app.log` (événements `oidc_*`, par exemple `oidc_token_exchange_failed`) pour voir l'erreur renvoyée par l'IdP.

## Session expirée / déconnexion intempestive

- Augmenter `SESSION_EXPIRY_HOURS` (défaut: 24).
- Vérifier la connectivité Redis (si Redis redémarre, toutes les sessions sont perdues).
- En HTTP, `SECURE_COOKIES` doit être `false`; en HTTPS, il doit être `true`.

## Quota atteint — impossible de créer un déploiement

L'erreur `quota dépassé` signifie que l'utilisateur a atteint son nombre maximum
de déploiements simultanés. Les limites par rôle sont définies dans
`backend/k8s_utils.py:get_role_limits()`.

Pour supprimer les déploiements orphelins:
```bash
kubectl get deployments -A -l managed-by=labondemand
kubectl delete deployment <name> -n <namespace>
```

## Terminal WebSocket ne se connecte pas

1. Vérifier que le pod est en état `Running`.
2. L'endpoint WebSocket (`/api/v1/k8s/terminal`) requiert que le pod ait un shell
   disponible (`/bin/sh` ou `/bin/bash`).
3. Un code `403` indique généralement que l'utilisateur n'est pas propriétaire
   du pod, n'est pas admin, ou que les labels LabOnDemand (`managed-by`,
   `user-id`, `app-type`) sont absents ou incohérents.
4. Les pods de base de données des stacks MySQL/WordPress/LAMP ne sont pas
   ouverts au terminal.
5. Vérifier que le proxy (Nginx / Traefik) est configuré pour passer les headers
   `Upgrade` et `Connection` WebSocket.

## Réinitialiser le mot de passe admin

```bash
# Demande le nouveau mot de passe (non affiché) ; crée le compte s'il n'existe pas
docker compose exec api python -m backend.reset_admin

# Autre compte, ou mot de passe pris dans ADMIN_DEFAULT_PASSWORD (sans TTY)
docker compose exec api python -m backend.reset_admin --username alice
docker compose exec -T api python -m backend.reset_admin --from-env
```

Le compte est réactivé et repasse au rôle `admin`. Le mot de passe doit respecter
la politique de l'application (12 caractères minimum, majuscule, minuscule,
chiffre, caractère spécial).
