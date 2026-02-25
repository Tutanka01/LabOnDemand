# LabOnDemand

<div align="center">
    <h2 align="center"><a href="https://makhal.fr"><img alt="banner" src="Diagrammes/Images/banner-projet.jpeg" width="400" /></a></h2>
</div>

**LabOnDemand** est une plateforme open-source permettant aux enseignants et étudiants de déployer des environnements de laboratoire isolés (VS Code, Jupyter, WordPress, LAMP, MySQL…) sur Kubernetes, sans connaissances Kubernetes.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

## Démarrage rapide

```bash
git clone <repo> && cd LabOnDemand
cp .env.example .env          # adapter ADMIN_DEFAULT_PASSWORD et CLUSTER_EXTERNAL_IP
nano kubeconfig.yaml            # ajouter le server API Kubernetes
docker compose up --build
# → API sur http://localhost:8000  |  Frontend sur http://localhost:80
# → Compte admin: admin / valeur de ADMIN_DEFAULT_PASSWORD
```

Voir [documentation/development-setup.md](documentation/development-setup.md) pour la configuration complète (.env, kubeconfig, stockage persistant).

## Fonctionnalités

- **Déploiements en 1 clic** : VS Code, Jupyter, WordPress + MariaDB, MySQL + phpMyAdmin, LAMP, ou image Docker personnalisée
- **RBAC** : rôles student / teacher / admin avec quotas CPU/RAM enforced côté serveur
- **Terminal web** intégré (Xterm.js, WebSocket) — accès shell aux pods sans SSH
- **Ingress automatique** : sous-domaine par déploiement avec TLS optionnel (cert-manager)
- **SSO / OIDC** : intégration avec les IdP universitaires (CAS, Keycloak, etc.)
- **Sessions Redis** distribuées — cookie HttpOnly, SameSite, Secure
- **Logging structuré JSON** avec rotation (`logs/app.log`, `access.log`, `audit.log`)
- **Volumes persistants** : PVC automatiques avec fallback `emptyDir` si pas de StorageClass
- **Templates dynamiques** : bibliothèque de déploiements configurable depuis l'interface admin

## Documentation

| Document | Contenu |
|---|---|
| [architecture.md](documentation/architecture.md) | Structure du code, flux d'une requête, RBAC, Ingress |
| [development-setup.md](documentation/development-setup.md) | Setup local, variables .env, migrations |
| [security.md](documentation/security.md) | Sessions, RBAC, mots de passe, OIDC, secrets K8s |
| [troubleshooting.md](documentation/troubleshooting.md) | Problèmes courants et solutions |
| [platform-setup.md](documentation/platform-setup.md) | Installation K3s + Ingress + MetalLB |
| [authentication.md](documentation/authentication.md) | Auth locale et SSO détaillé |
| [storage.md](documentation/storage.md) | Volumes persistants, PVC, StorageClass |
| [lamp.md](documentation/lamp.md) | Stack LAMP |
| [wordpress.md](documentation/wordpress.md) | Stack WordPress |
| [terminal.md](documentation/terminal.md) | Terminal web WebSocket |
| [logging.md](documentation/logging.md) | Logging structuré |

## Stack technique

| Composant | Technologie |
|---|---|
| Backend API | FastAPI (Python 3.11) |
| Frontend | HTML / Vanilla JS / CSS |
| Base de données | MariaDB + SQLAlchemy |
| Sessions | Redis |
| Orchestration | Kubernetes (via client Python officiel) |
| Proxy | Nginx |
| Auth SSO | OIDC / OAuth2 (authlib) |

## Licence

AGPL v3 — voir [LICENSE](LICENSE).
