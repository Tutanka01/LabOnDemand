# Guide de démarrage rapide - LabOnDemand

## ✅ Problèmes résolus

### 1. Erreur JSON "Unexpected token 'T', Traceback"
**Cause :** Le serveur renvoyait des tracebacks Python au lieu de JSON valide.
**Solution :** Ajout d'un gestionnaire d'erreurs global dans `error_handlers.py` qui garantit des réponses JSON valides.

### 2. Erreur "Table 'labondemand.users' doesn't exist"
**Cause :** Base de données non initialisée.
**Solution :** Script d'initialisation `init_db.py` amélioré.

### 3. Architecture monolithique du main.py
**Cause :** Fichier de 833 lignes difficile à maintenir.
**Solution :** Refactorisation KISS en modules focalisés.

## 🚀 Démarrage

### 1. Initialiser la base de données
```bash
docker exec -it labondemand-api python backend/init_db.py
```

### 2. Tester la connexion
```bash
docker exec -it labondemand-api python backend/test_connection.py
```

### 3. Démarrer l'API (si pas déjà fait)
```bash
docker-compose up -d
```

### 4. Accéder à l'interface
- URL : http://localhost:8000/login.html
- Identifiants : admin / admin123

## 🔧 Scripts utiles

### Test de connexion
```bash
docker exec -it labondemand-api python backend/test_connection.py
```

### Réinitialiser l'admin
```bash
docker exec -it labondemand-api python backend/reset_admin.py
```

### Health check API
```bash
curl http://localhost:8000/api/v1/health
```

## 📊 Architecture refactorisée

```
backend/
├── main.py              (115 lignes) - Application principale
├── config.py            (35 lignes)  - Configuration centralisée
├── k8s_utils.py         (135 lignes) - Utilitaires Kubernetes
├── deployment_service.py (315 lignes) - Service de déploiement
├── k8s_router.py        (280 lignes) - Routeur Kubernetes
├── templates.py         (95 lignes)  - Templates et presets
├── error_handlers.py    (60 lignes)  - Gestion d'erreurs
├── init_db.py           (110 lignes) - Initialisation DB
└── test_connection.py   (90 lignes)  - Tests de connexion
```

## ✅ Améliorations apportées

1. **Gestion d'erreurs robuste** : Plus de tracebacks en réponse
2. **Frontend résistant** : Gestion des erreurs JSON malformées
3. **Modules focalisés** : Principe KISS appliqué
4. **Scripts utiles** : Outils de test et d'initialisation
5. **Initialisation fiable** : Setup automatique de la DB

## 🔍 Debug

Si problème de connexion :
1. Vérifier que Docker est démarré
2. Exécuter le test de connexion
3. Réinitialiser la DB si nécessaire
4. Consulter les logs : `docker logs labondemand-api`

## 📝 Notes

- L'avertissement bcrypt est normal et sans impact
- La base de données est maintenant correctement initialisée
- L'interface de login gère les erreurs proprement
- L'architecture est maintenable et extensible

## 🔐 Sessions (Redis)

- L'API utilise Redis pour stocker les sessions (TTL géré côté Redis).
- En dev, le service `redis` est lancé par `compose.yaml` et `REDIS_URL` est défini pour l'API.
- Variables utiles:
	- `REDIS_URL=redis://redis:6379/0`
	- `SESSION_EXPIRY_HOURS=24`
	- `SECURE_COOKIES=False` (dev) / `True` (prod)
	- `SESSION_SAMESITE=Lax` | `Strict`
	- `COOKIE_DOMAIN=example.com` (prod)

En prod, utilisez un Redis externe/HA (pas le service compose) et mettez `SECURE_COOKIES=True`.
