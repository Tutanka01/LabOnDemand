# Dépannage

## L'API ne démarre pas

**Symptôme**: `docker compose up` échoue sur le service `api`.

**Causes courantes**:

1. **Base de données non prête** — Depuis la v2 du compose.yaml, l'API attend un
   healthcheck MariaDB sain. Si MariaDB met trop de temps à démarrer, augmenter
   `start_period` dans le healthcheck.

2. **Redis inaccessible** — Vérifier `REDIS_URL`. En l'absence de Redis,
   les sessions tombent en mode mémoire (pas de persistance entre redémarrages).

3. **Kubeconfig manquant** — L'API a besoin d'un kubeconfig valide. En développement,
   monter `~/.kube:/root/.kube:ro` dans le conteneur.

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
4. Activer `DEBUG_MODE=true` pour accéder à `/api/v1/diagnostic/test-auth` et
   inspecter les claims OIDC reçus.

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
3. Vérifier que le proxy (Nginx / Traefik) est configuré pour passer les headers
   `Upgrade` et `Connection` WebSocket.

## Réinitialiser le mot de passe admin

```bash
# Via le script inclus
docker compose exec api python reset_admin.py

# Ou via docker_reset_admin.py (sans accès réseau à la BDD)
docker compose exec api python docker_reset_admin.py
```
