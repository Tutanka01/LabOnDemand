# LabOnDemand - Vision et specification du systeme de devoirs

> Document de reference produit + technique. Il fixe la vision, tranche les choix
> structurants (domaine cible, modele d'evaluation, architecture du grader),
> decrit l'experience cible et donne un modele de donnees, une API et une roadmap
> assez precis pour commencer a developper.
>
> Decisions verrouillees :
> - Domaine cible : **sysadmin / web / deploiement**.
> - Modele d'evaluation : **boite noire comportementale** d'abord (on teste le systeme vu de l'exterieur).
> - Execution des tests : **Grader Pod externe et isole**. Le contenu des tests est ecrit par l'enseignant.
> - Philosophie de notation : **la preuve d'abord, la note ensuite**. L'automatisation trie, l'humain decide.

---

# Etat d'avancement

**Fait — Phase 1 / MVP-1 (le devoir devient reel)** :
- Backend : modele `AssignmentSubmission` (1 ligne/etudiant/devoir, upsert), router etudiant
  `/api/v1/student/assignments` (liste, detail, submit, submission), endpoints de correction
  cote prof (liste des rendus, detail, grade), champ `deliverables` ajoute a `Assignment`,
  migrations + tests (`tests/test_submissions.py`, 10 verts).
- Frontend : « Mes devoirs » comme page d'accueil etudiant, page detail (consignes +
  livrables en **Markdown**, ouverture du lab pousse, rendu texte + liens), vue de
  correction prof (tableau + dialogue note/feedback), dialogue de creation enrichi (enonce
  + livrables Markdown avec apercu), i18n FR/EN.
- Lab provisionne par **push prof** (reutilise `deploy-all`) ; rendu = **texte + liens**
  (pas d'upload de fichiers).

**Fait — Phase 2 / MVP-2 briques 1 & 2 (modele + ecriture des tests)** :
- Backend : modeles `GradingSpec` (batterie de probes par devoir, `checks` JSON) et
  `GradingRun` (execution + resultats, token usage unique), champ `grading_mode` sur
  `Assignment`, 3 migrations idempotentes, schemas Pydantic `Probe / GradingSpecCreate /
  GradingSpecResponse / GradingRunResponse / GradingRunCallbackRequest`.
- Backend : endpoints `GET/POST /api/v1/classrooms/{cid}/assignments/{aid}/grading-spec`
  (upsert avec activation automatique du `grading_mode`).
- Frontend : onglet **« Tests automatiques »** dans le dialogue de creation/edition de devoir
  (liste de probes, formulaire par kind HTTP/TCP/SQL/Fichier/Commande/Script avec champs
  specifiques, section « Script avance » depliable, selecteur `grading_mode` + timeout,
  sauvegarde independante ou integree au save du devoir), types TypeScript (`Probe,
  GradingSpec, GradingRun...`), appels API (`getGradingSpec, saveGradingSpec, runTestsStudent,
  getGradingRun, testNow, runTestsAll`), CSS probe editor, i18n 65+ cles FR/EN.
- Build TypeScript/Vite confirme propre.

**Reste a faire (MVP-2)** :
- Brique 3 : image Grader (`dockerfiles/grader/`), service `grader_service.py` (Job K8s
  isole, NetworkPolicy, ServiceAccount sans droits, token hash, TTL).
- Brique 4 : endpoints d'execution (`run-tests` etudiant, `test-now` / `run-tests-all` prof,
  hook `on_submit`, endpoint interne token-authentifie).
- Brique 5 : UI triage — progression check par check etudiant, colonne verdict `x/5` +
  note suggeree prof.
- Brique 6 : tests backend (K8s mocke), reconciliation cleanup, validation securite.

**Phase 3 et suivantes** : cockpit prof avance, start-lab a la demande, bouton « Je suis
bloque », Lab Blueprints, SSO, assistant IA.

---

# Partie I - Vision

## 1. De la plateforme de labs a l'infrastructure pedagogique

LabOnDemand sait aujourd'hui lancer des environnements. C'est utile, mais ce n'est pas
encore une plateforme pedagogique. Une plateforme qui lance des conteneurs reste un outil
d'infrastructure tant qu'elle ne comprend pas l'intention du professeur, le parcours de
l'etudiant, la preuve du travail rendu et la boucle de feedback. Le vrai sujet n'est pas
de demarrer un lab plus vite. Le vrai sujet est de transformer un lab en experience
d'apprentissage complete.

La vision cible : LabOnDemand devient l'endroit ou un enseignant cree une mission
pedagogique complete, la publie a une classe, suit l'avancement, aide ceux qui bloquent,
recolte les rendus, corrige avec l'aide de tests automatiques, donne du feedback et
reutilise ses meilleurs TP d'une annee a l'autre. Pour l'etudiant, c'est encore plus
simple : il voit ses devoirs, ouvre le bon environnement, travaille, rend, recoit un
retour. Il ne devrait jamais avoir a comprendre ce qu'est un namespace, un service, une
image Docker ou un deploiement Kubernetes pour faire son travail.

Le centre de gravite change. Aujourd'hui le lab est percu comme l'objet principal. Demain
le lab devient un moyen au service d'une mission. L'objet central devient le devoir : un
objectif, un environnement, des consignes, une preuve de travail et un feedback.

## 2. La regle d'or

> L'etudiant ne devrait jamais avoir a comprendre l'infrastructure pour faire son devoir,
> et l'enseignant ne devrait jamais avoir a devenir DevOps pour creer un bon TP.

Cette phrase tranche toutes les decisions d'interface, de modele de donnees, d'API et de
roadmap. Si une fonctionnalite rapproche le produit de cette promesse, elle merite d'etre
consideree. Si elle expose plus de complexite technique a l'etudiant ou impose plus de
travail DevOps au professeur, elle doit etre questionnee.

## 3. Le nouveau modele mental : le devoir comme ecart d'etat

C'est le point le plus important du document, et c'est lui qui distingue LabOnDemand d'un
codewars ou d'un LeetCode.

Un codewars evalue une fonction : une entree, une sortie, un probleme ferme, sans
environnement. Si c'etait notre besoin, nous n'aurions pas besoin de Kubernetes : ces
outils existent deja et sont meilleurs pour ca.

Un lab LabOnDemand est l'inverse : un **systeme vivant, avec un etat, souvent
multi-service** (LAMP = apache + mysql + php, WordPress, nginx, etc.). Notre valeur unique
n'est pas "le code est juste", c'est **"le systeme que tu as monte fonctionne reellement"**.

D'ou la definition produit :

> Un devoir, c'est un **etat de depart** (le blueprint), un **etat cible** (le but), et un
> ensemble de **signaux observables** qui mesurent l'ecart entre les deux. On n'evalue pas
> un fichier rendu. On evalue **la transformation que l'etudiant fait subir a un
> environnement**.

C'est exactement ce qu'aucun codewars ne peut faire : il n'a pas d'environnement persistant
a transformer. Nous, si. "Deploie un WordPress qui sert une page titree X", "repare cette
conf nginx cassee", "cree un schema MySQL avec une table users", "expose une API Flask
/health" : ce sont des etats cibles d'un systeme, pas des fonctions.

Dans l'interface on parle de devoir, mission ou TP. Dans le backend l'objet garde le nom
`Assignment`. L'etudiant realise une mission, le professeur cree un devoir, le systeme
stocke un assignment.

---

# Partie II - Le coeur : qu'est-ce qu'on evalue, et comment

## 4. Domaine cible assume : sysadmin / web / deploiement

On ne cherche pas a tout evaluer. On se specialise sur ce que seul un lab permet bien :
monter, configurer, deployer et faire fonctionner un systeme reel. C'est la que la
boite noire est la plus naturelle et la plus solide. Tout le produit est optimise pour ce
terrain ; l'algo pur (style codewars) n'est pas une cible et ne doit pas dicter
l'architecture.

## 5. On evalue un systeme vivant, pas un fichier rendu

La consequence directe du modele "ecart d'etat" : l'objet d'evaluation est l'environnement
de l'etudiant a un instant T (au rendu, ou a la demande), observe de l'exterieur. Le
fichier rendu existe encore (texte, lien, capture) mais il devient secondaire face a la
question "est-ce que ca marche ?".

Probleme dur a garder en tete en permanence : **le lab est mortel, la soumission est
eternelle**. Les `Deployment` ont un `expires_at` et une tache de cleanup. Au moment de la
correction, le lab de l'etudiant aura souvent disparu. On ne peut donc pas se reposer sur
"le prof ira regarder le lab plus tard". Il faut capturer la preuve **au moment ou le
systeme est observe** : c'est le role du Grader Run et du snapshot de soumission.

## 6. Les trois couches d'evaluation

| Couche | Quoi | Automatisable | Place dans le produit |
|---|---|---|---|
| **Comportementale (boite noire)** | Le systeme fait-il ce qu'il doit, vu de l'exterieur ? HTTP 200, port ouvert, requete SQL OK, contenu de page | Oui, robuste, agnostique au langage | **Coeur du produit** |
| **Artefact (boite blanche)** | Le contenu interne est-il correct ? fichier present, conf bien ecrite, sortie d'une commande, N commits git | Partiel, plus fragile, contournable | Secondaire, formatif |
| **Comprehension** | A-t-il compris ? Bon choix de design ? | Non, jamais | Humain, toujours |

Principe : **80 % de l'energie sur la couche comportementale.** L'artefact est un appoint.
La comprehension reste humaine, et c'est une force, pas une lacune. L'automatisation ne
remplace pas le professeur : elle lui rend du temps.

## 7. L'abstraction Probe

Plutot que de coder en dur des "types de tests", tout repose sur un objet declaratif unique :
la **Probe**. Une probe est une verification qui produit un verdict.

```
Probe = {
  id:         "health-200"
  name:       "La route /health repond 200"
  vantage:    outside | inside        # de l'exterieur (reseau) ou dans le pod (exec)
  kind:       http | tcp | sql | file | command | script
  config:     { ... }                 # depend du kind (url, port, path, query, cmd...)
  expect:     { ... }                 # status, contains, regex, exit_code, rows...
  weight:     1                       # ponderation indicative (pas une note finale)
  visibility: student | summary | teacher_only
}
```

Exemples concrets pour le domaine cible :

- `http` outside : `GET http://lab/health` attend status 200 et body contient `"ok"`.
- `http` outside : `GET http://lab/users` attend un JSON contenant un tableau non vide.
- `tcp` outside : le port 3306 est ouvert.
- `sql` outside : `SELECT count(*) FROM users` retourne >= 1.
- `file` inside : `/etc/nginx/nginx.conf` existe et contient `gzip on`.
- `command` inside : `systemctl is-active apache2` retourne exit code 0.
- `script` : un script fourni par l'enseignant s'execute et renvoie un verdict structure.

Ce modele unique permet de passer d'un simple `curl` a un grader complet sans changer
l'architecture : on ajoute des probes, c'est tout. Une probe `outside/http` et une probe
`inside/command` vivent dans le meme moteur.

## 8. Le Grader Pod : architecture d'execution

C'est le vrai sujet technique. La question n'est pas "quel type de test" mais **ou il
s'execute**. Deux options, deux usages :

**Option A - le test tourne DANS le lab de l'etudiant** (exec dans son pod).
- Reutilise l'exec existant (`k8s_terminal`). Trivial.
- Mais l'etudiant voit/peut trafiquer les tests et falsifier le resultat.
- Verdict : **uniquement pour l'auto-evaluation formative** (aide pendant le travail).

**Option B - un Grader Pod ephemere, isole, qui attaque le lab de l'exterieur.**
- Un Job Kubernetes jetable, dans un namespace verrouille, qui execute les probes contre
  le lab cible puis renvoie son verdict a l'API.
- Tests caches possibles, non trafiquables, resultat fiable.
- Verdict : **le seul modele viable pour de la notation.**

On choisit **B** comme modele de reference, parce qu'il epouse l'architecture k8s existante
(on sait deja orchestrer des pods) et parce que c'est lui qui permet de grader sans tricher.
A peut venir plus tard comme mode "self-check" optionnel.

### Le Grader Pod en detail

```
            +-----------------------------+
            |   API LabOnDemand           |
            |  cree un GradingRun         |
            +--------------+--------------+
                           | cree un Job + token a usage unique
                           v
   +----------------------------------------------+
   |  Grader Pod (Job ephemere, namespace grader) |
   |  - image grader fournie par la plateforme    |
   |    (curl, bash, python, jq, psql, mysql...)  |
   |  - recoit la liste des probes + l'URL du lab |
   |  - NetworkPolicy : egress AUTORISE seulement |
   |    vers le pod du lab cible + API resultats   |
   |  - aucun credential cluster, aucun kubeconfig |
   |  - timeout strict, CPU/RAM plafonnes          |
   +----------------------+-----------------------+
                          | execute chaque probe
                          v
            +-----------------------------+
            |  Lab de l'etudiant (cible)  |
            +-----------------------------+
                          |
                          | POST resultats (token a usage unique)
                          v
            +-----------------------------+
            |   API : enregistre le       |
            |   GradingRun + GradingResult|
            +-----------------------------+
```

Garanties de securite non negociables :
- Le Grader Pod n'a **jamais** d'acces au cluster (pas de service account privilegie, pas
  de kubeconfig).
- NetworkPolicy stricte : il ne peut joindre que le lab cible et l'endpoint de resultats.
- Time-box et quotas CPU/RAM : un grader ne doit jamais pouvoir mettre le cluster en danger.
- Le token de retour des resultats est a usage unique et lie au GradingRun.
- Le Job est supprime apres execution (TTL court).

### Qui ecrit les tests, et comment (cote enseignant)

Le contenu des tests est ecrit par l'enseignant, a deux niveaux :

1. **Niveau simple (sans code) - le defaut.** L'enseignant remplit un formulaire : "fais un
   GET sur `/health`, attends 200 et `ok`". La plateforme genere la probe `http`. Pareil
   pour port ouvert, requete SQL simple, presence/contenu de fichier. C'est le cas
   majoritaire pour sysadmin/web/deploiement, et ca tient en quelques clics.

2. **Niveau script (pour les power users).** L'enseignant fournit un script (bash/python)
   qui s'execute dans le Grader Pod contre le lab et respecte un **contrat de sortie**
   simple : sortie JSON sur stdout decrivant les checks, ou exit code 0 = succes /
   non-zero = echec. Exemple minimal de contrat :

   ```json
   { "checks": [
       { "id": "health", "name": "/health repond", "status": "pass",
         "message": "200 OK en 42ms", "weight": 1, "visibility": "student" },
       { "id": "users", "name": "/users renvoie une liste", "status": "fail",
         "message": "attendu un tableau, recu 500", "weight": 2, "visibility": "summary" }
   ] }
   ```

   Cote infra c'est simple : la plateforme fournit l'image grader avec les outils usuels,
   monte le script de l'enseignant, et l'execute. L'enseignant ne gere aucune infra ; il
   ecrit juste des verifications. Un mode expert (image grader custom de l'enseignant)
   pourra venir plus tard, sous validation admin.

## 9. Du verdict a la note : la preuve d'abord, le triage ensuite

Position ferme : en v1, **aucune note finale automatique**. Le Grader Run produit un
**bundle de preuves** : "14:32 - GET /health a renvoye 200 ; fichier app.py present ;
4/5 probes passees ; capture jointe". L'enseignant note **en regardant les preuves**, avec
une note suggeree (somme ponderee des probes passees) qu'il peut accepter ou ignorer.

Pourquoi : ca evite d'un coup le debat "un script peut-il noter justement", le gaming, et
la responsabilite d'une mauvaise note automatique. Et on garde 90 % du gain de temps.

**Le vrai produit, ce n'est pas l'auto-grading, c'est le triage.** Le probleme reel du prof
aujourd'hui ("il se connecte, il regarde lab par lab") c'est que 30 etudiants = 30 labs a
cliquer, ce qui ne scale pas. Les probes transforment "30 labs a inspecter" en "un dashboard
de 30 verdicts evides, et je n'ouvre a la main que les cas ambigus". L'automatisation trie,
l'humain juge le residu. C'est plus modeste que "la machine corrige", donc beaucoup plus
atteignable, et c'est la vraie valeur.

Piege ed-tech a eviter : sur-investir l'auto-grader parce que c'est techniquement excitant,
alors que l'essentiel de l'apprentissage n'est pas auto-evaluable.

## 10. Anti-triche et visibilite

- Les probes ont une visibilite : `student` (sortie complete visible), `summary` (juste
  pass/fail), `teacher_only` (cachee a l'etudiant).
- **Formatif vs sommatif.** Pendant le travail, les probes doivent etre visibles : c'est un
  outil d'apprentissage. Pour la note, on s'appuie sur des probes cachees executees dans le
  Grader Pod, non trafiquables. Ne jamais pretendre qu'une probe visible executee dans le
  pod de l'etudiant est une notation securisee.
- Le rendu reste possible meme si des probes echouent (sauf configuration contraire) : un
  echec de test est aussi une information pedagogique.

---

# Partie III - Les objets du produit

## 11. Le devoir (Assignment / Mission)

Un devoir est une mission pedagogique complete : une intention (ce qu'on doit apprendre ou
demontrer), un environnement (le blueprint), des consignes, une definition de la preuve de
travail, une grille d'evaluation (les probes), et une boucle de feedback.

Cycle de vie cote enseignant : `brouillon` -> (validation technique du lab et des probes) ->
`pret a publier` -> `publie` -> `cloture` (apres deadline) -> `archive`. Un devoir archive
n'est plus modifiable mais reste duplicable (la duplication cree un nouveau brouillon). Une
publication fige la version (consignes + blueprint + probes) : un etudiant deja engage n'est
pas impacte par une modification ulterieure sans decision explicite.

Cycle de vie cote etudiant : `non commence` -> `lab pret` -> `en cours` -> (`bloque`) ->
`rendu` / `rendu en retard` -> `corrige` / `reprise demandee`. Ces statuts structurent
l'experience ; ils ne sont pas des details techniques caches.

Types de missions (le moule s'adapte au besoin, on ne force pas tout dans un seul format) :
- **TP guide** : etapes, checklist, quelques probes formatives visibles. Debutants.
- **Defi comportemental** : un objectif, un lab, des probes boite noire. "Fais que ca
  marche." C'est le format phare du domaine cible.
- **Rendu manuel** : consignes ouvertes, correction humaine, la plateforme fournit le lab
  et capture la preuve.
- **Hybride** : lab + probes pour guider + rendu structure + correction humaine qui
  s'appuie sur les preuves sans s'y reduire. Cible a terme.

## 12. Le Lab Blueprint (allege, introduit plus tard)

Le blueprint est la recette reproductible d'un environnement (point de depart de l'ecart
d'etat). A terme : versionne, immuable une fois publie, avec validation et previsualisation.

**Decision de sequencement : le blueprint complet n'est pas dans le MVP.** Au depart on
reutilise les `Template` existants comme blueprints "shadow" (un template = un blueprint
simple). Le modele `LabBlueprint` / `LabBlueprintVersion` versionne arrive en phase
ulterieure, sans big-bang. La premiere vraie rupture produit n'est pas le blueprint, c'est
l'experience devoir.

## 13. La soumission comme preuve de travail

La soumission n'est pas juste un fichier. C'est une preuve structuree et defendable : qui a
rendu quoi, quand, dans quel contexte, avec quel lab, quels resultats de probes, quel
feedback. En cas de contestation ou de probleme technique, elle permet de comprendre ce qui
s'est passe.

Une `AssignmentSubmission` porte au minimum : mission, etudiant, numero de tentative, date,
indication de retard, deadline au moment du rendu, texte, liens, fichiers, lab associe,
**snapshot technique leger** (id du lab, nom du deployment, namespace, image, urls, statut,
date de creation), reference au dernier Grading Run, note, feedback, correcteur, statut.

Snapshot : on capture le minimum au moment du rendu (le lab pouvant disparaitre ensuite).
Le snapshot riche (logs, archive de volume, hash git, captures) est explicitement hors MVP.

Politique de rendus multiples configurable. Defaut pedagogique : plusieurs rendus autorises
jusqu'a la deadline, on corrige la derniere version. Le rendu tardif est un etat pedagogique
visible, pas une erreur technique.

## 14. Les evenements pedagogiques (apres le MVP-1)

Pour suivre le parcours (qui n'a pas commence, qui bloque, depuis quand), on enregistre des
evenements a nomenclature explicite : `assignment.viewed`, `lab.opened`, `tests.run`,
`submission.created`, `submission.late`, `feedback.published`, `revision.requested`,
`help.requested`, `lab.expired`. Ils alimentent le cockpit, les alertes et les exports.

Note : en MVP-1, beaucoup de statuts peuvent etre **derives** sans table d'evenements (a un
deployment ? a une soumission ? en retard vs `due_at` ?). On ajoute les evenements quand on
a besoin du temporel.

---

# Partie IV - L'experience (UI / UX)

L'exigence est une tres belle UI et une excellente UX. La regle : a chaque ecran, une action
principale evidente, un langage produit (pas de jargon k8s), des etats de chargement et
d'erreur soignes, et zero recherche manuelle pour retrouver "le bon lab".

## 15. UX etudiant

### 15.1 "Mes devoirs" (la nouvelle porte d'entree)

Remplace le catalogue de templates comme page d'accueil etudiant. Une grille de cartes,
groupees par etat : **A faire**, **En cours**, **Deadline proche**, **Rendu**, **Corrige**,
**Reprise demandee**.

Chaque carte affiche : titre, classe, type de mission, deadline (avec compte a rebours
lisible quand elle approche), statut, etat du lab (eteint / pret / en cours), et **un bouton
principal contextuel** : Demarrer, Continuer, Ouvrir le lab, Rendre, Voir le feedback,
Reprendre. La couleur et l'intitule du bouton changent selon l'etat. Les cartes en retard
ou bloquees sont visuellement distinctes (sans etre punitives).

Micro-UX : skeleton loaders pendant le chargement, etat vide accueillant ("Aucun devoir
pour l'instant"), tri par deadline par defaut, filtre par classe.

### 15.2 Detail d'un devoir : le poste de travail

Layout deux colonnes.

- **Colonne principale (le contenu)** : objectif, consignes structurees (etapes,
  ressources, criteres de reussite), et la liste des **tests visibles** avec leur etat
  (a executer / vert / rouge) et leur message pedagogique.
- **Colonne d'action (sticky, a droite)** : statut du lab, temps restant avant expiration,
  bouton **Ouvrir mon lab**, bouton **Lancer les tests** (self-check formatif), bouton
  **Je suis bloque** (phase ulterieure), bouton **Rendre**, et la deadline.

Quand l'etudiant lance les tests, il voit une progression check par check (en cours -> vert
/ rouge) avec, pour chaque probe visible, un message clair ("/health a renvoye 500 au lieu
de 200"). C'est l'experience la plus motivante : un retour immediat et concret sur son
systeme.

### 15.3 Ouverture du lab

Transparente. L'etudiant clique sur Ouvrir : si un lab existe il est repris, sinon il est
cree (selon la strategie du devoir). Pendant l'attente : etat clair "Preparation... / Pret"
avec une barre de progression, jamais de jargon. En MVP, le lab peut etre pre-pousse par le
prof (voir migration) : l'etudiant n'a alors qu'a Ouvrir.

### 15.4 Rendu

Le formulaire correspond exactement a ce que le prof a demande : si on attend un lien + une
capture + un commentaire, il y a ces trois champs et rien d'autre. L'etudiant peut lancer
les tests avant de rendre. Au rendu, on capture le snapshot du lab et on declenche
eventuellement un Grading Run. Confirmation claire, avec l'horodatage et l'eventuel badge
"en retard".

## 16. UX enseignant

### 16.1 Le cockpit (pas un tableau de bord)

Un tableau de bord montre des chiffres ; un cockpit permet d'agir. Pendant une seance, le
prof voit : devoirs actifs, labs en erreur, etudiants bloques, etudiants non commences, labs
qui expirent bientot, rendus recus, **probes massivement en echec** (signal qu'une consigne
ou le blueprint pose probleme a toute la classe). Chaque alerte a une action directe : voir,
relancer, prolonger, repondre, corriger, exporter.

### 16.2 La page d'un devoir : centre de pilotage

Un tableau qui raisonne **en etudiants, pas en deploiements** : nom, statut, lab, derniere
activite, rendu, retard, **resultat des probes (ex : 4/5)**, note, action. Tri et filtre par
statut. Actions groupees : relancer les labs echoues, prolonger ceux qui expirent,
(re)lancer les tests sur toute la classe, relancer les non-commences, prolonger la deadline,
exporter en CSV, dupliquer le devoir vers une autre classe.

### 16.3 La correction : tout au meme endroit

Quand le prof ouvre un rendu : contenu soumis, fichiers, liens, commentaire de l'etudiant,
snapshot technique du lab, **resultats detailles des probes** (avec sorties), historique des
tentatives, et un bouton pour ouvrir le lab de l'etudiant si besoin (l'echappatoire, rare).
Il corrige avec une note (libre, ou pre-remplie par la suggestion ponderee des probes), un
commentaire, des feedbacks reutilisables, ou demande une reprise.

L'enjeu UX : faire en sorte que le prof passe ses deux heures de correction sur les 6 cas
ambigus, pas sur les 24 cas evidents. Les verdicts de probes trient ; la vue de correction
met le residu humain en avant.

### 16.4 La creation d'un devoir et de ses tests (l'atelier)

Un wizard en quelques etapes : intention -> environnement (choix d'un blueprint/template en
langage pedagogique) -> consignes -> **definition des tests** -> regles de rendu et deadline
-> previsualisation comme etudiant -> validation technique -> publication.

L'etape "tests" est cle et doit rester simple :
- Un bouton "Ajouter un test" qui ouvre un mini-formulaire par type : **Requete HTTP**
  (URL, methode, status attendu, texte attendu), **Port ouvert**, **Requete SQL**,
  **Fichier present/contenu**, **Commande**. Chaque test a un nom lisible, une ponderation,
  et une visibilite (visible eleve / resume / cache).
- Un onglet "Script avance" pour coller un script respectant le contrat de sortie JSON.
- Un bouton **"Tester maintenant"** qui lance un Grading Run contre le lab de demonstration
  du prof et affiche les verdicts : le prof voit immediatement si ses tests sont justes.

Promesse : creer un TP complet (consignes + environnement + tests) en 15 minutes, sans
ecrire de Dockerfile, et le plus souvent sans ecrire une ligne de code de test.

---

# Partie V - Mise en oeuvre

## 17. Modele de donnees

Existant a conserver : `User`, `Template`, `Deployment`, `Classroom`, `Enrollment`,
`Assignment`, `AssignmentDeployment`, `RuntimeConfig`, `UserQuotaOverride`.

`Assignment` (enrichi) :
- existant : `classroom_id`, `title`, `instructions`, `template_key`, `cpu_preset`,
  `ram_preset`, `due_at`, `status`.
- a ajouter : `mission_type` (guided|challenge|manual|hybrid), `grading_mode`
  (none|self_check|graded), `submission_policy` (single|multi|keep_all),
  `late_policy` (block|allow_badge), `max_attempts` (nullable),
  `blueprint_version_id` (nullable, plus tard).
- Attention migration : aujourd'hui `status` vaut `active`/archive et `deploy-all` teste
  `status == "active"`. Le passage a la machine a etats `draft/published/...` doit etre fait
  en preservant ce chemin (ou en mappant `published` -> deployable).

`GradingSpec` (la batterie de tests d'un devoir) - peut etre une table ou un champ JSON sur
l'Assignment pour le MVP :
- `assignment_id`, `grader_image` (nullable -> image plateforme par defaut),
  `timeout_seconds`, `checks` (JSON : liste de Probes), `custom_script` (nullable).

`Probe` (dans `checks`) :
- `id`, `name`, `kind`, `vantage`, `config` (JSON), `expect` (JSON), `weight`, `visibility`.

`GradingRun` :
- `id`, `assignment_id`, `user_id`, `submission_id` (nullable), `deployment_id`,
  `trigger` (student_self|on_submit|teacher), `status` (queued|running|done|error),
  `started_at`, `finished_at`, `total_checks`, `passed_checks`, `score_suggestion`,
  `results` (JSON : verdict par probe avec message et sortie).

`AssignmentSubmission` :
- `assignment_id`, `user_id`, `attempt_no`, `submitted_at`, `is_late`, `due_at_snapshot`,
  `text`, `links` (JSON), `files` (JSON), `deployment_id`, `lab_snapshot` (JSON),
  `latest_grading_run_id`, `grade`, `feedback`, `graded_by`, `status`.

`AssignmentEvent` (apres MVP-1) :
- `assignment_id`, `user_id`, `type`, `payload` (JSON), `created_at`.

Plus tard : `LabBlueprint`, `LabBlueprintVersion`, `HelpRequest`.

## 18. API cible

Construite autour des gestes produit, pas des ressources k8s.

Etudiant :
- `GET  /api/v1/student/assignments` - liste de mes devoirs (avec statut derive).
- `GET  /api/v1/student/assignments/{id}` - detail (consignes + probes visibles + etat lab).
- `POST /api/v1/student/assignments/{id}/open-lab` - ouvre/repris/cree le lab.
- `GET  /api/v1/student/assignments/{id}/lab-status` - etat du lab.
- `POST /api/v1/student/assignments/{id}/run-tests` - lance un Grading Run (self-check).
- `GET  /api/v1/student/assignments/{id}/grading-runs/{run_id}` - resultats.
- `POST /api/v1/student/assignments/{id}/submit` - rend (snapshot + grading on_submit).
- `POST /api/v1/student/assignments/{id}/help` - signale un blocage (phase ulterieure).

Enseignant :
- CRUD devoirs dans une classe (existant a etendre).
- `POST /classrooms/{cid}/assignments/{aid}/deploy-all` - existant (push classe).
- `POST /.../assignments/{aid}/grading-spec` - definit/maj les tests.
- `POST /.../assignments/{aid}/test-now` - lance un Grading Run sur le lab de demo du prof.
- `POST /.../assignments/{aid}/run-tests-all` - relance les tests sur toute la classe.
- `GET  /.../assignments/{aid}/progress` - tableau etudiants + verdicts.
- `GET  /.../submissions/{sid}` - vue de correction complete.
- `POST /.../submissions/{sid}/feedback` - note + commentaire + (reprise).
- `POST /.../assignments/{aid}/extend-deadline`, `.../export` (CSV), `.../duplicate`.

Interne (Grader Pod) :
- `POST /api/v1/internal/grading-runs/{run_id}/results` - protege par token a usage unique.

## 19. Securite et gouvernance

- Grader Pod : isole, sans acces cluster, NetworkPolicy stricte (egress vers le lab cible +
  endpoint resultats uniquement), time-box, quotas CPU/RAM, Job a TTL court, token resultats
  a usage unique. Voir section 8.
- Mode script enseignant : execute uniquement dans le Grader Pod isole, jamais sur l'API ni
  dans un pod privilegie. Le mode "image grader custom" reste derriere une validation admin.
- Quotas a plusieurs niveaux (etudiant, classe, devoir, cluster). Afficher au prof l'impact
  d'un predeploiement ou d'un run de tests sur toute la classe.
- Ne jamais logger tokens, mots de passe, secrets OIDC, credentials DB, bearer tokens k8s.
- SSO : l'amorce existe deja (`auth_provider`, `external_id`, `sso.py`). L'integration
  institutionnelle (CAS/OIDC/SAML) est un sujet de production a ne pas reporter trop tard.

## 20. Migration depuis l'existant

Progressive, sans big-bang :
1. **Reutiliser l'existant** : `deploy-all` + `AssignmentDeployment` poussent deja un lab par
   etudiant. Le MVP-1 s'appuie dessus : l'etudiant ouvre son lab pre-pousse, il n'y a pas
   besoin de construire le start-lab a la demande tout de suite.
2. Faire de `AssignmentDeployment` la **source unique** du lien devoir<->lab (aujourd'hui le
   lien repose aussi sur une convention de nommage `{slug}-u{id}` + un label : a consolider).
3. Templates existants utilises comme blueprints "shadow".
4. Le start-lab tire par l'etudiant (get-or-create, reprise de lab en pause, politique
   d'expiration) arrive en MVP-2 : c'est la partie technique la plus piegeuse.

## 21. MVP strict

Objectif : rendre le devoir reel pour l'etudiant et corrigeable pour le prof, avec un
premier niveau de tests boite noire. Coupe en deux livraisons.

**MVP-1 - le devoir devient reel**
- Page etudiant "Mes devoirs" (liste, statuts derives).
- Page detail devoir (consignes + bouton Ouvrir le lab pre-pousse via `AssignmentDeployment`).
- `AssignmentSubmission` minimal (texte + liens + fichiers + snapshot leger).
- Vue prof : liste des rendus + commentaire + note optionnelle.

**MVP-2 - les tests boite noire et le triage**
- `GradingSpec` + probes simples par formulaire (HTTP, port, fichier, commande, SQL).
- Grader Pod isole + `GradingRun` + endpoint interne de resultats.
- Bouton "Lancer les tests" (etudiant, self-check) et "Tester maintenant" (prof).
- Colonne verdicts (ex 4/5) dans le tableau prof + note suggeree dans la correction.
- Statuts par etudiant derives ou premiers `AssignmentEvent` si besoin du temporel.

Hors MVP : assistant IA, tests caches sophistiques, snapshot de volume complet, grilles
complexes, projets multi-jalons, wizard blueprint complet, start-lab a la demande (MVP-2+).

## 22. Roadmap

- **Phase 1** : experience etudiant (Mes devoirs, detail, lien devoir<->lab, rendu simple,
  correction basique). = MVP-1.
- **Phase 2** : tests boite noire + Grader Pod + triage cote prof. = MVP-2.
- **Phase 3** : experience enseignant avancee (cockpit, actions groupees, export, reprise) +
  start-lab a la demande.
- **Phase 4** : humanisation (bouton "Je suis bloque", alertes actionnables, relances,
  prolongations, gestion de l'attente lors des demarrages concurrents) + evenements complets.
- **Phase 5** : Lab Blueprints comme vraie couche produit (modele, versioning, validation,
  previsualisation, migration des templates).
- **Phase 6** : deploiement institutionnel (SSO CAS/OIDC/SAML, quotas par classe, import
  annuaire/CSV, export LMS/Moodle, gouvernance).
- **Phase 7** : assistant IA (brouillons de missions, suggestion de probes, reformulation de
  consignes, synthese des erreurs frequentes), toujours sous controle du professeur. L'IA
  assiste et analyse ; elle ne publie pas, ne note pas seule, ne genere pas un grader
  executable sans validation.

## 23. Vision finale

> LabOnDemand doit permettre a un enseignant de creer une mission pedagogique complete en
> quinze minutes, sans jamais ecrire un Dockerfile, et a un etudiant de la realiser sans
> jamais voir un namespace.

Le devoir est l'experience. Le lab est l'atelier. La soumission est la preuve. Les probes
trient. Le feedback ferme la boucle. Et ce qu'on evalue, fondamentalement, c'est **l'ecart
entre l'etat de depart d'un systeme et l'etat cible**, observe de l'exterieur, puis juge par
un humain. C'est ce que seul un lab permet, et c'est la qu'est notre valeur.
