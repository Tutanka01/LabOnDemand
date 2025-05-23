#!/usr/bin/env python3
# filepath: c:\Users\zhiri\Nextcloud\mo\Projects\LabOnDemand\backend\tests\test_ui.py
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import os

# Configuration de test
BASE_URL = "http://localhost:8000"

class TestUserInterface(unittest.TestCase):
    def setUp(self):
        """Préparer l'environnement de test"""
        # Utilisation de Chrome pour les tests d'interface
        self.driver = webdriver.Chrome()
        self.driver.implicitly_wait(10)
        
        # Informations de connexion pour les différents rôles
        self.admin_user = {"username": "admin", "password": "adminpassword"}
        self.teacher_user = {"username": "teacher", "password": "teacherpassword"}
        self.student_user = {"username": "student", "password": "studentpassword"}
        
    def tearDown(self):
        """Nettoyer l'environnement après les tests"""
        if self.driver:
            self.driver.quit()
    
    def login(self, username, password):
        """Fonction utilitaire pour se connecter au système"""
        self.driver.get(f"{BASE_URL}/login.html")
        
        # Attendre que le formulaire de connexion soit chargé
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        
        # Remplir le formulaire
        username_field = self.driver.find_element(By.ID, "username")
        password_field = self.driver.find_element(By.ID, "password")
        
        username_field.clear()
        username_field.send_keys(username)
        
        password_field.clear()
        password_field.send_keys(password)
        
        # Soumettre le formulaire
        self.driver.find_element(By.CLASS_NAME, "btn-login").click()
        
        # Attendre la redirection vers la page d'accueil
        try:
            WebDriverWait(self.driver, 5).until(
                lambda driver: driver.current_url == f"{BASE_URL}/index.html"
            )
            return True
        except TimeoutException:
            return False
    
    def logout(self):
        """Fonction utilitaire pour se déconnecter"""
        logout_btn = self.driver.find_element(By.ID, "logout-btn")
        logout_btn.click()
        
        # Attendre la redirection vers la page de connexion
        WebDriverWait(self.driver, 5).until(
            lambda driver: driver.current_url == f"{BASE_URL}/login.html"
        )
    
    def test_1_login_page_loads(self):
        """Vérifier que la page de connexion se charge correctement"""
        self.driver.get(f"{BASE_URL}/login.html")
        
        # Vérifier la présence des éléments du formulaire
        username_field = self.driver.find_element(By.ID, "username")
        password_field = self.driver.find_element(By.ID, "password")
        login_button = self.driver.find_element(By.CLASS_NAME, "btn-login")
        
        self.assertIsNotNone(username_field)
        self.assertIsNotNone(password_field)
        self.assertIsNotNone(login_button)
        
        # Vérifier la présence du lien d'inscription
        register_link = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Pas encore inscrit')]")
        self.assertIsNotNone(register_link)
    
    def test_2_register_page_loads(self):
        """Vérifier que la page d'inscription se charge correctement"""
        self.driver.get(f"{BASE_URL}/register.html")
        
        # Vérifier la présence des éléments du formulaire
        username_field = self.driver.find_element(By.ID, "username")
        email_field = self.driver.find_element(By.ID, "email")
        full_name_field = self.driver.find_element(By.ID, "full_name")
        password_field = self.driver.find_element(By.ID, "password")
        confirm_password_field = self.driver.find_element(By.ID, "confirm_password")
        register_button = self.driver.find_element(By.CLASS_NAME, "btn-login")
        
        self.assertIsNotNone(username_field)
        self.assertIsNotNone(email_field)
        self.assertIsNotNone(full_name_field)
        self.assertIsNotNone(password_field)
        self.assertIsNotNone(confirm_password_field)
        self.assertIsNotNone(register_button)
        
        # Vérifier la présence du lien de connexion
        login_link = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Déjà inscrit')]")
        self.assertIsNotNone(login_link)
    
    def test_3_successful_login_logout(self):
        """Vérifier le processus de connexion et déconnexion"""
        # Connexion
        success = self.login(self.student_user["username"], self.student_user["password"])
        self.assertTrue(success, "La connexion a échoué")
        
        # Vérifier que l'élément affichant le nom d'utilisateur est présent
        username_display = self.driver.find_element(By.ID, "username-display")
        self.assertIn(self.student_user["username"], username_display.text)
        
        # Déconnexion
        self.logout()
        
        # Vérifier que nous sommes redirigés vers la page de connexion
        current_url = self.driver.current_url
        self.assertEqual(current_url, f"{BASE_URL}/login.html")
    
    def test_4_failed_login(self):
        """Vérifier le comportement en cas d'échec de connexion"""
        self.driver.get(f"{BASE_URL}/login.html")
        
        # Attendre que le formulaire de connexion soit chargé
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        
        # Remplir le formulaire avec des identifiants incorrects
        username_field = self.driver.find_element(By.ID, "username")
        password_field = self.driver.find_element(By.ID, "password")
        
        username_field.clear()
        username_field.send_keys("utilisateur_inexistant")
        
        password_field.clear()
        password_field.send_keys("mauvais_mot_de_passe")
        
        # Soumettre le formulaire
        self.driver.find_element(By.CLASS_NAME, "btn-login").click()
        
        # Attendre que le message d'erreur apparaisse
        WebDriverWait(self.driver, 5).until(
            EC.visibility_of_element_located((By.ID, "error-message"))
        )
        
        # Vérifier que le message d'erreur est affiché
        error_message = self.driver.find_element(By.ID, "error-message")
        self.assertTrue(error_message.is_displayed())
    
    def test_5_admin_access_admin_page(self):
        """Vérifier qu'un administrateur peut accéder à la page d'administration"""
        # Connexion en tant qu'administrateur
        success = self.login(self.admin_user["username"], self.admin_user["password"])
        self.assertTrue(success, "La connexion a échoué")
        
        # Accéder à la page d'administration
        self.driver.get(f"{BASE_URL}/admin.html")
        
        # Vérifier que la page d'administration est chargée
        WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.CLASS_NAME, "users-table"))
        )
        
        # Vérifier la présence du tableau des utilisateurs
        users_table = self.driver.find_element(By.CLASS_NAME, "users-table")
        self.assertIsNotNone(users_table)
        
        # Déconnexion
        self.logout()
    
    def test_6_student_cannot_access_admin_page(self):
        """Vérifier qu'un étudiant ne peut pas accéder à la page d'administration"""
        # Connexion en tant qu'étudiant
        success = self.login(self.student_user["username"], self.student_user["password"])
        self.assertTrue(success, "La connexion a échoué")
        
        # Tenter d'accéder à la page d'administration
        self.driver.get(f"{BASE_URL}/admin.html")
        
        # Attendre un moment pour voir la redirection
        time.sleep(2)
        
        # Vérifier que nous sommes redirigés vers la page d'accès refusé
        current_url = self.driver.current_url
        self.assertEqual(current_url, f"{BASE_URL}/access-denied.html")
        
        # Déconnexion (depuis la page d'accès refusé)
        self.driver.find_element(By.ID, "back-to-home").click()
        
        # Attendre d'être redirigé vers la page d'accueil
        WebDriverWait(self.driver, 5).until(
            lambda driver: driver.current_url == f"{BASE_URL}/index.html"
        )
        
        self.logout()
    
    def test_7_user_role_display(self):
        """Vérifier que le rôle de l'utilisateur s'affiche correctement"""
        roles = [
            {"role": "admin", "username": self.admin_user["username"], "password": self.admin_user["password"]},
            {"role": "teacher", "username": self.teacher_user["username"], "password": self.teacher_user["password"]},
            {"role": "student", "username": self.student_user["username"], "password": self.student_user["password"]}
        ]
        
        for role_info in roles:
            # Connexion
            success = self.login(role_info["username"], role_info["password"])
            self.assertTrue(success, f"La connexion a échoué pour {role_info['role']}")
            
            # Vérifier l'affichage du rôle
            role_element = self.driver.find_element(By.ID, "user-role")
            role_badge = role_element.find_element(By.CLASS_NAME, "role-badge")
            
            if role_info["role"] == "admin":
                self.assertIn("Administrateur", role_badge.text)
            elif role_info["role"] == "teacher":
                self.assertIn("Enseignant", role_badge.text)
            else:
                self.assertIn("Étudiant", role_badge.text)
            
            # Déconnexion avant de passer au rôle suivant
            self.logout()

if __name__ == "__main__":
    unittest.main()
