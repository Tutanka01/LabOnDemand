# Logs d'Audit — Guide complet

Ce document décrit en détail la fonctionnalité **Logs d'Audit** de LabOnDemand :
son architecture, les événements tracés, l'API backend, l'interface d'administration
et les bonnes pratiques d'exploitation.

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Événements audités](#2-événements-audités)
3. [Format des entrées](#3-format-des-entrées)
4. [API backend](#4-api-backend)
   - [GET /api/v1/audit-logs](#get-apiv1audit-logs)
   - [GET /api/v1/audit-logs/stats](#get-apiv1audit-logsstats)
5. [Interface d'administration](#5-interface-dadministration)
   - [KPI cards](#kpi-cards)
   - [Graphique d'activité](#graphique-dactivité)
   - [Filtres](#filtres)
   - [Tableau des logs](#tableau-des-logs)
   - [Modal de détail](#modal-de-détail)
   - [Export JSON](#export-json)
6. [Filtres et pagination — référence](#6-filtres-et-pagination--référence)
7. [Catégories d'événements](#7-catégories-dévénements)
8. [Exemples pratiques](#8-exemples-pratiques)
9. [Sécurité et accès](#9-sécurité-et-accès)
10. [Exploitation en production](#10-exploitation-en-production)
11. [Références fichiers](#11-références-fichiers)

---

## 1. Vue d'ensemble

Le fichier `logs/audit.log` est généré en continu par le backend FastAPI.
Chaque action sensible (connexion, modification d'utilisateur, déploiement, etc.)
y est écrite sous forme de **JSON structuré en une ligne** par le logger
`labondemand.audit`.

Avant cette fonctionnalité, la seule façon de consulter ces logs était une connexion
SSH au serveur suivi d'un `cat` ou `tail -f` du fichier.

La fonctionnalité **Logs d'Audit** ajoute :

- Un **endpoint API** sécurisé pour lire, filtrer et exporter les logs
- Un **onglet dédié** dans le dashboard d'administration (`admin.html#audit`)
- Des **statistiques** en temps réel (KPI, histogramme 7 jours, top événements)

```
┌─────────────────────────────────────────────────────────────────┐
│  Admin Dashboard  ─────────────────────────────── /admin.html   │
│                                                                  │
│  [Utilisateurs] [Templates] [Runtimes] [Parc des Labs] [Audit]  │
│                                                         ▲        │
│                                              Onglet Audit ────── │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  KPI Cards : Total · Auth · Users · Déploiements · Warn  │    │
│  │  Sparkbar 7 jours                                        │    │
│  │  Filtres : search · catégorie · event · niveau · dates   │    │
│  │  Tableau paginé (50/page)                                │    │
│  │  Modal de détail au clic sur une ligne                   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │ window.api()
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  GET /api/v1/audit-logs?page=1&search=…&category=auth&…        │
│  GET /api/v1/audit-logs/stats                                   │
│  (admin only — cookie session_id)                               │
└─────────────────────────────────────────────────────────────────┘
         │ lecture directe du fichier
         ▼
   logs/audit.log  (JSON, une ligne par événement)
```

---

## 2. Événements audités

Tous les événements écrits dans `audit.log` par `logging.getLogger("labondemand.audit")` :

### Authentification

| Événement | Déclencheur | Champs clés |
|---|---|---|
| `login_success` | Connexion réussie | `user_id`, `username`, `role`, `session_id`, `client_ip` |
| `login_failed` | Échec de connexion | `username`, `reason`, `client_ip` |
| `logout` | Déconnexion | `user_id`, `username`, `role`, `session_id` |

### Gestion des utilisateurs

| Événement | Déclencheur | Champs clés |
|---|---|---|
| `user_registered` | Création d'un compte | `user_id`, `username`, `role`, `is_active` |
| `user_updated` | Modification d'un compte | `user_id`, `username`, `role`, `updated_by` |
| `user_deleted` | Suppression d'un compte | `user_id`, `username`, `sessions_revoked`, `namespace_deleted` |
| `user_self_update` | Mise à jour de son propre profil | `user_id`, `username`, `fields[]` |
| `password_changed` | Changement de mot de passe | `user_id`, `username`, `self_service` |
| `quota_override_set` | Dérogation de quota accordée | `target_user_id`, `admin_user_id`, `max_apps`, `max_cpu_m`, `max_mem_mi`, `expires_at` |
| `users_imported_csv` | Import CSV en masse | `created`, `errors`, `skipped` |

### Déploiements

| Événement | Déclencheur | Champs clés |
|---|---|---|
| `deployment_created` | Nouveau lab créé | `deployment_name`, `deployment_type`, `namespace`, `user_id`, `username`, `node_port` |
| `deployment_deleted` | Lab supprimé | `namespace`, `name`, `user_id`, `deployment_type`, `delete_service`, `delete_persistent` |
| `deployment_paused` | Lab mis en pause | `namespace`, `display_name`, `user_id`, `stack_mode`, `components[]` |
| `deployment_resumed` | Lab repris | `namespace`, `display_name`, `user_id`, `stack_mode`, `components[]` |

---

## 3. Format des entrées

Chaque ligne de `audit.log` est un objet JSON **compact** (pas d'indentation) :

```json
{
  "timestamp":  "2026-02-26T09:18:16.140Z",
  "level":      "INFO",
  "logger":     "labondemand.audit",
  "message":    "deployment_created",
  "request_id": "732732e6-4a1b-4c3d-9f2a-1e3b5c7d9e0f",
  "deployment_name": "vscode-alice-1",
  "deployment_type": "vscode",
  "namespace":  "labondemand-user-42",
  "user_id":    42,
  "username":   "alice",
  "node_port":  31042,
  "replicas":   1
}
```

### Description des champs communs

| Champ | Type | Description |
|---|---|---|
| `timestamp` | string ISO 8601 UTC | Horodatage de l'événement (millisecondes) |
| `level` | `INFO` \| `WARNING` \| `ERROR` | Niveau de sévérité |
| `logger` | string | Toujours `labondemand.audit` pour ce fichier |
| `message` | string | Slug de l'événement (ex: `login_success`) |
| `request_id` | UUID | Identifiant de la requête HTTP — permet de corréler avec `access.log` |
| _autres_ | mixte | Champs spécifiques à l'événement (voir tableau §2) |

### Niveaux utilisés

| Niveau | Signification dans le contexte audit |
|---|---|
| `INFO` | Action normale, réussie |
| `WARNING` | Tentative échouée ou action à surveiller (ex: `login_failed`) |
| `ERROR` | Erreur inattendue lors d'une action sensible |

---

## 4. API backend

Le router est défini dans `backend/routers/audit_logs.py` et enregistré sous
le préfixe `/api/v1/audit-logs`. **Tous les endpoints sont réservés aux admins**
(dépendance `is_admin` de `security.py`).

### GET /api/v1/audit-logs

Liste paginée des entrées d'`audit.log`, du plus récent au plus ancien.

#### Paramètres de requête

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `page` | int ≥ 1 | `1` | Numéro de page |
| `page_size` | int 1–500 | `50` | Entrées par page |
| `search` | string | — | Recherche fulltext dans le JSON de chaque entrée |
| `category` | string | — | `auth` \| `users` \| `deployments` — groupe d'événements |
| `event` | string | — | Slug exact de l'événement (ex: `login_failed`) |
| `level` | string | — | `INFO` \| `WARNING` \| `ERROR` |
| `username` | string | — | Filtre partiel sur `username` ou `target_username` |
| `date_from` | datetime ISO 8601 | — | Borne de début (incluse) |
| `date_to` | datetime ISO 8601 | — | Borne de fin (incluse) |
| `export` | `json` | — | Si présent, retourne un fichier JSON téléchargeable |

#### Réponse (application/json)

```json
{
  "total":      142,
  "page":       1,
  "page_size":  50,
  "pages":      3,
  "entries": [
    {
      "timestamp":    "2026-02-26T09:18:16.140Z",
      "level":        "INFO",
      "logger":       "labondemand.audit",
      "message":      "login_success",
      "request_id":   "732732e6-...",
      "user_id":      1,
      "username":     "admin",
      "role":         "admin",
      "client_ip":    "192.168.1.10",
      "event_label":  "Connexion"
    }
    // ...
  ],
  "available_events": ["login_success", "login_failed", "logout", "..."],
  "categories": ["auth", "users", "deployments"]
}
```

Le champ `event_label` est ajouté par le backend — c'est la traduction française du slug.

#### Mode export (téléchargement)

Ajouter `?export=json` retourne tous les résultats filtrés (jusqu'à 500 entrées)
avec un header `Content-Disposition` pour déclencher le téléchargement :

```
Content-Disposition: attachment; filename="audit-export-20260226-091816.json"
Content-Type: application/json
```

#### Exemples cURL

```bash
# Connexions échouées des dernières 24h
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?event=login_failed&date_from=2026-02-25T00:00:00"

# Toutes les actions sur l'utilisateur alice
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?username=alice"

# Alertes et erreurs uniquement
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?level=WARNING"

# Export JSON de tous les déploiements du mois
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?category=deployments&date_from=2026-02-01T00:00:00&export=json" \
  -o audit-deploiements-fevrier.json

# Page 2, 100 entrées par page, recherche fulltext
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?search=labondemand-user-42&page=2&page_size=100"
```

---

### GET /api/v1/audit-logs/stats

Statistiques globales calculées sur l'intégralité du fichier `audit.log`.
Aucun paramètre de filtre (toujours calculé sur tout le fichier).

#### Réponse

```json
{
  "total": 1543,
  "last_event_at": "2026-02-26T09:18:16.140Z",
  "by_level": {
    "INFO":    1520,
    "WARNING":   21,
    "ERROR":      2
  },
  "by_category": {
    "auth":        620,
    "users":       184,
    "deployments": 739,
    "other":         0
  },
  "top_events": [
    { "event": "deployment_created", "label": "Déploiement créé",  "count": 501 },
    { "event": "login_success",      "label": "Connexion",         "count": 480 },
    { "event": "deployment_deleted", "label": "Déploiement supprimé", "count": 238 },
    { "event": "logout",             "label": "Déconnexion",       "count": 140 }
  ],
  "activity_7d": [
    { "date": "2026-02-20", "count": 89 },
    { "date": "2026-02-21", "count": 112 },
    { "date": "2026-02-22", "count": 45 },
    { "date": "2026-02-23", "count": 0  },
    { "date": "2026-02-24", "count": 0  },
    { "date": "2026-02-25", "count": 201 },
    { "date": "2026-02-26", "count": 67 }
  ]
}
```

---

## 5. Interface d'administration

L'onglet **Logs d'Audit** est accessible depuis `http://<host>/admin.html#audit`.
Il se charge de façon différée (lazy) à la première ouverture, comme l'onglet
"Parc des Labs".

### KPI cards

Cinq cartes en haut de page donnent une vision instantanée de l'activité :

| Carte | Couleur | Contenu |
|---|---|---|
| **Total** | Bleu | Nombre total d'entrées dans `audit.log` |
| **Authentification** | Violet | Connexions + déconnexions + échecs |
| **Utilisateurs** | Vert | Créations, modifications, suppressions, imports |
| **Déploiements** | Ambre | Labs créés, supprimés, mis en pause, repris |
| **Alertes** | Rouge | Somme des niveaux WARNING + ERROR |

### Graphique d'activité

Un **mini graphique en barres** (sparkbar) affiche le nombre d'événements par jour
sur les 7 derniers jours calendaires. Chaque barre est accompagnée du jour de la semaine
et d'un tooltip au survol indiquant la date complète et le nombre d'événements.

### Filtres

Les filtres sont cumulatifs — tous ceux cochés s'appliquent simultanément.
Le résultat est rafraîchi immédiatement (debounce 350ms pour les champs texte).

| Filtre | Type | Comportement |
|---|---|---|
| **Recherche** | Texte | Fulltext dans le JSON complet de chaque entrée |
| **Catégorie** | Sélect | Groupe d'événements (`auth`, `users`, `deployments`) |
| **Événement** | Sélect | Slug exact d'un événement spécifique |
| **Niveau** | Sélect | `INFO`, `WARNING` ou `ERROR` |
| **Utilisateur** | Texte | Correspondance partielle sur `username` ou `target_username` |
| **Du / Au** | Date | Plage de dates (bornes incluses) |

Le bouton **Réinitialiser** efface tous les filtres d'un coup.

Le sélecteur "Événement" est peuplé dynamiquement depuis la réponse de `/stats`
et se réinitialise automatiquement quand la catégorie change.

### Tableau des logs

Le tableau affiche **50 entrées par page** (côté serveur), du plus récent au plus ancien.

| Colonne | Description |
|---|---|
| **Horodatage** | Date + heure UTC formatés en français |
| **Niveau** | Badge coloré : `INFO` (bleu) · `WARN` (ambre) · `ERR` (rouge) |
| **Événement** | Badge avec icône contextuelle et libellé français |
| **Détails** | Résumé des champs métier (chips inline) |
| **Utilisateur** | `username` ou `target_username` si disponible |
| **IP Client** | Adresse IP de l'émetteur de la requête |

Chaque ligne est **cliquable** et ouvre le modal de détail.

**Badges d'événements — couleurs par catégorie :**

| Couleur | Catégorie |
|---|---|
| Violet | Authentification (connexion, déconnexion) |
| Bleu | Gestion des utilisateurs |
| Ambre | Déploiements |
| Vert | Quotas |
| Rouge | Actions destructives (suppression, échec connexion) |
| Gris | Autres |

### Modal de détail

Un clic sur une ligne ouvre un panneau latéral modal affichant **tous les champs JSON**
de l'entrée dans un tableau à deux colonnes (Champ / Valeur).

- Les objets imbriqués sont affichés en JSON indenté avec coloration de fond
- Le champ `event_label` est remplacé par le badge lisible dans l'en-tête
- Le modal se ferme avec `Échap`, clic hors du panneau ou sur la croix

### Export JSON

Le bouton **Exporter JSON** télécharge un fichier `.json` contenant toutes les entrées
correspondant aux filtres courants (jusqu'à 500 entrées par export).

Le nom du fichier inclut la date et l'heure de l'export :
```
audit-export-20260226-091816.json
```

---

## 6. Filtres et pagination — référence

### Logique de filtrage (côté backend)

Les filtres sont appliqués **en mémoire** après lecture du fichier, dans cet ordre :

1. Filtre `event` (slug exact sur le champ `message`)
2. Filtre `category` (appartenance à la liste d'événements de la catégorie)
3. Filtre `level`
4. Filtre `username` (recherche partielle, insensible à la casse, sur `username` et `target_username`)
5. Filtre `date_from` / `date_to` (sur le champ `timestamp` parsé en UTC)
6. Filtre `search` (fulltext sur la sérialisation JSON complète de l'entrée)

Les filtres `event` et `category` sont mutuellement redondants :
spécifier les deux revient à chercher un événement ET à vérifier qu'il appartient
à la catégorie (comportement ET logique).

### Pagination côté serveur

La pagination est réalisée côté serveur : seule la tranche demandée est retournée.
Le frontend ne charge pas tous les logs en mémoire.

```
total    = 1543 entrées filtrées
page     = 2
page_size= 50
pages    = ⌈1543 / 50⌉ = 31

offset   = (2 - 1) × 50 = 50
slice    = entries[50:100]
```

---

## 7. Catégories d'événements

Les catégories sont définies dans `backend/routers/audit_logs.py` :

```python
CATEGORIES = {
    "auth": [
        "login_success", "login_failed", "logout"
    ],
    "users": [
        "user_registered", "user_updated", "user_deleted",
        "user_self_update", "password_changed",
        "quota_override_set", "users_imported_csv"
    ],
    "deployments": [
        "deployment_created", "deployment_deleted",
        "deployment_paused", "deployment_resumed"
    ],
}
```

Tout événement ne correspondant à aucune catégorie tombe dans `other`.
Pour ajouter une catégorie, modifier ce dictionnaire et redémarrer le backend.

---

## 8. Exemples pratiques

### Surveiller les connexions échouées

Identifier une attaque par force brute ou des identifiants erronés en masse :

**Via l'UI** : onglet Audit → Catégorie : `Authentification` → Événement : `Échec connexion`

**Via l'API** :
```bash
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?event=login_failed&level=WARNING"
```

**Via le fichier** :
```bash
grep '"message":"login_failed"' logs/audit.log | jq '{ts: .timestamp, user: .username, ip: .client_ip, reason: .reason}'
```

---

### Retrouver qui a supprimé un utilisateur

**Via l'UI** : onglet Audit → Événement : `Suppression utilisateur` → Utilisateur : `alice`

**Via l'API** :
```bash
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?event=user_deleted&username=alice"
```

**Via le fichier** :
```bash
grep '"message":"user_deleted"' logs/audit.log | grep '"username":"alice"' | jq .
```

---

### Auditer l'activité d'un utilisateur spécifique

Toutes les actions tracées pour `bob` (connexions, modifications de profil, déploiements) :

**Via l'UI** : onglet Audit → Utilisateur : `bob`

**Via l'API** :
```bash
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?username=bob&page_size=200"
```

---

### Exporter les logs d'un incident

Exporter tous les événements d'un jour donné pour analyse externe :

```bash
# Via l'UI : définir Du=2026-02-20 Au=2026-02-20, puis clic "Exporter JSON"

# Via l'API :
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?date_from=2026-02-20T00:00:00&date_to=2026-02-20T23:59:59&export=json" \
  -o incident-20260220.json
```

---

### Vérifier les dérogations de quota accordées

```bash
curl -H "Cookie: session_id=<tok>" \
  "http://localhost:8000/api/v1/audit-logs?event=quota_override_set"
```

Chaque entrée contient `target_user_id`, `admin_user_id`, `max_apps`, `max_cpu_m`,
`max_mem_mi` et `expires_at` — permettant de savoir qui a accordé quoi, à qui et jusqu'à quand.

---

### Corréler un événement audit avec une requête HTTP

Chaque entrée audit contient un `request_id`. Utiliser ce même identifiant pour
retrouver la requête HTTP correspondante dans `access.log` :

```bash
# 1. Trouver le request_id dans audit.log
REQUEST_ID=$(grep '"message":"user_deleted"' logs/audit.log | tail -1 | jq -r '.request_id')

# 2. Retrouver la requête HTTP dans access.log
grep "$REQUEST_ID" logs/access.log | jq '{method, path, status_code, duration_ms, client_ip}'
```

---

## 9. Sécurité et accès

### Contrôle d'accès

Les deux endpoints `/api/v1/audit-logs` et `/api/v1/audit-logs/stats` exigent :
- Une session valide (cookie `session_id` HttpOnly)
- Le rôle `admin` (vérifié par la dépendance `is_admin` dans `security.py`)

Tout accès sans session ou avec un rôle insuffisant retourne `401` ou `403`.

### Ce que les logs peuvent révéler

Les entrées d'audit contiennent des données potentiellement sensibles :
- Adresses IP des clients
- Noms d'utilisateur
- IDs de session (tronqués, mais présents)
- Structures des namespaces Kubernetes

**Recommandations** :
- Restreindre l'accès physique au fichier `logs/audit.log` sur le serveur
- Ne pas exposer l'endpoint `/api/v1/audit-logs` sans authentification
- En production, monter `logs/` sur un volume chiffré ou sécurisé
- Inclure `audit.log` dans votre politique de rétention et de conformité RGPD si applicable

### Ce qui n'est pas loggé

Pour des raisons de sécurité, les éléments suivants ne sont **jamais** écrits dans les logs :
- Les mots de passe (en clair ou hashés)
- Les secrets Kubernetes générés
- Les tokens de session complets (seul un préfixe tronqué peut apparaître dans `access.log`)
- Les clés OIDC ou secrets OAuth

---

## 10. Exploitation en production

### Rétention et rotation

`audit.log` dispose de sa propre configuration de rotation, indépendante des fichiers applicatifs (`app.log`, `access.log`). Elle est pilotée par deux variables d'environnement dédiées :

```
AUDIT_LOG_MAX_BYTES    (défaut: 10 MiB)  → seuil avant rotation
AUDIT_LOG_BACKUP_COUNT (défaut: 30)      → archives conservées : audit.log.1 … audit.log.30
```

Avec ces valeurs par défaut, la capacité totale est **~310 MiB** d'historique audit.

Les fichiers applicatifs continuent d'utiliser `LOG_MAX_BYTES` (5 MiB) et `LOG_BACKUP_COUNT` (10), soit ~55 MiB chacun.

**Capacité totale du dossier `logs/` avec les défauts :**

| Fichier | Archive max | Archives | Capacité |
|---------|------------|----------|----------|
| `app.log` | 5 MiB | 10 | ~55 MiB |
| `access.log` | 5 MiB | 10 | ~55 MiB |
| `audit.log` | 10 MiB | 30 | ~310 MiB |
| **Total** | | | **~420 MiB** |

**Lecture multi-fichiers dans l'UI :**
L'API lit automatiquement `audit.log` ET tous les fichiers rotatés (`audit.log.1` … `audit.log.N`). Les entrées sont fusionnées et triées par timestamp : l'historique complet reste visible même après plusieurs rotations, sans intervention manuelle.

**Pour conserver ~1 an d'audit** avec un volume de ~500 événements/jour (~50 Ko/jour) :
```bash
AUDIT_LOG_MAX_BYTES=10485760   # 10 MiB par fichier (défaut)
AUDIT_LOG_BACKUP_COUNT=365     # 365 archives → ~3,5 GiB total (adapter selon l'espace disque)
```

À adapter selon votre volume d'activité et vos obligations réglementaires (RGPD, ISO 27001, etc.).

### Collecte vers un SIEM ou stack d'observabilité

Le format JSON structuré est nativement compatible avec les agents de collecte :

**Promtail / Loki (recommandé pour les environnements K8s) :**
```yaml
scrape_configs:
  - job_name: labondemand-audit
    static_configs:
      - targets: ["localhost"]
        labels:
          job:       labondemand-audit
          severity:  audit
          __path__:  /app/logs/audit.log
    pipeline_stages:
      - json:
          expressions:
            level:   level
            event:   message
            user:    username
      - labels:
          level:
          event:
          user:
```

**Filebeat / Elasticsearch :**
```yaml
filebeat.inputs:
  - type: log
    paths:
      - /app/logs/audit.log
    json.keys_under_root: true
    json.add_error_key:  true
    fields:
      source: labondemand-audit
    fields_under_root: true
```

**Fluent Bit :**
```ini
[INPUT]
    Name   tail
    Path   /app/logs/audit.log
    Tag    labondemand.audit
    Parser json

[OUTPUT]
    Name   es
    Match  labondemand.audit
    Host   elasticsearch
    Index  labondemand-audit
```

### Alertes recommandées

| Condition | Seuil suggéré | Signification |
|---|---|---|
| `login_failed` dans 1 min sur même IP | > 5 | Force brute potentielle |
| `user_deleted` | Tout événement | Suppression d'un compte |
| `level = WARNING ou ERROR` | Tout événement | Action anormale |
| `quota_override_set` | Tout événement | Dérogation accordée |
| `users_imported_csv` | Tout événement | Import de masse |
| Absence d'événements > 1h en journée | — | Problème de logging |

### Analyse ad hoc en ligne de commande

```bash
# Nombre d'événements par type
jq -r '.message' logs/audit.log | sort | uniq -c | sort -rn | head -20

# Top 10 des IPs qui ont échoué à se connecter
grep '"login_failed"' logs/audit.log | jq -r '.client_ip' | sort | uniq -c | sort -rn | head -10

# Activité par heure sur les dernières 24h
grep '"timestamp"' logs/audit.log | \
  jq -r '.timestamp[0:13]' | \
  sort | uniq -c

# Taille du fichier et nombre de lignes
wc -l logs/audit.log
du -sh logs/audit.log

# Suivre en temps réel (équivalent tail -f avec jq)
tail -f logs/audit.log | jq '{ts: .timestamp, ev: .message, user: .username, ip: .client_ip}'
```

---

## 11. Références fichiers

| Fichier | Rôle |
|---|---|
| `backend/routers/audit_logs.py` | Router FastAPI — endpoints de lecture et stats |
| `backend/routers/__init__.py` | Export du `audit_router` |
| `backend/main.py` | Enregistrement du router (`app.include_router`) |
| `backend/logging_config.py` | Configuration du logger `labondemand.audit` et rotation |
| `backend/config.py` | Variables `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`, `AUDIT_LOG_MAX_BYTES`, `AUDIT_LOG_BACKUP_COUNT` |
| `frontend/admin.html` | Onglet "Logs d'Audit" + panel HTML |
| `frontend/js/audit-logs.js` | Logique JS : stats, filtres, tableau, modal, export |
| `frontend/css/admin.css` | Styles des KPI, sparkbar, badges, modal de détail |
| `logs/audit.log` | Fichier de logs (généré à l'exécution) |

### Fichiers source des événements audités

| Événement | Fichier source |
|---|---|
| `login_success`, `login_failed`, `logout` | `backend/auth_router.py` |
| `user_registered`, `user_updated`, `user_deleted` | `backend/auth_router.py` |
| `user_self_update`, `password_changed` | `backend/auth_router.py` |
| `quota_override_set`, `users_imported_csv` | `backend/auth_router.py` |
| `deployment_created`, `deployment_paused`, `deployment_resumed` | `backend/deployment_service.py` |
| `deployment_deleted` | `backend/routers/k8s_deployments.py` |

---

## Voir aussi

- [`logging.md`](logging.md) — Configuration complète du système de logging
- [`security.md`](security.md) — RBAC, sessions, liste complète des événements audités
- [`admin-guide.md`](admin-guide.md) — Guide complet pour les administrateurs
- [`architecture.md`](architecture.md) — Vue d'ensemble du projet
