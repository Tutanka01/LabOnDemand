#!/usr/bin/env python3
# filepath: c:\Users\zhiri\Nextcloud\mo\Projects\LabOnDemand\backend\reset_admin.py
"""
Script pour réinitialiser le compte administrateur
Ce script supprime l'admin existant et en crée un nouveau avec des identifiants connus
"""
from sqlalchemy.orm import sessionmaker
import os
import sys
from pathlib import Path

# Ajout du répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent))

from database import engine
from models import User, UserRole
from security import get_password_hash

def reset_admin_account():
    """
    Réinitialise le compte administrateur avec des identifiants connus
    """
    # Créer une session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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
    reset_admin_account()
    print("=== Opération terminée ===")
