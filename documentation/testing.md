---
title: Tests
summary: Guide des tests automatisés de LabOnDemand — lancement via Docker Compose, organisation des fichiers de test, fixtures disponibles et configuration des mocks.
read_when: |
  - Tu écris ou modifies des tests dans backend/tests/
  - Tu veux lancer la suite de tests et interpréter les résultats
  - Tu ajoutes une nouvelle fonctionnalité et dois créer les tests correspondants
---

# Tests

## Lancer les tests

La suite pytest tourne entièrement en mémoire — aucune dépendance externe (MariaDB, Redis, Kubernetes) n'est requise.

```bash
# Depuis un conteneur déjà démarré (recommandé)
docker compose exec api python -m pytest backend/tests/ -q

# Avec affichage des logs (utile pour déboguer)
docker compose exec api python -m pytest backend/tests/ -q -s

# Un seul fichier
docker compose exec api python -m pytest backend/tests/test_classrooms.py -q

# Un seul test
docker compose exec api python -m pytest backend/tests/test_auth.py::test_login_success -v

# Stopper au premier échec
docker compose exec api python -m pytest backend/tests/ -x -q

# Relancer uniquement les tests en échec
docker compose exec api python -m pytest backend/tests/ --lf -q
```

> **Alternative hors Docker** (si tu as un virtualenv configuré) :
> ```bash
> PYTHONPATH=. pytest backend/tests/ -q
> ```
> Voir `documentation/development-setup.md` pour les prérequis.

---

## Ce que les tests couvrent

| Fichier | Périmètre |
|---|---|
| `test_health.py` | Endpoints publics (`/`, `/status`, `/health`) |
| `test_auth.py` | Login, logout, `/me`, changement de mot de passe |
| `test_sso.py` | Flow OIDC complet, mapping de rôle, réconciliation par email |
| `test_users.py` | CRUD utilisateurs, RBAC par rôle, import CSV |
| `test_templates.py` | CRUD templates, validation des champs |
| `test_runtime_configs.py` | CRUD configurations runtime |
| `test_deployments.py` | Cycle de vie déploiement (créer, pause, resume, supprimer) |
| `test_storage.py` | PVCs : liste, détail, suppression forcée, droits d'accès |
| `test_monitoring.py` | Stats cluster, ping, namespaces (RBAC admin/teacher) |
| `test_quotas.py` | Résumé des quotas par rôle |
| `test_security.py` | Validation des mots de passe, hachage, RBAC HTTP, sessions |
| `test_classrooms.py` | Classrooms CRUD, inscriptions, devoirs, déploiement en masse |
| `test_submissions.py` | Soumissions étudiants, notation manuelle, statut de correction |
| `test_migrations.py` | Idempotence des 18 migrations SQL |
| `test_seed.py` | Idempotence du seeding (admin, templates, runtime configs) |

---

## Architecture des tests

**Aucune dépendance externe** — la suite tourne entièrement en mémoire :

- **Base de données** : SQLite in-memory (remplace MariaDB)
- **Redis** : classe `_FakeRedis` avec un dict Python
- **Kubernetes** : `kubernetes.client` mocké via `unittest.mock`

L'ordre d'initialisation dans `conftest.py` est critique :

```
1. Variables d'environnement (REDIS_URL, SSO_ENABLED…)
2. Patch redis.from_url  ← session_store.py le lit au moment de l'import
3. Patch kubernetes.config ← main.py l'appelle au module level
4. Remplacement engine/SessionLocal dans backend.database
5. Import de backend.main  ← tout est en place
6. Fixtures pytest
```

**Isolation** : la fixture `_isolate` (autouse) vide toutes les tables et le store de sessions avant chaque test.

---

## Fixtures disponibles

| Fixture | Type | Description |
|---|---|---|
| `db` | `Session` | Session SQLAlchemy ouverte sur le SQLite in-memory |
| `client` | `AsyncClient` | Client HTTP non authentifié |
| `admin_client` | `AsyncClient` | Client authentifié en tant qu'admin |
| `teacher_client` | `AsyncClient` | Client authentifié en tant qu'enseignant |
| `student_client` | `AsyncClient` | Client authentifié en tant qu'étudiant |
| `admin_user` | `User` | Utilisateur admin en base |
| `teacher_user` | `User` | Utilisateur enseignant en base |
| `student_user` | `User` | Utilisateur étudiant en base |
| `inactive_user` | `User` | Utilisateur désactivé (`is_active=False`) |
| `oidc_user` | `User` | Utilisateur SSO (`auth_provider=oidc`, `external_id` défini) |
| `mock_k8s` | `dict` | Mocks K8s : `{"apps": ..., "core": ..., "networking": ...}` |
| `sample_template` | `Template` | Template actif en base |
| `sample_runtime_config` | `RuntimeConfig` | Config runtime active en base |

---

## Ajouter un test

```python
# backend/tests/test_mon_feature.py

async def test_mon_endpoint(admin_client, mock_k8s):
    r = await admin_client.get("/api/v1/mon-endpoint")
    assert r.status_code == 200
    assert "clé" in r.json()
```

Les tests **async** sont détectés automatiquement (`asyncio_mode = auto` dans `pytest.ini`). Pour les tests qui touchent Kubernetes, ajouter la fixture `mock_k8s`.

### Exemple : test d'une route classrooms

```python
async def test_teacher_can_create_classroom(teacher_client):
    r = await teacher_client.post("/api/v1/classrooms", json={
        "name": "INF101",
        "description": "Programmation objet"
    })
    assert r.status_code == 200
    assert r.json()["name"] == "INF101"

async def test_student_cannot_create_classroom(student_client):
    r = await student_client.post("/api/v1/classrooms", json={"name": "X"})
    assert r.status_code == 403
```

---

## Tests exclus de la suite automatique

`test_ui.py` (tests Selenium) nécessite un navigateur et un serveur live — il est exclu du `pytest.ini` et doit être lancé manuellement :

```bash
# Démarrer l'application d'abord
docker compose up

# Dans un autre terminal
pip install selenium
pytest backend/tests/test_ui.py -v
```
