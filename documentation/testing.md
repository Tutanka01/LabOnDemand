# Tests

## Installation rapide

```bash
# Depuis la racine du projet
pip install -r requirements.txt -r backend/requirements-test.txt
```

> **Note** : la version de `bcrypt` doit rester `>=4.0.1,<4.1` (contrainte de `passlib`).
> Sur Python 3.14, assurez-vous que `pydantic-core` est bien installé.

---

## Lancer les tests

Toutes les commandes se lancent depuis **la racine du projet** :

```bash
# Suite complète
PYTHONPATH=. pytest backend/tests/ -q

# Avec affichage des logs (utile pour déboguer)
PYTHONPATH=. pytest backend/tests/ -q -s

# Un seul fichier
PYTHONPATH=. pytest backend/tests/test_auth.py -q

# Un seul test
PYTHONPATH=. pytest backend/tests/test_auth.py::test_login_success -v

# Stopper au premier échec
PYTHONPATH=. pytest backend/tests/ -x -q

# Relancer uniquement les tests en échec
PYTHONPATH=. pytest backend/tests/ --lf -q
```

---

## Ce que les tests couvrent

| Fichier | Périmètre |
|---|---|
| `test_health.py` | Endpoints publics (`/`, `/status`, `/health`) |
| `test_auth.py` | Login, logout, `/me`, changement de mot de passe, SSO |
| `test_users.py` | CRUD utilisateurs, RBAC par rôle |
| `test_templates.py` | CRUD templates, validation des champs |
| `test_runtime_configs.py` | CRUD configurations runtime |
| `test_deployments.py` | Cycle de vie déploiement (créer, pause, resume, supprimer) |
| `test_storage.py` | PVCs : liste, détail, suppression forcée, droits d'accès |
| `test_monitoring.py` | Stats cluster, ping, namespaces (RBAC admin/teacher) |
| `test_quotas.py` | Résumé des quotas par rôle |
| `test_security.py` | Validation des mots de passe, hachage, RBAC HTTP, sessions |
| `test_migrations.py` | Idempotence des migrations SQL |
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
| `inactive_user` | `User` | Utilisateur désactivé |
| `oidc_user` | `User` | Utilisateur SSO (auth_provider=oidc) |
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

Les tests **async** sont détectés automatiquement (`asyncio_mode = auto` dans `pytest.ini`).
Pour les tests qui touchent Kubernetes, ajouter la fixture `mock_k8s`.

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
