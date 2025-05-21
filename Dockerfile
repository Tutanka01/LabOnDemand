FROM python:3.13-slim

WORKDIR /app

# Installation de kubectl
RUN apt-get update && \
    apt-get install -y curl && \
    curl -LO "https://dl.k8s.io/release/stable.txt" && \
    KUBECTL_VERSION=$(cat stable.txt) && \
    curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/ && \
    rm stable.txt && \
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