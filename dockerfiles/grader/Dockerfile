# Image Grader LabOnDemand — exécute les probes boîte noire contre le lab d'un étudiant.
#
# Cette image est volontairement minimale et SANS aucun accès au cluster :
# c'est un Job Kubernetes jetable, isolé par NetworkPolicy, qui n'a que les outils
# nécessaires pour "attaquer" un lab de l'extérieur (HTTP, TCP, SQL) puis imprimer
# son verdict en JSON sur stdout. L'API lit ensuite ce stdout (modèle pull).
#
# Build :
#   docker build -t labondemand/grader:latest dockerfiles/grader/
#
# Le script de notation n'utilise QUE la bibliothèque standard Python (urllib, socket,
# subprocess) : aucune dépendance pip à installer, l'image reste légère et reproductible.

FROM python:3.13-slim

# Outils de diagnostic réseau / clients SQL utilisés par les probes et les scripts profs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        jq \
        netcat-openbsd \
        default-mysql-client \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root (le Job force aussi runAsNonRoot côté manifeste).
RUN useradd --create-home --uid 10001 grader

WORKDIR /app
COPY grader.py /app/grader.py

USER 10001

ENTRYPOINT ["python", "/app/grader.py"]
