"""
Application principale LabOnDemand
Principe KISS : configuration simple et routage centralisé
"""
import os
import uvicorn
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .session import setup_session_handler

# Initialiser Kubernetes
settings.init_kubernetes()

# Créer l'application FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    debug=settings.DEBUG_MODE,
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration du middleware de session
setup_session_handler(app)

# Création des tables de base de données
Base.metadata.create_all(bind=engine)

# ============= INCLUSION DES ROUTEURS =============

# Routeurs d'authentification et de laboratoires
from .auth_router import router as auth_router
from .lab_router import router as lab_router
from .k8s_router import router as k8s_router

app.include_router(auth_router)
app.include_router(lab_router)
app.include_router(k8s_router)

# ============= ENDPOINTS DE BASE =============

@app.get("/")
async def read_root():
    """Endpoint racine - Message de bienvenue"""
    return {"message": "Bienvenue sur l'API LabOnDemand !"}

@app.get("/api/v1/status")
async def get_status():
    """Status de l'API"""
    return {
        "status": "API en cours d'exécution", 
        "version": app.version,
        "debug": settings.DEBUG_MODE
    }

# ============= ENDPOINT DE DIAGNOSTIC =============

@app.post("/api/v1/diagnostic/test-auth")
async def test_auth(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint de diagnostic pour tester l'authentification
    ATTENTION: Ne pas utiliser en production!
    """
    try:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        
        if not username or not password:
            return {
                "success": False,
                "message": "Le nom d'utilisateur et le mot de passe sont requis",
                "details": None
            }
        
        from .security import authenticate_user
        user = authenticate_user(db, username, password)
        
        if user:
            return {
                "success": True,
                "message": "Authentification réussie",
                "details": {
                    "user_id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role.value,
                    "is_active": user.is_active
                }
            }
        else:
            return {
                "success": False,
                "message": "Échec de l'authentification",
                "details": None
            }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "message": f"Erreur lors de l'authentification: {str(e)}",
            "details": traceback.format_exc()
        }

# ============= POINT D'ENTRÉE =============

def main():
    """Point d'entrée pour lancer l'API"""
    uvicorn.run(
        "backend.main:app", 
        host="0.0.0.0", 
        port=settings.API_PORT, 
        reload=settings.DEBUG_MODE
    )

if __name__ == "__main__":
    main()
