# Guide administrateur LabOnDemand

Ce guide couvre toutes les fonctionnalités réservées au rôle `admin` :
gestion des utilisateurs, dérogations de quotas, import CSV, supervision du cluster et dark mode.

---

## Accès à l'interface d'administration

- **Gestion des utilisateurs** : `http://<host>/admin.html`
- **Statistiques du cluster** : `http://<host>/admin-stats.html`
- **API (Swagger)** : `http://<host>/docs` (uniquement si `DEBUG_MODE=true`)
- **Health check** : `GET /api/v1/health`

Un compte administrateur est automatiquement créé au premier démarrage.
Le mot de passe initial est défini par `ADMIN_DEFAULT_PASSWORD` dans `.env`
(**à changer immédiatement en production**).

---

## Gestion des utilisateurs

### Créer un utilisateur

```http
POST /api/v1/auth/register
Authorization: session_id cookie (admin)

{
  "username": "alice",
  "email": "alice@example.com",
  "full_name": "Alice Martin",
  "password": "S3cur3Pass!word",
  "role": "student"
}
```

Règles du mot de passe : **12 caractères minimum**, 1 majuscule, 1 minuscule,
1 chiffre, 1 caractère spécial.

> En mode SSO (`SSO_ENABLED=True`), la création de comptes locaux est désactivée.
> Les comptes sont créés automatiquement à la première connexion SSO.

### Modifier un utilisateur

```http
PUT /api/v1/auth/users/{id}

{
  "role": "teacher",        // Marque role_override=true (le SSO ne réécrasera plus ce rôle)
  "is_active": true,
  "email": "alice@new.com"
}
```

> Modifier le rôle via cette API active le drapeau `role_override = True` :
> les connexions SSO suivantes n'écraseront plus le rôle assigné manuellement.

### Supprimer un utilisateur

```http
DELETE /api/v1/auth/users/{id}
```

La suppression déclenche automatiquement :
1. **Invalidation de toutes les sessions Redis** de l'utilisateur
2. **Suppression du namespace Kubernetes** `labondemand-user-{id}` et de toutes ses ressources
3. **Suppression en cascade** des entrées `deployments` et `user_quota_overrides` en base

---

## Import CSV d'utilisateurs

Permet de créer une classe entière en une opération (ex. 30 étudiants).

### Format du fichier CSV

```csv
username,email,full_name,role,password
alice,alice@univ.fr,Alice Martin,student,S3cur3Pass!word1
bob,bob@univ.fr,Bob Dupont,student,S3cur3Pass!word2
prof.dupond,dupond@univ.fr,Prof. Dupond,teacher,S3cur3Pass!word3
```

Règles :
- L'en-tête `username,email,full_name,role,password` est **obligatoire**
- `full_name` peut être vide
- `role` : `student`, `teacher` ou `admin`
- Chaque mot de passe doit respecter la politique de sécurité (12 car. min.)
- Les utilisateurs dont le `username` ou l'`email` existent déjà sont ignorés (`skipped`)

### Endpoint

```http
POST /api/v1/auth/users/import
Content-Type: multipart/form-data
Authorization: session_id cookie (admin)

file: <fichier.csv>
```

### Réponse

```json
{
  "summary": { "created": 28, "errors": 1, "skipped": 1, "total": 30 },
  "results": [
    { "line": 2, "username": "alice",   "status": "created", "user_id": 42 },
    { "line": 3, "username": "bob",     "status": "skipped", "detail": "Email déjà utilisé" },
    { "line": 4, "username": "charlie", "status": "error",   "detail": "Mot de passe trop faible" }
  ]
}
```

### Via cURL

```bash
curl -X POST http://localhost:8000/api/v1/auth/users/import \
  -H "Cookie: session_id=<token>" \
  -F "file=@etudiants.csv"
```

---

## Dérogations de quotas (`UserQuotaOverride`)

Par défaut, chaque rôle a des limites fixées dans `k8s_utils.get_role_limits()`.
Un admin peut accorder une dérogation temporaire ou permanente à un utilisateur
spécifique, sans modifier le code.

### Obtenir la dérogation actuelle

```http
GET /api/v1/auth/users/{id}/quota-override
```

Réponse si aucune dérogation :
```json
{ "user_id": 5, "override": null }
```

Réponse avec dérogation active :
```json
{
  "user_id": 5,
  "override": {
    "id": 1,
    "max_apps": 8,
    "max_cpu_m": 4000,
    "max_mem_mi": 8192,
    "max_storage_gi": 10,
    "expires_at": "2026-07-01T00:00:00",
    "created_at": "2026-02-01T10:00:00"
  }
}
```

### Définir ou modifier une dérogation

```http
PUT /api/v1/auth/users/{id}/quota-override
  ?max_apps=8
  &max_cpu_m=4000
  &max_mem_mi=8192
  &max_storage_gi=10
  &expires_at=2026-07-01T00:00:00
```

Tous les paramètres sont optionnels. `null` signifie "utiliser la valeur du rôle".
`expires_at` absent ou `null` = dérogation permanente.

**Cas d'usage typique** : un étudiant prépare un projet intensif et a besoin
de plus de CPU pendant 2 semaines.

```bash
curl -X PUT "http://localhost:8000/api/v1/auth/users/42/quota-override?max_apps=10&max_cpu_m=4000&expires_at=2026-03-15T00:00:00" \
  -H "Cookie: session_id=<token_admin>"
```

### Supprimer une dérogation

```http
DELETE /api/v1/auth/users/{id}/quota-override
```

Après suppression, l'utilisateur retrouve les limites par défaut de son rôle.

### Comment la dérogation est appliquée

```
get_role_limits(role="student", user_id=42)
  │
  ├── Charge les limites par défaut du rôle student
  ├── Requête SQL : SELECT * FROM user_quota_overrides WHERE user_id=42 AND (expires_at IS NULL OR expires_at > now)
  └── Si override trouvé : remplace max_apps, max_cpu_m, max_mem_mi selon les valeurs non-NULL
      → retourne les limites fusionnées
```

---

## Supervision du cluster

### Health check

```bash
curl http://localhost:8000/api/v1/health
```

```json
{
  "status":    "healthy",   // "degraded" si un composant échoue
  "db":        "ok",
  "redis":     "ok",
  "k8s":       "ok",
  "timestamp": "2026-02-26T10:00:00"
}
```

Valeurs possibles par composant : `"ok"` ou `"error: <message>"`.

Intégrer dans Docker Compose, Prometheus Blackbox Exporter ou tout outil de
monitoring externe.

### Statistiques du cluster

Page `admin-stats.html` — accessible aux admins et enseignants.

Via l'API :

```http
GET /api/v1/k8s/monitoring/cluster-stats
GET /api/v1/k8s/monitoring/namespaces
GET /api/v1/k8s/monitoring/nodes
```

---

## Gestion du rôle SSO (`role_override`)

En mode SSO, les rôles sont déduits des claims OIDC à chaque connexion.
Le drapeau `role_override = True` (posé automatiquement lors d'un `PUT /users/{id}`)
empêche le callback SSO d'écraser le rôle assigné manuellement.

**Cas d'usage** : promouvoir un étudiant en enseignant sans qu'il perde ce rôle
à la prochaine connexion SSO.

| `role_override` | Comportement lors du prochain login SSO           |
|-----------------|---------------------------------------------------|
| `False`         | Le rôle est mis à jour depuis les claims OIDC     |
| `True`          | Le rôle conserve la valeur définie par l'admin    |

> Le rôle `admin` n'est **jamais** écrasé par le SSO, quelle que soit la valeur
> de `role_override`.

---

## Cache de découverte OIDC

Le document `/.well-known/openid-configuration` de l'IdP est mis en cache pour
éviter une requête réseau à chaque connexion SSO.

| Variable                      | Défaut | Description                             |
|-------------------------------|--------|-----------------------------------------|
| `OIDC_DISCOVERY_TTL_SECONDS`  | 3600   | Durée de validité du cache (en secondes)|

Après expiration, le cache est rafraîchi à la prochaine demande de connexion SSO.
Si l'IdP est temporairement indisponible, le cache périmé est utilisé en fallback
(avec un log `oidc_discovery_using_stale_cache`).

Pour forcer un rafraîchissement immédiat : redémarrer l'API ou attendre l'expiration.

---

## Interface dark mode

Tous les utilisateurs ont accès au bouton 🌙 dans le header pour basculer
entre mode clair et mode sombre. La préférence est sauvegardée dans `localStorage`.

En l'absence de préférence stockée, le mode suit la configuration système
(`prefers-color-scheme`).

Pour changer le mode par défaut à l'échelle de la plateforme, modifier
`frontend/js/darkmode.js` (fonction `getPreferredTheme`).

---

## Commandes utiles

| Objectif | Commande |
|----------|----------|
| Healthcheck API | `curl http://localhost:8000/api/v1/health` |
| Lister les utilisateurs | `curl -H "Cookie: session_id=<tok>" http://localhost:8000/api/v1/auth/users` |
| Importer un CSV | `curl -X POST -F "file=@users.csv" -H "Cookie: session_id=<tok>" http://localhost:8000/api/v1/auth/users/import` |
| Voir la dérogation quota | `curl -H "Cookie: session_id=<tok>" http://localhost:8000/api/v1/auth/users/42/quota-override` |
| Logs d'audit | `tail -f logs/audit.log` |
| Logs application | `docker compose logs -f api` |
| Namespaces K8s actifs | `kubectl get ns -l managed-by=labondemand` |

---

## Sécurité — rappels admin

- Changer `ADMIN_DEFAULT_PASSWORD` dès la première connexion
- Ne jamais activer `DEBUG_MODE=True` en production (expose Swagger + test-auth)
- Surveiller `logs/audit.log` pour les actions sensibles : `user_deleted`, `quota_override_set`, `users_imported_csv`
- Les sessions expirées sont automatiquement purgées par Redis (TTL Redis = `SESSION_EXPIRY_HOURS`)
- Un admin supprimé voit ses sessions immédiatement invalidées
