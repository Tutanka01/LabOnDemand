---
title: Sécurité LabOnDemand
summary: Modèle de sécurité complet — sessions serveur, CSRF, isolation Kubernetes par namespace, headers HTTP, RBAC et recommandations pour la production.
read_when: |
  - Tu audites ou renforces la sécurité de la plateforme
  - Tu travailles sur l'authentification, les sessions Redis ou la protection CSRF
  - Tu prépares un déploiement en production et veux appliquer les bonnes pratiques de sécurité
---

# Sécurité LabOnDemand

## Authentification

LabOnDemand utilise des **sessions côté serveur** (pas de JWT). Le token de session
est opaque pour le client et ne contient aucune donnée sensible.

### Flux de connexion locale

```
1. POST /api/v1/auth/login  {username, password}
2. Backend vérifie le hash bcrypt
3. Crée une session Redis (token 32 octets URL-safe, TTL = SESSION_EXPIRY_HOURS)
4. Set-Cookie: session_id=<token>; HttpOnly; SameSite=Strict; [Secure]
5. Toutes les requêtes API suivantes portent ce cookie automatiquement
```

### Flux SSO / OIDC

```
1. GET /api/v1/auth/sso/login → génère state anti-CSRF, redirige vers l'IdP
2. IdP authentifie l'utilisateur
3. GET /api/v1/auth/sso/callback?code=…&state=…
4. Vérification du state (cookie oidc_state)
5. Échange du code contre access_token
6. Récupération des claims (sub, email, nom, rôle)
7. Recherche du compte : d'abord par external_id (sub), puis par email en fallback
   → external_id est contraint UNIQUE : un seul compte par identifiant SSO
8. Création ou mise à jour du compte local
9. Session Redis créée comme pour l'auth locale
```

Le document de découverte OIDC est mis en cache avec un TTL de
`OIDC_DISCOVERY_TTL_SECONDS` secondes (défaut : 3600 s = 1 h). En cas
d'indisponibilité de l'IdP après expiration, le cache périmé est utilisé
en fallback plutôt que de bloquer toutes les connexions.

### Gestion des sessions

| Paramètre              | Défaut   | Description                             |
|------------------------|----------|-----------------------------------------|
| `SESSION_EXPIRY_HOURS` | 24       | Durée de vie de la session              |
| `SECURE_COOKIES`       | true     | Cookie `Secure` (HTTPS requis si true)  |
| `SESSION_SAMESITE`     | Strict   | Protection CSRF                         |
| `COOKIE_DOMAIN`        | (vide)   | Restreindre le cookie à un domaine      |

### Invalidation des sessions

- **Au logout** : seule la session active est supprimée.
- **À la suppression d'un utilisateur** : **toutes** ses sessions Redis sont
  invalidées immédiatement via `security.delete_user_sessions(user_id)`.
  Cette fonction scanne les clés Redis par pattern `session:*` et supprime
  toutes les entrées correspondant à l'utilisateur avant la suppression en base.

---

## RBAC (Contrôle d'accès basé sur les rôles)

### Rôles

| Rôle    | Description                                                         |
|---------|---------------------------------------------------------------------|
| student | Utilisateur standard, quotas faibles, ne voit que ses propres labs |
| teacher | Quotas plus élevés, peut voir les labs de ses étudiants             |
| admin   | Accès complet : CRUD utilisateurs, templates, runtime configs, quotas |

### Enforcement

Les dépendances FastAPI `get_current_user()`, `is_admin()`, et `is_teacher_or_admin()`
dans `security.py` sont injectées sur chaque endpoint.

L'isolation des ressources est également appliquée côté Kubernetes :
- Namespace dédié par utilisateur (`labondemand-user-{id}`)
- `ResourceQuota` et `LimitRange` par namespace selon le rôle

### Quotas applicatifs par rôle

| Ressource           | student | teacher | admin  |
|---------------------|---------|---------|--------|
| max apps            | 4       | 10      | 100    |
| CPU request max     | 2500m   | 4000m   | 16000m |
| RAM request max     | 6144 Mi | 8192 Mi | 65536 Mi |
| max pods            | 6       | 20      | 100    |

Ces valeurs peuvent être **surchargées par utilisateur** via `UserQuotaOverride`.
Voir `documentation/resource-limits.md`.

---

## Politique de mots de passe

Les mots de passe locaux doivent satisfaire :
- Au moins **12 caractères**
- Au moins 1 majuscule, 1 minuscule, 1 chiffre, 1 caractère spécial

Enforcement dans `security.py:validate_password_strength()`. Appliqué à :
- La création de compte (`register`)
- La modification de mot de passe (`PUT /users/{id}`, `POST /change-password`, `PUT /me`)
- L'import CSV (`POST /users/import`)

---

## Rate limiting

`slowapi` applique des limites par IP :

| Endpoint | Limite |
|----------|--------|
| `POST /api/v1/auth/login` | 5 / minute |
| `POST /api/v1/auth/register` | 5 / minute |
| `POST /api/v1/k8s/deployments` | 10 / 5 minutes |
| `POST /api/v1/k8s/pods` | 10 / 5 minutes |

En cas de dépassement, l'API retourne `429 Too Many Requests`.

---

## Sécurité des conteneurs K8s déployés

Tous les conteneurs créés par LabOnDemand appliquent le contexte de sécurité :

```yaml
securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
  seccompProfile:
    type: RuntimeDefault
```

---

## Nettoyage des ressources à la suppression d'utilisateur

```
DELETE /api/v1/auth/users/{id}
  1. delete_user_sessions(user_id)    → sessions Redis invalidées
  2. cleanup_user_namespace(user_id)  → namespace K8s + toutes ses ressources supprimés
  3. db.delete(user)                  → user + deployments + overrides (CASCADE)
```

Cela évite les **sessions orphelines** (utilisateur supprimé mais token encore valide)
et les **namespaces zombies** (ressources K8s qui persistent sans propriétaire en base).

---

## Secrets Kubernetes

Les mots de passe de base de données (MySQL, MariaDB, WordPress) sont générés
aléatoirement avec `secrets.token_urlsafe()` à chaque déploiement et stockés
dans des Secrets Kubernetes (type Opaque). Ils ne sont **jamais loggés**.

---

## Protection anti-CSRF (OIDC)

Un `state` aléatoire (`secrets.token_urlsafe(32)`) est généré au démarrage du
flow OIDC, stocké dans un cookie HttpOnly (TTL 10 min), et vérifié au retour
du callback. Toute non-concordance retourne `400 Bad Request`.

---

## Endpoint de diagnostic

`POST /api/v1/diagnostic/test-auth` n'est accessible que si `DEBUG_MODE=True`.
**Ne jamais activer `DEBUG_MODE` en production.**

---

## Audit trail

Toutes les actions sensibles sont tracées dans `logs/audit.log` :

| Événement | Champs |
|-----------|--------|
| `login_success` | user_id, username, role, session_id, client_ip |
| `login_failed` | username, reason, client_ip |
| `logout` | user_id, username, session_id |
| `user_registered` | user_id, username, role |
| `user_updated` | user_id, username, role, updated_by |
| `user_deleted` | user_id, username, sessions_revoked, namespace_deleted |
| `quota_override_set` | target_user_id, admin_user_id, max_apps, max_cpu_m, expires_at |
| `users_imported_csv` | created, errors, skipped |
| `user_namespace_cleanup` | user_id, namespace, status |
| `deployment_deleted` | namespace, name, user_id, deployment_type |
| `oidc_user_created` | username, role |

---

## Checklist sécurité production

- [ ] `SECURE_COOKIES=True` (HTTPS uniquement)
- [ ] `SESSION_SAMESITE=Strict`
- [ ] `DEBUG_MODE=False`
- [ ] `ADMIN_DEFAULT_PASSWORD` changé dès le premier démarrage
- [ ] Redis non accessible publiquement (réseau interne Docker/K8s uniquement)
- [ ] `OIDC_CLIENT_SECRET` dans un secret K8s ou fichier `.env` non versionné
- [ ] Logs montés sur un volume persistant et monitorés
- [ ] Rotation des logs activée (`LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
