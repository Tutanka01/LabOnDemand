# LabOnDemand ✨

<div align="center">
    <h2 align="center"><a href="https://makhal.fr"><img alt="pangolin" src="Diagrammes/Images/banner-projet.jpeg" width="400" /></a></h2>
</div>

**LabOnDemand** est une plateforme open-source de gestion de laboratoires virtuels, conçue pour permettre aux étudiants et professeurs de créer et gérer facilement des environnements de travail isolés sur Kubernetes. Déployez des instances VS Code, Jupyter Notebooks, ou vos propres applications conteneurisées en quelques clics !

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
<!-- Ajoutez d'autres badges ici (build status, etc.) quand ils seront pertinents -->

## 📹 Présentation du Projet

Regardez notre vidéo de présentation qui explique les principales fonctionnalités et l'utilisation de LabOnDemand :

[![LabOnDemand Video](https://img.shields.io/badge/Vidéo-Présentation%20du%20Projet-red)](Diagrammes/Video/LabOnDemand.mp4)

## 🚀 Fonctionnalités Clés

*   Déploiement Facile : UI pour lancer des environnements pré-configurés (VS Code, Jupyter, WordPress) ou des images Docker personnalisées.
*   Gestion Kubernetes Simplifiée : création de Deployments/Services, labels standardisés, et conformité K8s (validation des noms).
*   Rôles & Autorisations : étudiants, enseignants, admins. Les étudiants peuvent supprimer uniquement leurs propres applications (contrôle d’étiquettes managed-by=labondemand, user-id).
*   Quotas par Rôle (enforcement côté serveur) : limites sur nombre d’apps, CPU et mémoire avec mode fail-closed si la mesure est indisponible. Carte de quotas sur le dashboard.
*   Observabilité par Application : métriques CPU (m) et mémoire (Mi) par application, en Live (metrics-server) ou estimation (requests). Liste triable par consommation.
*   Statistiques Admin : vue dédiée pour l’état cluster/noeuds (si metrics-server présent), avec agrégations utiles.
*   WordPress pour Étudiants : stack complète WordPress + MariaDB gérée; suppression traite la stack (web + db) proprement.
*   Sécurité des Sessions : cookies HttpOnly, Secure, SameSite, domaine/expiration configurables; contrôles de rôle côté API.
*   Accès Simplifié : exposition via NodePort (par défaut), configurable.
*   Templates Dynamiques : templates en base (icône/desc/tags) + runtime-configs pour piloter l’affichage aux étudiants.

## 🏗️ Architecture du Projet

LabOnDemand est structuré autour de trois composants principaux :

1.  **Backend API (FastAPI/Python)** : Le cerveau de l'application. Il gère la logique métier, les interactions avec l'API Kubernetes et expose les endpoints pour le frontend.
2.  **Frontend (HTML/JavaScript/CSS)** : L'interface utilisateur web, permettant aux utilisateurs d'interagir avec l'API pour gérer leurs laboratoires.
3.  **Base de Données (MariaDB)** : Utilisée pour stocker les informations relatives aux laboratoires, utilisateurs (fonctionnalité future), et configurations.
4.  **Proxy NGINX** : Sert le frontend statique et redirige les appels API vers le backend FastAPI.

##  visionary Architecture (Objectif à Terme)

L'objectif est de faire évoluer LabOnDemand vers une solution robuste et hautement disponible :

```mermaid
graph TD
    %% --- Style Definitions ---
    classDef default fill:#ececff,stroke:#9370db,stroke-width:2px,color:#333;
    classDef external fill:#fceecb,stroke:#e9a70f,stroke-width:2px,color:#333;
    classDef network fill:#d1e7dd,stroke:#146c43,stroke-width:2px,color:#333;
    classDef haproxy fill:#f8d7da,stroke:#842029,stroke-width:2px,color:#333;
    classDef k8snode fill:#cfe2ff,stroke:#0a58ca,stroke-width:2px,color:#333;
    classDef k8singress fill:#fff3cd,stroke:#997404,stroke-width:1px,color:#333;
    classDef k8sapp fill:#d1e7dd,stroke:#0f5132,stroke-width:1px,color:#333;
    classDef k8ssvc fill:#e2d9f3,stroke:#563d7c,stroke-width:1px,color:#333;

    %% --- External Layer ---
    User["Utilisateur"]:::external
    DNS["DNS<br/>(*.lab.makhal.fr)"]:::external
    User -- "DNS Lookup" --> DNS

    %% --- HA Layer with Keepalived ---
    subgraph "HAProxy + Keepalived Layer"
        direction TB
        VIP["<b>Adresse IP Virtuelle (VIP)</b><br/>(Gérée par Keepalived)"]:::network

        subgraph "HAProxy Instances"
            direction LR
            HAProxy1["<b>HAProxy 1 (MASTER)</b><br/>Actif - Détient la VIP<br/><i>Keepalived</i>"]:::haproxy
            HAProxy2["<b>HAProxy 2 (BACKUP)</b><br/>Passif - Prêt à prendre le relais<br/><i>Keepalived</i>"]:::haproxy
        end
        HAProxy1 <-- "VRRP Heartbeat" --> HAProxy2
    end

    DNS -- "Virtual IP" --> VIP
    User -- "Connects (HTTP/S)" --> VIP
    VIP -- "Traffic to Active" --> HAProxy1

    %% --- Kubernetes Cluster Layer ---
    subgraph "Kubernetes Cluster (3 Nodes)"
        direction TB
        subgraph "Worker Nodes"
             direction LR
             Node1["K8s Node 1<br/>(Worker)"]:::k8snode
             Node2["K8s Node 2<br/>(Worker)"]:::k8snode
             Node3["K8s Node 3<br/>(Worker)"]:::k8snode
        end
        IngressSvc["Ingress Controller Service<br/>(Type: NodePort)"]:::k8ssvc
        subgraph "Ingress Controller Pods"
            direction LR
             IngressPod1["Ingress Pod 1"]:::k8singress
             IngressPod2["Ingress Pod 2"]:::k8singress
        end
        AppSvc["Application Service<br/>(Type: ClusterIP)"]:::k8ssvc
        subgraph "Application Pods (ex: VSCode)"
            direction LR
             AppPod1["App Pod 1"]:::k8sapp
             AppPod2["App Pod 2"]:::k8sapp
        end
        HAProxy1 -- "Forward to NodePort" --> Node1
        HAProxy1 -- "Forward to NodePort" --> Node2
        HAProxy1 -- "Forward to NodePort" --> Node3
        Node1 -- "Kube-proxy routes" --> IngressSvc
        Node2 -- "Kube-proxy routes" --> IngressSvc
        Node3 -- "Kube-proxy routes" --> IngressSvc
        IngressSvc -- "Selects Ingress Pod" --> IngressPod1
        IngressSvc -- "Selects Ingress Pod" --> IngressPod2
        IngressPod1 -- "Routes by Rule" --> AppSvc
        IngressPod2 -- "Routes by Rule" --> AppSvc
        AppSvc -- "Selects App Pod" --> AppPod1
        AppSvc -- "Selects App Pod" --> AppPod2
    end
```

## 🛠️ Mise en Place (Développement Local)

### Prérequis

*   **Docker & Docker Compose :** Pour construire et lancer les services localement.
*   **Cluster Kubernetes Fonctionnel :** Minikube, Kind, K3s, ou un cluster distant.
*   **`kubectl` :** Configuré pour interagir avec votre cluster.
*   **Helm (Optionnel, mais recommandé) :** Pour l'installation de l'Ingress Controller.
*   **Fichier `kubeconfig` :** Un fichier `kubeconfig` valide pour l'accès à votre cluster Kubernetes.

### Configuration Initiale

1.  **Clonez le dépôt :**
    ```bash
    git clone <URL_DU_DEPOT_LABONDEMAND>
    cd LabOnDemand
    ```

2.  **Configuration Kubernetes :**
    *   **⚠️ Configuration et Accès au Cluster :** L'application nécessite l'accès à un cluster Kubernetes via un fichier `kubeconfig`.
        *   **Pour le développement local avec Docker Compose :**
            Le fichier `kubeconfig.yaml` est monté comme un volume en lecture seule dans le conteneur API via `compose.yaml` :
            ```yaml
            # Dans compose.yaml, pour le service 'api':
            volumes:
              - ./backend:/app/backend
              - ./.env:/app/.env
              - ./kubeconfig.yaml:/root/.kube/config:ro # Montez votre kubeconfig local en lecture seule
            ```
            Assurez-vous que votre fichier `kubeconfig.yaml` est valide et situé à la racine du projet.
        *   **Pour un déploiement en cluster (Production) :** L'API devrait utiliser un **ServiceAccount Kubernetes** avec les permissions RBAC appropriées. Ne jamais embarquer un `kubeconfig` avec des droits étendus dans une image.
        *   **Besoin d'aide pour créer un cluster Kubernetes ?** Consultez notre tutoriel sur [Comment installer un cluster Kubernetes](https://makhal.fr/posts/k8s/k8s1-3/) qui vous guidera à travers le processus d'installation.

3.  **Fichier d'Environnement :**
    Créez un fichier `.env` à la racine du projet à partir de l'exemple (s'il n'y a pas de `.env.example`, créez-le) :
    ```bash
    cp .env.example .env # Ou créez .env manuellement
    ```
    Modifiez `.env` avec vos configurations (ports, identifiants de base de données) :
    ```dotenv
    # Exemple de .env
    API_PORT=8000
    FRONTEND_PORT=80
    DB_PORT=3306
    DB_ROOT_PASSWORD=supersecretrootpassword
    DB_USER=labondemand
    DB_PASSWORD=labondemandpassword
    DB_NAME=labondemand
    # DEBUG_MODE=True # Décommentez pour le mode debug de FastAPI/Uvicorn
    ```

4.  **(Optionnel) Installation de l'Ingress Controller NGINX :**
    Si vous souhaitez utiliser un Ingress pour exposer vos services (recommandé pour une utilisation plus avancée que NodePort) :
    ```bash
    helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
    helm repo update
    helm install nginx-ingress ingress-nginx/ingress-nginx --namespace ingress-nginx --create-namespace
    ```

### Diagrammes de flux

Flux d'authentification actuel :

```mermaid
sequenceDiagram
    participant U as Utilisateur
    participant F as Frontend
    participant A as API d'authentification
    participant S as Session Store
    participant DB as Base de données

    %% Flux de connexion
    U->>F: Accéder à la page de connexion
    F->>U: Afficher le formulaire de connexion
    U->>F: Soumettre identifiants
    F->>A: POST /api/v1/auth/login
    A->>DB: Vérifier identifiants
    DB-->>A: Utilisateur valide
    A->>S: Créer une session
    S-->>A: ID de session
    A-->>F: Réponse + Cookie de session
    F-->>U: Redirection vers le dashboard

    %% Flux de requête authentifiée
    U->>F: Accéder à une page protégée
    F->>A: GET /api/v1/... + Cookie de session
    A->>S: Vérifier la session
    S-->>A: Session valide
    A->>DB: Charger les données utilisateur
    DB-->>A: Données utilisateur
    A-->>F: Données + Autorisation
    F-->>U: Afficher la page protégée

    %% Flux de déconnexion
    U->>F: Cliquer sur déconnexion
    F->>A: POST /api/v1/auth/logout + Cookie de session
    A->>S: Supprimer la session
    S-->>A: Session supprimée
    A-->>F: Réponse + Suppression du cookie
    F-->>U: Redirection vers la page de connexion
```

Flux de suppression d'une application (étudiant) :

```mermaid
sequenceDiagram
    participant E as Étudiant
    participant F as Frontend
    participant K as API K8s (FastAPI)
    participant K8s as Kubernetes API

    E->>F: Clic "Supprimer" sur une app
    F->>K: DELETE /api/v1/k8s/deployments/{ns}/{name}?delete_service=true (cookie de session)
    K->>K: Vérifier session + rôle
    alt Étudiant
        K->>K: Lire le Deployment (ou par stack-name, ou label app)
        K->>K: Vérifier labels managed-by=labondemand et user-id=étudiant
        alt App non possédée
            K-->>F: 403 Forbidden
        else App possédée
            opt Stack WordPress
                K->>K8s: delete Deployment wordpress et mariadb
                K->>K8s: delete Service(s) associés (si demandé)
            end
            opt App unitaire
                K->>K8s: delete Deployment {name}
                K->>K8s: delete Service {name}-service (si demandé)
            end
            K-->>F: 200 OK (message de succès)
            F-->>E: Retirer l’app de l’UI
        end
    else Admin/Enseignant
        K->>K: Peut supprimer toute app LabOnDemand
        K->>K8s: delete Deployment/Service(s)
        K-->>F: 200 OK
    end
```
### Démarrage de l'Application

Lancez l'ensemble des services avec Docker Compose :

```bash
docker compose up -d --build
```

Une fois démarré, l'application sera accessible aux adresses suivantes (par défaut) :

*   **Frontend LabOnDemand :** [http://localhost](http://localhost) (ou `http://localhost:${FRONTEND_PORT}`)
*   **API LabOnDemand :** [http://localhost:8000](http://localhost:8000) (ou `http://localhost:${API_PORT}`)
*   **Documentation API (Swagger UI) :** [http://localhost:8000/docs](http://localhost:8000/docs)
*   **Documentation API (ReDoc) :** [http://localhost:8000/redoc](http://localhost:8000/redoc)

## 📁 Structure des Fichiers

```
└── LabOnDemand /
    ├── readme.md           # Ce fichier
    ├── compose.yaml        # Configuration Docker Compose
    ├── Dockerfile          # Dockerfile pour l'API backend
    ├── LICENSE             # Licence du projet
    ├── requirements.txt    # Dépendances Python pour le backend
    ├── .env.example        # Modèle pour le fichier .env (À CRÉER SI MANQUANT)
    ├── backend/
    │   └── main.py         # Logique de l'API FastAPI et interaction Kubernetes
    ├── Diagrammes/         # Schémas d'architecture
    │   ├── Diagramme-API.drawio
    │   └── diagramme.md
    ├── dockerfiles/        # Dockerfiles pour les images des laboratoires
    │   ├── jupyter/
    │   │   └── Dockerfile
    │   └── vscode/
    │       └── Dockerfile
    ├── frontend/           # Fichiers de l'interface utilisateur web
    │   ├── index.html
    │   ├── script.js
    │   ├── style.css
    │   └── css/
    │       ├── app-status.css
    │       └── lab-status.css
    └── nginx/
        └── nginx.conf      # Configuration du proxy NGINX
```

## 🧩 UML (modèle conceptuel)

```mermaid
classDiagram
        direction LR
        class User {
            +int id
            +string username
            +UserRole role
        }

        class Session {
            +string session_id
            +datetime created_at
            +int user_id
        }

        class Template {
            +int id
            +string key
            +string name
            +string deployment_type
            +string default_image
            +int default_port
            +string[] tags
            +bool active
        }

        class RuntimeConfig {
            +int id
            +string key
            +string label
            +bool allowed_for_students
            +bool active
        }

        class AppInstance {
            +string name
            +string namespace
            +string app_type
            +map<string,string> labels // managed-by, user-id, stack-name, component
        }

        class QuotaLimits {
            +int max_apps
            +int cpu_m
            +int mem_mi
        }

        class UsageSummary {
            +int apps
            +int cpu_m
            +int mem_mi
            +bool metrics_live
        }

        User "1" -- "*" AppInstance : possède
        Template "1" -- "*" AppInstance : instancie
        User "1" -- "1" QuotaLimits : selon rôle
        User "1" -- "1" UsageSummary : consommation
        RuntimeConfig "*" ..> Template : visibilité/affichage
```

## 💡 Développement et Maintenance

### Contribution au Projet

Nous encourageons les contributions au projet LabOnDemand ! Voici comment vous pouvez participer :

1. **Fork** le dépôt GitHub
2. **Créez une branche** pour votre fonctionnalité ou correction
3. **Commitez vos changements** avec des messages clairs
4. **Faites une Pull Request** vers le dépôt principal

### Ressources et Documentation Supplémentaires

Pour vous aider dans votre utilisation et développement avec LabOnDemand, voici quelques ressources additionnelles :

* **[Installation d'un Cluster Kubernetes](https://makhal.fr/posts/k8s/k8s1-3/)** - Guide détaillé pour mettre en place votre propre cluster Kubernetes
* **[Documentation Kubernetes Officielle](https://kubernetes.io/fr/docs/home/)** - Référence complète pour l'utilisation de Kubernetes
* **[FastAPI Documentation](https://fastapi.tiangolo.com/)** - Documentation de FastAPI, utilisé pour le backend de l'application
* **Docs du projet**
    * `documentation/QUICKSTART.md` — Démarrage rapide (Docker Compose, kubeconfig)
    * `documentation/auth-flow.md` — Détails d’authentification et sécurité des sessions
    * `documentation/wordpress.md` — Stack WordPress (web + mariadb), notes de suppression
    * `documentation/auth-summary.md` — Résumé des rôles et autorisations
    * `documentation/pvc-mise-en-place.md` — Stockage persistant

## 📝 Licence

Ce projet est sous licence [GNU AFFERO GENERAL PUBLIC LICENSE v3](LICENSE) - voir le fichier LICENSE pour plus de détails.

---

© 2025 LabOnDemand - Créé avec ❤️ par Mohamad El Akhal.