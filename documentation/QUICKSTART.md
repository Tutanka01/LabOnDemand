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

### 5. Lancer une stack LAMP et ouvrir un terminal
1. Dans le dashboard, ouvrez le catalogue et choisissez « Stack LAMP »
2. Donnez un nom et validez; attendez que les 3 pods (web, db, phpmyadmin) soient Running
3. Dans les détails, utilisez les URLs affichées pour le Web et phpMyAdmin
4. Ouvrez le terminal du pod web pour éditer /var/www/html (non-root)

Docs: voir documentation/lamp.md et documentation/terminal.md

### 6. Bureau NetBeans via NoVNC
1. Depuis le catalogue, sélectionnez « NetBeans Desktop (NoVNC) »
2. Validez le nom proposé (les ressources CPU/RAM minimales sont préconfigurées)
3. Une fois le déploiement lancé, accédez au panneau de statut :
	- Cherchez le bloc « Bureau intégré NoVNC » : le bouton « Ouvrir dans la page » s’active dès que le service est prêt.
	- Le bloc « Ports exposés » récapitule les NodePorts (NoVNC 6901, VNC 5901, Audio 4901)
	- La section « Infos de connexion » rappelle les identifiants par défaut : `kasm_user` / `password`
4. Cliquez sur « Ouvrir dans la page » pour lancer NetBeans directement dans une fenêtre intégrée au tableau de bord.
5. Besoin d’un accès alternatif ? Le lien NoVNC externe et les NodePorts restent disponibles pour ouvrir la session dans un nouvel onglet ou via un client VNC classique (port 5901) avec les mêmes identifiants.

### 7. Réutiliser un volume persistant VS Code/Jupyter
1. Depuis le dashboard, cliquez sur « Rafraîchir » dans la carte « Vos volumes persistants » pour charger la liste.
2. Lors d’un nouveau lancement VS Code ou Jupyter, choisissez le PVC souhaité dans la liste déroulante « Volume persistant » (ou laissez vide pour créer un nouveau volume).
3. Après l’arrêt d’un environnement, revenez sur la carte pour supprimer les volumes dont vous n’avez plus besoin; un volume encore `Bound` demandera une confirmation forcée.
4. Les volumes réutilisables sont préfixés avec des labels LabOnDemand (`managed-by=labondemand`, `user-id=<id>`); si la StorageClass par défaut est absente, la sélection reste disponible mais le déploiement basculera en `emptyDir`.

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
5. Examiner les fichiers JSON dans `logs/` (`app.log`, `access.log`, `audit.log`)

### Journaux structurés

- Les logs applicatifs sont persistés dans `logs/` via Docker Compose (`./logs:/app/logs`).
- Trois flux JSON : `app.log` (technique), `access.log` (requêtes HTTP), `audit.log` (événements sensibles).
- Variables utiles : `LOG_LEVEL`, `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`, `LOG_ENABLE_CONSOLE`.
- Détails et exemples : voir `documentation/logging.md`.

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
