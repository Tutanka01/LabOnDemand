# Cycle de vie des labs — TTL & nettoyage automatique

Ce document décrit le mécanisme d'expiration des laboratoires, la tâche de fond
qui les nettoie, et la gestion des namespaces Kubernetes orphelins.

---

## Pourquoi un TTL ?

Sans limite de durée, les labs abandonnés accumulent des ressources Kubernetes
(CPU, RAM, PVC, Secrets, ConfigMaps) indéfiniment. Un étudiant qui oublie
10 labs en pause bloque le stockage pour tous les autres utilisateurs.

Le TTL (Time To Live) donne une date d'expiration à chaque déploiement.
Passée cette date, le lab est automatiquement mis en pause, puis peut être
supprimé après une période de grâce.

---

## TTL par défaut selon le rôle

| Rôle    | TTL par défaut | Variable d'environnement   |
|---------|---------------|----------------------------|
| student | 7 jours        | `LAB_TTL_STUDENT_DAYS=7`   |
| teacher | 30 jours       | `LAB_TTL_TEACHER_DAYS=30`  |
| admin   | illimité       | —                          |

La date d'expiration est calculée **à la création** du déploiement :

```python
expires_at = datetime.now(UTC) + timedelta(days=TTL_DAYS)
```

Elle est stockée dans la colonne `deployments.expires_at`.

Un admin peut prolonger ou supprimer l'expiration d'un lab via l'API ou
directement en base (voir section [Prolongation manuelle](#prolongation-manuelle)).

---

## La tâche de nettoyage (`backend/tasks/cleanup.py`)

### Démarrage

La tâche est lancée automatiquement au démarrage de l'API par `main.bootstrap()` :

```python
asyncio.create_task(run_cleanup_loop())
```

Elle tourne dans une boucle asyncio infinie, sans dépendance externe (pas
d'APScheduler, pas de CronJob K8s).

### Fréquence

Configurable via `CLEANUP_INTERVAL_MINUTES` (défaut : 60 minutes).

```env
CLEANUP_INTERVAL_MINUTES=30   # vérification toutes les 30 minutes
```

### Ce que fait chaque cycle

```
_run_cleanup_cycle()
  │
  ├── 1. Labs expirés (status=active, expires_at ≤ now)
  │     → pause_application(namespace, name, user)
  │     → deployments.status = "paused"
  │     → log: deployment_auto_paused_expired
  │
  └── 2. Namespaces orphelins (labondemand-user-N sans user en base)
        → CoreV1Api().delete_namespace(namespace)
        → log: orphan_namespace_deleted
```

### Gestion des erreurs

Chaque opération est encapsulée dans un `try/except` individuel : si un lab
échoue à être mis en pause (ex. Kubernetes injoignable), les autres labs du
cycle continuent. Une exception dans `_run_cleanup_cycle()` est journalisée
et le cycle suivant reprend normalement.

---

## Statuts des déploiements

| Status    | Signification                                        |
|-----------|------------------------------------------------------|
| `active`  | Lab en cours d'exécution, réplicas > 0               |
| `paused`  | Lab suspendu (réplicas = 0, données préservées)       |
| `expired` | Lab expiré — en attente de suppression               |
| `deleted` | Lab supprimé (ligne conservée pour l'historique)      |

---

## Table `deployments`

La table `deployments` (ajoutée en phase B) traçe chaque lab :

```sql
CREATE TABLE deployments (
  id              INTEGER PRIMARY KEY AUTO_INCREMENT,
  user_id         INTEGER NOT NULL,     -- FK → users.id (CASCADE DELETE)
  name            VARCHAR(100) NOT NULL,
  deployment_type VARCHAR(50)  NOT NULL DEFAULT 'custom',
  namespace       VARCHAR(100) NOT NULL,
  stack_name      VARCHAR(100),
  status          VARCHAR(30)  NOT NULL DEFAULT 'active',
  created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
  deleted_at      DATETIME,
  last_seen_at    DATETIME,
  expires_at      DATETIME,             -- NULL pour les admins (illimité)
  cpu_requested   VARCHAR(20),
  mem_requested   VARCHAR(20)
);
```

Cette table permet :
- l'historique de tous les labs (actifs, supprimés, expirés)
- la détection des zombies (labs actifs mais pod absent)
- le calcul des statistiques d'usage par utilisateur ou par type

---

## Prolongation manuelle

Un admin peut prolonger la durée de vie d'un lab en mettant à jour `expires_at`
via SQL direct ou via un futur endpoint dédié :

```sql
UPDATE deployments
SET expires_at = DATE_ADD(NOW(), INTERVAL 14 DAY)
WHERE id = <id_du_lab>;
```

Pour rendre un lab permanent (admin) :

```sql
UPDATE deployments SET expires_at = NULL WHERE id = <id>;
```

---

## Namespaces orphelins

Un namespace est dit **orphelin** lorsque l'utilisateur qui lui correspond a été
supprimé de la base de données mais que le namespace Kubernetes existe toujours
(ex. suppression directe en base, bug, migration).

La tâche de nettoyage les détecte en comparant les namespaces préfixés
`labondemand-user-*` avec la table `users`.

```
Namespace : labondemand-user-42
  → user_id extrait : 42
  → SELECT * FROM users WHERE id = 42 → vide
  → delete_namespace("labondemand-user-42")
```

> **Note** : si la suppression K8s échoue (permissions RBAC manquantes, timeout),
> l'erreur est journalisée mais la boucle continue. Vérifier les logs avec
> `grep orphan_namespace logs/app.log`.

---

## Nettoyage immédiat à la suppression d'utilisateur

En complément de la tâche périodique, la suppression d'un utilisateur via
`DELETE /api/v1/auth/users/{id}` déclenche immédiatement :

1. **Invalidation des sessions Redis** (`security.delete_user_sessions`) — scan
   par pattern `session:*` et suppression de toutes les entrées où `user_id = N`.
2. **Suppression du namespace K8s** (`DeploymentService.cleanup_user_namespace`) —
   appel `CoreV1Api().delete_namespace("labondemand-user-N")`.

Ces deux opérations sont non-bloquantes : une erreur n'empêche pas la suppression
en base. Tout est tracé dans `audit.log` avec le nombre de sessions révoquées et
le statut de la suppression du namespace.

---

## Configuration complète

```env
# TTL des labs par rôle
LAB_TTL_STUDENT_DAYS=7
LAB_TTL_TEACHER_DAYS=30

# Fréquence de la tâche de nettoyage
CLEANUP_INTERVAL_MINUTES=60
```

Ces variables sont lues au démarrage par `backend/tasks/cleanup.py`.
Aucun redémarrage du serveur n'est nécessaire si elles sont changées via
un rechargement du service (les valeurs sont lues une seule fois au boot).

---

## Checklist opérationnelle

- [ ] Vérifier que la tâche de nettoyage démarre : `grep cleanup_task_started logs/app.log`
- [ ] Surveiller les labs auto-paused : `grep deployment_auto_paused_expired logs/app.log`
- [ ] Vérifier les namespaces orphelins : `grep orphan_namespace logs/app.log`
- [ ] En cas de namespace non supprimé : vérifier les RBAC K8s avec `kubectl auth can-i delete namespaces`
- [ ] Ajuster `LAB_TTL_STUDENT_DAYS` si les étudiants se plaignent d'expiration trop rapide
