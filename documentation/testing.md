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

La suite pytest tourne entièrement en mémoire — aucune dépendance externe (MariaDB, Redis, Kubernetes) n'est requise, ni `.env`, ni `kubeconfig.yaml`. Elle s'exécute dans le service Compose `tests` (profil `test`), construit depuis la cible `test` du `Dockerfile` racine (image API + `backend/requirements-test.txt`), sans réseau (`network_mode: none`).

```bash
# Suite complète (reconstruit l'image avec le code courant)
docker compose --profile test run --rm --build tests

# Arguments pytest : ils remplacent la commande par défaut (répertoire de travail : backend/)
docker compose --profile test run --rm --build tests python -m pytest tests/test_classrooms.py -q
docker compose --profile test run --rm --build tests python -m pytest tests/test_auth.py -k login -v
docker compose --profile test run --rm --build tests python -m pytest -x -q -s
```

Le code est copié dans l'image au moment du build : sans `--build`, c'est la version de la dernière construction qui est testée.

L'image d'exécution de l'API ne contient pas pytest : `docker compose exec api python -m pytest ...` ne fonctionne plus.

Pour le frontend, la vérification minimale est la construction de l'image de production (type-check TypeScript + build Vite) :

```bash
docker compose build frontend
```

La CI GitHub Actions (`.github/workflows/ci.yml`) exécute ces mêmes étapes sur chaque pull request et chaque push sur `master` : validation des fichiers Compose, suite backend, construction de l'image API et de l'image frontend.

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
| `test_files.py` | Explorateur de fichiers des volumes (liste, téléversement, téléchargement zip, garde-fous de chemin) |
| `test_grading.py` | Grader Pod : manifeste Job + NetworkPolicy, score, endpoints, watcher |

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

## Tests hors suite automatique

Il n'y a plus de tests d'interface Selenium (`test_ui.py` visait l'ancien frontend statique, supprimé). Les vérifications d'interface se font manuellement (captures ou notes dans la pull request).

`tests/load_test_deployments.py` (racine du dépôt) est un script de charge qui crée de vrais déploiements sur le cluster ; il n'est pas lancé par pytest. Mode d'emploi en tête du fichier.
