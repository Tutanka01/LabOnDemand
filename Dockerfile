FROM python:3.13-slim AS base

# Set proxy environment variables for build steps
#ENV http_proxy=http://proxy.makhal:3128
#ENV https_proxy=http://proxy.makhal:3128
#ENV HTTP_PROXY=http://proxy.makhal:3128
#ENV HTTPS_PROXY=http://proxy.makhal:3128

WORKDIR /app

# Pas de kubectl : l'API pilote le cluster via le client Python kubernetes.
# ca-certificates est déjà fourni par l'image python:3.13-slim.

# Dépendances Python d'abord : la couche reste en cache tant que
# requirements.txt ne change pas, même si le code backend évolue.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code (ne copiez PAS le fichier .env dans l'image !)
COPY backend/ /app/backend/

# Image de test : dépendances pytest en plus, aucun secret ni kubeconfig.
# Utilisée par compose.test.yaml (docker compose -f compose.test.yaml run --rm tests).
FROM base AS test
RUN pip install --no-cache-dir -r backend/requirements-test.txt
ENV PYTHONPATH=/app
CMD ["python", "-m", "pytest", "backend/tests", "-q"]

# Image d'exécution (cible par défaut : dernier stage)
FROM base AS runtime

# Exposition du port utilisé par l'API (sera écrasé par la variable d'environnement si définie)
EXPOSE 8000

# Commande pour démarrer l'API en utilisant uvicorn directement
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
