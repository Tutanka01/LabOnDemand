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
