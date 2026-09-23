---
title: Migrations de la base de données
summary: Schéma versionné par Alembic — démarrage de l'API, ligne de commande, écriture d'une révision, mise à niveau des installations existantes, sauvegarde, retour arrière et dépannage.
read_when: |
  - Tu modifies backend/models.py (colonne, table, index, contrainte, type)
  - Tu mets à jour une installation existante vers une nouvelle version
  - L'API refuse de démarrer avec « schema_upgrade_failed » dans les logs
---

# Migrations de la base de données

Le schéma MariaDB est versionné par **Alembic**. Chaque évolution de
`backend/models.py` est décrite par une *révision* (fichier Python dans
`backend/alembic/versions/`) ; la base enregistre la révision appliquée dans
la table `alembic_version`.

| Fichier | Rôle |
|---|---|
| `backend/db_migrate.py` | Mise à jour au démarrage (`upgrade_schema`), verrou, ligne de commande, configuration Alembic (programmatique : pas d'`alembic.ini`, l'image ne copie que `backend/`) |
| `backend/alembic/env.py` | Environnement Alembic : moteur de l'application + `Base.metadata` |
| `backend/alembic/versions/` | Révisions ; `0001_baseline` = schéma complet à l'introduction d'Alembic |
| `backend/migrations.py` | Mise à niveau des bases **antérieures** à Alembic uniquement (figé) |

> `backend/migrations.py` ne reçoit plus aucune nouvelle entrée : toute
> évolution du schéma passe par une révision Alembic.

---

## Au démarrage de l'API

`bootstrap()` (`backend/main.py`) appelle `upgrade_schema()` avant de servir la
moindre requête :

1. **Verrou** : `GET_LOCK('labondemand_schema:<base>')` sur une connexion
   dédiée. Plusieurs workers ou réplicas démarrant ensemble migrent chacun leur
   tour ; le suivant trouve la base déjà à jour. Le verrou est lié à la session
   MariaDB : il est libéré même si le processus meurt. Pas de verrou sur SQLite
   (tests).
2. **État de la base** (log `schema_state`) :
   - `fresh` (aucune table) : `upgrade head` ;
   - `legacy` (tables présentes, pas de `alembic_version`) : voir
     [Mise à niveau d'une installation existante](#mise-à-niveau-dune-installation-existante) ;
   - `versioned` : `upgrade head` si la base est en retard.
3. **Contrôle final** : la base doit être à la révision *head* du code
   (log `schema_up_to_date`).

**Un échec est fatal** : log `CRITICAL schema_upgrade_failed` avec la cause,
puis arrêt du démarrage (uvicorn quitte avec un code non nul). L'API ne sert
jamais de requêtes sur un schéma incomplet ou incertain. Relancer est sans
risque : chaque étape est idempotente et protégée par le verrou.

> En développement, `compose.yaml` lance uvicorn avec `--reload` : après un
> échec, le processus de rechargement reste vivant mais l'API ne répond pas.
> Corrigez puis redémarrez le conteneur (`docker compose restart api`).

Les **seeds** (admin, templates, runtimes) s'exécutent ensuite. Un échec de seed
n'est **pas** fatal : il est journalisé (`ERROR seed_failed`), les autres seeds
et le démarrage continuent, et il sera retenté au prochain démarrage. Le schéma
étant à jour, l'application reste cohérente ; bloquer toute la plateforme pour
une donnée par défaut serait pire.

| Variable | Défaut | Rôle |
|---|---|---|
| `DB_SCHEMA_LOCK_TIMEOUT` | `300` | Attente maximale du verrou de schéma, en secondes (`0` : ne pas attendre). Au-delà, le démarrage échoue. |

---

## Ligne de commande

Dans le conteneur `api` (même moteur, même `.env` que l'application) :

```bash
docker compose exec api python -m backend.db_migrate current          # état + révision de la base
docker compose exec api python -m backend.db_migrate upgrade          # comme au démarrage (verrou compris)
docker compose exec api python -m backend.db_migrate upgrade --sql    # SQL des révisions (plage : --sql REV:head), sans rien exécuter
docker compose exec api python -m backend.db_migrate check            # échoue si les modèles divergent des révisions
docker compose exec api python -m backend.db_migrate history          # liste des révisions
docker compose exec api python -m backend.db_migrate heads            # révision head du code
docker compose exec api python -m backend.db_migrate revision --autogenerate -m "add foo"
```

`stamp REV` (enregistre une révision sans rien exécuter) et `downgrade REV`
existent pour le développement et le dépannage ; ne les utilisez pas sur une
base de production sans sauvegarde. Code de sortie non nul en cas d'erreur.

---

## Modifier le schéma : une révision par changement de modèle

**Règle** : toute modification de `backend/models.py` qui touche le schéma
(table, colonne, type, nullabilité, index, contrainte, clé étrangère) est
livrée **dans le même commit** qu'une révision Alembic. Le test
`test_models_have_no_pending_changes` fait échouer la suite sinon.

1. Base de développement à jour :
   `docker compose exec api python -m backend.db_migrate upgrade`
2. Modifier `backend/models.py`.
3. Générer la révision (le fichier apparaît dans `backend/alembic/versions/`,
   monté depuis l'hôte) :

   ```bash
   docker compose exec api python -m backend.db_migrate revision --autogenerate \
       -m "add classroom capacity" --rev-id 0002_classroom_capacity
   ```

   `--rev-id` est facultatif mais donne des identifiants lisibles et ordonnés.
4. **Relire et corriger la révision à la main.** L'autogénération est un
   brouillon :
   - un renommage apparaît comme *suppression + ajout* (perte de données) :
     le réécrire avec `op.alter_column(..., new_column_name=...)` ;
   - les `server_default` ne sont pas comparés : les ajouter si besoin ;
   - une colonne `NOT NULL` ajoutée à une table existante exige un
     `server_default` ou un remplissage (`op.execute(...)`) avant la contrainte ;
   - les modifications d'`Enum` et de longueur de `String` sont à vérifier sur
     MariaDB ;
   - les migrations de données (`op.execute`, `sa.table(...)`) s'écrivent dans
     la même révision.
5. Écrire `downgrade()` quand c'est raisonnable (utile en développement) ; en
   production le retour arrière passe par la sauvegarde.
6. Vérifier :

   ```bash
   docker compose -f compose.test.yaml run --rm --build tests
   docker compose -f compose.test.yaml --profile mariadb run --rm --build tests-mariadb
   docker compose -f compose.test.yaml --profile mariadb down -v
   ```

Bonnes pratiques :

- **Une révision = un changement logique**, petite. Le DDL de MariaDB n'est pas
  transactionnel : une révision qui échoue à mi-parcours laisse ses premières
  instructions appliquées.
- Ne jamais modifier une révision déjà déployée (ni la baseline) : en créer une
  nouvelle.
- Une seule tête : si deux branches ajoutent chacune une révision sur la même
  parente, `test_revisions_have_a_single_head_rooted_at_baseline` échoue (et
  le démarrage refuse plusieurs têtes). Rebaser sa révision en corrigeant son
  `down_revision`.
- Pas de `naming_convention` : les index gardent les noms SQLAlchemy
  (`ix_<table>_<colonne>`) et MariaDB nomme les clés étrangères
  `<table>_ibfk_N`. Pour supprimer une contrainte, vérifier son nom réel
  (`SHOW CREATE TABLE`).

---

## Mise à niveau d'une installation existante

### Première mise à jour vers une version avec Alembic

Une base créée avant Alembic n'a pas de table `alembic_version` : elle est
détectée comme `legacy` au premier démarrage, qui, sous le verrou :

1. crée les tables manquantes (`create_all`, jamais d'`ALTER`) ;
2. rejoue la liste `ALTER` historique (`backend/migrations.py`) : seules les
   erreurs « déjà appliqué » sont ignorées (MariaDB 1050, 1060, 1061, 1091 et
   leurs équivalents SQLite) ; toute autre erreur arrête le démarrage ;
3. remplace l'index `ix_users_external_id` par sa version unique si nécessaire
   et supprime le doublon historique `idx_users_external_id_unique` ;
4. compare la base aux modèles : s'il manque encore une table ou une colonne,
   le *stamp* est refusé ; les autres écarts sont journalisés
   (`WARNING legacy_schema_drift`) ;
5. enregistre la baseline (`stamp 0001_baseline`), puis `upgrade head`.

Logs attendus : `schema_state` (`legacy`), `legacy_schema_upgrade_started`,
`legacy_migration_applied`…, `legacy_schema_stamped`, `schema_up_to_date`.

Aucune donnée n'est supprimée : seuls des tables, colonnes et index sont
ajoutés et l'index doublon est retiré. Les tables inconnues des modèles
(ex. l'ancienne table `labs`) sont conservées et ignorées par Alembic.

Un premier démarrage interrompu reprend au suivant : la base reste `legacy`
tant que la baseline n'est pas enregistrée, et toutes ces étapes sont
idempotentes.

### Mises à jour suivantes

La base est `versioned` : le démarrage applique simplement les révisions
manquantes. Pour prévisualiser : `python -m backend.db_migrate upgrade --sql
<révision actuelle>:head`.

### Procédure recommandée

1. **Sauvegarder** (ci-dessous) et vérifier que le fichier n'est pas vide.
2. Déployer la nouvelle version et suivre `docker compose logs -f api`
   jusqu'à `schema_up_to_date` puis « Application startup complete ».
3. En cas d'échec : lire le log `schema_upgrade_failed`, corriger (voir
   [Dépannage](#dépannage)), redémarrer.

---

## Sauvegarde et retour arrière

**Toujours sauvegarder avant une mise à jour.** Le DDL de MariaDB n'étant pas
transactionnel, la sauvegarde est la seule garantie de retour à l'état exact
d'avant la migration.

```bash
# Sauvegarde (mots de passe lus dans le conteneur, jamais sur la ligne de commande de l'hôte)
docker compose exec -T db sh -c 'exec mariadb-dump -uroot -p"$MYSQL_ROOT_PASSWORD" \
    --single-transaction --routines --triggers --databases "$MYSQL_DATABASE"' \
    > backup-labondemand-$(date +%F-%H%M).sql
```

Retour arrière après une migration ratée ou une version à abandonner :

1. Arrêter l'API : `docker compose stop api`.
2. Restaurer la sauvegarde **dans une base vide** (opération destructive :
   uniquement avec une sauvegarde vérifiée). Les tables créées par la nouvelle
   version n'étant pas dans la sauvegarde, une restauration par-dessus la base
   existante les laisserait en place :

   ```bash
   docker compose exec -T db sh -c 'exec mariadb -uroot -p"$MYSQL_ROOT_PASSWORD" \
       -e "DROP DATABASE \`$MYSQL_DATABASE\`"'
   docker compose exec -T db sh -c 'exec mariadb -uroot -p"$MYSQL_ROOT_PASSWORD"' \
       < backup-labondemand-AAAA-MM-JJ-HHMM.sql
   ```

3. Redéployer l'image **précédente** et la démarrer.

Une image gérant Alembic refuse de démarrer sur une base migrée par une
version plus récente (« révision inconnue ») : c'est voulu, l'ancien code ne
connaît pas le nouveau schéma. La baseline refuse `downgrade` ; `downgrade`
vers une révision intermédiaire reste possible si les révisions concernées
l'implémentent, mais la restauration est la voie sûre en production.

Cas particulier du premier passage à Alembic : la mise à niveau legacy
n'applique que la liste `ALTER` que l'image précédente exécutait déjà, plus la
table `alembic_version` et l'index unique. La dernière image pré-Alembic
démarre donc sur la base mise à niveau (elle ignore `alembic_version`) ; elle
peut recréer l'index doublon `idx_users_external_id_unique`, que `check`
signalera ensuite. La restauration reste préférable.

---

## Dépannage

| Message (log `schema_upgrade_failed` ou CLI) | Cause | Action |
|---|---|---|
| `… users.external_id sont partagées par plusieurs comptes … Dédoublonnez` | Doublons SSO bloquant l'index unique (base legacy) | Exécuter la requête `SELECT` indiquée, fusionner ou corriger les comptes, redémarrer |
| `Verrou de schéma … non obtenu en N s` | Une autre instance migre (ou est bloquée) | Attendre sa fin (`SELECT * FROM information_schema.PROCESSLIST`), relancer, ou augmenter `DB_SCHEMA_LOCK_TIMEOUT` |
| `La base est à la révision '…', inconnue de cette version` | Image plus ancienne que la base | Redéployer la version qui a migré la base, ou restaurer la sauvegarde |
| `Base legacy incomplète après mise à niveau, stamp de la baseline refusé` | Base legacy trop éloignée des modèles | Comparer avec `SHOW CREATE TABLE`, corriger à la main (sauvegarde d'abord), redémarrer |
| `Migration legacy '…' en échec` | Erreur réelle (droits, verrou, syntaxe…) sur une étape legacy | Lire l'erreur MariaDB jointe, corriger, redémarrer |
| `DB_SCHEMA_LOCK_TIMEOUT invalide` | Valeur non entière ou négative | Corriger `.env` |

`python -m backend.db_migrate current` affiche l'état (`fresh`, `legacy`,
`versioned`), la révision de la base et la révision head du code.

---

## Tests

| Commande | Couverture |
|---|---|
| `docker compose -f compose.test.yaml run --rm --build tests` | SQLite : base vierge → head sans écart avec les modèles, baseline identique à `create_all`, bases legacy (4 variantes) stampées et idempotentes, erreurs réelles propagées, démarrage fatal, CLI |
| `docker compose -f compose.test.yaml --profile mariadb run --rm --build tests-mariadb` | MariaDB 11.8 jetable (tmpfs) : mêmes scénarios, DDL identique à `create_all` (noms `ibfk_N` compris), deux démarrages concurrents sérialisés par `GET_LOCK` |

Le profil `mariadb` est opt-in (`TEST_MARIADB=1`) : la suite par défaut n'en a
pas besoin. Supprimer ensuite le serveur jetable :
`docker compose -f compose.test.yaml --profile mariadb down -v`.
