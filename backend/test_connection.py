"""
Script de test de connexion simple
Principe KISS : test basique de l'authentification
"""
import requests
import json

def test_connection():
    """Test de connexion basique"""
    base_url = "http://localhost:8000"
    
    print("🧪 Test de connexion LabOnDemand")
    print("=" * 40)
    
    # Test 1: Vérifier que l'API répond
    try:
        response = requests.get(f"{base_url}/")
        if response.status_code == 200:
            print("✅ API accessible")
        else:
            print(f"❌ API inaccessible: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        return False
    
    # Test 2: Vérifier le health check
    try:
        response = requests.get(f"{base_url}/api/v1/health")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Base de données: {data.get('database', 'unknown')}")
            print(f"✅ Utilisateurs: {data.get('users', 'unknown')}")
        else:
            print(f"❌ Health check échoué: {response.status_code}")
    except Exception as e:
        print(f"⚠️  Health check non disponible: {e}")
    
    # Test 3: Test de connexion admin
    try:
        login_data = {
            "username": "admin",
            "password": "admin123"
        }
        
        response = requests.post(
            f"{base_url}/api/v1/auth/login",
            json=login_data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Connexion admin réussie")
            print(f"   Utilisateur: {data['user']['username']}")
            print(f"   Rôle: {data['user']['role']}")
            return True
        else:
            print(f"❌ Connexion admin échouée: {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Erreur: {error_data.get('message', 'Inconnue')}")
            except:
                print(f"   Réponse: {response.text[:100]}...")
            return False
            
    except Exception as e:
        print(f"❌ Erreur lors du test de connexion: {e}")
        return False

def test_frontend_endpoints():
    """Test des endpoints utilisés par le frontend"""
    base_url = "http://localhost:8000"
    
    print("\n🎯 Test des endpoints frontend")
    print("=" * 40)
    
    # Test /api/v1/auth/me sans authentification
    try:
        response = requests.get(f"{base_url}/api/v1/auth/me")
        if response.status_code == 401:
            print("✅ Endpoint /auth/me protégé correctement")
        else:
            print(f"⚠️  Endpoint /auth/me: status {response.status_code}")
    except Exception as e:
        print(f"❌ Erreur test /auth/me: {e}")
    
    # Test des templates
    try:
        response = requests.get(f"{base_url}/api/v1/k8s/templates")
        if response.status_code == 401:
            print("✅ Endpoint /templates protégé correctement")
        else:
            print(f"⚠️  Endpoint /templates: status {response.status_code}")
    except Exception as e:
        print(f"❌ Erreur test /templates: {e}")

if __name__ == "__main__":
    success = test_connection()
    test_frontend_endpoints()
    
    print("\n" + "=" * 40)
    if success:
        print("✅ Tous les tests sont passés!")
        print("🚀 Vous pouvez maintenant accéder à l'interface:")
        print("   http://localhost:8000/login.html")
        print("   Identifiants: admin / admin123")
    else:
        print("❌ Certains tests ont échoué")
        print("💡 Vérifiez que l'API est démarrée")
