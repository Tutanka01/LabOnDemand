## Mise en place d'un PVC sur k3s

Cette documentation explique comment configurer un PersistentVolumeClaim (PVC) sur un cluster k3s, qui est une distribution légère de Kubernetes. Un PVC permet aux applications de demander de l'espace de stockage persistant.

Voila le script a lancer :

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

Et normalement vous devriez voir quelque chose comme ça :

```plaintext
NAME               STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/data-pvc   Bound    pvc-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   5Gi        RWO            local-path     1m
NAME                                     CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM                     STORAGECLASS   REASON   AGE
persistentvolume/pvc-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   5Gi        RWO            Delete           Bound    default/data-pvc          local-path                1m
NAME         READY   STATUS    RESTARTS   AGE
pod/pvc-tester   1/1     Running   0          1m
```

Vous pouvez maintenant accéder au pod et vérifier que le volume est monté correctement :

```bash
kubectl exec -it pvc-tester -- sh
cd /data
ls -la
exit
```