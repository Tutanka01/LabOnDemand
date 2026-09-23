---
title: Terminal Web intégré (sans SSH)
summary: Terminal shell interactif dans le navigateur via WebSocket et Xterm.js — fonctionnement, sécurité par rôle et dépannage des problèmes courants.
read_when: |
  - Tu travailles sur le WebSocket terminal (backend/routers ou frontend Xterm.js)
  - Tu dépannes un problème de terminal (double écho, déconnexion, redimensionnement)
  - Tu veux comprendre les restrictions d'accès au terminal selon le rôle utilisateur
---

# Terminal Web intégré (sans SSH)

Le terminal intégré de LabOnDemand permet d’ouvrir une session shell interactive vers un pod Kubernetes directement depuis le navigateur, sans SSH. Il s’appuie sur Xterm.js et un WebSocket exec côté backend FastAPI.

## Utilisation

1. Dans le tableau de bord, ouvrez les détails d’une application
2. Cliquez sur « Ouvrir le terminal » sur le pod souhaité
3. La console s’ouvre; le redimensionnement est automatique
4. Tapez vos commandes comme dans un shell classique

## Caractéristiques techniques

- WebSocket: /api/v1/k8s/terminal/{namespace}/{pod}
- Xterm.js avec addons:
  - FitAddon: ajuste la taille aux dimensions de l’UI
  - AttachAddon: attache directement les flux stdin/stdout/stderr → latence faible et encodage correct
  - WebGLAddon: rendu accéléré (fallback automatique si indisponible)
- Inactivité: pas de keepalive applicatif, voir « Fin de session et inactivité » ci-dessous
- Resize: l’UI envoie les dimensions pour adapter le TTY du côté du pod

## Sécurité et restrictions

- Authentification de la session requise
- Le terminal applique le même contrôle d'accès que les endpoints de déploiement :
  le propriétaire du lab et les admins sont autorisés; un enseignant n'a accès
  qu'aux pods de ses propres labs.
- Les pods doivent porter les labels LabOnDemand cohérents (`managed-by`,
  `user-id`, `app-type`).
- Les pods de base de données (`component=database`) des stacks mysql,
  wordpress et lamp ne sont pas accessibles par terminal.
- Le backend tourne l’exec avec TTY, sous l’utilisateur du conteneur (ex. non-root pour LAMP web)

## Fin de session et inactivité

- Le pont WebSocket ↔ exec ne bloque jamais la boucle d'événements de l'API :
  authentification, ouverture du flux exec et écritures (saisie,
  redimensionnement) passent par le pool de threads. Un thread lecteur par
  session attend la sortie du pod (`update(timeout=0.5)`, sans attente active)
  et c'est lui qui ferme le flux exec.
- Le redimensionnement envoyé par l'UI (`{"type": "resize", "cols": N, "rows": N}`)
  est transmis au pod sur le canal 4 du protocole exec (`{"Width": N, "Height": N}`),
  dimensions bornées entre 1 et 1000.
- La session se termine :
  - quand le navigateur ferme le WebSocket : le flux exec est fermé (le shell du
    pod reçoit SIGHUP) et le thread lecteur s'arrête ;
  - quand le processus du pod se termine (`exit`) : la dernière sortie est
    transmise, puis le WebSocket est fermé avec le code 1000 ;
  - après `TERMINAL_IDLE_TIMEOUT_SECONDS` secondes (défaut 1800, `0` = jamais)
    sans aucun échange dans un sens ou dans l'autre (saisie, redimensionnement
    ou sortie du pod) : fermeture avec le code 4408. Une commande qui affiche
    régulièrement (build, logs suivis) garde donc la session ouverte.
- Codes de fermeture affichés par l'UI (« Session terminee (code N) ») :
  4401 session absente/expirée ou compte inactif, 4403 accès refusé,
  4404 pod introuvable, 4408 inactivité, 1011 échec d'ouverture de l'exec ou
  erreur interne, 1000 fin normale.
- Derrière un proxy, garder `TERMINAL_IDLE_TIMEOUT_SECONDS` inférieur au délai de
  lecture du proxy pour que la fermeture vienne de l'API, avec un code explicite.

## Dépannage

- Double-écriture/écho: résolu par l’AttachAddon (pas de handler onmessage redondant)
- Latence: le thread lecteur relaie chaque trame dès sa réception (trames déjà arrivées regroupées par message); WebGL améliore le rendu
- Police/couleurs: la feuille de style du dashboard adapte l’apparence de la console
- Déconnexion: si la connexion réseau coupe, ré-ouvrez le terminal depuis les détails du déploiement
