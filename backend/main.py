"""
Application principale LabOnDemand
Principe KISS : configuration simple et routage centralisé
"""
import os
import uvicorn
from datetime import datetime
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from .config import settings
from .database import Base, engine, get_db, SessionLocal
from .session import setup_session_handler
from .error_handlers import global_exception_handler
from . import models  # Importer les modèles pour enregistrer les tables avant create_all
from .models import User, UserRole, Template
from .security import get_password_hash
from .templates import get_deployment_templates

# Initialiser Kubernetes
settings.init_kubernetes()

# Créer l'application FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    debug=settings.DEBUG_MODE,
)

# Ajouter le gestionnaire d'erreurs global
app.add_exception_handler(Exception, global_exception_handler)

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

# Création des tables de base de données (nécessite l'import de models ci-dessus)
Base.metadata.create_all(bind=engine)

# S'assurer qu'un compte admin par défaut existe (simple et fonctionnel)
@app.on_event("startup")
def ensure_admin_exists():
    try:
        with SessionLocal() as db:
            # Re-créer les tables au cas où (idempotent)
            Base.metadata.create_all(bind=engine)
            admin = db.query(User).filter(User.role == UserRole.admin).first()
            if not admin:
                admin = User(
                    username="admin",
                    email="admin@labondemand.local",
                    full_name="Administrateur",
                    hashed_password=get_password_hash("admin123"),
                    role=UserRole.admin,
                    is_active=True,
                )
                db.add(admin)
                db.commit()

            # Seed des templates de base si vide
            if db.query(Template).count() == 0:
                defaults = get_deployment_templates().get("templates", [])
                for t in defaults:
                    db.add(Template(
                        key=t.get("id"),
                        name=t.get("name"),
                        description=t.get("description"),
                        icon=t.get("icon"),
                        deployment_type=t.get("deployment_type", "custom"),
                        default_image=t.get("default_image"),
                        default_port=t.get("default_port"),
                        default_service_type=t.get("default_service_type", "NodePort"),
                        active=True,
                    ))
                db.commit()
    except Exception as e:
        # On ne casse pas le démarrage pour éviter l'indisponibilité totale
        print(f"[startup] Impossible d'assurer la présence de l'admin: {e}")

# ============= INCLUSION DES ROUTEURS =============

# Routeurs d'authentification et de laboratoires
from .auth_router import router as auth_router
from .k8s_router import router as k8s_router

app.include_router(auth_router)
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

@app.get("/api/v1/health")
async def health_check(db: Session = Depends(get_db)):
    """Vérification de santé de l'API"""
    try:
        # Test de connexion DB
        db.execute(text("SELECT 1"))
        
        # Test des tables
        from .models import User
        user_count = db.query(User).count()
        
        return {
            "status": "healthy",
            "database": "connected",
            "users": user_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
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
