#!/usr/bin/env python3
"""
Script de test pour vérifier la création de NodePort
"""
import requests
import json

def test_nodeport_creation():
    """Test de création d'un déploiement avec NodePort"""
    
    # URL de l'API
    url = "http://localhost/api/v1/k8s/deployments"
    
    # Paramètres pour créer un déploiement simple avec NodePort
    params = {
        'name': 'test-nodeport',
        'image': 'nginx:latest',
        'replicas': 1,
        'namespace': 'labondemand-custom',
        'create_service': True,
        'service_port': 80,
        'service_target_port': 80,
        'service_type': 'NodePort',
        'deployment_type': 'custom',
        'cpu_request': '100m',
        'cpu_limit': '500m',
        'memory_request': '128Mi',
        'memory_limit': '512Mi'
    }
    
    try:
        print("=== Test de création de déploiement avec NodePort ===")
        print(f"URL: {url}")
        print(f"Paramètres: {json.dumps(params, indent=2)}")
        
        # Faire la requête
        response = requests.post(url, params=params)
        
        print(f"\n=== Réponse ===")
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        if response.headers.get('content-type', '').startswith('application/json'):
            try:
                data = response.json()
                print(f"Response JSON: {json.dumps(data, indent=2)}")
                
                # Vérifier si le NodePort est présent
                if 'service_info' in data and 'node_port' in data['service_info']:
                    node_port = data['service_info']['node_port']
                    print(f"\n✅ NodePort trouvé: {node_port}")
                else:
                    print(f"\n❌ NodePort manquant dans la réponse")
                    
            except json.JSONDecodeError as e:
                print(f"Erreur de parsing JSON: {e}")
                print(f"Response text: {response.text}")
        else:
            print(f"Response text: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"Erreur de requête: {e}")
    except Exception as e:
        print(f"Erreur inattendue: {e}")

if __name__ == "__main__":
    test_nodeport_creation()
