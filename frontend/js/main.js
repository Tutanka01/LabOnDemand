// Configuration
const API_URL = ''; // URL vide pour utiliser les chemins relatifs via le proxy Nginx

// Éléments du DOM
const apiStatus = document.getElementById('api-status');
const namespacesList = document.getElementById('namespaces-list');
const podsList = document.getElementById('pods-list');
const createPodForm = document.getElementById('create-pod-form');
const createPodResult = document.getElementById('create-pod-result');
const refreshPodsButton = document.getElementById('refresh-pods');
const deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));
const confirmDeleteButton = document.getElementById('confirm-delete');

// Variables globales
let podToDelete = null;

// Fonctions pour les interactions avec l'API
async function fetchWithTimeout(url, options = {}, timeout = 5000) {
    try {
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), timeout);
        const response = await fetch(url, {
            ...options,
            signal: controller.signal
        });
        clearTimeout(id);
        return response;
    } catch (error) {
        if (error.name === 'AbortError') {
            throw new Error('Request timed out');
        }
        throw error;
    }
}

async function checkApiStatus() {
    try {
        const response = await fetchWithTimeout(`${API_URL}/api/v1/status`);
        if (response.ok) {
            const data = await response.json();
            apiStatus.textContent = `API en ligne - ${data.status} (version ${data.version})`;
            apiStatus.className = 'online';
            return true;
        } else {
            throw new Error('API returned an error');
        }
    } catch (error) {
        apiStatus.textContent = 'API hors ligne - Vérifiez que le serveur API est démarré';
        apiStatus.className = 'offline';
        console.error('API status check failed:', error);
        return false;
    }
}

async function fetchNamespaces() {
    try {
        const response = await fetch(`${API_URL}/api/v1/get-namespaces`);
        if (!response.ok) throw new Error('Failed to fetch namespaces');
        
        const data = await response.json();
        return data.namespaces;
    } catch (error) {
        console.error('Error fetching namespaces:', error);
        return [];
    }
}

async function fetchPods() {
    try {
        const response = await fetch(`${API_URL}/api/v1/get-pods`);
        if (!response.ok) throw new Error('Failed to fetch pods');
        
        const data = await response.json();
        return data.pods || [];
    } catch (error) {
        console.error('Error fetching pods:', error);
        return [];
    }
}

async function createPod(name, image, namespace = 'default') {
    try {
        const url = `${API_URL}/api/v1/create-pod?name=${encodeURIComponent(name)}&image=${encodeURIComponent(image)}&namespace=${encodeURIComponent(namespace)}`;
        const response = await fetch(url, { method: 'POST' });
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to create pod');
        }
        
        return { success: true, message: data.message };
    } catch (error) {
        console.error('Error creating pod:', error);
        return { success: false, message: error.message };
    }
}

async function deletePod(namespace, name) {
    try {
        const url = `${API_URL}/api/v1/delete-pod/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`;
        const response = await fetch(url, { method: 'DELETE' });
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to delete pod');
        }
        
        return { success: true, message: data.message };
    } catch (error) {
        console.error('Error deleting pod:', error);
        return { success: false, message: error.message };
    }
}

// Fonctions d'affichage
function displayNamespaces(namespaces) {
    if (namespaces.length === 0) {
        namespacesList.innerHTML = '<p>Aucun namespace trouvé.</p>';
        return;
    }
    
    let html = '<ul class="list-group">';
    namespaces.forEach(namespace => {
        html += `<li class="list-group-item">${namespace}</li>`;
    });
    html += '</ul>';
    
    namespacesList.innerHTML = html;
}

function displayPods(pods) {
    if (pods.length === 0) {
        podsList.innerHTML = '<p>Aucun pod trouvé.</p>';
        return;
    }
    
    let html = `
        <div class="table-responsive">
            <table class="table table-striped table-hover">
                <thead>
                    <tr>
                        <th>Nom</th>
                        <th>Namespace</th>
                        <th>IP</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    pods.forEach(pod => {
        html += `
            <tr>
                <td>${pod.name || 'N/A'}</td>
                <td>${pod.namespace || 'N/A'}</td>
                <td>${pod.ip || 'N/A'}</td>
                <td>
                    <div class="pod-controls">
                        <button class="btn btn-sm btn-danger delete-pod" 
                            data-name="${pod.name}" 
                            data-namespace="${pod.namespace}">
                            Supprimer
                        </button>
                    </div>
                </td>
            </tr>
        `;
    });
    
    html += `
                </tbody>
            </table>
        </div>
    `;
    
    podsList.innerHTML = html;
    
    // Ajouter les écouteurs d'événements pour les boutons de suppression
    document.querySelectorAll('.delete-pod').forEach(button => {
        button.addEventListener('click', function() {
            const name = this.getAttribute('data-name');
            const namespace = this.getAttribute('data-namespace');
            showDeleteConfirmation(namespace, name);
        });
    });
}

function showNotification(element, message, isSuccess) {
    const notificationClass = isSuccess ? 'success' : 'error';
    element.innerHTML = `<div class="notification ${notificationClass}">${message}</div>`;
    
    // Effacer la notification après 5 secondes
    setTimeout(() => {
        element.innerHTML = '';
    }, 5000);
}

function showDeleteConfirmation(namespace, name) {
    podToDelete = { namespace, name };
    document.querySelector('#deleteModal .modal-body').textContent = 
        `Êtes-vous sûr de vouloir supprimer le pod "${name}" du namespace "${namespace}" ?`;
    deleteModal.show();
}

// Chargement initial
async function loadInitialData() {
    const isApiAvailable = await checkApiStatus();
    if (!isApiAvailable) return;
    
    // Charger les namespaces
    const namespaces = await fetchNamespaces();
    displayNamespaces(namespaces);
    
    // Charger les pods
    const pods = await fetchPods();
    displayPods(pods);
}

// Gestionnaires d'événements
createPodForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const name = document.getElementById('pod-name').value;
    const image = document.getElementById('pod-image').value;
    const namespace = document.getElementById('pod-namespace').value || 'default';
    
    createPodResult.innerHTML = '<div class="notification">Création en cours...</div>';
    
    const result = await createPod(name, image, namespace);
    showNotification(createPodResult, result.message, result.success);
    
    if (result.success) {
        // Réinitialiser le formulaire
        document.getElementById('pod-name').value = '';
        // Actualiser la liste des pods
        const pods = await fetchPods();
        displayPods(pods);
    }
});

refreshPodsButton.addEventListener('click', async function() {
    refreshPodsButton.disabled = true;
    refreshPodsButton.textContent = 'Chargement...';
    
    const pods = await fetchPods();
    displayPods(pods);
    
    refreshPodsButton.disabled = false;
    refreshPodsButton.textContent = 'Rafraîchir';
});

confirmDeleteButton.addEventListener('click', async function() {
    if (!podToDelete) return;
    
    const { namespace, name } = podToDelete;
    deleteModal.hide();
    
    const result = await deletePod(namespace, name);
    showNotification(podsList.parentNode, result.message, result.success);
    
    if (result.success) {
        // Actualiser la liste des pods
        const pods = await fetchPods();
        displayPods(pods);
    }
    
    // Réinitialiser
    podToDelete = null;
});

// Démarrer le chargement au chargement de la page
document.addEventListener('DOMContentLoaded', loadInitialData);

// Vérifier périodiquement l'état de l'API
setInterval(checkApiStatus, 30000);  // Vérifier toutes les 30 secondes