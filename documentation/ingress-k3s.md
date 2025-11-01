# Intégrer un Ingress Controller solide sur K3s

Ce guide décrit une mise en place robuste — mais raisonnable — d'un Ingress Controller pour les clusters K3s utilisés par LabOnDemand. L'objectif est de remplacer l'exposition NodePort par des URLs de la forme `*.apps.labondemand.univ-pau.fr`, tout en restant simple à maintenir.

---

## 1. Préparer le cluster K3s

1. **Installer (ou réinstaller) K3s sans Traefik** – nous utiliserons `ingress-nginx`, plus prévisible pour un usage pédagogique :
   ```bash
   curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
     --disable servicelb \
     --disable traefik \
     --write-kubeconfig-mode=644 \
     --tls-san $(hostname -I | awk '{print $1}')" sh -
   ```
   *Le TLS SAN garantit que l'IP principale du nœud figure dans les certificats API Kubernetes.*

2. *Ajouter des workers* :
Recuperer le token d'accès sur le master :
   ```bash
   sudo cat /var/lib/rancher/k3s/server/node-token
   ```
Puis installer K3s sur chaque nœud worker :

   ```bash
   curl -sfL https://get.k3s.io | \
      K3S_URL="https://<IP_MASTER>:6443" \
      K3S_TOKEN="<TOKEN>" \
      INSTALL_K3S_EXEC="agent" \
      sh -
   ```

3. **Vérifier l'accès `kubectl`** :
   ```bash
   sudo k3s kubectl get nodes
   ```
   Ajuster `KUBECONFIG=/etc/rancher/k3s/k3s.yaml` si nécessaire.

---

## 2. Installer `ingress-nginx`

1. **Ajouter le dépôt Helm** (sur le poste admin) :
   ```bash
   helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
   helm repo update
   ```

2. **Installer le contrôleur** :
    ```bash
    helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
       --namespace ingress-nginx \
       --create-namespace \
       --set controller.replicaCount=1 \
       --set controller.service.type=NodePort \
       --set controller.metrics.enabled=true
    ```
    *Mode NodePort : parfait pour un labo mono-nœud. Pour un LoadBalancer direct (port 80/443 exposés), voir l'option MetalLB ci-dessous.*

3. **Valider le déploiement** :
   ```bash
   kubectl get svc -n ingress-nginx
   kubectl get pods -n ingress-nginx -w
   ```

---

## 3. Option LoadBalancer : MetalLB + Ingress NGINX

Pour exposer directement les ports 80/443 sans passer par des NodePort, installer MetalLB en mode L2 puis réinstaller le contrôleur en `LoadBalancer`.

1. **Déployer MetalLB** :
    ```bash
    kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.15.2/config/manifests/metallb-native.yaml
    ```

2. **Définir une plage d'adresses disponible sur votre LAN** (adapter les IPs) :
    ```bash
    kubectl create -f - <<'EOF'
    apiVersion: metallb.io/v1beta1
    kind: IPAddressPool
    metadata:
       name: metallb-pool
       namespace: metallb-system
    spec:
       addresses:
       - 192.168.100.200-192.168.100.210
    ---
    apiVersion: metallb.io/v1beta1
    kind: L2Advertisement
    metadata:
       name: metallb-l2
       namespace: metallb-system
    spec:
       ipAddressPools:
       - metallb-pool
    EOF
    ```

3. **Réinstaller `ingress-nginx` en mode LoadBalancer** :
    ```bash
    helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
       --namespace ingress-nginx \
       --create-namespace \
       --set controller.replicaCount=1 \
       --set controller.service.type=LoadBalancer \
       --set controller.metrics.enabled=true
    ```

4. **Récupérer l'IP externe affectée** :
    ```bash
    kubectl get svc -n ingress-nginx ingress-nginx-controller -o wide
    ```

Mettre à jour l'enregistrement DNS wildcard `*.apps.labondemand.univ-pau.fr` vers cette adresse. Les commandes de validation (`curl -I http://<external-ip>`) permettent de vérifier que NGINX répond bien.

---

## 4. DNS interne pour `*.apps.labondemand.univ-pau.fr`

Choisir un mode selon votre réseau local :

| Option | Description | Mise en œuvre rapide |
| --- | --- | --- |
| **DNS institutionnel** | Déclarer une délégation ou un enregistrement wildcard vers l'IP du nœud / du LoadBalancer. | (recommandé en production) |
| **dnsmasq local** | Router `*.apps.labondemand.univ-pau.fr` vers l'IP du nœud sur chaque poste. | `/etc/dnsmasq.d/labondemand.conf` : `address=/apps.labondemand.univ-pau.fr/192.168.56.10` |
| **/etc/hosts** (dépannage) | Entrées statiques ; ne gère pas le wildcard. | Insérer chaque sous-domaine manuellement. |

Pour un labo isolé, `dnsmasq` est souvent le meilleur compromis :
```bash
sudo bash -c 'cat > /etc/dnsmasq.d/labondemand.conf <<"EOF"
address=/apps.labondemand.univ-pau.fr/192.168.56.10
EOF'
sudo systemctl restart dnsmasq
```
Remplacer `192.168.56.10` par l'adresse du nœud/ou du VIP.

---

## 5. Certificat wildcard (facultatif mais conseillé)

Deux approches simples :

1. **mkcert (AC locale)** pour tests :
   ```bash
   mkcert -install
   mkcert "*.apps.labondemand.univ-pau.fr"
   kubectl create secret tls labondemand-wildcard \
     --cert="_wildcard.apps.labondemand.univ-pau.fr.pem" \
     --key="_wildcard.apps.labondemand.univ-pau.fr-key.pem" \
     -n labondemand-backend
   ```
   Créer le namespace si besoin (`kubectl create ns labondemand-backend`).

2. **cert-manager** + DNS challenge :
   - Installer cert-manager (Helm, `jetstack` repo).
   - Créer un `ClusterIssuer` DNS (ex: Gandi, OVH, Cloudflare).
   - Déclarer un certificat wildcard et pointer l'annotation `cert-manager.io/cluster-issuer` sur l'Ingress.

Sans TLS, l'application fonctionnera en HTTP mais les cookies `Secure` ne seront pas envoyés.

---

## 6. Variables `.env` côté backend

Ajouter ou adapter les clés suivantes (valeurs indicatives) :

```ini
# Activer l'Ingress
INGRESS_ENABLED=true
INGRESS_BASE_DOMAIN=apps.labondemand.univ-pau.fr
INGRESS_CLASS_NAME=nginx
INGRESS_TLS_SECRET=labondemand-wildcard   # secret TLS (laisser vide pour HTTP)
INGRESS_DEFAULT_PATH=/
INGRESS_PATH_TYPE=Prefix
INGRESS_FORCE_TLS_REDIRECT=true
INGRESS_AUTO_TYPES=custom,jupyter,vscode,wordpress,mysql,lamp
INGRESS_EXCLUDED_TYPES=netbeans
# Optionnel : annotations supplémentaires (clé=valeur, séparées par des virgules)
# INGRESS_EXTRA_ANNOTATIONS=nginx.ingress.kubernetes.io/proxy-body-size=256m
```

- Les stacks listées dans `INGRESS_AUTO_TYPES` seront exposées via Ingress (service converti en `ClusterIP`).
- `netbeans` reste en NodePort (flux VNC/audio).

Redémarrer l'API FastAPI si nécessaire pour recharger la configuration.

---

## 7. Vérifier le routage applicatif

1. Lancer un déploiement via LabOnDemand (ex: VS Code).
2. Vérifier que le service est `ClusterIP` :
   ```bash
   kubectl get svc -n <namespace-utilisateur>
   ```
3. Vérifier l'Ingress correspondant :
   ```bash
   kubectl get ingress -n <namespace-utilisateur>
   kubectl describe ingress <nom>
   ```
4. Tester depuis un poste client :
   ```bash
   curl -I https://<app>-u42.apps.labondemand.univ-pau.fr
   ```

Les détails d'application (`GET /deployments/{ns}/{name}/details`) renvoient désormais :
- `ingresses[]` par service,
- `access_urls[]` incluant les URLs Ingress,
- les credentials WordPress/MySQL/LAMP intègrent un `url`/`url_hint` orienté Ingress.

---

## 8. Dépannage rapide

| Symptôme | Piste |
| --- | --- |
| `kubectl get ingress` vide | Vérifier `INGRESS_ENABLED` et `INGRESS_BASE_DOMAIN`, re-déployer l'app. |
| 404 depuis l'URL | Contrôler que `ingress-nginx` voit bien le service (`kubectl describe ingress`). |
| Pas de certificat TLS | Secret absent ou référence `INGRESS_TLS_SECRET` incorrecte. |
| Toujours redirigé vers HTTP | Ajouter `INGRESS_FORCE_TLS_REDIRECT=true` (Nginx) ou configurer le middleware Traefik. |
| DNS ne résout pas | Tester `dig <sous-domaine>` depuis le poste, ajuster `dnsmasq`/DNS entreprise. |

---

## 9. Étapes suivantes

- Industrialiser TLS avec cert-manager + DNS-01.
- Activer `MetalLB` pour fournir une IP externe fixe au contrôleur.
- Ajouter des règles RBAC minimales pour que `ingress-nginx` n'utilise que les namespaces LabOnDemand (`ingressClass` dédiée).
- Surveiller `ingress-nginx` (metrics déjà activées) via Prometheus/Grafana.

Cette configuration reste volontairement simple : un Ingress Controller unique, un wildcard DNS/TLS, pas de CRD exotique. Elle couvre les besoins actuels sans over-engineering tout en préparant l'évolution vers un cluster partagé.
