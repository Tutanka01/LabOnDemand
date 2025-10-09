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
from .models import User, UserRole, Template, RuntimeConfig
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
            # Migration douce: ajouter la colonne 'tags' si absente
            try:
                db.execute(text("ALTER TABLE templates ADD COLUMN tags VARCHAR(255) NULL"))
                db.commit()
            except Exception:
                pass
            # Créer la table runtime_configs si absente (migration douce)
            try:
                db.execute(text(
                    "CREATE TABLE IF NOT EXISTS runtime_configs ("
                    "id INTEGER PRIMARY KEY AUTO_INCREMENT,"
                    "key VARCHAR(50) UNIQUE NOT NULL,"
                    "default_image VARCHAR(200),"
                    "target_port INTEGER,"
                    "default_service_type VARCHAR(30) NOT NULL DEFAULT 'NodePort',"
                    "allowed_for_students BOOLEAN DEFAULT TRUE,"
                    "min_cpu_request VARCHAR(20),"
                    "min_memory_request VARCHAR(20),"
                    "min_cpu_limit VARCHAR(20),"
                    "min_memory_limit VARCHAR(20),"
                    "active BOOLEAN DEFAULT TRUE,"
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
                    "updated_at DATETIME NULL"
                    ")"
                ))
                db.commit()
            except Exception:
                pass
            # Migration douce: ajouter la colonne allowed_for_students si absente
            try:
                db.execute(text("ALTER TABLE runtime_configs ADD COLUMN allowed_for_students BOOLEAN DEFAULT TRUE"))
                db.commit()
            except Exception:
                pass
            admin = db.query(User).filter(User.role == UserRole.admin).first()
            if not admin:
                # Mot de passe admin via variable d'environnement (sécurisé). Fallback: mot de passe aléatoire.
                import secrets
                admin_password = settings.ADMIN_DEFAULT_PASSWORD
                if not admin_password:
                    admin_password = secrets.token_urlsafe(24)
                    print("[startup] ADMIN_DEFAULT_PASSWORD non défini. Un mot de passe admin aléatoire a été généré (affiché ci-dessous).")

                admin = User(
                    username="admin",
                    email="admin@labondemand.local",
                    full_name="Administrateur",
                    hashed_password=get_password_hash(admin_password),
                    role=UserRole.admin,
                    is_active=True,
                )
                db.add(admin)
                db.commit()
                print(f"[startup] Compte admin créé. Nom d'utilisateur=admin, Mot de passe={admin_password}")

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
            else:
                # Assurer la présence des templates essentiels (WordPress, MySQL, LAMP)
                defaults = {t.get("id"): t for t in get_deployment_templates().get("templates", [])}

                tpl_wp = db.query(Template).filter(Template.key == "wordpress").first()
                if not tpl_wp:
                    d = defaults.get("wordpress", {})
                    db.add(Template(
                        key="wordpress",
                        name=d.get("name", "WordPress"),
                        description=d.get("description"),
                        icon=d.get("icon"),
                        deployment_type="wordpress",
                        default_image=d.get("default_image", "bitnamilegacy/wordpress:6.8.2-debian-12-r5"),
                        default_port=d.get("default_port", 8080),
                        default_service_type=d.get("default_service_type", "NodePort"),
                        active=True,
                    ))
                    db.commit()

                tpl_mysql = db.query(Template).filter(Template.key == "mysql").first()
                if not tpl_mysql:
                    d = defaults.get("mysql", {})
                    db.add(Template(
                        key="mysql",
                        name=d.get("name", "MySQL + phpMyAdmin"),
                        description=d.get("description"),
                        icon=d.get("icon"),
                        deployment_type="mysql",
                        default_image=d.get("default_image", "mysql:9"),
                        default_port=d.get("default_port", 8080),
                        default_service_type=d.get("default_service_type", "NodePort"),
                        active=True,
                    ))
                    db.commit()

                tpl_lamp = db.query(Template).filter(Template.key == "lamp").first()
                if not tpl_lamp:
                    d = defaults.get("lamp", {})
                    db.add(Template(
                        key="lamp",
                        name=d.get("name", "Stack LAMP"),
                        description=d.get("description"),
                        icon=d.get("icon"),
                        deployment_type="lamp",
                        default_image=d.get("default_image", "php:8.2-apache"),
                        default_port=d.get("default_port", 8080),
                        default_service_type=d.get("default_service_type", "NodePort"),
                        tags=",".join(d.get("tags", []) or []),
                        active=True,
                    ))
                    db.commit()
                tpl_netbeans = db.query(Template).filter(Template.key == "netbeans").first()
                if not tpl_netbeans:
                    d = defaults.get("netbeans", {})
                    db.add(Template(
                        key="netbeans",
                        name=d.get("name", "NetBeans Desktop (NoVNC)"),
                        description=d.get("description"),
                        icon=d.get("icon"),
                        deployment_type="netbeans",
                        default_image=d.get("default_image", "tutanka01/labondemand:netbeansjava"),
                        default_port=d.get("default_port", 6901),
                        default_service_type=d.get("default_service_type", "NodePort"),
                        tags=",".join(d.get("tags", []) or []),
                        active=True,
                    ))
                    db.commit()
            # Seed des runtime configs si vide (dynamiques pour remplacer le hardcode)
            if db.query(RuntimeConfig).count() == 0:
                # valeurs inspirées de templates.DeploymentConfig
                db.add(RuntimeConfig(
                    key="vscode",
                    default_image="tutanka01/k8s:vscode",
                    target_port=8080,
                    default_service_type="NodePort",
                    allowed_for_students=True,
                    min_cpu_request="200m",
                    min_memory_request="256Mi",
                    min_cpu_limit="500m",
                    min_memory_limit="512Mi",
                    active=True,
                ))
                db.add(RuntimeConfig(
                    key="jupyter",
                    default_image="tutanka01/k8s:jupyter",
                    target_port=8888,
                    default_service_type="NodePort",
                    allowed_for_students=True,
                    min_cpu_request="250m",
                    min_memory_request="512Mi",
                    min_cpu_limit="500m",
                    min_memory_limit="1Gi",
                    active=True,
                ))
                db.add(RuntimeConfig(
                    key="wordpress",
                    default_image="bitnamilegacy/wordpress:6.8.2-debian-12-r5",
                    target_port=8080,
                    default_service_type="NodePort",
                    allowed_for_students=True,
                    active=True,
                ))
                db.add(RuntimeConfig(
                    key="lamp",
                    default_image="php:8.2-apache",
                    target_port=8080,
                    default_service_type="NodePort",
                    allowed_for_students=True,
                    active=True,
                ))
                db.add(RuntimeConfig(
                    key="netbeans",
                    default_image="tutanka01/labondemand:netbeansjava",
                    target_port=6901,
                    default_service_type="NodePort",
                    allowed_for_students=True,
                    min_cpu_request="500m",
                    min_memory_request="1Gi",
                    min_cpu_limit="1000m",
                    min_memory_limit="2Gi",
                    active=True,
                ))
                db.commit()
            else:
                # S'assurer que WordPress et MySQL existent et sont autorisés aux étudiants
                wp = db.query(RuntimeConfig).filter(RuntimeConfig.key == "wordpress").first()
                if not wp:
                    db.add(RuntimeConfig(
                        key="wordpress",
                        default_image="bitnamilegacy/wordpress:6.8.2-debian-12-r5",
                        target_port=8080,
                        default_service_type="NodePort",
                        allowed_for_students=True,
                        active=True,
                    ))
                    db.commit()
                elif wp.allowed_for_students is None:
                    wp.allowed_for_students = True
                    db.commit()
                mysql_rc = db.query(RuntimeConfig).filter(RuntimeConfig.key == "mysql").first()
                if not mysql_rc:
                    db.add(RuntimeConfig(
                        key="mysql",
                        default_image="phpmyadmin:latest",
                        target_port=8080,
                        default_service_type="NodePort",
                        allowed_for_students=True,
                        active=True,
                    ))
                    db.commit()
                lamp_rc = db.query(RuntimeConfig).filter(RuntimeConfig.key == "lamp").first()
                if not lamp_rc:
                    db.add(RuntimeConfig(
                        key="lamp",
                        default_image="php:8.2-apache",
                        target_port=8080,
                        default_service_type="NodePort",
                        allowed_for_students=True,
                        active=True,
                    ))
                    db.commit()
                netbeans_rc = db.query(RuntimeConfig).filter(RuntimeConfig.key == "netbeans").first()
                if not netbeans_rc:
                    db.add(RuntimeConfig(
                        key="netbeans",
                        default_image="tutanka01/labondemand:netbeansjava",
                        target_port=6901,
                        default_service_type="NodePort",
                        allowed_for_students=True,
                        min_cpu_request="500m",
                        min_memory_request="1Gi",
                        min_cpu_limit="1000m",
                        min_memory_limit="2Gi",
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
from .k8s_router import quotas_router

app.include_router(auth_router)
app.include_router(k8s_router)
app.include_router(quotas_router)

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
