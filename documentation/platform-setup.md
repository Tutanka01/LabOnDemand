# Mise en place de la plateforme (k3s + Ingress)

Ce guide décrit la marche recommandée pour préparer un cluster k3s propre à LabOnDemand : installation du cluster, déploiement d`ingress-nginx`, option MetalLB, DNS wildcard et certificats TLS.

## 1. Préparer le cluster k3s

1. Installer k3s **sans Traefik** (nous utilisons `ingress-nginx`).
   ```bash
   curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
     --disable servicelb \
     --disable traefik \
     --write-kubeconfig-mode=644 \
     --tls-san $(hostname -I | awk '{print $1}')" sh -
   ```
2. Ajouter les workers en réutilisant le token du nœud maître :
   ```bash
   sudo cat /var/lib/rancher/k3s/server/node-token
   curl -sfL https://get.k3s.io | \
      K3S_URL="https://<IP_MASTER>:6443" \
      K3S_TOKEN="<TOKEN>" \
      INSTALL_K3S_EXEC="agent" sh -
   ```
3. Vérifier l'accès `kubectl` et exporter `KUBECONFIG=/etc/rancher/k3s/k3s.yaml` si nécessaire :
   ```bash
   sudo k3s kubectl get nodes
   ```

## 2. Déployer `ingress-nginx`

1. Ajouter le dépôt Helm :
   ```bash
   helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
   helm repo update
   ```
2. Installer le contrôleur (mode NodePort par défaut) :
   ```bash
   helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
      --namespace ingress-nginx \
      --create-namespace \
      --set controller.replicaCount=1 \
      --set controller.service.type=NodePort \
      --set controller.metrics.enabled=true
   ```
3. Valider : `kubectl get pods -n ingress-nginx -w` et `kubectl get svc -n ingress-nginx`.

## 3. Option LoadBalancer : MetalLB

Pour exposer directement 80/443 sans NodePort :

1. Déployer MetalLB :
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.15.2/config/manifests/metallb-native.yaml
   ```
2. Déclarer une plage IP disponible :
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
3. Réinstaller `ingress-nginx` en `LoadBalancer` :
   ```bash
   helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
      --namespace ingress-nginx \
      --create-namespace \
      --set controller.replicaCount=1 \
      --set controller.service.type=LoadBalancer \
      --set controller.metrics.enabled=true
   ```
4. Récupérer l'IP externe : `kubectl get svc ingress-nginx-controller -n ingress-nginx -o wide`.

## 4. DNS wildcard `*.apps.labondemand.makhal`

| Option | Description | Mise en œuvre rapide |
| --- | --- | --- |
| DNS institutionnel | Entrée wildcard pointant vers l'IP NodePort/LoadBalancer | Recommandé en production |
| `dnsmasq` local | Redirige `*.apps.labondemand.makhal` vers l'IP du nœud sur chaque poste | `/etc/dnsmasq.d/labondemand.conf` puis `systemctl restart dnsmasq` |
| `/etc/hosts` | Dépannage uniquement, pas de wildcard | Entrées manuelles pour chaque sous-domaine |

Exemple `dnsmasq` :
```bash
sudo bash -c 'cat > /etc/dnsmasq.d/labondemand.conf <<"EOF"
address=/apps.labondemand.makhal/192.168.56.10
EOF'
sudo systemctl restart dnsmasq
```

## 5. Certificat wildcard (recommandé)

1. **mkcert** pour les environnements de test :
   ```bash
   mkcert -install
   mkcert "*.apps.labondemand.makhal"
   kubectl create secret tls labondemand-wildcard \
   --cert="_wildcard.apps.labondemand.makhal.pem" \
   --key="_wildcard.apps.labondemand.makhal-key.pem" \
     -n labondemand-backend
   ```
2. **cert-manager + DNS-01** en production : installer cert-manager, créer un `ClusterIssuer` et attacher l'annotation `cert-manager.io/cluster-issuer` à l'Ingress généré par LabOnDemand.

Sans TLS, les cookies `Secure` ne sont pas envoyés : pensez à ajuster `SECURE_COOKIES` dans `.env` si vous restez en HTTP.

## 6. Variables `.env` côté backend

```ini
INGRESS_ENABLED=true
INGRESS_BASE_DOMAIN=apps.labondemand.makhal
INGRESS_CLASS_NAME=nginx
INGRESS_TLS_SECRET=labondemand-wildcard
INGRESS_DEFAULT_PATH=/
INGRESS_PATH_TYPE=Prefix
INGRESS_FORCE_TLS_REDIRECT=true
INGRESS_AUTO_TYPES=custom,jupyter,vscode,wordpress,mysql,lamp
INGRESS_EXCLUDED_TYPES=netbeans
# INGRESS_EXTRA_ANNOTATIONS=nginx.ingress.kubernetes.io/proxy-body-size=256m
```

- Les types listés dans `INGRESS_AUTO_TYPES` seront exposés via Ingress (services convertis en `ClusterIP`).
- Ajoutez `INGRESS_EXTRA_ANNOTATIONS` pour propager vos réglages nginx.

## 7. Vérifications rapides

1. Déployer une stack (ex: VS Code) depuis LabOnDemand.
2. Vérifier que le service est passé en `ClusterIP` (`kubectl get svc -n <namespace>`).
3. Contrôler l'Ingress généré (`kubectl describe ingress <name>`).
4. Tester l'URL : `curl -I https://<app>-u42.apps.labondemand.makhal`.

Les détails de déploiement (`GET /deployments/{ns}/{name}/details`) doivent faire remonter `ingresses[]` et `access_urls[]`.

## 8. Dépannage

| Symptôme | Piste |
| --- | --- |
| `kubectl get ingress` vide | Vérifier `INGRESS_ENABLED`, `INGRESS_BASE_DOMAIN`, redéployer l'app |
| 404 sur l'URL | `kubectl describe ingress` pour valider la résolution du service |
| Pas de TLS | Secret absent ou référence `INGRESS_TLS_SECRET` incorrecte |
| Toujours en HTTP | Activer `INGRESS_FORCE_TLS_REDIRECT=true` |
| DNS ne résout pas | `dig <sous-domaine>` depuis un poste client |

## 9. Étapes suivantes

- Automatiser TLS avec cert-manager + DNS challenge.
- Activer MetalLB en L2 ou BGP selon votre réseau.
- Restreindre l'IngressClass via RBAC pour limiter la portée à LabOnDemand.
- Supervision : exporter les métriques `controller.metrics.enabled=true` vers Prometheus/Grafana.
