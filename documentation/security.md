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

Redis reste sur un réseau interne Docker/Kubernetes. Dans `compose.yaml`, le
service Redis n'est pas publié sur l'hôte et utilise `REDIS_PASSWORD` via une
URL du type `redis://:<password>@redis:6379/0`.

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
| teacher | Quotas plus élevés, gère uniquement ses propres labs par défaut      |
| admin   | Accès complet : CRUD utilisateurs, templates, runtime configs, quotas |

### Enforcement

Les dépendances FastAPI `get_current_user()`, `is_admin()`, et `is_teacher_or_admin()`
dans `security.py` sont injectées sur chaque endpoint.

L'isolation des ressources est également appliquée côté Kubernetes :
- Namespace dédié par utilisateur (`labondemand-user-{id}`)
- `ResourceQuota` et `LimitRange` par namespace selon le rôle
- Labels obligatoires sur les ressources LabOnDemand : `managed-by=labondemand`,
  `user-id=<id>`, `app-type=<type>`, et `stack-name=<nom>` pour les stacks.
- Les opérations sensibles sur un lab (détails, identifiants, terminal, pause,
  reprise, suppression) vérifient que l'appelant est le propriétaire ou un admin.

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

## Isolation du Grader Pod (correction automatique)

Le Job qui exécute les tests d'un devoir est **hostile par hypothèse** (il fait tourner des
probes, voire un script fourni par l'enseignant) : il est donc fortement isolé. Le manifeste
généré par `backend/grader_service.py` garantit :

- **Aucun accès cluster** : `ServiceAccount` `grader-sa` **sans aucun RoleBinding** +
  `automountServiceAccountToken: false`. Pas de kubeconfig monté.
- **NetworkPolicy egress restreinte** : ingress refusé ; egress autorisé uniquement vers les
  namespaces de labs (`namespaceSelector: managed-by=labondemand`) et le DNS du cluster
  (port 53). Internet, l'API et l'infra sont injoignables depuis le grader.
- **Time-box & TTL** : `activeDeadlineSeconds`, `backoffLimit: 0`, `restartPolicy: Never`,
  `ttlSecondsAfterFinished` court (auto-suppression).
- **Ressources plafonnées** + même durcissement conteneur que ci-dessus (non-root,
  capabilities droppées, seccomp RuntimeDefault).
- **Script enseignant** : exécuté **uniquement** dans ce Job isolé, jamais côté API ni dans
  un pod privilégié ; taille bornée (`custom_script` ≤ 50 000 caractères).

> L'enforcement de la NetworkPolicy dépend du CNI du cluster. Les autres garde-fous (SA sans
> droits, pas de kubeconfig, quotas, time-box, TTL) restent actifs même sans support
> NetworkPolicy. Détails complets : [`grader-pod.md`](grader-pod.md).

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

Le `kubeconfig.yaml` local est un secret opérationnel. Il doit rester hors
versioning, être monté en lecture seule en développement, et être remplacé en
production par une configuration in-cluster ou un service account à droits
minimaux.

---

## CORS et proxy HTTP

Les origines autorisées sont configurées côté FastAPI via `CORS_ORIGINS`.
Le proxy Nginx relaie les requêtes API sans refléter arbitrairement l'en-tête
`Origin` avec des cookies. Toute nouvelle origine frontend doit être ajoutée
explicitement à la configuration applicative.

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

## RBAC pédagogique (classes et devoirs)

Le système de classes introduit des règles RBAC supplémentaires au-dessus du RBAC K8s.

### Accès teacher

Un teacher peut :
- Créer, modifier, archiver ses propres classes (`owner_id = current_user.id`)
- Inscrire et retirer des étudiants de ses classes
- Créer, modifier, archiver des devoirs dans ses classes
- Déclencher un déploiement en masse pour toute la classe (deploy-all)
- Définir la batterie de tests d'un devoir (`GradingSpec`) et lancer les tests (`test-now`, `run-tests-all`)
- Consulter toutes les soumissions de ses devoirs, avec les résultats de tests détaillés (non filtrés)
- Noter manuellement une soumission (grade + feedback), en s'appuyant sur la note suggérée

Un teacher **ne peut pas** :
- Voir ou modifier les classes d'un autre teacher
- Accéder aux labs K8s des étudiants directement (sauf admin)

### Accès student

Un student peut :
- Voir uniquement les devoirs des classes où il est inscrit (`enrolled_at IS NOT NULL`, `removed_at IS NULL`)
- Soumettre une fois par devoir (UNIQUE `assignment_id, user_id` — la soumission est mise à jour si elle existe déjà)
- Lancer ses propres tests en self-check (`run-tests`) si `grading_mode ≠ none`
- Consulter son propre résultat de correction, avec la visibilité limitée par `Probe.visibility` (sondes `teacher_only` masquées)

### Visibilité des résultats de correction (GradingSpec)

Chaque sonde (`Probe`) dans une `GradingSpec` a un niveau de visibilité :

| Visibilité | Visible par l'étudiant | Visible par l'enseignant |
|---|---|---|
| `student` | oui (nom, statut, message, sortie) | oui |
| `summary` | pass/fail seulement (sans message ni sortie) | oui complet |
| `teacher_only` | non (masquée) | oui complet |

Cela permet de masquer les sondes de sécurité ou les critères de notation interne à l'enseignant.
Le filtrage est appliqué côté serveur (`grader_service.filter_results_for_student`) pour toutes
les réponses destinées à l'étudiant.

---

## Audit trail

Toutes les actions sensibles sont tracées dans `logs/audit.log` :

### Actions système et accès

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
| `oidc_user_created` | username, role |

### Actions K8s

| Événement | Champs |
|-----------|--------|
| `deployment_deleted` | namespace, name, user_id, deployment_type |
| `user_namespace_cleanup` | user_id, namespace, status |

### Actions pédagogiques

| Événement | Champs |
|-----------|--------|
| `classroom_created` | classroom_id, name, owner_id |
| `classroom_archived` | classroom_id, name, owner_id |
| `students_enrolled` | classroom_id, count, enrolled_by |
| `assignment_created` | assignment_id, classroom_id, title, grading_mode |
| `assignment_bulk_spawn` | assignment_id, total, ok, skipped, error |
| `submission_created` | submission_id, assignment_id, user_id, is_late |
| `submission_graded` | submission_id, assignment_id, graded_by, grade |

---

## Checklist sécurité production

- [ ] `SECURE_COOKIES=True` (HTTPS uniquement)
- [ ] `SESSION_SAMESITE=Strict`
- [ ] `DEBUG_MODE=False`
- [ ] `ADMIN_DEFAULT_PASSWORD` changé dès le premier démarrage
- [ ] Redis non accessible publiquement et protégé par `REDIS_PASSWORD`
- [ ] `CORS_ORIGINS` limité aux domaines frontend attendus
- [ ] `kubeconfig.yaml` local non versionné, droits restreints, rotation effectuée si exposé
- [ ] `OIDC_CLIENT_SECRET` dans un secret K8s ou fichier `.env` non versionné
- [ ] Logs montés sur un volume persistant et monitorés
- [ ] Rotation des logs activée (`LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
