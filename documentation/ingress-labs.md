---
title: Accès aux labs via Ingress (ports 80/443)
summary: Exposer les labs LabOnDemand sur des URLs en ports standard (80/443) avec Traefik, sans MetalLB ni ServiceLB, pour contourner le filtrage des NodePorts (30000-32767) par le réseau de l'université.
read_when: |
  - Les étudiants ne peuvent pas ouvrir les URLs NodePort des labs (réseau qui filtre les ports hauts)
  - Tu déploies ou dépanne le contrôleur Ingress du cluster k3s
  - Tu configures INGRESS_ENABLED / INGRESS_BASE_DOMAIN côté backend
---

# Accès aux labs via Ingress (ports 80/443)

## Pourquoi

Par défaut, LabOnDemand expose chaque lab avec un service `NodePort` :
l'URL ressemble à `http://10.3.17.147:30641/`. Le réseau de l'université
n'autorise que les ports « classiques » (80, 443, 8080, 3000…) et filtre la
plage NodePort `30000-32767` : les étudiants ne peuvent donc pas ouvrir les
labs.

La solution est d'utiliser un **Ingress** : une URL par lab sur le **port 80**
(ou 443 en HTTPS), sans port exotique :

```
http://vscode-5172-u1.10.3.17.139.sslip.io/
```

## Architecture

```
Navigateur étudiant
   │  http://<app>-<id>-u<user>.<INGRESS_BASE_DOMAIN>/   (port 80)
   ▼
Nœud k3s (10.3.17.139 / .147 / .148)
   │  Traefik en DaemonSet, hostNetwork → écoute le port 80 de chaque nœud
   ▼
Service ClusterIP du lab  →  Pod (code-server, Jupyter, WordPress…)
```

Points clés :

- Le cluster k3s a été installé avec `--disable servicelb --disable traefik` :
  il n'y a **ni LoadBalancer ni contrôleur Ingress** disponible par défaut.
- Le manifeste `deploy/ingress/traefik-ingress.yaml` déploie Traefik en
  **DaemonSet avec `hostNetwork: true`** : chaque nœud écoute directement sur
  les ports 80 et 443. Aucun besoin de MetalLB, de ServiceLB ou d'un
  LoadBalancer externe.
- L'`IngressClass` s'appelle `traefik` (à reporter dans `.env`).
- Le backend génère un objet `Ingress` par lab quand `INGRESS_ENABLED=true`
  (voir `backend/deployment_service.py`, `create_ingress_manifest`).

## Prérequis

- Accès `kubectl` au cluster (le `kubeconfig.yaml` du dépôt).
- Un nom DNS qui résout vers l'IP d'un nœud (voir la section DNS).

## Étape 1 — Déployer le contrôleur Ingress

```bash
kubectl apply -f deploy/ingress/traefik-ingress.yaml
```

Vérifications :

```bash
kubectl get pods -n traefik -o wide     # 1 pod par nœud, READY 1/1
kubectl get ingressclass traefik        # controller: traefik.io/ingress-controller
curl -s -o /dev/null -w '%{http_code}\n' http://10.3.17.139/   # 404 attendu (aucun Ingress)
```

Un `404` de Traefik sur le port 80 est le signe que le contrôleur répond.

## Étape 2 — Configurer le backend (`.env`)

```ini
INGRESS_ENABLED=true
INGRESS_BASE_DOMAIN=10.3.17.139.sslip.io
INGRESS_CLASS_NAME=traefik
INGRESS_TLS_SECRET=
INGRESS_DEFAULT_PATH=/
INGRESS_PATH_TYPE=Prefix
INGRESS_FORCE_TLS_REDIRECT=false
INGRESS_AUTO_TYPES=custom,jupyter,vscode,wordpress,mysql,lamp,netbeans
INGRESS_EXCLUDED_TYPES=
```

Puis recréer le conteneur API (un simple `restart` ne relit pas `env_file`) :

```bash
docker compose up -d api
```

## Étape 3 — Déployer un lab et vérifier

1. Déployer un lab (ex. VS Code) depuis l'interface.
2. Contrôler l'Ingress créé :

   ```bash
   kubectl get ingress -A
   kubectl describe ingress -n labondemand-user-1 vscode-5172-ingress
   ```

3. Ouvrir l'URL affichée dans l'interface, ou tester en ligne de commande :

   ```bash
   curl -sI http://vscode-5172-u1.10.3.17.139.sslip.io/
   # HTTP/1.1 302 Found  -> redirection vers ./login (code-server)
   ```

Le détail d'un déploiement (`GET /api/v1/k8s/deployments/.../details`) renvoie
`access_urls[]` avec l'URL Ingress : c'est ce que l'interface affiche.

## Comportement

- Les types listés dans `INGRESS_AUTO_TYPES` sont convertis en service
  `ClusterIP` + `Ingress` : leur URL NodePort disparaît (l'Ingress devient le
  seul accès).
- `netbeans` (bureau distant) est couvert lui aussi : son seul accès réellement
  fonctionnel est le **noVNC** (HTTP + WebSocket), donc parfait derrière
  l'Ingress — voir la section dédiée ci-dessous.
- Pour les **labs déjà déployés** avant l'activation, il n'y a pas d'Ingress :
  redéployez-les depuis l'interface, ou créez l'Ingress à la main :

  ```yaml
  apiVersion: networking.k8s.io/v1
  kind: Ingress
  metadata:
    name: vscode-5172-ingress
    namespace: labondemand-user-1
    labels:                       # labels du Deployment (kubectl get deploy -o yaml)
      app: vscode-5172
      app-type: vscode
      managed-by: labondemand
      user-id: "1"
      user-role: admin
    annotations:
      traefik.ingress.kubernetes.io/router.entrypoints: web
  spec:
    ingressClassName: traefik
    rules:
      - host: vscode-5172-u1.10.3.17.139.sslip.io
        http:
          paths:
            - path: /
              pathType: Prefix
              backend:
                service:
                  name: vscode-5172-service
                  port:
                    number: 8080
  ```

  Les labels `managed-by`, `app` et `user-id` sont nécessaires pour que
  l'Ingress soit listé dans l'interface.

## NetBeans (bureau distant)

NetBeans est servi par **noVNC** sur le port `6901` (HTTP + WebSocket) : il
fonctionne donc derrière l'Ingress comme n'importe quel lab, y compris le
clavier/souris qui transitent par le WebSocket (validé : page `noVNC` en 200 et
upgrade WebSocket `101` à travers Traefik).

État réel des ports déclarés pour l'image
`tutanka01/labondemand:netbeansjava` (vérifié via `netstat` dans le pod) :

| Port du service | Rôle annoncé | Écoute réelle dans le pod |
| --- | --- | --- |
| `6901` | noVNC (navigateur) | ✅ `python3` (websockify) |
| `5901` | VNC classique | ❌ rien (x11vnc écoute sur `5900`) |
| `4901` | audio | ❌ rien |

Le noVNC est donc le seul accès fonctionnel, et c'est précisément celui que
l'Ingress expose : passer le service en `ClusterIP` ne perd rien. Si un client
VNC classique devient nécessaire, il faudra d'abord corriger le mapping
`5901 → 5900` côté `backend/deployment_service.py`, puis passer par
`kubectl port-forward` (les ports hauts restent filtrés pour les étudiants).

Identifiants : l'UI affiche le couple `kasm_user` / `VNC_PW` du Secret du lab
(endpoint « identifiants de connexion »).

## DNS

L'hôte d'un lab est `<app>-<id>-u<user>.<INGRESS_BASE_DOMAIN>`, par exemple
`vscode-5172-u1.10.3.17.139.sslip.io`.

| Option | Description | Mise en œuvre |
| --- | --- | --- |
| `sslip.io` (zéro config) | L'IP du nœud est encodée dans le nom : `*.10.3.17.139.sslip.io` résout vers `10.3.17.139`. Aucun DNS à administrer. | `INGRESS_BASE_DOMAIN=10.3.17.139.sslip.io` |
| DNS interne (recommandé si dispo) | Wildcard `*.apps.labondemand.univ-pau.fr` → IP du nœud | Demander l'enregistrement, puis `INGRESS_BASE_DOMAIN=apps.labondemand.univ-pau.fr` |
| `/etc/hosts` | Dépannage uniquement, pas de wildcard | Une ligne par lab |

> `sslip.io` dépend d'un DNS public : les postes clients doivent pouvoir
> résoudre `*.sslip.io`. En cas de doute, préférez un wildcard interne.

## TLS (optionnel)

`sslip.io` ne fournit pas de certificat : la configuration par défaut est donc
en **HTTP clair**. Pour passer en HTTPS :

1. Créer un secret TLS wildcard (mkcert pour un test, cert-manager en
   production) dans chaque namespace utilisateur, ou un secret par lab.
2. Renseigner `INGRESS_TLS_SECRET=<nom-du-secret>` puis redémarrer l'API.
   Le backend ajoute alors `spec.tls` à l'Ingress et les URLs passent en
   `https://` (Traefik sert sur l'entrypoint `websecure`, déjà déclaré sur le
   port 443).

Sans TLS, les mots de passe des labs (code-server, phpMyAdmin…) circulent en
clair : à réserver au réseau interne, ou activer TLS.

## Dépannage

| Symptôme | Piste |
| --- | --- |
| `404` sur l'URL | L'Ingress n'existe pas ou le `host` ne correspond pas : `kubectl get ingress -A` |
| `502`/`503` | Le service ne trouve pas de pod prêt : `kubectl get endpoints -n <namespace>` |
| Rien ne répond sur le port 80 | `kubectl get pods -n traefik -o wide` (1 pod par nœud) puis tester depuis un poste client |
| Le nom ne résout pas | `dig <hôte>` ; sinon wildcard DNS interne ou `/etc/hosts` |
| L'interface n'affiche pas d'URL Ingress | Vérifier `INGRESS_ENABLED`/`INGRESS_BASE_DOMAIN`, `docker compose up -d api`, puis redéployer le lab |
| `kubectl get ingressclass` vide | Le manifeste n'est pas appliqué ou Traefik n'est pas prêt |
| Colonne `ADDRESS` vide dans `kubectl get ingress` | Normal : sans LoadBalancer, Traefik ne publie pas d'adresse dans le statut. Le routage fonctionne quand même (tester avec `curl -H 'Host: <hôte>' http://<ip-noeud>/`) |

## Désinstallation

```bash
kubectl delete -f deploy/ingress/traefik-ingress.yaml
```

Puis repasser `INGRESS_ENABLED=false` et `docker compose up -d api` pour
revenir aux NodePorts.

## Références

- `deploy/ingress/traefik-ingress.yaml` — manifeste du contrôleur.
- `documentation/platform-setup.md` — variante ingress-nginx + MetalLB.
- `documentation/architecture.md` — section Ingress.
