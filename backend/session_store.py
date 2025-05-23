from datetime import datetime, timedelta
import os
from typing import Dict, Any, Optional
import json
import pickle
from pathlib import Path

# Définition de la classe pour le stockage des sessions
class SessionStore:
    """
    Classe pour gérer le stockage des sessions utilisateur.
    Cette implémentation utilise un stockage en mémoire avec persistance sur disque optionnelle,
    mais peut être étendue pour utiliser Redis ou une base de données.
    """
    def __init__(self, persist_path: Optional[str] = None, expiry_time_hours: int = 24):
        """
        Initialise le gestionnaire de sessions
        
        Args:
            persist_path: Chemin où les sessions seront sauvegardées (None pour pas de persistance)
            expiry_time_hours: Durée de vie des sessions en heures
        """
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.expiry_time = timedelta(hours=expiry_time_hours)
        self.persist_path = persist_path
        
        # Créer le répertoire de persistance s'il n'existe pas
        if persist_path:
            path = Path(persist_path)
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            
            # Charger les sessions existantes s'il y en a
            self._load_sessions()
    
    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        """
        Stocke une session avec ses données
        
        Args:
            session_id: Identifiant unique de la session
            data: Données à associer à la session
        """
        expiry = datetime.utcnow() + self.expiry_time
        self.sessions[session_id] = {
            "data": data,
            "expiry": expiry
        }
        
        # Persister les sessions si configuré
        if self.persist_path:
            self._persist_sessions()
    
    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les données d'une session
        
        Args:
            session_id: Identifiant unique de la session
            
        Returns:
            Les données de la session ou None si la session n'existe pas ou a expiré
        """
        if session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        
        # Vérifier si la session a expiré
        if datetime.utcnow() > session["expiry"]:
            self.delete(session_id)
            return None
        
        return session["data"]
    
    def delete(self, session_id: str) -> bool:
        """
        Supprime une session
        
        Args:
            session_id: Identifiant unique de la session
            
        Returns:
            True si la session a été supprimée, False sinon
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            
            # Mettre à jour la persistance
            if self.persist_path:
                self._persist_sessions()
            return True
        return False
    
    def cleanup(self) -> int:
        """
        Supprime toutes les sessions expirées
        
        Returns:
            Nombre de sessions supprimées
        """
        now = datetime.utcnow()
        expired_sessions = [
            sid for sid, session in self.sessions.items()
            if now > session["expiry"]
        ]
        
        for sid in expired_sessions:
            del self.sessions[sid]
        
        # Mettre à jour la persistance
        if self.persist_path and expired_sessions:
            self._persist_sessions()
        
        return len(expired_sessions)
    
    def _persist_sessions(self) -> None:
        """
        Sauvegarde les sessions sur disque
        """
        if not self.persist_path:
            return
        
        try:
            sessions_file = Path(self.persist_path) / "sessions.pkl"
            with open(sessions_file, 'wb') as f:
                pickle.dump(self.sessions, f)
        except Exception as e:
            print(f"Erreur lors de la persistance des sessions: {e}")
    
    def _load_sessions(self) -> None:
        """
        Charge les sessions depuis le disque
        """
        if not self.persist_path:
            return
        
        sessions_file = Path(self.persist_path) / "sessions.pkl"
        if not sessions_file.exists():
            return
        
        try:
            with open(sessions_file, 'rb') as f:
                self.sessions = pickle.load(f)
                
            # Nettoyer les sessions expirées au chargement
            self.cleanup()
        except Exception as e:
            print(f"Erreur lors du chargement des sessions: {e}")
            # En cas d'erreur, commencer avec un stockage vide
            self.sessions = {}

# Création d'une instance globale du gestionnaire de sessions
# Le chemin de persistance est facultatif et peut être configuré via une variable d'environnement
SESSION_PERSIST_PATH = os.getenv("SESSION_PERSIST_PATH", "./sessions")
SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))

# Instance globale du gestionnaire de sessions
session_store = SessionStore(
    persist_path=SESSION_PERSIST_PATH,
    expiry_time_hours=SESSION_EXPIRY_HOURS
)
