#!/usr/bin/env python3
"""
Script de lancement des tests LabOnDemand
Principe KISS : Tests essentiels uniquement
"""
import unittest
import os

def run_auth_tests():
    """Exécute uniquement les tests d'authentification essentiels"""
    print("\n=== Tests d'authentification ===\n")
    
    # Charger les tests
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.dirname(__file__), pattern="test_auth.py")
    
    # Exécuter les tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

def main():
    """Point d'entrée principal"""
    print("🧪 Tests LabOnDemand (version simplifiée)")
    print("=" * 40)
    
    success = run_auth_tests()
    
    print("\n" + "=" * 40)
    if success:
        print("✅ Tous les tests ont réussi!")
        return True
    else:
        print("❌ Certains tests ont échoué.")
        return False

if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
