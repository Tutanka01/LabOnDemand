#!/usr/bin/env python3
"""
Script pour réinitialiser le compte administrateur dans un environnement Docker
Ce script crée ou met à jour l'utilisateur admin avec des identifiants connus
"""
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from passlib.context import CryptContext

# Configuration de la base de données
DB_USER = os.getenv("DB_USER", "labondemand")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "labondemand")

# Construction de l'URL de connexion
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Création du moteur de base de données et de la session
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Configuration du contexte de hachage de mot de passe
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    """Crée un hash du mot de passe"""
    return pwd_context.hash(password)

def reset_admin_account():
    """
    Réinitialise le compte administrateur avec des identifiants connus
    """
    from backend.models import User, UserRole, Base
    
    # S'assurer que les tables existent
    Base.metadata.create_all(bind=engine)
    
    # Créer une session
    db = SessionLocal()
    
    try:
        # Définir les identifiants administrateur
        admin_username = "admin"
        admin_password = "admin123"
        admin_email = "admin@labondemand.local"
        
        print(f"Recherche d'un utilisateur admin existant avec le nom d'utilisateur '{admin_username}'...")
        
        # Vérifier si un utilisateur admin existe déjà avec ce nom d'utilisateur
        existing_admin = db.query(User).filter(User.username == admin_username).first()
        
        if existing_admin:
            print(f"Utilisateur admin trouvé (ID: {existing_admin.id})")
            print("Mise à jour du mot de passe...")
            
            # Mettre à jour le mot de passe
            existing_admin.hashed_password = get_password_hash(admin_password)
            db.commit()
            
            print(f"Mot de passe de l'administrateur réinitialisé à : {admin_password}")
        else:
            print("Aucun utilisateur admin trouvé avec ce nom d'utilisateur.")
            print("Création d'un nouvel utilisateur admin...")
            
            # Créer un nouvel utilisateur admin
            new_admin = User(
                username=admin_username,
                email=admin_email,
                hashed_password=get_password_hash(admin_password),
                full_name="Administrateur",
                role=UserRole.admin,
                is_active=True
            )
            
            db.add(new_admin)
            db.commit()
            db.refresh(new_admin)
            
            print(f"Nouvel utilisateur admin créé (ID: {new_admin.id})")
            print(f"Nom d'utilisateur: {admin_username}")
            print(f"Mot de passe: {admin_password}")
        
        # Afficher tous les utilisateurs pour déboguer
        print("\nListe de tous les utilisateurs dans la base de données:")
        users = db.query(User).all()
        for user in users:
            print(f"ID: {user.id}, Nom: {user.username}, Email: {user.email}, Rôle: {user.role.name}, Actif: {user.is_active}")
        
    except Exception as e:
        print(f"Erreur lors de la réinitialisation du compte admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("=== Réinitialisation du compte administrateur ===")
    # Ajouter le répertoire parent au path pour résoudre les imports
    import sys
    sys.path.insert(0, '/app')
    
    reset_admin_account()
    print("=== Opération terminée ===")
