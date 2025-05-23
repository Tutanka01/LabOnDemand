from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

from database import Base, engine
from models import User, UserRole
from security import get_password_hash

def init_database():
    """
    Initialise la base de données et crée un utilisateur admin par défaut
    """
    # Créer toutes les tables dans la base de données
    Base.metadata.create_all(bind=engine)
    
    # Créer une session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    # Vérifier si un utilisateur admin existe déjà
    admin_exists = db.query(User).filter(User.role == UserRole.admin).first() is not None
    
    # Si aucun admin n'existe, en créer un par défaut
    if not admin_exists:
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        admin_email = os.getenv("ADMIN_EMAIL", "admin@labondemand.local")
        
        admin_user = User(
            username=admin_username,
            email=admin_email,
            hashed_password=get_password_hash(admin_password),
            full_name="Administrateur",
            role=UserRole.admin
        )
        
        db.add(admin_user)
        db.commit()
        print(f"Utilisateur administrateur créé : {admin_username}")
    else:
        print("Un utilisateur administrateur existe déjà")
    
    db.close()

if __name__ == "__main__":
    print("Initialisation de la base de données...")
    init_database()
    print("Initialisation terminée!")
