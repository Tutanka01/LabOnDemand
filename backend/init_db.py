"""
Script d'initialisation de la base de données LabOnDemand
Principe KISS : initialisation simple et fiable
"""
import os
import sys
from pathlib import Path
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# Racine du projet dans le path : le script fonctionne lancé depuis backend/
# (python init_db.py) comme depuis la racine (python -m backend.init_db).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from backend.database import engine
    from backend.db_migrate import upgrade_schema
    from backend.models import User, UserRole
    from backend.security import get_password_hash
except ImportError as e:
    print(f"Erreur d'import: {e}")
    print("Assurez-vous d'être dans le bon répertoire et que les modules existent")
    sys.exit(1)

def check_database_connection():
    """Vérifie la connexion à la base de données"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Connexion à la base de données réussie")
            return True
    except Exception as e:
        print(f"❌ Erreur de connexion à la base de données: {e}")
        return False

def create_tables():
    """Crée ou met à jour le schéma via les migrations Alembic (comme au démarrage de l'API)"""
    try:
        print("🔨 Migration du schéma...")
        revision = upgrade_schema()
        print(f"✅ Schéma à jour (révision {revision})")
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la création des tables: {e}")
        return False

def create_admin_user():
    """Crée l'utilisateur administrateur par défaut"""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Vérifier si un admin existe déjà
        existing_admin = db.query(User).filter(User.role == UserRole.admin).first()
        
        if existing_admin:
            print(f"✅ Administrateur existe déjà: {existing_admin.username}")
            return True
        
        # Créer le compte admin
        admin = User(
            username="admin",
            email="admin@labondemand.local",
            full_name="Administrateur",
            hashed_password=get_password_hash("admin123"),
            role=UserRole.admin,
            is_active=True
        )
        
        db.add(admin)
        db.commit()
        print("✅ Utilisateur admin créé")
        print("   Nom d'utilisateur: admin")
        print("   Mot de passe: admin123")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la création de l'admin: {e}")
        db.rollback()
        return False
    finally:
        db.close()

def verify_setup():
    """Vérifie que tout est bien configuré"""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Compter les utilisateurs
        user_count = db.query(User).count()
        admin_count = db.query(User).filter(User.role == UserRole.admin).count()
        
        print(f"📊 Statistiques:")
        print(f"   - Utilisateurs total: {user_count}")
        print(f"   - Administrateurs: {admin_count}")
        
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la vérification: {e}")
        return False
    finally:
        db.close()

def main():
    """Fonction principale d'initialisation"""
    print("🚀 Initialisation de la base de données LabOnDemand")
    print("=" * 50)
    
    # Étape 1: Vérifier la connexion
    if not check_database_connection():
        print("❌ Impossible de se connecter à la base de données")
        print("Vérifiez votre configuration dans database.py")
        return False
    
    # Étape 2: Créer les tables
    if not create_tables():
        print("❌ Impossible de créer les tables")
        return False
    
    # Étape 3: Créer l'admin
    if not create_admin_user():
        print("❌ Impossible de créer l'utilisateur admin")
        return False
    
    # Étape 4: Vérification finale
    if not verify_setup():
        print("❌ Erreur lors de la vérification")
        return False
    
    print("=" * 50)
    print("✅ Initialisation terminée avec succès!")
    print("Vous pouvez maintenant démarrer l'API")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
