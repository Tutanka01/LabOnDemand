# Documentation LabOnDemand

Point d'entrée unique de la documentation. Commencez ici, puis naviguez vers
les guides spécialisés selon votre profil.

---

## Démarrage express (≈ 10 minutes)

1. **Prérequis**
   - Docker Desktop + Docker Compose Plugin
   - `kubectl` pointant vers un cluster (k3s, kind, Minikube, ou distant)
   - Helm (si vous installez un Ingress Controller)

2. **Préparer la configuration**
   ```bash
   cp .env.example .env
   # Renseigner : DB_PASSWORD, DB_ROOT_PASSWORD, ADMIN_DEFAULT_PASSWORD
   # Optionnel  : INGRESS_*, SSO/OIDC, LAB_TTL_*
   ```

3. **Lancer**
   ```bash
   docker compose up -d --build
   docker compose logs -f api   # attendre "Application startup complete"
   ```

4. **Se connecter**
   - Ouvrir `http://localhost/login.html`
   - Connexion admin : `admin` / valeur de `ADMIN_DEFAULT_PASSWORD`

5. **Nettoyer**
   ```bash
   docker compose down -v
   ```

> Besoin de préparer un cluster k3s + Ingress + MetalLB ? Voir `platform-setup.md`.

---

## Où continuer ?

### Opérations & infrastructure

| Document | Contenu |
|----------|---------|
| [`platform-setup.md`](platform-setup.md) | k3s, ingress-nginx, MetalLB, DNS, TLS |
| [`development-setup.md`](development-setup.md) | Variables d'environnement, exécution locale, migrations, logs |
| [`troubleshooting.md`](troubleshooting.md) | Problèmes courants et solutions |

### Architecture & fonctionnement

| Document | Contenu |
|----------|---------|
| [`architecture.md`](architecture.md) | Vue d'ensemble, structure des fichiers, flux de requêtes, modèle de données |
| [`lifecycle.md`](lifecycle.md) | TTL des labs, tâche de nettoyage automatique, namespaces orphelins |
| [`logging.md`](logging.md) | Logs JSON structurés, audit trail, variables de configuration |

### Sécurité & accès

| Document | Contenu |
|----------|---------|
| [`security.md`](security.md) | Sessions, RBAC, mots de passe, rate limiting, suppression propre |
| [`authentication.md`](authentication.md) | Auth locale et SSO/OIDC — diagramme complet, variables, endpoints |

### Ressources & quotas

| Document | Contenu |
|----------|---------|
| [`resource-limits.md`](resource-limits.md) | ResourceQuota K8s, limites applicatives, dérogations `UserQuotaOverride` |
| [`storage.md`](storage.md) | PVC, StorageClass, intégration UI |

### Administration

| Document | Contenu |
|----------|---------|
| [`admin-guide.md`](admin-guide.md) | Gestion utilisateurs, import CSV, dérogations de quotas, health check, dark mode |

### Stacks de déploiement

| Document | Contenu |
|----------|---------|
| [`lamp.md`](lamp.md) | Stack LAMP (Apache + PHP + MySQL + phpMyAdmin) |
| [`wordpress.md`](wordpress.md) | Stack WordPress + MariaDB |
| [`terminal.md`](terminal.md) | Terminal WebSocket dans les pods |

---

## Commandes de référence rapide

| Objectif | Commande |
|----------|----------|
| Healthcheck API | `curl http://localhost:8000/api/v1/health` |
| Logs en direct | `docker compose logs -f api` |
| Audit trail | `tail -f logs/audit.log` |
| Labs expirés nettoyés | `grep deployment_auto_paused_expired logs/app.log` |
| Namespaces K8s actifs | `kubectl get ns -l managed-by=labondemand` |
| Lancer les tests | `python backend/tests/run_tests.py --all` |

---

## Fonctionnalités clés

### Pour les étudiants et enseignants
- Déploiement en 1 clic : VS Code, Jupyter, LAMP, WordPress, MySQL, Custom
- Pause/Resume sans perte de données
- Terminal web intégré dans les pods
- Dashboard avec suivi des quotas CPU/RAM
- Expiration automatique des labs (TTL configurable)
- Mode sombre/clair (toggle dans le header, persisté en localStorage)

### Pour les administrateurs
- RBAC 3 niveaux : student / teacher / admin
- Import CSV d'utilisateurs (création en masse)
- Dérogations de quota individuelles et temporaires
- SSO/OIDC avec mapping automatique des rôles
- Suppression propre d'utilisateur (sessions + namespace K8s)
- Health check enrichi (DB + Redis + K8s)
- Audit trail complet dans `logs/audit.log`

### Pour les ops
- Health check `GET /api/v1/health` — DB + Redis + K8s
- Nettoyage automatique des labs expirés (tâche asyncio)
- Isolation réseau par namespace Kubernetes
- ResourceQuota + LimitRange par namespace et par rôle
- Logs JSON rotatifs (app, access, audit)
