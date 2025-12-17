FROM python:3.13-slim

# Set proxy environment variables for build steps
#ENV http_proxy=http://cache.univ-pau.fr:3128
#ENV https_proxy=http://cache.univ-pau.fr:3128
#ENV HTTP_PROXY=http://cache.univ-pau.fr:3128
#ENV HTTPS_PROXY=http://cache.univ-pau.fr:3128

WORKDIR /app

# Installation de kubectl (sans dépendre de dl.k8s.io)
# Note: sur Debian (base de python:*-slim), kubectl est fourni par le package "kubernetes-client".
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates kubernetes-client && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copie des fichiers du projet
COPY requirements.txt .
COPY backend/ /app/backend/
# Ne copiez PAS le fichier .env dans l'image !

# Installation des dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Vérification que kubectl est correctement installé
RUN kubectl version --client

# Exposition du port utilisé par l'API (sera écrasé par la variable d'environnement si définie)
EXPOSE 8000

# Commande pour démarrer l'API en utilisant uvicorn directement
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]