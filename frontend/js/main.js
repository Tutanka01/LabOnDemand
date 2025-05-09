// Configuration
const API_URL = ''; // URL vide pour utiliser les chemins relatifs via le proxy Nginx

// Éléments du DOM
const apiStatus = document.getElementById('api-status');
const namespacesList = document.getElementById('namespaces-list');
const podsList = document.getElementById('pods-list');
const deploymentsList = document.getElementById('deployments-list');
const createPodForm = document.getElementById('create-pod-form');
const createPodResult = document.getElementById('create-pod-result');
const createDeploymentForm = document.getElementById('create-deployment-form');
const createDeploymentResult = document.getElementById('create-deployment-result');
const refreshPodsButton = document.getElementById('refresh-pods');
const refreshDeploymentsButton = document.getElementById('refresh-deployments');
const deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));
const confirmDeleteButton = document.getElementById('confirm-delete');
const deleteDeploymentModal = new bootstrap.Modal(document.getElementById('deleteDeploymentModal'));
const confirmDeleteDeploymentButton = document.getElementById('confirm-delete-deployment');
const createServiceCheckbox = document.getElementById('create-service');
const serviceOptions = document.getElementById('service-options');
const deploymentDetailsModal = new bootstrap.Modal(document.getElementById('deploymentDetailsModal'));
const deploymentDetailsContent = document.getElementById('deployment-details-content');
const deploymentTypeSelect = document.getElementById('deployment-type');
const customDeploymentOptions = document.getElementById('custom-deployment-options');
const vscodeDeploymentOptions = document.getElementById('vscode-deployment-options');
const jupyterDeploymentOptions = document.getElementById('jupyter-deployment-options');
const deploymentTypeInfo = document.getElementById('deployment-type-info');
const deploymentTypeDescription = document.getElementById('deployment-type-description');
const cpuPresetSelect = document.getElementById('cpu-preset');
const memoryPresetSelect = document.getElementById('memory-preset');
const vscodeCpuPresetSelect = document.getElementById('vscode-cpu-preset');
const vscodeMemoryPresetSelect = document.getElementById('vscode-memory-preset');
const jupyterCpuPresetSelect = document.getElementById('jupyter-cpu-preset');
const jupyterMemoryPresetSelect = document.getElementById('jupyter-memory-preset');

// Variables globales
let podToDelete = null;
let deploymentToDelete = null;
let deploymentTemplates = [];
let resourcePresets = {
    cpu: [],
    memory: []
};

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

async function fetchDeployments() {
    try {
        const response = await fetch(`${API_URL}/api/v1/get-deployments`);
        if (!response.ok) throw new Error('Failed to fetch deployments');
        
        const data = await response.json();
        return data.deployments || [];
    } catch (error) {
        console.error('Error fetching deployments:', error);
        return [];
    }
}

async function fetchDeploymentTemplates() {
    try {
        const response = await fetch(`${API_URL}/api/v1/get-deployment-templates`);
        if (!response.ok) throw new Error('Failed to fetch deployment templates');
        
        const data = await response.json();
        return data.templates || [];
    } catch (error) {
        console.error('Error fetching deployment templates:', error);
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

async function createDeployment(params = {}) {
    try {
        // Construire l'URL avec tous les paramètres disponibles
        let queryParams = Object.entries(params)
            .filter(([key, value]) => value !== undefined && value !== null)
            .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
            .join('&');
        
        const url = `${API_URL}/api/v1/create-deployment?${queryParams}`;
        
        const response = await fetch(url, { method: 'POST' });
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to create deployment');
        }
        
        return { success: true, message: data.message, deploymentType: data.deployment_type };
    } catch (error) {
        console.error('Error creating deployment:', error);
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

async function deleteDeployment(namespace, name) {
    try {
        const url = `${API_URL}/api/v1/delete-deployment/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`;
        const response = await fetch(url, { method: 'DELETE' });
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to delete deployment');
        }
        
        return { success: true, message: data.message };
    } catch (error) {
        console.error('Error deleting deployment:', error);
        return { success: false, message: error.message };
    }
}

async function fetchDeploymentDetails(namespace, name) {
    try {
        const response = await fetch(`${API_URL}/api/v1/get-deployment-details/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`);
        if (!response.ok) throw new Error('Failed to fetch deployment details');
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching deployment details:', error);
        return null;
    }
}

async function fetchResourcePresets() {
    try {
        const response = await fetch(`${API_URL}/api/v1/get-resource-presets`);
        if (!response.ok) throw new Error('Failed to fetch resource presets');
        
        return await response.json();
    } catch (error) {
        console.error('Error fetching resource presets:', error);
        // Retourner des préréglages par défaut en cas d'erreur
        return {
            cpu: [
                {"label": "Très faible (0.1 CPU)", "request": "100m", "limit": "200m"},
                {"label": "Faible (0.25 CPU)", "request": "250m", "limit": "500m"},
                {"label": "Moyen (0.5 CPU)", "request": "500m", "limit": "1000m"},
                {"label": "Élevé (1 CPU)", "request": "1000m", "limit": "2000m"},
                {"label": "Très élevé (2 CPU)", "request": "2000m", "limit": "4000m"}
            ],
            memory: [
                {"label": "Très faible (128 Mi)", "request": "128Mi", "limit": "256Mi"},
                {"label": "Faible (256 Mi)", "request": "256Mi", "limit": "512Mi"},
                {"label": "Moyen (512 Mi)", "request": "512Mi", "limit": "1Gi"},
                {"label": "Élevé (1 Gi)", "request": "1Gi", "limit": "2Gi"},
                {"label": "Très élevé (2 Gi)", "request": "2Gi", "limit": "4Gi"}
            ]
        };
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

function displayDeployments(deployments) {
    if (deployments.length === 0) {
        deploymentsList.innerHTML = '<p>Aucun déploiement trouvé.</p>';
        return;
    }
    
    let html = `
        <div class="table-responsive">
            <table class="table table-striped table-hover">
                <thead>
                    <tr>
                        <th>Nom</th>
                        <th>Namespace</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    deployments.forEach(deployment => {
        html += `
            <tr>
                <td>${deployment.name || 'N/A'}</td>
                <td>${deployment.namespace || 'N/A'}</td>
                <td>
                    <div class="deployment-controls">
                        <button class="btn btn-sm btn-info view-deployment-details" 
                            data-name="${deployment.name}" 
                            data-namespace="${deployment.namespace}">
                            Détails
                        </button>
                        <button class="btn btn-sm btn-danger delete-deployment" 
                            data-name="${deployment.name}" 
                            data-namespace="${deployment.namespace}">
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
    
    deploymentsList.innerHTML = html;
    
    // Ajouter les écouteurs d'événements pour les boutons de détails
    document.querySelectorAll('.view-deployment-details').forEach(button => {
        button.addEventListener('click', function() {
            const name = this.getAttribute('data-name');
            const namespace = this.getAttribute('data-namespace');
            showDeploymentDetails(namespace, name);
        });
    });
    
    // Ajouter les écouteurs d'événements pour les boutons de suppression
    document.querySelectorAll('.delete-deployment').forEach(button => {
        button.addEventListener('click', function() {
            const name = this.getAttribute('data-name');
            const namespace = this.getAttribute('data-namespace');
            showDeleteDeploymentConfirmation(namespace, name);
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

function showDeleteDeploymentConfirmation(namespace, name) {
    deploymentToDelete = { namespace, name };
    document.querySelector('#deleteDeploymentModal .modal-body').textContent = 
        `Êtes-vous sûr de vouloir supprimer le déploiement "${name}" du namespace "${namespace}" ? Cette action supprimera également tout service associé.`;
    deleteDeploymentModal.show();
}

// Fonction pour afficher les détails du déploiement
async function showDeploymentDetails(namespace, name) {
    // Afficher la modale avec un indicateur de chargement
    deploymentDetailsContent.innerHTML = `
        <div class="text-center">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Chargement...</span>
            </div>
            <p>Chargement des détails...</p>
        </div>
    `;
    deploymentDetailsModal.show();
    
    // Récupérer les détails du déploiement
    const details = await fetchDeploymentDetails(namespace, name);
    
    if (!details) {
        deploymentDetailsContent.innerHTML = `
            <div class="alert alert-danger">
                Impossible de récupérer les détails du déploiement "${name}".
            </div>
        `;
        return;
    }
    
    // Construire l'affichage des détails
    let html = `
        <div class="deployment-details">
            <h4>${details.deployment.name}</h4>
            <div class="row">
                <div class="col-md-6">
                    <h5>Informations du déploiement</h5>
                    <ul class="list-group mb-3">
                        <li class="list-group-item"><strong>Namespace:</strong> ${details.deployment.namespace}</li>
                        <li class="list-group-item"><strong>Image:</strong> ${details.deployment.image || 'N/A'}</li>
                        <li class="list-group-item"><strong>Réplicas:</strong> ${details.deployment.replicas} (disponibles: ${details.deployment.available_replicas || 0})</li>
                    </ul>
                </div>
                <div class="col-md-6">
                    <h5>Pods (${details.pods.length})</h5>
                    <ul class="list-group mb-3">
    `;
    
    // Ajouter les informations sur les pods
    details.pods.forEach(pod => {
        let nodeInfo = '';
        if (pod.node_name) {
            const internalIP = pod.node_addresses.find(addr => addr.type === 'InternalIP');
            const externalIP = pod.node_addresses.find(addr => addr.type === 'ExternalIP');
            nodeInfo = `<br><strong>Nœud:</strong> ${pod.node_name}`;
            if (internalIP) {
                nodeInfo += `<br><strong>IP interne du nœud:</strong> ${internalIP.address}`;
            }
            if (externalIP) {
                nodeInfo += `<br><strong>IP externe du nœud:</strong> ${externalIP.address}`;
            }
        }
        
        html += `
            <li class="list-group-item">
                <strong>Pod:</strong> ${pod.name}<br>
                <strong>IP du pod:</strong> ${pod.pod_ip || 'N/A'}<br>
                <strong>Statut:</strong> ${pod.status || 'N/A'}
                ${nodeInfo}
            </li>
        `;
    });
    
    html += `
                    </ul>
                </div>
            </div>
    `;
    
    // Ajouter les informations sur les services
    if (details.services && details.services.length > 0) {
        html += `
            <div class="row">
                <div class="col-12">
                    <h5>Services (${details.services.length})</h5>
                    <div class="table-responsive">
                        <table class="table table-bordered table-hover">
                            <thead>
                                <tr>
                                    <th>Nom</th>
                                    <th>Type</th>
                                    <th>Cluster IP</th>
                                    <th>Ports</th>
                                </tr>
                            </thead>
                            <tbody>
        `;
        
        details.services.forEach(service => {
            const portDetails = service.ports.map(port => {
                let portInfo = `${port.port} → ${port.target_port}`;
                if (port.node_port) {
                    portInfo += ` (NodePort: <strong class="text-danger">${port.node_port}</strong>)`;
                }
                return portInfo;
            }).join('<br>');
            
            html += `
                <tr>
                    <td>${service.name}</td>
                    <td>${service.type}</td>
                    <td>${service.cluster_ip || 'N/A'}</td>
                    <td>${portDetails}</td>
                </tr>
            `;
        });
        
        html += `
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    }
    
    // Ajouter les URL d'accès si elles existent
    if (details.access_urls && details.access_urls.length > 0) {
        html += `
            <div class="mt-4">
                <h5>URLs d'accès</h5>
                <div class="alert alert-success">
                    <p>Utilisez une des URLs suivantes pour accéder à votre application:</p>
                    <ul class="list-group">
        `;
        
        details.access_urls.forEach(url => {
            html += `
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        <a href="${url.url}" target="_blank">${url.url}</a>
                        <small>(via ${url.node})</small>
                    </div>
                    <span class="badge bg-primary">NodePort: ${url.node_port}</span>
                </li>
            `;
        });
        
        html += `
                    </ul>
                </div>
            </div>
        `;
    }
    
    html += `</div>`;
    
    // Mettre à jour le contenu de la modale
    deploymentDetailsContent.innerHTML = html;
}

// Fonction pour afficher/masquer les options de service
function toggleServiceOptions() {
    serviceOptions.style.display = createServiceCheckbox.checked ? 'block' : 'none';
}

// Fonction pour basculer entre les types de déploiement
function toggleDeploymentOptions() {
    const deploymentType = deploymentTypeSelect.value;
    
    // Masquer toutes les options
    customDeploymentOptions.classList.add('d-none');
    vscodeDeploymentOptions.classList.add('d-none');
    jupyterDeploymentOptions.classList.add('d-none');
    
    // Afficher les options selon le type de déploiement
    if (deploymentType === 'custom') {
        customDeploymentOptions.classList.remove('d-none');
    } else if (deploymentType === 'vscode') {
        vscodeDeploymentOptions.classList.remove('d-none');
    } else if (deploymentType === 'jupyter') {
        jupyterDeploymentOptions.classList.remove('d-none');
    }
    
    // Afficher les informations sur le type de déploiement
    const template = deploymentTemplates.find(t => t.id === deploymentType);
    if (template) {
        deploymentTypeDescription.textContent = template.description;
        deploymentTypeInfo.classList.remove('d-none');
    } else {
        deploymentTypeInfo.classList.add('d-none');
    }
}

// Chargement initial
async function loadInitialData() {
    const isApiAvailable = await checkApiStatus();
    if (!isApiAvailable) return;
    
    // Charger les templates de déploiement
    deploymentTemplates = await fetchDeploymentTemplates();
    toggleDeploymentOptions(); // Initialiser l'affichage selon le type sélectionné
    
    // Charger les préréglages de ressources
    resourcePresets = await fetchResourcePresets();
    
    // Charger les namespaces
    const namespaces = await fetchNamespaces();
    displayNamespaces(namespaces);
    
    // Charger les pods
    const pods = await fetchPods();
    displayPods(pods);
    
    // Charger les déploiements
    const deployments = await fetchDeployments();
    displayDeployments(deployments);
}

// Gestionnaires d'événements
createServiceCheckbox.addEventListener('change', toggleServiceOptions);
deploymentTypeSelect.addEventListener('change', toggleDeploymentOptions);

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

createDeploymentForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    
    // Récupérer les valeurs du formulaire selon le type de déploiement
    const deploymentType = deploymentTypeSelect.value;
    const name = document.getElementById('deployment-name').value;
    let params = {
        name,
        deployment_type: deploymentType
    };
    
    if (deploymentType === 'custom') {
        // Options pour un déploiement personnalisé
        const image = document.getElementById('deployment-image').value;
        const replicas = document.getElementById('deployment-replicas').value || 1;
        const namespace = document.getElementById('deployment-namespace').value || 'default';
        const createService = document.getElementById('create-service').checked;
        
        // Obtenir les valeurs des ressources en fonction des préréglages
        const cpuPresetIndex = cpuPresetSelect.selectedIndex;
        const memoryPresetIndex = memoryPresetSelect.selectedIndex;
        
        // Ressources CPU
        const cpuRequestValue = resourcePresets.cpu[cpuPresetIndex]?.request || "100m";
        const cpuLimitValue = resourcePresets.cpu[cpuPresetIndex]?.limit || "500m";
        
        // Ressources mémoire
        const memoryRequestValue = resourcePresets.memory[memoryPresetIndex]?.request || "128Mi";
        const memoryLimitValue = resourcePresets.memory[memoryPresetIndex]?.limit || "512Mi";
        
        // Ajouter les paramètres spécifiques
        params = {
            ...params,
            image,
            replicas,
            namespace,
            create_service: createService,
            cpu_request: cpuRequestValue,
            cpu_limit: cpuLimitValue,
            memory_request: memoryRequestValue,
            memory_limit: memoryLimitValue
        };
        
        // Si un service est demandé, ajouter ses options
        if (createService) {
            params.service_type = document.getElementById('service-type').value;
            params.service_port = document.getElementById('service-port').value;
            params.service_target_port = document.getElementById('service-target-port').value;
        }
    } else if (deploymentType === 'vscode') {
        // Options pour un déploiement VS Code
        const namespace = document.getElementById('vscode-namespace').value || 'default';
        
        // Obtenir les valeurs des ressources en fonction des préréglages
        const cpuPresetIndex = vscodeCpuPresetSelect.selectedIndex;
        const memoryPresetIndex = vscodeMemoryPresetSelect.selectedIndex;
        
        // Pour VS Code, on utilise directement l'index sélectionné
        const cpuIndex = cpuPresetIndex;
        const memoryIndex = memoryPresetIndex;
        
        // Ressources CPU - Utilisation directe de l'index sélectionné
        const cpuRequestValue = resourcePresets.cpu[cpuIndex]?.request || "250m";
        const cpuLimitValue = resourcePresets.cpu[cpuIndex]?.limit || "500m";
        
        // Ressources mémoire - Utilisation directe de l'index sélectionné
        const memoryRequestValue = resourcePresets.memory[memoryIndex]?.request || "256Mi";
        const memoryLimitValue = resourcePresets.memory[memoryIndex]?.limit || "512Mi";
        
        // Pour VS Code, certains paramètres sont définis par défaut dans le backend
        params = {
            ...params,
            namespace,
            image: "tutanka01/k8s:vscode", // Obligatoire de fournir une image même si le backend la remplace
            create_service: true,
            service_port: 80,
            service_target_port: 8080,
            service_type: 'NodePort',
            cpu_request: cpuRequestValue,
            cpu_limit: cpuLimitValue,
            memory_request: memoryRequestValue,
            memory_limit: memoryLimitValue
        };
    } else if (deploymentType === 'jupyter') {
        // Options pour un déploiement Jupyter Notebook
        const namespace = document.getElementById('jupyter-namespace').value || 'default';
        
        // Obtenir les valeurs des ressources en fonction des préréglages
        const cpuPresetIndex = jupyterCpuPresetSelect.selectedIndex;
        const memoryPresetIndex = jupyterMemoryPresetSelect.selectedIndex;
        
        // Pour Jupyter, on utilise directement l'index sélectionné
        const cpuIndex = cpuPresetIndex;
        const memoryIndex = memoryPresetIndex;
        
        // Ressources CPU
        const cpuRequestValue = resourcePresets.cpu[cpuIndex]?.request || "250m";
        const cpuLimitValue = resourcePresets.cpu[cpuIndex]?.limit || "500m";
        
        // Ressources mémoire - les notebooks ont besoin de plus de mémoire
        const memoryRequestValue = resourcePresets.memory[memoryIndex]?.request || "512Mi";
        const memoryLimitValue = resourcePresets.memory[memoryIndex]?.limit || "1Gi";  // Minimum 1Gi pour Jupyter
        
        // Pour Jupyter, certains paramètres sont définis par défaut
        params = {
            ...params,
            namespace,
            image: "tutanka01/k8s:jupyter", // Obligatoire de fournir une image même si le backend la remplace
            create_service: true,
            service_port: 80,
            service_target_port: 8888,
            service_type: 'NodePort',
            cpu_request: cpuRequestValue,
            cpu_limit: cpuLimitValue,
            memory_request: memoryRequestValue,
            memory_limit: memoryLimitValue
        };
    }
    
    createDeploymentResult.innerHTML = '<div class="notification">Création en cours...</div>';
    
    const result = await createDeployment(params);
    showNotification(createDeploymentResult, result.message, result.success);
    
    if (result.success) {
        // Réinitialiser le formulaire
        document.getElementById('deployment-name').value = '';
        // Actualiser la liste des déploiements
        const deployments = await fetchDeployments();
        displayDeployments(deployments);
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

refreshDeploymentsButton.addEventListener('click', async function() {
    refreshDeploymentsButton.disabled = true;
    refreshDeploymentsButton.textContent = 'Chargement...';
    
    const deployments = await fetchDeployments();
    displayDeployments(deployments);
    
    refreshDeploymentsButton.disabled = false;
    refreshDeploymentsButton.textContent = 'Rafraîchir';
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

confirmDeleteDeploymentButton.addEventListener('click', async function() {
    if (!deploymentToDelete) return;
    
    const { namespace, name } = deploymentToDelete;
    deleteDeploymentModal.hide();
    
    const result = await deleteDeployment(namespace, name);
    showNotification(deploymentsList.parentNode, result.message, result.success);
    
    if (result.success) {
        // Actualiser la liste des déploiements
        const deployments = await fetchDeployments();
        displayDeployments(deployments);
    }
    
    // Réinitialiser
    deploymentToDelete = null;
});

// Démarrer le chargement au chargement de la page
document.addEventListener('DOMContentLoaded', loadInitialData);

// Vérifier périodiquement l'état de l'API
setInterval(checkApiStatus, 30000);  // Vérifier toutes les 30 secondes