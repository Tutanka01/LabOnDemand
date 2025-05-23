#!/usr/bin/env python3
# filepath: c:\Users\zhiri\Nextcloud\mo\Projects\LabOnDemand\backend\tests\test_auth.py
import unittest
import requests
import json
import time
from urllib.parse import urlparse

# Configuration de test
BASE_URL = "http://localhost:8000"
API_V1 = f"{BASE_URL}/api/v1"

class TestAuthentication(unittest.TestCase):
    def setUp(self):
        """Prépare les tests en créant un utilisateur de test"""
        # Données pour l'utilisateur de test
        self.test_user = {
            "username": f"testuser_{int(time.time())}",
            "email": f"test_{int(time.time())}@example.com",
            "full_name": "Utilisateur de Test",
            "password": "Password123!",
            "role": "student"
        }

        self.admin_credentials = {
            "username": "admin",
            "password": "adminpassword"
        }

        # Créer un utilisateur de test
        self.admin_session = requests.Session()
        
        # Se connecter en tant qu'admin
        response = self.admin_session.post(
            f"{API_V1}/auth/login",
            json=self.admin_credentials
        )
        
        if response.status_code != 200:
            self.fail(f"Impossible de se connecter en tant qu'admin: {response.text}")
        
        # Utiliser la session admin pour créer l'utilisateur de test
        response = self.admin_session.post(
            f"{API_V1}/auth/register",
            json=self.test_user
        )
        
        if response.status_code != 201:
            self.fail(f"Impossible de créer l'utilisateur de test: {response.text}")
        
        # Récupérer l'ID du nouvel utilisateur
        self.test_user_id = response.json()["id"]
        
        # Session utilisée pour les tests
        self.session = requests.Session()

    def tearDown(self):
        """Nettoie l'environnement de test en supprimant l'utilisateur créé"""
        # Supprimer l'utilisateur de test
        response = self.admin_session.delete(f"{API_V1}/auth/users/{self.test_user_id}")
        if response.status_code != 204:
            print(f"Attention: Impossible de supprimer l'utilisateur de test: {response.text}")
        
        # Fermer les sessions
        self.session.close()
        self.admin_session.close()

    def test_1_register_user(self):
        """Test d'inscription d'un nouvel utilisateur"""
        # Créer un nouvel utilisateur avec un nom différent
        new_user = {
            "username": f"newuser_{int(time.time())}",
            "email": f"new_{int(time.time())}@example.com",
            "full_name": "Nouvel Utilisateur",
            "password": "Password123!",
            "role": "student"
        }
        
        response = self.admin_session.post(f"{API_V1}/auth/register", json=new_user)
        self.assertEqual(response.status_code, 201)
        
        user_data = response.json()
        self.assertEqual(user_data["username"], new_user["username"])
        self.assertEqual(user_data["email"], new_user["email"])
        self.assertEqual(user_data["role"], new_user["role"])
        
        # Supprimer cet utilisateur après le test
        new_user_id = user_data["id"]
        self.admin_session.delete(f"{API_V1}/auth/users/{new_user_id}")

    def test_2_login_user(self):
        """Test de connexion utilisateur"""
        response = self.session.post(
            f"{API_V1}/auth/login", 
            json={
                "username": self.test_user["username"],
                "password": self.test_user["password"]
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Vérifier que la réponse contient les bonnes informations
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], self.test_user["username"])
        
        # Vérifier que le cookie de session est défini
        cookies = self.session.cookies
        self.assertIn("session_id", cookies)

    def test_3_invalid_login(self):
        """Test d'échec de connexion avec des identifiants invalides"""
        response = requests.post(
            f"{API_V1}/auth/login", 
            json={
                "username": self.test_user["username"],
                "password": "mauvais_mot_de_passe"
            }
        )
        
        self.assertEqual(response.status_code, 401)

    def test_4_get_current_user(self):
        """Test de récupération des informations de l'utilisateur actuel"""
        # Se connecter d'abord
        self.session.post(
            f"{API_V1}/auth/login", 
            json={
                "username": self.test_user["username"],
                "password": self.test_user["password"]
            }
        )
        
        # Vérifier que nous pouvons obtenir les informations de l'utilisateur
        response = self.session.get(f"{API_V1}/auth/me")
        self.assertEqual(response.status_code, 200)
        
        user_data = response.json()
        self.assertEqual(user_data["username"], self.test_user["username"])
        self.assertEqual(user_data["email"], self.test_user["email"])

    def test_5_check_role(self):
        """Test de vérification du rôle de l'utilisateur"""
        # Se connecter d'abord
        self.session.post(
            f"{API_V1}/auth/login", 
            json={
                "username": self.test_user["username"],
                "password": self.test_user["password"]
            }
        )
        
        # Vérifier le rôle
        response = self.session.get(f"{API_V1}/auth/check-role")
        self.assertEqual(response.status_code, 200)
        
        role_data = response.json()
        self.assertEqual(role_data["role"], "student")
        self.assertFalse(role_data["can_manage_users"])

    def test_6_update_profile(self):
        """Test de mise à jour du profil utilisateur"""
        # Se connecter d'abord
        self.session.post(
            f"{API_V1}/auth/login", 
            json={
                "username": self.test_user["username"],
                "password": self.test_user["password"]
            }
        )
        
        # Mettre à jour le profil
        update_data = {
            "full_name": "Nouveau Nom Complet"
        }
        
        response = self.session.put(f"{API_V1}/auth/me", json=update_data)
        self.assertEqual(response.status_code, 200)
        
        user_data = response.json()
        self.assertEqual(user_data["full_name"], update_data["full_name"])

    def test_7_admin_user_management(self):
        """Test des fonctionnalités d'administration des utilisateurs"""
        # Vérifier que l'admin peut lister tous les utilisateurs
        response = self.admin_session.get(f"{API_V1}/auth/users")
        self.assertEqual(response.status_code, 200)
        
        # Vérifier que l'admin peut obtenir un utilisateur spécifique
        response = self.admin_session.get(f"{API_V1}/auth/users/{self.test_user_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], self.test_user["username"])
        
        # Vérifier que l'admin peut modifier un utilisateur
        update_data = {
            "role": "teacher"
        }
        
        response = self.admin_session.put(
            f"{API_V1}/auth/users/{self.test_user_id}", 
            json=update_data
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "teacher")

    def test_8_logout(self):
        """Test de déconnexion d'un utilisateur"""
        # Se connecter d'abord
        self.session.post(
            f"{API_V1}/auth/login", 
            json={
                "username": self.test_user["username"],
                "password": self.test_user["password"]
            }
        )
        
        # Maintenant, se déconnecter
        response = self.session.post(f"{API_V1}/auth/logout")
        self.assertEqual(response.status_code, 200)
        
        # Vérifier que le cookie de session est supprimé
        cookie_header = response.headers.get('Set-Cookie', '')
        
        # Après la déconnexion, nous ne devrions pas pouvoir accéder aux données de l'utilisateur
        response = self.session.get(f"{API_V1}/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_9_access_control(self):
        """Test du contrôle d'accès basé sur les rôles"""
        # Un étudiant ne devrait pas pouvoir accéder à la liste des utilisateurs
        student_session = requests.Session()
        
        student_session.post(
            f"{API_V1}/auth/login", 
            json={
                "username": self.test_user["username"],
                "password": self.test_user["password"]
            }
        )
        
        response = student_session.get(f"{API_V1}/auth/users")
        self.assertNotEqual(response.status_code, 200)
        
        student_session.close()

if __name__ == '__main__':
    unittest.main()
