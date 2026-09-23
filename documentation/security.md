---
title: Sécurité LabOnDemand
summary: Modèle de sécurité complet — sessions serveur, CSRF, limitation de débit, isolation Kubernetes par namespace, headers HTTP, RBAC et recommandations pour la production.
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
1. POST /api/v1/auth/login  {username, password}  + X-Requested-With (voir CSRF)
2. Limitation de débit : par IP, puis seuil d'échecs par nom d'utilisateur
   (429 + Retry-After, sans vérifier le mot de passe)
3. Backend vérifie le hash bcrypt (même coût si le nom est inconnu)
4. Crée une session Redis (token 32 octets URL-safe, TTL = SESSION_EXPIRY_HOURS)
5. Set-Cookie: session_id=<token>; HttpOnly; SameSite=Lax; Path=/; [Secure]
6. Toutes les requêtes API suivantes portent ce cookie automatiquement
```

Le jeton n'est renvoyé ni dans le corps de la réponse ni dans un en-tête :
seul le cookie HttpOnly le transporte, hors de portée de JavaScript.

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
| `SESSION_SAMESITE`     | Lax      | `Lax`, `Strict` ou `None` (voir ci-dessous) |
| `COOKIE_DOMAIN`        | (vide)   | Vide = cookie limité à l'hôte (recommandé) |

L'API refuse de démarrer si la configuration des cookies est dangereuse
(`validate_cookie_settings()` dans `backend/session.py`) : valeur inconnue de
`SESSION_SAMESITE`, `SameSite=None` sans `SECURE_COOKIES=True`, ou
`COOKIE_DOMAIN` qui englobe `INGRESS_BASE_DOMAIN`. `Lax` est le défaut :
`Strict` fait perdre la session au retour de l'IdP SSO et sur les liens
entrants, sans gain réel puisque les requêtes mutantes sont protégées par le
middleware CSRF.

### Cookie de session et domaine des labs

Les labs sont servis sur `<app>-<id>-u<user>.<INGRESS_BASE_DOMAIN>` et leur
contenu est contrôlé par l'étudiant (JavaScript arbitraire). Deux règles :

- **`COOKIE_DOMAIN` ne doit jamais englober `INGRESS_BASE_DOMAIN`** (même
  domaine ou domaine parent) : le navigateur enverrait le cookie de session de
  chaque visiteur au lab, et son propriétaire pourrait le lire. Exemple refusé
  au démarrage : `COOKIE_DOMAIN=univ.fr` avec `INGRESS_BASE_DOMAIN=labs.univ.fr`.
  Laisser `COOKIE_DOMAIN` vide limite le cookie à l'hôte exact de l'application.
- **Servir les labs sur un domaine enregistrable distinct** (recommandé), par
  exemple `labondemand.univ.fr` pour l'application et `univ-labs.fr` pour les
  labs, plutôt que sur un domaine frère comme `labs.univ.fr`. Entre
  sous-domaines d'un même domaine enregistrable, un lab reste « same-site » :
  `SameSite` ne le filtre pas, et il peut poser des cookies sur le domaine
  parent (« cookie tossing »), par exemple imposer son propre `session_id`
  pour connecter la victime à un compte qu'il contrôle. Seul un domaine
  enregistrable distinct supprime ces vecteurs. La protection CSRF de l'API
  (ci-dessous) ne dépend pas de `SameSite` et reste active dans tous les cas.

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

### Stockage des mots de passe

Hachage **bcrypt** (`$2b$`, coût 12) via la bibliothèque `bcrypt` utilisée
directement (`backend/password_hashing.py`, exposé par `security.py`) ; passlib,
non maintenu, a été retiré. Les hachages existants (`$2b$`, `$2a$`, `$2y$`)
restent valides sans migration.

bcrypt n'utilise que les **72 premiers octets** (UTF-8) du mot de passe. Comme
passlib auparavant, l'application tronque explicitement à 72 octets, au hachage
comme à la vérification : les comptes créés avec un mot de passe plus long
continuent de se connecter avec le même mot de passe. Un mot de passe contenant
un caractère NUL est refusé ; un hachage vide (comptes SSO) ou invalide ne
vérifie jamais.

---

## Limitation de débit

Implémentation : `backend/rate_limit.py` (slowapi + limits).

| Protection | Clé | Défaut | Variable |
|------------|-----|--------|----------|
| `POST /api/v1/auth/login` | IP cliente | 30 / minute | `RATE_LIMIT_LOGIN` |
| Échecs de connexion | nom d'utilisateur, toutes IP | 10 / 15 minutes | `RATE_LIMIT_LOGIN_FAILURES` |
| `POST /api/v1/k8s/deployments`, `POST /api/v1/k8s/pods` | utilisateur (IP à défaut) | 10 / 5 minutes | `RATE_LIMIT_DEPLOY` |

- **Réponse** : `429 Too Many Requests` avec l'en-tête `Retry-After`
  (secondes) et un message traduit ; événements d'audit `rate_limit_exceeded`
  et `login_throttled`.
- **Par IP, volontairement large** : toute une salle de TP peut sortir par la
  même IP (NAT). Relever `RATE_LIMIT_LOGIN` si plus de 30 personnes se
  connectent dans la même minute derrière un même NAT.
- **Par nom d'utilisateur** : freine les attaques distribuées sur un compte.
  Une fois le seuil atteint, la tentative est refusée **avant** toute
  vérification du mot de passe, même correct, jusqu'à la fin de la fenêtre
  (ouverte au premier échec). Une connexion réussie remet le compteur à zéro.
  Les noms inconnus sont comptés comme les autres et subissent la même
  vérification bcrypt qu'un mauvais mot de passe : ni la réponse ni sa durée
  ne révèlent l'existence d'un compte. Le nom est normalisé comme le fait la
  collation MariaDB (casse, accents, espaces, caractères invisibles) ; seule
  son empreinte SHA-256 est stockée.
- **Compromis assumé** : connaissant un nom d'utilisateur, un tiers peut
  bloquer ses connexions locales pendant la fenêtre. Le blocage cesse seul ;
  ajuster `RATE_LIMIT_LOGIN_FAILURES` si besoin.
- **Stockage** : Redis (`REDIS_URL`, ou `RATE_LIMIT_STORAGE_URI` pour un
  stockage dédié) : compteurs partagés entre workers et conservés au
  redémarrage de l'API. Si Redis est injoignable, les compteurs passent en
  mémoire, par processus (limites toujours appliquées), et Redis est re-testé
  périodiquement ; si même ce repli échoue, la requête passe plutôt que de
  renvoyer une erreur 500. Les sessions dépendant aussi de Redis, une panne
  Redis bloque de toute façon les connexions.
- **Syntaxe** : `30/minute`, `10/5minute`, plusieurs limites séparées par `;`
  (`30/minute;200/hour`). Une valeur invalide empêche l'API de démarrer
  (slowapi ignorerait sinon la limite sans le signaler).

### IP cliente derrière nginx

uvicorn (`--proxy-headers`) remplace l'IP du socket par celle de
`X-Forwarded-For` **uniquement** si la connexion vient d'une adresse listée
dans `FORWARDED_ALLOW_IPS`. Dans `compose.yaml`, c'est par défaut l'IP fixe
de nginx (`FRONTEND_IPV4_ADDRESS`, sur le sous-réseau `LOD_NETWORK_SUBNET`).
Derrière un répartiteur de charge supplémentaire, ajouter son IP (liste
séparée par des virgules). **Jamais `*`** : uvicorn retiendrait alors
l'entrée de `X-Forwarded-For` choisie par le client, ce qui contourne toute
limite par IP. Le port de l'API n'est publié que sur `127.0.0.1`
(`API_BIND_ADDRESS`) : le trafic passe par nginx.

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

## Protection CSRF

Le navigateur joint le cookie de session à toute requête, y compris quand un
autre site la déclenche. Le middleware `backend/csrf.py` (enregistré dans
`main.py`, entre CORS et la journalisation) impose donc deux contrôles
cumulatifs à **toute requête mutante** (méthode autre que GET, HEAD, OPTIONS,
TRACE) sous `/api/`, connexion comprise (contre le « login CSRF ») :

1. **En-tête `X-Requested-With: XMLHttpRequest`** obligatoire. Un formulaire
   HTML ou un `fetch` « simple » ne peut pas le poser ; un `fetch` inter-origines
   qui le pose déclenche un preflight CORS, refusé pour toute origine non
   listée. Le frontend l'ajoute à chaque appel (`frontend-app/src/lib/api.ts`).
2. **Origine de confiance** : si `Origin` est présent, il doit être de
   confiance (`null` est refusé) ; sinon, l'origine du `Referer` est vérifiée.
   En l'absence des deux (client non navigateur), l'en-tête suffit.

Refus : `403` avec `"error": "csrf_failed"` et événement d'audit
`csrf_rejected`. Scripts et `curl` doivent donc envoyer l'en-tête :

```bash
curl -X POST -H "X-Requested-With: XMLHttpRequest" -H "Cookie: session_id=<tok>" …
```

Le « double submit cookie » est écarté : un lab servi sur un sous-domaine
pourrait écraser ce cookie. Les routes GET n'ont pas d'effet de bord
exploitable ; seule `GET /api/v1/k8s/deployments/labondemand` écrit en base
(elle recrée, de façon idempotente, les enregistrements manquants des labs de
l'appelant).

### Origines de confiance

- chaque entrée de `CORS_ORIGINS` (`*` est ignoré, avec un avertissement
  dans les journaux : ce n'est pas une origine) ;
- l'origine de `FRONTEND_BASE_URL`, si elle est définie ;
- l'origine de la requête elle-même : schéma (`X-Forwarded-Proto`, lu
  uniquement depuis un proxy de confiance) et en-tête `Host` transmis par
  nginx, port compris. `X-Forwarded-Host` n'est jamais utilisé ;
- la variante `https://` de ce même `Host` (jamais la variante `http://`).

L'interface servie par nginx (même hôte que `/api/`) fonctionne donc sans
configuration, y compris derrière un terminateur TLS (reverse proxy, load
balancer) placé devant nginx : nginx transmet alors `X-Forwarded-Proto: http`
mais le navigateur annonce `Origin: https://…`, d'où la variante https.

**En production, définissez `FRONTEND_BASE_URL`** (URL publique de
l'interface, p. ex. `https://labondemand.example.fr`) : c'est l'origine de
confiance explicite, indépendante des en-têtes transmis par les proxys, et la
cible de redirection après connexion SSO. Toute autre origine frontend (autre
hôte ou port, serveur de développement) doit être ajoutée à `CORS_ORIGINS`.
N'y ajoutez jamais un domaine de labs.

### Terminal WebSocket

La poignée de main de `/api/v1/k8s/terminal/{namespace}/{pod}` exige un en-tête
`Origin` de confiance (même liste) ; sinon la connexion est fermée avec le code
`4403` et l'événement `websocket_origin_rejected` est journalisé. Sans ce
contrôle, une page tierce ouverte par un utilisateur connecté pourrait piloter
un shell dans ses labs (les WebSocket ne sont pas soumises à CORS).

### State OIDC

Un `state` aléatoire (`secrets.token_urlsafe(32)`) est généré au démarrage du
flow OIDC, stocké dans un cookie HttpOnly (TTL 10 min), et vérifié au retour
du callback. Toute non-concordance retourne `400 Bad Request`. Les routes
`GET /sso/login` et `GET /sso/callback` modifient l'état (cookie, compte,
session) par nécessité du protocole ; ce `state` les protège.

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
| `login_throttled` | username, client_ip, retry_after |
| `rate_limit_exceeded` | method, path, limit, client_ip, user_id, retry_after |
| `csrf_rejected` | method, path, reason, origin, referer_origin, host, client_ip |
| `websocket_origin_rejected` | path, reason, origin, host, client_ip |
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
- [ ] `SESSION_SAMESITE=Lax` (défaut ; `Strict` casse le retour SSO)
- [ ] `COOKIE_DOMAIN` vide, labs servis sur un domaine enregistrable distinct
- [ ] `DEBUG_MODE=False`
- [ ] `ADMIN_DEFAULT_PASSWORD` changé dès le premier démarrage
- [ ] Redis non accessible publiquement et protégé par `REDIS_PASSWORD`
- [ ] `CORS_ORIGINS` limité aux origines frontend attendues (ni `*`, ni domaine de labs)
- [ ] `FORWARDED_ALLOW_IPS` limité aux proxys (jamais `*`), port API publié sur `127.0.0.1`
- [ ] `RATE_LIMIT_*` adaptés à la taille des salles derrière un même NAT
- [ ] `kubeconfig.yaml` local non versionné, droits restreints, rotation effectuée si exposé
- [ ] `OIDC_CLIENT_SECRET` dans un secret K8s ou fichier `.env` non versionné
- [ ] Logs montés sur un volume persistant et monitorés
- [ ] Rotation des logs activée (`LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
