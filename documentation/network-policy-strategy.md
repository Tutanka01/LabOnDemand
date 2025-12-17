# Stratégie NetworkPolicy pour LabOnDemand

## 1. Objectifs
- Isoler strictement les espaces étudiants afin qu'aucun Pod compromis ne puisse scanner ou atteindre d'autres clients ni les services d'infrastructure.
- Encadrer les flux sortants vers l'extérieur pour limiter l'exfiltration de données et la génération de trafic malveillant.
- Fournir un cadre simple à maintenir : conventions de nommage, jeux de labels et modèles de politiques prêts à l'emploi.
- Raccorder la sécurité réseau à l'observabilité (logs, alertes) pour détecter rapidement les dérives.

## 2. Périmètre et hypothèses
- Chaque étudiant dispose d'un namespace dédié (`student-<id>`). Les workloads partagés vivent dans `shared-services`, l'infra critique dans `platform`, et l'administration dans `ops`.
- Le cluster tourne sur un CNI compatible NetworkPolicy (Calico, Cilium ou équivalent) avec support egress.
- Les Pods doivent communiquer avec Kubernetes API, registre d'images interne, services OPS (auth, base de données) et éventuellement Internet filtré.

## 3. Principes directeurs
1. **Deny-all par défaut** : chaque namespace reçoit automatiquement `np-deny-all` (Ingress + Egress).
2. **Autoriser par cas d'usage** : politiques spécifiques versionnées avec l'application qui en a besoin.
3. **Étiquetage obligatoire** : tous les Pods portent `app`, `tier`, `namespace-type` et `exposure`.
4. **Séparation des plans** : flux management (API, metrics) vs flux applicatifs, pour faciliter l'audit.
5. **Automatisation** : génération des politiques par Helm/Kustomize à partir de templates validés sécurité.

## 4. Cartographie logique des flux
| Source | Destination | Motif | Mécanisme | Statut |
| --- | --- | --- | --- | --- |
| `student-*` | `student-*` (même namespace) | Collaboration intra-lab | `np-student-intra` autorise `app` identiques | Autorisé |
| `student-*` | `shared-services` (auth, API) | Authentification, provisioning | `np-shared-ingress` + `np-student-egress-shared` | Autorisé |
| `student-*` | `platform`, `ops` | Gestion cluster | Aucune règle -> bloqué | Interdit |
| `student-*` | Internet | Téléchargements contrôlés | `np-egress-internet` limité via FQDN/IPSet | Optionnel |
| `shared-services` | `platform` BDD | Services communs vers infra | Règle ciblée par `tier=db` | Autorisé |

## 5. Modèle de politiques
### 5.1 Baseline namespace
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: np-deny-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
```
> Injectée par un contrôleur (ex. Kyverno) dès la création du namespace.

### 5.2 Flux intra-namespace contrôlé
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: np-student-intra
spec:
  podSelector:
    matchLabels:
      namespace-type: student
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          namespace-type: student
    ports:
    - protocol: TCP
      port: 0
```
- Limite la communication aux Pods labellisés `namespace-type=student` du même namespace.

### 5.3 Accès aux services partagés
- `np-shared-ingress`: applique un `namespaceSelector` sur `namespace-type=student` + `podSelector` sur `tier=api` dans `shared-services`.
- `np-student-egress-shared`: restreint les étudiants à `namespace=shared-services` + ports `443/https` (auth) et `5432/postgres`.

### 5.4 Egress Internet contrôlé
- Utiliser une `GlobalNetworkPolicy` (Calico) ou un `NetworkPolicy` avec `ipBlock` et exceptions.
- Maintenir une `ConfigMap` de destinations autorisées (miroirs OS, dépôts Git). Pipeline CI met à jour la policy.

## 6. Gouvernance et automatisation
- **Templates Helm/Kustomize** : `templates/network-policies/` avec sous-chart `student`, `shared`, `ops`.
- **Admission controller** : Kyverno/OPA pour refuser la création d'un namespace sans label `namespace-type` / injection `np-deny-all`.
- **Tests** : suite `kubectl exec + netcat` automatisée dans `tests/test_network_policy.py` (à créer) + jobs GitHub Actions contre cluster KinD.

## 7. Observabilité & réponse incident
- Activer les flow logs du CNI (Calico Flow Logs, Cilium Hubble) -> export Loki + Grafana.
- Règles d'alerte : pics de refus egress vers IP inconnues, tentatives inter-namespace.
- Playbooks incident : `kubectl get networkpolicy -n student-123`, `hubble observe pod/student-123-*`.

## 8. Roadmap de mise en œuvre
1. **Semaine 1** : inventaire namespaces, ajout labels, déploiement deny-all automatisé.
2. **Semaine 2** : modéliser flux `shared-services`, livrer templates Helm + tests.
3. **Semaine 3** : activer egress contrôlé + collecte flow logs.
4. **Semaine 4** : revue sécurité, documentation finale, transfert équipe Ops.

---
Ce document servira de référence avant d'implémenter les NetworkPolicy et les contrôles associés dans le codebase LabOnDemand.
