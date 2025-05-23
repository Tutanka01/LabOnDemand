#!/usr/bin/env python3
# filepath: c:\Users\zhiri\Nextcloud\mo\Projects\LabOnDemand\backend\tests\run_tests.py
import unittest
import os
import sys
import time
import subprocess
import argparse

def run_backend_tests():
    """Exécute les tests d'API backend"""
    print("\n=== Exécution des tests d'API backend ===\n")
    
    # Charger les tests
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.dirname(__file__), pattern="test_auth.py")
    
    # Exécuter les tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

def run_ui_tests():
    """Exécute les tests d'interface utilisateur"""
    print("\n=== Exécution des tests d'interface utilisateur ===\n")
    
    # Charger les tests
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.dirname(__file__), pattern="test_ui.py")
    
    # Exécuter les tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

def ensure_dependencies():
    """Vérifie et installe les dépendances nécessaires pour les tests"""
    required_packages = ['selenium', 'requests']
    
    print("\n=== Vérification des dépendances ===\n")
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"✅ {package} est déjà installé")
        except ImportError:
            print(f"⚠️ Installation de {package}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            print(f"✅ {package} a été installé")
    
    print("\nToutes les dépendances sont installées!")
    
def check_server_running():
    """Vérifie si le serveur est en cours d'exécution"""
    import requests
    
    print("\n=== Vérification du serveur ===\n")
    
    try:
        response = requests.get("http://localhost:8000/api/v1/status")
        if response.status_code == 200:
            print("✅ Le serveur est en cours d'exécution")
            return True
    except:
        pass
    
    print("⚠️ Le serveur ne semble pas être en cours d'exécution")
    
    # Demander à l'utilisateur s'il souhaite continuer
    user_input = input("Voulez-vous continuer quand même ? (y/n): ")
    return user_input.lower() == 'y'

def main():
    parser = argparse.ArgumentParser(description='Exécuter les tests pour LabOnDemand')
    parser.add_argument('--all', action='store_true', help='Exécuter tous les tests')
    parser.add_argument('--backend', action='store_true', help='Exécuter uniquement les tests backend')
    parser.add_argument('--ui', action='store_true', help='Exécuter uniquement les tests d\'interface utilisateur')
    parser.add_argument('--skip-deps', action='store_true', help='Ignorer la vérification des dépendances')
    parser.add_argument('--skip-server-check', action='store_true', help='Ignorer la vérification du serveur')
    
    args = parser.parse_args()
    
    # Si aucune option n'est spécifiée, exécuter tous les tests
    if not args.backend and not args.ui:
        args.all = True
    
    if not args.skip_deps:
        ensure_dependencies()
    
    if not args.skip_server_check:
        if not check_server_running():
            print("Tests annulés. Assurez-vous que le serveur est en cours d'exécution.")
            return
    
    success = True
    
    if args.all or args.backend:
        backend_success = run_backend_tests()
        success = success and backend_success
    
    if args.all or args.ui:
        ui_success = run_ui_tests()
        success = success and ui_success
    
    # Résumé des résultats
    print("\n=== Résumé des tests ===\n")
    
    if success:
        print("✅ Tous les tests ont réussi!")
    else:
        print("❌ Certains tests ont échoué. Consultez les journaux pour plus de détails.")
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
