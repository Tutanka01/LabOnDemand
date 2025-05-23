# Documentation du Système d'Authentification - LabOnDemand

## Aperçu du Système

Le système d'authentification de LabOnDemand est une solution basée sur les sessions qui gère l'authentification des utilisateurs, l'autorisation basée sur les rôles, et la protection des ressources sur la plateforme. Ce système a été conçu pour être simple, sécurisé et bien intégré avec l'existant, sans utiliser de jetons JWT afin d'éviter toute sur-ingénierie.

## Architecture

Le système utilise une architecture à plusieurs niveaux :

1. **Stockage de sessions persistant** : Les sessions sont stockées côté serveur avec un mécanisme d'expiration.
2. **Gestion des cookies** : Les identifiants de session sont stockés dans des cookies sécurisés côté client.
3. **Middleware d'authentification** : Intercepte les requêtes pour valider les sessions et charger les informations utilisateur.
4. **Contrôle d'accès basé sur les rôles** : Les autorisations d'accès aux différentes ressources sont basées sur les rôles utilisateur.

## Modèle utilisateur

Les utilisateurs sont définis par trois rôles principaux :

- **Étudiant (student)** : Accès limité aux fonctionnalités de base et à leurs propres laboratoires.
- **Enseignant (teacher)** : Accès étendu pour créer et gérer des laboratoires, mais pas d'accès aux fonctions d'administration.
- **Administrateur (admin)** : Accès complet à toutes les fonctionnalités du système, y compris la gestion des utilisateurs.

## Flux d'authentification

Le flux d'authentification suit ces étapes :

1. **Connexion** : L'utilisateur fournit son nom d'utilisateur et mot de passe.
2. **Vérification** : Le système vérifie les identifiants dans la base de données.
3. **Création de session** : Si les identifiants sont valides, une nouvelle session est créée.
4. **Cookie de session** : Un cookie contenant l'identifiant de session est envoyé au client.
5. **Authentification pour les requêtes ultérieures** : Le cookie est automatiquement envoyé avec chaque requête et vérifié par le middleware.

## Structure du code

### Backend

#### Configuration de base et modèles

- **database.py** : Configuration de la connexion à la base de données.
- **models.py** : Définition des modèles de données, y compris le modèle Utilisateur et ses rôles.
- **schemas.py** : Schémas de validation des données pour l'API.

#### Gestion de l'authentification

- **security.py** : Fonctions de sécurité, hachage des mots de passe, et vérification des sessions.
- **session_store.py** : Implémentation du stockage persistant des sessions.
- **session.py** : Middleware pour la gestion des sessions dans FastAPI.

#### Points d'API

- **auth_router.py** : Endpoints pour l'authentification et la gestion des utilisateurs.
- **lab_router.py** : Endpoints pour la gestion des laboratoires, avec contrôle d'accès.
- **main.py** : Configuration principale de l'API et intégration des routeurs.

### Frontend

#### Pages principales

- **login.html** : Page de connexion.
- **register.html** : Page d'inscription.
- **index.html** : Tableau de bord principal.
- **admin.html** : Interface d'administration des utilisateurs.
- **access-denied.html** : Page affichée en cas d'accès non autorisé.

#### Scripts JavaScript

- **auth.js** : Fonctions de gestion de l'authentification côté client.
- **login.js** : Script gérant la page de connexion.
- **register.js** : Script gérant la page d'inscription.
- **admin.js** : Script pour l'interface d'administration des utilisateurs.
- **redirect.js** : Logique de redirection pour les utilisateurs non authentifiés.

## Fonctionnalités de sécurité

Le système inclut plusieurs fonctionnalités de sécurité :

1. **Hachage des mots de passe** : Les mots de passe sont hachés avec bcrypt avant d'être stockés.
2. **Cookies sécurisés** : Les cookies de session sont configurés avec les attributs appropriés (HttpOnly, SameSite, etc.).
3. **Rotation des sessions** : Les sessions ont une durée de vie limitée et sont invalidées après un certain temps d'inactivité.
4. **Protection CSRF** : Mise en œuvre implicite via la gestion des cookies SameSite.
5. **Validation des entrées** : Toutes les entrées utilisateur sont validées avec Pydantic avant traitement.

## API d'authentification

### Endpoints principaux

| Endpoint | Méthode | Description | Accès |
|----------|---------|-------------|-------|
| `/api/v1/auth/register` | POST | Enregistre un nouvel utilisateur | Public |
| `/api/v1/auth/login` | POST | Authentifie un utilisateur | Public |
| `/api/v1/auth/logout` | POST | Déconnecte l'utilisateur actuel | Authentifié |
| `/api/v1/auth/me` | GET | Récupère les informations de l'utilisateur connecté | Authentifié |
| `/api/v1/auth/check-role` | GET | Vérifie le rôle et les permissions de l'utilisateur | Authentifié |
| `/api/v1/auth/users` | GET | Liste tous les utilisateurs | Admin uniquement |
| `/api/v1/auth/users/{user_id}` | GET | Récupère un utilisateur spécifique | Admin uniquement |
| `/api/v1/auth/users/{user_id}` | PUT | Met à jour un utilisateur | Admin uniquement |
| `/api/v1/auth/users/{user_id}` | DELETE | Supprime un utilisateur | Admin uniquement |

### Schémas des requêtes et réponses

#### Connexion (Login)
```json
// Requête
{
  "username": "string",
  "password": "string"
}

// Réponse
{
  "user": {
    "id": 1,
    "username": "string",
    "email": "string",
    "full_name": "string",
    "role": "student|teacher|admin",
    "is_active": true,
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "session_id": "string"
}
```

#### Inscription (Register)
```json
// Requête
{
  "username": "string",
  "email": "string",
  "full_name": "string",
  "password": "string",
  "role": "student|teacher|admin"
}

// Réponse
{
  "id": 1,
  "username": "string",
  "email": "string",
  "full_name": "string",
  "role": "student|teacher|admin",
  "is_active": true,
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

#### Vérification de rôle (Check-role)
```json
// Réponse
{
  "role": "student|teacher|admin",
  "can_manage_users": false,
  "can_create_labs": false,
  "can_view_all_labs": false
}
```

## Intégration avec le système de déploiement

Le système d'authentification est intégré avec le système de déploiement Kubernetes :

1. **Propriété des laboratoires** : Chaque laboratoire est associé à son créateur.
2. **Labels Kubernetes** : Les déploiements incluent des labels contenant l'identifiant et le rôle de l'utilisateur.
3. **Limites de ressources** : Des quotas différents sont appliqués selon le rôle de l'utilisateur (les étudiants ont des ressources plus limitées).

## Tests

Le système est testé à deux niveaux :

1. **Tests d'API** : Vérifie le bon fonctionnement des endpoints d'API.
2. **Tests d'interface** : Vérifie l'expérience utilisateur à travers des tests d'interface automatisés.

Pour exécuter les tests, utilisez la commande suivante :
```
python backend/tests/run_tests.py
```

Options disponibles :
- `--backend` : Exécute uniquement les tests backend
- `--ui` : Exécute uniquement les tests d'interface utilisateur
- `--all` : Exécute tous les tests (par défaut)
- `--skip-deps` : Ignore la vérification des dépendances
- `--skip-server-check` : Ignore la vérification du serveur

## Bonnes pratiques

Pour maintenir la sécurité du système :

1. **Rotation régulière des mots de passe administrateur**
2. **Surveillance des journaux d'authentification**
3. **Mise à jour régulière des dépendances**
4. **Revue périodique des comptes utilisateur et des droits d'accès**

## Maintenance et dépannage

### Problèmes courants

1. **Sessions expirées prématurément** : Vérifier la configuration dans `session_store.py`
2. **Cookies non persistants** : Vérifier la configuration des cookies dans `session.py`
3. **Problèmes d'accès** : Vérifier le rôle de l'utilisateur et les dépendances d'authentification

### Journalisation

Le système consigne les événements importants comme les connexions réussies/échouées, les modifications de compte, etc.

## Extensions futures

Le système peut être étendu avec :

1. Authentification à deux facteurs (2FA)
2. Intégration SSO avec des fournisseurs externes (Google, GitHub, etc.)
3. Système de récupération de mot de passe
4. Journalisation avancée des activités

---

## Guide de démarrage rapide

### Pour les développeurs

1. **Configuration initiale** : Assurez-vous que la base de données est correctement configurée.
2. **Création d'utilisateurs** : Utilisez le script `init_db.py` pour créer les utilisateurs initiaux.
3. **Intégrer l'authentification** : Pour protéger un endpoint, utilisez la dépendance `get_current_user`.

### Pour les administrateurs

1. **Accès à l'interface d'administration** : Connectez-vous avec un compte administrateur et accédez à `/admin.html`.
2. **Gestion des utilisateurs** : Utilisez l'interface pour créer, modifier ou supprimer des utilisateurs.
3. **Surveillance** : Vérifiez régulièrement les journaux pour détecter toute activité suspecte.

### Pour les utilisateurs finaux

1. **Création de compte** : Accédez à la page d'inscription (`/register.html`) pour créer un nouveau compte.
2. **Connexion** : Utilisez la page de connexion (`/login.html`) pour accéder à votre compte.
3. **Gestion du profil** : Modifiez vos informations personnelles depuis l'interface utilisateur.
