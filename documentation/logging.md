# Observabilite et journalisation

Ce document decrit la pile de logging de LabOnDemand. Il couvre le format des journaux, l organisation du dossier `logs/`, la configuration via variables d environnement et les bonnes pratiques pour la collecte en production.

## Vue d ensemble

LabOnDemand emet des journaux structures en JSON. Le backend FastAPI utilise `logging.config.dictConfig` pour initialiser trois flux principaux:

- `app.log` : journal applicatif general (service, erreurs, execution interne)
- `access.log` : traces HTTP (middleware FastAPI et serveur uvicorn)
- `audit.log` : evenements de securite (authentification, gestion des sessions, operations Kubernetes critiques)

Tous les fichiers sont crees automatiquement au demarrage dans le dossier `logs/`, avec rotation (`RotatingFileHandler`). Une entree `logging_initialized` est ecrite lors de la mise en place pour confirmer la configuration active.

## Organisation du dossier `logs/`

Le dossier `logs/` est cree au demarrage si besoin. Chaque fichier tourne avec les parametres suivants:

- `LOG_MAX_BYTES` (defaut: 5 MiB) : taille maximale avant rotation
- `LOG_BACKUP_COUNT` (defaut: 10) : nombre d archives conservees par fichier

La rotation produit des fichiers numerotes (`app.log.1`, `app.log.2`, etc.) afin de limiter la consommation disque. L ecriture utilise UTF-8 et reste compatible avec la plupart des parseurs JSON.

## Format JSON

Chaque entree suit ce schema minimal:

```json
{
  "timestamp": "2025-10-27T18:22:43.517Z",
  "level": "INFO",
  "logger": "labondemand.auth",
  "message": "login_success",
  "request_id": "7d5c1d4f...",
  "user_id": "admin",
  "namespace": "labondemand-admin"
}
```

Champs detailles:

- `timestamp` : horodatage ISO 8601 en UTC
- `level` : niveau de log (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- `logger` : nom du logger (ex: `labondemand.audit`)
- `message` : evenement principal
- `request_id` : identifiant de requete (injecte par le middleware FastAPI)
- `extra_fields` : champs additionnels (ex: `user_id`, `deployment_name`, `status_code`). Lorsqu ils sont fournis, ils sont fusionnes a la racine du JSON.

En cas d exception, un champ `exception` contient la trace formattee. Les logs d acces uvicorn incluent `method`, `path`, `status_code` et `duration_ms` dans `access.log`.

## Loggers nommes

| Logger                | Description                                                   | Fichier cible   |
|----------------------|---------------------------------------------------------------|-----------------|
| `labondemand`        | Base applicative (services internes, erreurs techniques)       | `app.log`       |
| `labondemand.audit`  | Evenements sensibles (auth/login/logout, actions K8s)          | `audit.log`     |
| `labondemand.access` | Requetes HTTP (enrichies par le middleware)                    | `access.log`    |
| `uvicorn.error`      | Informations serveur uvicorn                                  | `app.log`       |
| `uvicorn.access`     | Trace brute uvicorn (mirroir vers `access.log`)               | `access.log`    |

Les loggers externes conservent leur niveau par defaut mais sont routes vers les handlers ci-dessus.

## Middleware et correlation

Le backend installe un middleware dans `backend/main.py` qui:

1. Genere un `request_id` unique pour chaque requete (UUID raccourci).
2. Stocke cet identifiant dans un `contextvar` accessible via `logging_config.get_request_id()`.
3. Ajoute le `request_id`, l utilisateur connecte (si disponible) et le statut HTTP dans `labondemand.access`.

Cela permet de reconstituer le parcours d une requete dans les trois log files.

## Variables d environnement utiles

| Variable              | Description                                  | Valeur par defaut |
|-----------------------|----------------------------------------------|-------------------|
| `LOG_DIR`             | Chemin du dossier de logs                    | `<repo>/logs`     |
| `LOG_LEVEL`           | Niveau minimal pour `labondemand`            | `INFO`            |
| `LOG_MAX_BYTES`       | Seuil de rotation par fichier (octets)       | `5242880`         |
| `LOG_BACKUP_COUNT`    | Nombre d archives conservees par handler     | `10`              |
| `LOG_ENABLE_CONSOLE`  | Active la sortie console (dev)               | `True`            |
|
| `WATCHFILES_FORCE_POLLING` | (Compose dev) force la surveillance par polling pour eviter l erreur `Invalid argument` avec les partages de fichiers Docker. | `true` (compose.yaml) |

Exporter `LOG_DIR` permet de rediriger les journaux vers un volume partage ou un chemin specifique. Sur Docker Compose, `compose.yaml` monte `./logs:/app/logs` pour persister localement entre redemarrages.

## Collecte et exploitation

- **Developpement** : `docker logs labondemand-api` affiche les messages consoles (si `LOG_ENABLE_CONSOLE=True`). Les fichiers restent consultables sur l hote dans `./logs`.
- **Production** : montez `LOG_DIR` sur un volume persistant. Un agent de collecte (Promtail, Fluent Bit, Filebeat) peut lire les fichiers JSON. Exemple de configuration Promtail:

```yaml
scrape_configs:
  - job_name: labondemand
    static_configs:
      - targets: ["localhost"]
        labels:
          job: labondemand
          __path__: /app/logs/*.log
```

- **Rotation et archivage** : pour des besoins specifiques, ajustez `LOG_MAX_BYTES` et `LOG_BACKUP_COUNT`. Une rotation externe (logrotate) peut etre ajoutee mais n est pas necessaire par defaut.

## Evenements audites

Quelques evenements clefs ecrits dans `audit.log`:

- `login_attempt`, `login_success`, `login_failure`
- `session_created`, `session_terminated`
- `deployment_requested`, `deployment_created`, `deployment_failed`
- `deployment_deleted`, `quota_violation`

Chaque entree inclut le `user_id`, le namespace cible et les metadonnees de la ressource Kubernetes concernee. Combinez ces logs avec `access.log` pour tracer l action precise ayant conduit a une modification cluster.

## Silencieux par defaut

Certains bruits de logs ont ete desactives:

- Les erreurs `404` esperes (favicon) ne clutter plus `app.log`.
- Les print statements historiques ont ete remplaces par des appels `logger` avec niveau approprie.
- Les sessions Redis rapportent uniquement les erreurs et evenements importants.

## Depannage

- **Fichiers absents** : le dossier n existe pas ou les droits ecriture sont insuffisants. Verifiez le montage (Compose: `./logs:/app/logs`).
- **Erreur WatchFiles** : assurez-vous que `WATCHFILES_FORCE_POLLING=true` (ajoute dans `compose.yaml`).
- **Format non JSON** : certains loggers tiers peuvent ecrire en texte brut; utilisez des filtres sur `logger` pour distinguer leur contenu.
- **Pas de `request_id`** : les journaux emis hors contexte HTTP (taches en arriere-plan) n ont pas d identifiant, ce comportement est normal.

## Bonnes pratiques

1. **Centralisez** : envoyez les trois fichiers vers votre stack d observabilite (ELK, Loki, etc.).
2. **Filtrez par `logger`** : `labondemand.audit` pour la conformite, `labondemand.access` pour l analyse trafic, `labondemand` pour le debug.
3. **Correliez via `request_id`** : reliez les evenements d une requete dans les differentes vues.
4. **Supervisez les erreurs** : alertez sur les `level` >= WARNING avec compromis sur le bruit.
5. **Documentez vos enrichissements** : si vous ajoutez des champs supplementaires via `extra={"extra_fields": {...}}`, mettez a jour ce document.

## Ressources supplementaires

- Implementation: `backend/logging_config.py`
- Middleware request-id: `backend/main.py`
- Configuration: `backend/config.py`
- Volume Compose: `compose.yaml`
- Exemple d audit: consulter `logs/audit.log`

Pour toute amelioration ou ajout de loggers, mettez a jour cette documentation et soumettez une merge request pour validation.
