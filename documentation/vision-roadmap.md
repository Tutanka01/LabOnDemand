---
title: Vision & Roadmap d'adoption massive
summary: Audit du projet (forces, faiblesses), analyse comparative des plateformes concurrentes, et roadmap priorisée P0/P1/P2 pour faire de LabOnDemand la plateforme adoptée massivement par les enseignants.
read_when: |
  - Tu prends une décision de priorisation produit (quelle feature shipper d'abord)
  - Tu veux comprendre le positionnement face à Instruqt / Strigo / Skillable / JupyterHub+nbgrader / CloVER VTL
  - Tu rejoins le projet et veux comprendre où on va à 18 mois
---

# Vision & Roadmap — LabOnDemand pour une adoption massive

> Document de vision produit. Source : audit interne du code (avril 2026) + veille marché des plateformes de labs éducatifs.

---

## 1. Résumé éclatant — ce que le projet est aujourd'hui

**LabOnDemand** est une **plateforme "Kubernetes-as-a-classroom"** : un enseignant ou un étudiant clique → un namespace isolé est créé → un pod (VS Code, Jupyter, LAMP, WordPress, MySQL+phpMyAdmin, image custom) est déployé avec quotas CPU/RAM stricts, ingress dédié, terminal web, volumes persistants, expiration automatique.

**État technique** : MVP solide d'infra DevOps interne, comparable à un mini-CloVER VTL ou un mini-Strigo côté cœur K8s.

**Le verdict honnête** : nous avons livré un excellent **runtime de labs**, pas encore une **plateforme pédagogique**. L'enseignant peut spawn des conteneurs ; il ne peut pas (encore) animer un cours.

---

## 2. Ce qui est déjà très bien fait (à préserver)

| Domaine | Qualité |
|---|---|
| Isolation K8s par utilisateur (namespace + ResourceQuota + LimitRange) | Excellent — beaucoup de plateformes payantes ne le font pas aussi rigoureusement |
| Lifecycle (TTL, grace period, cleanup orphelins, garde-fous SSO) | `tasks/cleanup.py` est mature |
| Audit + observabilité backend (`logs/audit.log`, request-id, structured JSON) | Au-dessus de la moyenne |
| Templates + RuntimeConfigs CRUD en BDD (admin UI) | Architecture flexible |
| Quota overrides individuels avec expiration | Rare et précieux |
| Terminal web (xterm.js + WebSocket exec) | Différenciateur |
| Documentation interne (frontmatter `read_when:`) | Très bien pensé pour onboarder |

---

## 3. Là où ça pèche — gaps concrets

### A. Trous pédagogiques (le plus grave pour les enseignants)
1. **Pas de notion de "classe" / "promo" / "cours"**. Un enseignant gère 30 students un par un.
2. **Pas de notion d'"assignment" / "TP"**. Pas de sujet attaché, pas de rendu, pas de correction. Aucune intégration **nbgrader** alors que Jupyter est natif.
3. **Pas de scénarios guidés multi-étapes** (killer feature d'Instruqt/Strigo).
4. **Pas de planification** : pas de "déploie 30 environnements lundi 14h pour ma classe".
5. **Pas de visibilité enseignant sur les étudiants** : le rôle `teacher` a quasi les mêmes droits qu'un `student` (cf. `auth_router.check-role` lignes 638–650).

### B. Trous d'intégration (le plus grave pour la DSI)
6. **Aucune intégration LTI 1.3 / LTI Advantage** → impossible d'embarquer un lab dans Moodle / Canvas / Blackboard avec SSO et passback de notes.
7. **Pas d'embed iframe** d'un lab dans un site externe.
8. **Pas de webhooks sortants** (Slack, email, Teams).
9. **Mono-cluster** : un seul `kubeconfig.yaml`.

### C. Trous UX enseignant
10. **Pas de bulk actions** admin.
11. **Pas de notifications** in-app/email.
12. **Pas de catalogue partagé** / marketplace de templates inter-établissements.
13. **Pas de "share link"** pour pair-programming / aide.
14. **i18n absent** : tout est en français codé en dur. Adoption hors France = zéro.
15. **Pas d'onboarding guidé**.

### D. Trous techniques / dette
16. **Fichiers obèses** : `deployment_service.py` = 2121 lignes, `routers/k8s_deployments.py` = 1320 lignes, `frontend/script.js` = 1287 lignes.
17. **Frontend vanilla pur** + CDN tiers (xterm, font-awesome) → risque supply chain.
18. **`POST /change-password` prend les mots de passe en query string** (`auth_router.py:652-657`) → secrets dans les logs nginx. **Bug de sécurité.**
19. **Pas de 2FA/MFA**.
20. **Pas de tests frontend / E2E**.
21. **Pas de WebSocket pour le statut des pods** → polling.
22. **Pas de support GPU** → exclut tout le marché IA/ML.
23. **Pas de snapshot/clone** d'environnement.
24. **Templates uniquement en BDD** → pas de GitOps.

---

## 4. Ce que font de mieux les concurrents

| Plateforme | Idée à voler |
|---|---|
| **Instruqt** | Tracks multi-étapes avec validation auto, embed dans LMS, LTI Advantage, multi-node K8s |
| **Strigo** | Assistant IA intégré au lab, labs-as-code via Git, lab recorder |
| **Skillable** | Validation de compétences + skill data analytics ; marketplace de 35M de labs |
| **JupyterHub + nbgrader + ngshare** | Workflow assignement→release→submit→autograde sur K8s (helm chart `ngshare`) |
| **IllumiDesk** | nbgrader + LTI + post grade automatique au LMS |
| **CloVER VTL** | Launch labs depuis Moodle via LTI, support GKE/EKS/AKS/OVH/on-prem |
| **CloudLabs** | "Fall checklist" universitaire (April–June window), gestion classroom complète |
| **Azure Lab Services** | Auto-shutdown intelligent → maîtrise des coûts |
| **KodeKloud** | 1000+ labs CKAD/CKA → preuve qu'un catalogue de scénarios prêts à l'emploi crée la traction |

---

## 5. Roadmap d'adoption massive

### P0 — *Indispensables pour qu'un enseignant choisisse LabOnDemand* (3–6 mois)

1. **Modèle `Classroom` + `Enrollment`** : un prof crée un cours, ajoute des étudiants (CSV import), assigne un template + des quotas spécifiques.
2. **`Assignment` model** : un TP = 1 template + sujet markdown + dataset + date limite + critères de validation. Bouton "Distribuer à toute la classe" → spawn N namespaces en batch.
3. **Intégration LTI 1.3 / LTI Advantage** : SSO depuis Moodle, NRPS pour roster sync, AGS pour grade passback.
4. **Vue "Tableau de bord enseignant"** : grille classe × étudiant avec statut lab, temps passé, dernière activité.
5. **Fix sécurité** : passer `change-password` en body JSON — `auth_router.py:652`.
6. **i18n EN minimum** (i18next côté frontend, gettext/babel côté backend).

### P1 — *Différenciateurs forts* (6–12 mois)

7. **Scénarios guidés multi-étapes** (markdown + checks bash exécutés dans le pod).
8. **Snapshot/clone de l'environnement étudiant** (via PVC clone K8s).
9. **Notifications** in-app + email + webhooks Slack/Teams.
10. **Pair-programming / share session** (token éphémère).
11. **Support GPU** + template "Jupyter+PyTorch+CUDA".
12. **Auto-shutdown intelligent** (idle detection sur trafic ingress).
13. **Bulk admin actions** + 2FA TOTP/WebAuthn.
14. **WebSocket events** pour statut temps réel.

### P2 — *Effet réseau et viralité* (12–18 mois)

15. **Marketplace publique de templates** (repo Git central).
16. **Assistant IA dans le lab** (panneau latéral utilisant l'API Anthropic).
17. **Embed iframe** d'un lab dans n'importe quel site avec token signé.
18. **Multi-cluster / multi-tenant école**.
19. **Cost analytics** par classe / département.
20. **Mobile-first responsive**.

---

## 6. La phrase à retenir

> **LabOnDemand est aujourd'hui le meilleur "Kubernetes-as-a-Service" éducatif qu'on puisse auto-héberger.** Pour devenir *la* plateforme adoptée massivement par les enseignants, il doit franchir un seul cap : passer du **runtime de conteneurs** au **système de classe**. Concrètement = `Classroom` + `Assignment` + `LTI 1.3`. Tout le reste suit.

---

## 7. Sources de la veille marché

- [Best Virtual IT Labs Software 2026 — CTO Club](https://thectoclub.com/tools/best-virtual-it-labs-software/)
- [Instruqt — Virtual IT Labs Software](https://instruqt.com/glossary/virtual-it-labs-software)
- [Strigo vs Skillable](https://strigo.io/vs/skillable/strigo-vs-skillable)
- [ngshare — nbgrader + JupyterHub on Kubernetes](https://discourse.jupyter.org/t/ngshare-a-solution-for-using-nbgrader-with-jupyterhub-and-kubernetes/4724)
- [nbgrader docs — JupyterHub config](https://nbgrader.readthedocs.io/en/latest/configuration/jupyterhub_config.html)
- [LTI 1.3 Moodle — CloVER VTL](https://www.clover-vtl.com/documentation/clover-vtl-administrators-guide/integrating-with-your-existing-lms/launch-lti-in-moodle/)
- [Moodle LTI 1.3 dev support](https://docs.moodle.org/dev/LTI_1.3_support)
- [CloudLabs — Fall 2026 Virtual Labs Checklist](https://cloudlabs.ai/blog/fall-2026-checklist-for-universities-are-your-virtual-labs-ready-for-the-next-semester)
- [Capterra — Skillable Lab on Demand](https://www.capterra.com/p/205253/Lab-on-Demand-LOB/)
- [Educational SaaS based on JupyterHub+nbgrader on Kubernetes (IEEE)](https://ieeexplore.ieee.org/document/9969419/)
