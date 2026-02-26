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
- Keepalive: messages périodiques pour maintenir la session active
- Resize: l’UI envoie les dimensions pour adapter le TTY du côté du pod

## Sécurité et restrictions

- Authentification de la session requise
- Contrôles de rôle et de labels: un étudiant ne peut pas ouvrir de terminal sur les pods de base de données (component=database) pour les stacks mysql/wordpress/lamp
- Le backend tourne l’exec avec TTY, sous l’utilisateur du conteneur (ex. non-root pour LAMP web)

## Dépannage

- Double-écriture/écho: résolu par l’AttachAddon (pas de handler onmessage redondant)
- Latence: la boucle de lecture côté backend utilise des timeouts courts et des rafales; WebGL améliore le rendu
- Police/couleurs: la feuille de style du dashboard adapte l’apparence de la console
- Déconnexion: si la connexion réseau coupe, ré-ouvrez le terminal depuis les détails du déploiement
