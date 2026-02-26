# Ressources et quotas LabOnDemand

## Architecture des gardes-fous

LabOnDemand applique plusieurs couches de protection pour éviter les dépassements
de ressources Kubernetes :

```
Requête de déploiement
  │
  ├── 1. Clamp applicatif         clamp_resources_for_role()         (k8s_utils.py)
  │       Plafonne CPU/RAM demandés selon le rôle
  │
  ├── 2. Vérification logique     DeploymentService._assert_user_quota()
  │       Compte les apps actives vs get_role_limits(role, user_id)
  │       ← Tient compte de UserQuotaOverride si elle existe
  │
  ├── 3. Préflight K8s            DeploymentService._preflight_k8s_quota()
  │       Additionne planned + used et vérifie vs ResourceQuota K8s
  │
  └── 4. Création K8s             Deployment + ResourceQuota + LimitRange
          ensure_namespace_baseline() applique les quotas par namespace
```

---

## 1. Quotas Kubernetes par namespace (ResourceQuota + LimitRange)

Source : `backend/k8s_utils.py` → `ensure_namespace_baseline()`

### ResourceQuota "baseline-quota"

| Rôle    | Pods | CPU request | RAM request | CPU limit | RAM limit | Deployments | Services | PVC | Stockage |
|---------|------|-------------|-------------|-----------|-----------|-------------|----------|-----|----------|
| student | 6    | 2500m       | 6 Gi        | 5         | 8 Gi      | 8           | 10       | 2   | 2 Gi     |
| teacher | 20   | 4000m       | 8 Gi        | 8         | 16 Gi     | 20          | 25       | —   | —        |
| admin   | 200  | 64000m      | 128 Gi      | 128       | 256 Gi    | 200         | 200      | 100 | 2 Ti     |

### LimitRange "baseline-limits" (valeurs par défaut par conteneur)

| Rôle    | CPU request défaut | RAM request défaut | CPU limit défaut | RAM limit défaut |
|---------|--------------------|--------------------|------------------|------------------|
| student | 100m               | 128 Mi             | 500m             | 512 Mi           |
| teacher | 250m               | 256 Mi             | 1000m            | 1 Gi             |
| admin   | 500m               | 512 Mi             | 2000m            | 2 Gi             |

---

## 2. Plafonds applicatifs (`get_role_limits`)

Source : `backend/k8s_utils.py` → `get_role_limits(role, user_id)`

### Limites par défaut

| Rôle    | max_apps | CPU request max | RAM request max | max_pods |
|---------|----------|-----------------|-----------------|----------|
| student | 4        | 2500m           | 6144 Mi         | 6        |
| teacher | 10       | 4000m           | 8192 Mi         | 20       |
| admin   | 100      | 16000m          | 65536 Mi        | 100      |

### Dérogations individuelles (`UserQuotaOverride`)

Un admin peut accorder une dérogation à un utilisateur spécifique, sans modifier
les valeurs globales par rôle. La dérogation peut être temporaire (avec `expires_at`)
ou permanente.

```
get_role_limits("student", user_id=42)
  │
  ├── Charge base student : max_apps=4, max_cpu_m=2500, max_mem_mi=6144
  ├── SELECT * FROM user_quota_overrides
  │   WHERE user_id=42 AND (expires_at IS NULL OR expires_at > now())
  └── Si override : max_apps=8, max_cpu_m=4000 → remplace les valeurs non-NULL
      → retourne {max_apps: 8, max_requests_cpu_m: 4000, max_requests_mem_mi: 6144, max_pods: 6}
```

**API admin pour les dérogations** (voir `documentation/admin-guide.md`) :

```http
PUT  /api/v1/auth/users/{id}/quota-override?max_apps=8&max_cpu_m=4000&expires_at=2026-07-01T00:00:00
GET  /api/v1/auth/users/{id}/quota-override
DELETE /api/v1/auth/users/{id}/quota-override
```

---

## 3. Clamp des ressources demandées (`clamp_resources_for_role`)

Source : `backend/k8s_utils.py` → `clamp_resources_for_role()`

| Rôle    | CPU request max | CPU limit max | RAM request max | RAM limit max | Réplicas max |
|---------|-----------------|---------------|-----------------|---------------|--------------|
| student | 500m            | 1000m         | 512 Mi          | 1 Gi          | 1            |
| teacher | 1000m           | 2000m         | 1 Gi            | 2 Gi          | 2            |
| admin   | 2000m           | 4000m         | 2 Gi            | 4 Gi          | 5            |

Toute valeur dépassant ces plafonds est **silencieusement réduite** avant
la création des manifests Kubernetes.

---

## 4. Templates et RuntimeConfig

Les templates définissent des ressources **minimales** pour chaque type de lab :

| Template  | CPU request min | CPU limit min | RAM request min | RAM limit min |
|-----------|-----------------|---------------|-----------------|---------------|
| vscode    | 150m            | 500m          | 256 Mi          | 512 Mi        |
| jupyter   | 250m            | 500m          | 512 Mi          | 1 Gi          |
| mysql/pma | 150m            | 300m          | 128 Mi          | 256 Mi        |
| lamp      | 250m            | 500m          | 256 Mi          | 512 Mi        |
| netbeans  | 500m            | 1000m         | 1 Gi            | 2 Gi          |

Ces minima sont appliqués même si l'utilisateur demande moins.

---

## 5. Endpoints de supervision des quotas

```http
GET /api/v1/quotas/me
```

Retourne pour l'utilisateur courant :

```json
{
  "limits": { "max_apps": 4, "max_requests_cpu_m": 2500, "max_requests_mem_mi": 6144 },
  "usage":  { "apps": 2, "cpu_m": 800, "mem_mi": 1024 },
  "remaining": { "apps": 2, "cpu_m": 1700, "mem_mi": 5120 }
}
```

Si une dérogation `UserQuotaOverride` est active pour l'utilisateur, les `limits`
reflèteront les valeurs de la dérogation et non celles du rôle par défaut.

---

## 6. Stockage et PVC

- Les étudiants sont limités à **2 PVC** et **2 Gi** de stockage total (ResourceQuota)
- Les enseignants n'ont pas de limite de stockage dans la configuration par défaut
- Les admins peuvent avoir jusqu'à **100 PVC** et **2 Ti**

Les PVC sont étiquetés `managed-by=labondemand` et `user-id=<id>`.

---

## 7. Modifier les limites

### Modifier les limites globales d'un rôle

```python
# backend/k8s_utils.py — get_role_limits()
elif role == "teacher":
    base = {
        "max_apps": 15,          # augmenter
        "max_requests_cpu_m": 6000,
        "max_requests_mem_mi": 12288,
        "max_pods": 30,
    }
```

Puis mettre à jour `ensure_namespace_baseline()` pour aligner le ResourceQuota K8s.

### Accorder une dérogation temporaire à un étudiant

```bash
curl -X PUT "http://localhost:8000/api/v1/auth/users/42/quota-override?max_apps=8&expires_at=2026-06-01T00:00:00" \
  -H "Cookie: session_id=<token_admin>"
```

### Supprimer une dérogation expirée

Les dérogations expirées restent en base mais sont ignorées par `get_role_limits()`
(filtrées par `expires_at > now()`). Elles peuvent être nettoyées manuellement :

```sql
DELETE FROM user_quota_overrides WHERE expires_at IS NOT NULL AND expires_at < NOW();
```

---

## 8. Checklist avant modification des quotas

- [ ] Mettre à jour les valeurs dans **toutes** les couches (Quota K8s, clamp, template, UI)
- [ ] Tester avec un compte du rôle cible
- [ ] Vérifier `GET /api/v1/quotas/me` pour confirmer les nouvelles bornes
- [ ] Vérifier les erreurs `_preflight_k8s_quota` dans les logs
- [ ] Documenter le changement dans ce fichier
