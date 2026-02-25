# Sécurité

## Authentification

LabOnDemand utilise des sessions côté serveur (pas de JWT).

### Flux de connexion locale

```
1. POST /api/v1/auth/login  {username, password}
2. Backend vérifie le hash bcrypt
3. Crée une session Redis (token 32 octets URL-safe)
4. Set-Cookie: session_id=<token>; HttpOnly; SameSite=Strict; [Secure]
5. Toutes les requêtes API suivantes portent ce cookie
```

### Flux SSO / OIDC

```
1. GET /api/v1/auth/sso/login → redirect vers l'IdP OIDC
2. IdP authentifie l'utilisateur → callback
3. GET /api/v1/auth/sso/callback?code=...
4. Backend échange le code contre un access_token + id_token
5. Extrait les claims (sub, email, nom, rôle via OIDC_ROLE_CLAIM)
6. Crée ou met à jour le compte local (auth_provider=oidc)
7. Crée une session comme pour l'auth locale
```

### Gestion des sessions

| Paramètre             | Défaut    | Description                              |
|-----------------------|-----------|------------------------------------------|
| `SESSION_EXPIRY_HOURS`| 24        | Durée de vie de la session               |
| `SECURE_COOKIES`      | true      | Cookie `Secure` (HTTPS requis si true)   |
| `SESSION_SAMESITE`    | Strict    | Protection CSRF                          |
| `COOKIE_DOMAIN`       | (vide)    | Restreindre le cookie à un domaine       |

### Stockage des sessions

- **Redis** (recommandé): `REDIS_URL=redis://redis:6379/0`
- **Mémoire** (fallback): sessions perdues au redémarrage, pas de scalabilité horizontale

## RBAC (Contrôle d'accès basé sur les rôles)

### Rôles

| Rôle    | Description                          |
|---------|--------------------------------------|
| student | Utilisateur standard, quotas faibles |
| teacher | Quotas plus élevés                   |
| admin   | Accès complet (CRUD utilisateurs, templates, runtime configs) |

### Enforcement

Les dépendances FastAPI `get_current_user()`, `is_admin()`, et `is_teacher_or_admin()`
dans `security.py` enforced sur chaque endpoint.

### Quotas par rôle (définis dans `k8s_utils.py`)

| Ressource       | student | teacher | admin |
|-----------------|---------|---------|-------|
| max deployments | 3       | 5       | 10    |
| CPU request     | 100m    | 200m    | 500m  |
| CPU limit       | 500m    | 1000m   | 2000m |
| RAM request     | 128Mi   | 256Mi   | 512Mi |
| RAM limit       | 512Mi   | 1Gi     | 2Gi   |

## Politique de mots de passe

Les mots de passe locaux doivent satisfaire:
- Au moins 12 caractères
- Au moins 1 majuscule, 1 minuscule, 1 chiffre, 1 caractère spécial

Enforcement dans `security.py:validate_password_strength()`.

## Sécurité des conteneurs K8s déployés

Tous les conteneurs créés par LabOnDemand appliquent le contexte de sécurité:

```yaml
securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
  seccompProfile:
    type: RuntimeDefault
```

## Rate limiting

`slowapi` applique un rate limit par IP sur les endpoints d'authentification
(`/api/v1/auth/login`, `/api/v1/auth/register`). Configurer via `limiter` dans
`security.py`.

## Endpoint de diagnostic

`/api/v1/diagnostic/test-auth` n'est accessible que si `DEBUG_MODE=true`.
Ne jamais activer `DEBUG_MODE` en production.

## Secrets K8s

Les mots de passe de base de données (MySQL, MariaDB, WordPress) sont générés
aléatoirement avec `secrets.token_urlsafe()` à chaque déploiement et stockés
dans des Secrets Kubernetes (type Opaque). Ils ne sont jamais loggés.
