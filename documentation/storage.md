---
title: Stockage persistant (PVC)
summary: Configuration du stockage persistant pour LabOnDemand — StorageClass k3s, création de PVC, intégration avec l'UI et comportement de fallback en emptyDir.
read_when: |
  - Tu configures la persistance des données sur un nouveau cluster (StorageClass, NFS, Ceph)
  - Tu dépannes un PVC bloqué en Pending ou des données perdues après redémarrage
  - Tu veux comprendre comment LabOnDemand gère les volumes réutilisables pour les utilisateurs
---

# Stockage persistant (PVC)

Cette page centralise la manière d'exposer du stockage durable à LabOnDemand : configuration des StorageClass sur k3s, création d'un PVC générique et intégration avec l'UI (volumes réutilisables).

## 1. Préparer une StorageClass par défaut

Sur k3s, la classe `local-path` est fournie. Vérifiez qu'elle est bien marquée `default` :
```bash
kubectl get storageclass
```
Si aucune classe par défaut n'apparaît, créez-en une (local-path provisioner, NFS, Ceph, etc.). Sans StorageClass, LabOnDemand démarrera les pods en `emptyDir` (pas de persistance).

## 2. PVC minimal de validation

Script prêt à l'emploi :
```bash
cat <<'YAML' > pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
  namespace: default
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: local-path
  resources:
    requests:
      storage: 5Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: pvc-tester
  namespace: default
spec:
  containers:
    - name: app
      image: busybox:1.36
      command: ["sh","-c","sleep 36000"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: data-pvc
YAML

kubectl apply -f pvc.yaml
kubectl get pvc,pv,pods
```
Résultat attendu :
```
pvc/data-pvc   Bound   5Gi
pod/pvc-tester Running
```
Vérifier dans le conteneur :
```bash
kubectl exec -it pvc-tester -- sh
cd /data && ls -la
exit
```

## 3. Intégration LabOnDemand

- Lorsqu'un utilisateur crée un VS Code, Jupyter ou LAMP, le backend tente de provisionner un PVC (`managed-by=labondemand`, `user-id=<id>`). Faute de StorageClass par défaut, un `emptyDir` est utilisé.
- La carte « Vos volumes persistants » (dashboard) liste les PVC labellisés. Rafraîchir la carte pour détecter les volumes existants.
- Pour réutiliser un volume, choisir le PVC dans le formulaire de création (dropdown) ou laisser vide pour en créer un nouveau.
- Suppression :
  - Via l'UI, un volume `Bound` demande une confirmation explicite.
  - Lors de la suppression d'une stack WordPress/LAMP, le paramètre `delete_persistent=false` permet de conserver DB + volume web.

## 4. Bonnes pratiques

1. **Nommer clairement** vos PVC (`<user>-home`, `<promo>-dataset`).
2. **Surveiller les quotas** : voir `documentation/resource-limits.md` pour les limites `count/persistentvolumeclaims` et `requests.storage` appliquées par rôle.
3. **Sauvegarder** : montez les volumes sur un backend fiable (NFS RAID, Ceph, rook). Le provisioner `local-path` ne protège pas contre la perte du nœud.
4. **Nettoyer automatiquement** : utilisez les labels `managed-by=labondemand` pour vos jobs de ménage ou outils d'observabilité.

## 5. Dépannage

| Symptôme | Piste |
| --- | --- |
| PVC bloqué en `Pending` | StorageClass inexistante, quota atteint ou nœuds sans volume local libre |
| L'UI n'affiche aucun volume | Rafraîchir la carte; vérifier que les PVC ont les labels `managed-by=labondemand`/`user-id` |
| Données volatiles après redémarrage | Pas de StorageClass par défaut → fallback `emptyDir` |
| Message `AlreadyExists` sur Secret ou PVC | Stack supprimée partiellement; effacer les ressources restantes ou passer `delete_persistent=false` |

Pour la configuration du provisioner (local-path, NFS, Longhorn, rook-ceph...) reportez-vous au guide de votre storage provider. LabOnDemand fonctionne tant que Kubernetes peut satisfaire les `PersistentVolumeClaim` standards.
