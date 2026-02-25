"""
Script de diagnostic pour LabOnDemand
Principe KISS : vérifications essentielles
"""
import os
import sys
from pathlib import Path
from sqlalchemy import text

# Ajout du répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent))

def check_imports():
    """Vérifie que tous les modules peuvent être importés"""
    try:
        from database import engine, Base
        from models import User, UserRole
        from security import get_password_hash
        print("✅ Imports OK")
        return True
    except ImportError as e:
        print(f"❌ Erreur d'import: {e}")
        return False

def check_database():
    """Vérifie l'état de la base de données"""
    try:
        from database import engine
        
        # Test de connexion
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        print("✅ Connexion DB OK")
        
        # Test des tables
        with engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES"))
            tables = [row[0] for row in result]
            
        if 'users' in tables:
            print("✅ Table users existe")
        else:
            print("❌ Table users manquante")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Erreur DB: {e}")
        return False

def check_admin():
    """Vérifie qu'un admin existe"""
    try:
        from database import engine
        from models import User, UserRole
        from sqlalchemy.orm import sessionmaker
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()
        
        admin = db.query(User).filter(User.role == UserRole.admin).first()
        
        if admin:
            print(f"✅ Admin existe: {admin.username}")
            return True
        else:
            print("❌ Aucun admin trouvé")
            return False
            
    except Exception as e:
        print(f"❌ Erreur vérification admin: {e}")
        return False
    finally:
        if 'db' in locals():
            db.close()

def main():
    """Diagnostic complet"""
    print("🔍 Diagnostic LabOnDemand")
    print("=" * 30)
    
    issues = []
    
    if not check_imports():
        issues.append("Problème d'imports")
    
    if not check_database():
        issues.append("Problème de base de données")
    
    if not check_admin():
        issues.append("Aucun administrateur")
    
    print("=" * 30)
    
    if issues:
        print("❌ Problèmes détectés:")
        for issue in issues:
            print(f"   - {issue}")
        print("\n💡 Solutions:")
        print("   1. Exécutez: python init_db.py")
        print("   2. Ou exécutez: python reset_admin.py")
        return False
    else:
        print("✅ Tout fonctionne correctement!")
        return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
