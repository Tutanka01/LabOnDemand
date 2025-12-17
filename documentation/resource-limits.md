# Guide complet des ressources LabOnDemand

## 1. Vue d'ensemble
- LabOnDemand applique plusieurs couches de garde-fous pour éviter les dépassements de ressources Kubernetes : quotas de namespace, LimitRange, plafonds logiques côté API, templates avec ressources minimales et presets côté UI/scripts.
- Chaque requête de déploiement traverse les étapes suivantes :
  1. Clamp des valeurs demandées en fonction du rôle (`backend/k8s_utils.py` > `clamp_resources_for_role`).
  2. Application des minima par template (`backend/templates.py` et `backend/deployment_service.py`).
  3. Vérification logique des quotas LabOnDemand (`DeploymentService._assert_user_quota`).
  4. Préflight contre les `ResourceQuota` Kubernetes (`DeploymentService._preflight_k8s_quota`).
  5. Création des objets Kubernetes avec labels standards (`create_labondemand_labels`).
- Les sections suivantes décrivent toutes les valeurs impliquées et où les modifier.

## 2. Garde-fous Kubernetes (ResourceQuota & LimitRange)
Source : [`backend/k8s_utils.py`](../backend/k8s_utils.py) > `ensure_namespace_baseline`

### 2.1 ResourceQuota "baseline-quota"
| Rôle     | Pods | requests.cpu | requests.memory | limits.cpu | limits.memory | Deployments | Services | PVC | Stockage |
|----------|------|--------------|-----------------|------------|---------------|-------------|----------|-----|----------|
| student  | 6    | 2500m        | 6Gi             | 5          | 8Gi           | 8           | 10       | 2   | 2Gi      |
| teacher  | 20   | 4000m        | 8Gi             | 8          | 16Gi          | 20          | 25       | —   | —        |
| admin    | 200  | 64000m       | 128Gi           | 128        | 256Gi         | 200         | 200      | 100 | 2Ti      |

- Les valeurs sont idempotentes : si le quota existe déjà mais diffère, il est patché lors de chaque lancement.
- En cas de RBAC limitant l'accès (erreur 403), le processus ignore l'échec pour ne pas bloquer les déploiements, mais le namespace conserve alors ses quotas existants.

### 2.2 LimitRange "baseline-limits"
| Rôle     | defaultRequest CPU | defaultRequest RAM | default CPU | default RAM |
|----------|--------------------|--------------------|-------------|-------------|
| student  | 100m               | 128Mi              | 1000m       | 512Mi       |
| teacher  | 250m               | 256Mi              | 2000m       | 1Gi         |
| admin    | 500m               | 512Mi              | 4000m       | 2Gi         |

- Ces valeurs définissent les `requests` et `limits` par défaut pour tout conteneur créé dans le namespace lorsque les manifests n'en fournissent pas.
- Pour modifier ces valeurs, ajustez `lr_request` et `lr_default` dans `ensure_namespace_baseline`.

### 2.3 Exemple de modification ResourceQuota
```python
# backend/k8s_utils.py
if role == "teacher":
    rq_hard = {
        "pods": "30",  # augmenter la limite de pods
        "requests.cpu": "6000m",
        "requests.memory": "12Gi",
        # ...
    }
```
Après modification, redéployer le backend ou déclencher une création de déploiement pour appliquer le nouveau patch sur les namespaces enseignants.

## 3. Plafonds applicatifs LabOnDemand
Source : [`backend/deployment_service.py`](../backend/deployment_service.py)

### 3.1 Limites logiques par rôle (`get_role_limits`)
| Rôle     | max_apps | max_requests_cpu_m | max_requests_mem_mi | max_pods |
|----------|---------:|-------------------:|--------------------:|---------:|
| student  | 4        | 2500               | 6144                | 6        |
| teacher  | 10       | 4000               | 8192                | 20       |
| admin    | 100      | 16000              | 65536               | 100      |

- Utilisé par `_assert_user_quota` pour refuser un déploiement avant d'atteindre Kubernetes.
- Le calcul se base sur l'utilisation réelle (_pods et quotas) via `_get_user_usage`.

### 3.2 Clamp des ressources demandées (`clamp_resources_for_role`)
| Rôle     | CPU request max | CPU limit max | RAM request max | RAM limit max | Réplicas max |
|----------|----------------:|--------------:|----------------:|--------------:|-------------:|
| student  | 500m            | 1000m         | 512Mi           | 1Gi           | 1            |
| teacher  | 1000m           | 2000m         | 1Gi             | 2Gi           | 2            |
| admin    | 2000m           | 4000m         | 2Gi             | 4Gi           | 5            |

- Toute demande excédant ces plafonds est automatiquement réduite avant la création Kubernetes.
- Pour autoriser plus de CPU aux admins, augmentez `max_cpu_req` et `max_cpu_lim` dans la branche `else` du helper.

### 3.3 Préflight ResourceQuota
- `_preflight_k8s_quota` additionne les ressources planifiées avec les valeurs `used` retournées par Kubernetes et refuse l'opération si un `ResourceQuota` serait dépassé.
- Les messages d'erreur détaillent la ressource fautive (`requests.cpu(m): 4000+500>4000 m`).

## 4. Templates et RuntimeConfig
Sources : [`backend/templates.py`](../backend/templates.py) et [`backend/main.py`](../backend/main.py)

### 4.1 Minima appliqués par template (`DeploymentConfig`)
| Template | Image par défaut             | target_port | min_cpu_request | min_cpu_limit | min_mem_request | min_mem_limit |
|----------|------------------------------|-------------|----------------:|--------------:|----------------:|--------------:|
| vscode   | tutanka01/k8s:vscode         | 8080        | 100m            | 1000m         | 256Mi           | 1Gi           |
| jupyter  | tutanka01/k8s:jupyter        | 8888        | 100m            | 1000m         | 512Mi           | 1Gi           |
| mysql    | phpmyadmin:latest (UI)       | 8080        | 100m            | 300m          | 128Mi           | 256Mi         |
| lamp     | php:8.2-apache               | 8080        | 250m            | 500m          | 256Mi           | 512Mi         |
| netbeans | tutanka01/labondemand:netbeansjava | 6901   | 250m            | 1000m         | 1Gi             | 2Gi           |

- Ces minima sont appliqués même si l'utilisateur fournit des valeurs plus faibles.
- Le fichier `backend/main.py` réplique ces valeurs lors du seed des `RuntimeConfig` (création initiale de la base).

### 4.2 Exemple : ajuster le CPU minimum VS Code
```python
# backend/templates.py
VSCODE_CONFIG = {
    "min_cpu_request": "100m",  # overcommit par défaut
    "min_cpu_limit": "1000m",
    # ...
}

# backend/main.py (seed RuntimeConfig)
min_cpu_request="100m",
```
Après modification, mettre à jour la configuration en base soit via un `UPDATE runtime_configs`, soit en purgeant la table avant de relancer l'app (le seed ne réécrit pas une entrée déjà existante).

## 5. Presets UI et outils
- **Frontend** : les listes déroulantes CPU/RAM du formulaire étudiant/admin sont mappées dans [`frontend/script.js`](../frontend/script.js) autour des lignes 2000+. Exemple :
  ```javascript
  const cpuValues = {
      'very-low': { request: '100m', limit: '200m' },
      'low': { request: '250m', limit: '500m' },
      // ...
  };
  ```
  Adapter ces presets permet d'exposer de nouvelles options sans toucher au backend.
- **Load test** : [`tests/load_test_deployments.py`](../tests/load_test_deployments.py) lance par défaut 60 déploiements VS Code en preset "low" (0.25 vCPU / 256 Mi). Utiliser `--cpu medium` pour simuler des charges plus lourdes.
- **Templates admin (back-office)** : le CRUD des templates consomme les valeurs `RuntimeConfig` via [`frontend/js/templates.js`](../frontend/js/templates.js). Tout changement dans `RuntimeConfig` doit être reflété via l'API ou un script SQL.

## 6. Stockage et PVC
- Les étudiants sont limités à 2 PVC et 2 Gi de stockage cumulé via `requests.storage` (voir §2.1).
- Les admins peuvent monter jusqu'à 100 PVC avec un budget de 2 Ti.
- Le backend étiquette les PVC avec `managed-by=labondemand` et `user-id=<id>` dans [`DeploymentService` > montée PVC](../backend/deployment_service.py).
- Pour modifier la taille par défaut d'un volume, ajuster la logique de création dans `DeploymentService` (section `create_deployment` autour de la gestion des PVC).

## 7. Endpoints de supervision
- `GET /api/v1/quotas/me` (`backend/k8s_router.py`) : retourne `limits`, `usage` et `remaining` pour alimenter le dashboard.
- `GET /api/v1/k8s/pvcs` / `/pvcs/all` : inventaire des volumes, utile pour auditer l'utilisation du stockage.
- `GET /api/v1/k8s/deployments/labondemand` : permet de corréler les pods actifs et les quotas consommés.

## 8. Paramètres globaux
- [`backend/config.py`](../backend/config.py) :
  - `USER_NAMESPACE_PREFIX` détermine le format des namespaces users (`labondemand-user-<id>` par défaut).
  - `DEFAULT_NAMESPACES` fournit les namespaces des templates partagés (utilisés lorsqu'aucun namespace dédié n'est requis).
- Variables d'environnement à considérer : `CLUSTER_EXTERNAL_IP`, `DEBUG_MODE`, etc., pour contextualiser les recommandations de quotas.

## 9. Exemples de modifications ciblées
1. **Augmenter la limite CPU par défaut pour les enseignants**
   ```python
   # backend/k8s_utils.py
   elif role == "teacher":
       lr_default = {"cpu": "1500m", "memory": "1Gi"}
   ```
   Vérifier ensuite que `clamp_resources_for_role` reflète ce nouveau plafond.

2. **Autoriser 3 réplicas aux enseignants**
   ```python
   # backend/k8s_utils.py > clamp_resources_for_role
   elif role == "teacher":
       max_replicas = 3
   ```
   Mettre à jour le front (`frontend/script.js`) pour autoriser la saisie d'un nombre supérieur à 2.

3. **Modifier la limite de PVC étudiants**
   ```python
   # backend/k8s_utils.py
   rq_hard = {
       "count/persistentvolumeclaims": "3",
       "requests.storage": "4Gi",
       # ...
   }
   ```
   Informer les étudiants via la documentation ou l'UI afin d'éviter les surprises.

## 10. Checklist avant/après modification
- [ ] Mettre à jour les valeurs dans **toutes** les couches concernées (Quota, Clamp, Template, UI).
- [ ] Tester avec `tests/load_test_deployments.py` en utilisant le rôle cible.
- [ ] Vérifier le retour de `GET /api/v1/quotas/me` pour confirmer les nouvelles bornes.
- [ ] Contrôler les erreurs renvoyées par `_preflight_k8s_quota` pour s'assurer que Kubernetes accepte les nouvelles valeurs.
- [ ] Documenter le changement (ex : ajouter une note dans `documentation/logging.md` ou un changelog interne).

Ce document centralise les points de tension liés aux ressources. En cas de doute, inspecter directement [`backend/deployment_service.py`](../backend/deployment_service.py) qui contient la logique d'orchestration complète, puis valider les changements via un test de lancement contrôlé.
