// Importation du gestionnaire d'authentification
import authManager from './js/auth.js';

document.addEventListener('DOMContentLoaded', async () => {
    // Vérifier l'authentification avant de continuer
    const isAuthenticated = await authManager.init();
    if (!isAuthenticated) return; // L'utilisateur sera redirigé vers la page de connexion
    
    // --- Éléments DOM et variables globales ---
    const views = document.querySelectorAll('.view');
    const showLaunchViewBtn = document.getElementById('show-launch-view-btn');
    const serviceCards = document.querySelectorAll('.service-card:not(.disabled)');
    const backBtns = document.querySelectorAll('.back-btn');
    const configForm = document.getElementById('config-form');
    const activeLabsList = document.getElementById('active-labs-list');
    const noLabsMessage = document.querySelector('.no-labs-message');
    const configServiceName = document.getElementById('config-service-name');
    const serviceTypeInput = document.getElementById('service-type');
    const serviceIconInput = document.getElementById('service-icon-class');
    const deploymentTypeInput = document.getElementById('deployment-type');
    const jupyterOptions = document.getElementById('jupyter-options');
    const customDeploymentOptions = document.getElementById('custom-deployment-options');
    const statusContent = document.getElementById('status-content');
    const statusActions = document.querySelector('.status-actions');
    const refreshPodsBtn = document.getElementById('refresh-pods');
    const refreshDeploymentsBtn = document.getElementById('refresh-deployments');
    const apiStatusEl = document.getElementById('api-status');
    const k8sSectionToggle = document.getElementById('k8s-section-toggle');
    const k8sResources = document.getElementById('k8s-resources');
    const userGreeting = document.getElementById('user-greeting');
    const logoutBtn = document.getElementById('logout-btn');

    // URL de base de l'API (à adapter selon votre configuration)
    const API_BASE_URL = ''; // Vide pour les requêtes relatives
    const API_V1 = `${API_BASE_URL}/api/v1`;

    // Compteur pour les labs (utilisé pour les demos uniquement)
    let labCounter = 0;

    // --- Section collapsible pour Kubernetes ---
    if (k8sSectionToggle) {
        k8sSectionToggle.addEventListener('click', () => {
            k8sSectionToggle.classList.toggle('active');
            k8sResources.classList.toggle('active');
        });
    }    // --- Initialiser les informations utilisateur ---
    function initUserInfo() {
        // Mettre à jour le message de bienvenue
        userGreeting.textContent = `Bonjour, ${authManager.getUserDisplayName()}`;
        
        // Ajouter une icône selon le rôle
        let roleIcon = '';
        switch (authManager.getUserRole()) {
            case 'admin':
                roleIcon = '<i class="fas fa-user-shield"></i>';
                break;
            case 'teacher':
                roleIcon = '<i class="fas fa-chalkboard-teacher"></i>';
                break;
            case 'student':
                roleIcon = '<i class="fas fa-user-graduate"></i>';
                break;
            default:
                roleIcon = '<i class="fas fa-user"></i>';
        }
        userGreeting.innerHTML += ` ${roleIcon}`;
        
        // Configurer le bouton de déconnexion
        logoutBtn.addEventListener('click', async () => {
            await authManager.logout();
        });
        
        // Ajuster l'interface selon le rôle
        if (authManager.isAdmin() || authManager.isTeacher()) {
            // Afficher la section Kubernetes pour les admins et enseignants
            document.querySelector('.collapsible-section').style.display = 'block';
        } else {
            // Masquer la section Kubernetes pour les étudiants
            document.querySelector('.collapsible-section').style.display = 'none';
        }
    }

    // --- Vérifie la connexion avec l'API ---
    async function checkApiStatus() {
        try {
            const response = await fetch(`${API_V1}/status`);
            if (response.ok) {
                const data = await response.json();
                apiStatusEl.textContent = `API v${data.version} connectée`;
                apiStatusEl.classList.add('online');
                apiStatusEl.classList.remove('offline');
                return true;
            } else {
                throw new Error('Réponse API non OK');
            }
        } catch (error) {
            console.error('Erreur de connexion à l\'API:', error);
            apiStatusEl.textContent = 'API non disponible';
            apiStatusEl.classList.add('offline');
            apiStatusEl.classList.remove('online');
            return false;
        }
    }

    // --- Fonctions de Rendu des listes K8s ---
    async function fetchAndRenderNamespaces() {
        const namespacesListEl = document.getElementById('namespaces-list');
        
        try {
            const response = await fetch(`${API_V1}/get-namespaces`);
            if (!response.ok) throw new Error('Erreur lors de la récupération des namespaces');
            
            const data = await response.json();
            const namespaces = data.namespaces || [];
            
            // Filtre pour n'afficher que les namespaces LabOnDemand
            const labNamespaces = namespaces.filter(ns => 
                ns.startsWith('labondemand-') || ns === 'default'
            );
            
            if (labNamespaces.length === 0) {
                namespacesListEl.innerHTML = '<div class="no-items-message">Aucun namespace trouvé</div>';
                return;
            }
            
            const listItems = labNamespaces.map(ns => {
                // Ajouter une icône spécifique selon le type de namespace
                let icon = "fa-project-diagram";
                let typeLabel = "";
                
                if (ns === "labondemand-jupyter") {
                    icon = "fa-brands fa-python";
                    typeLabel = '<span class="namespace-type jupyter">Jupyter</span>';
                } else if (ns === "labondemand-vscode") {
                    icon = "fa-solid fa-code";
                    typeLabel = '<span class="namespace-type vscode">VSCode</span>';
                } else if (ns === "labondemand-custom") {
                    icon = "fa-solid fa-cube";
                    typeLabel = '<span class="namespace-type custom">Custom</span>';
                }
                
                return `
                    <div class="list-group-item">
                        <i class="fas ${icon}"></i> ${ns} ${typeLabel}
                    </div>
                `;
            }).join('');
            
            namespacesListEl.innerHTML = `<div class="list-group">${listItems}</div>`;
        } catch (error) {
            console.error('Erreur:', error);
            namespacesListEl.innerHTML = '<div class="error-message">Erreur lors du chargement des namespaces</div>';
        }
    }

    async function fetchAndRenderPods() {
        const podsListEl = document.getElementById('pods-list');
        
        try {
            const response = await fetch(`${API_V1}/get-pods`);
            if (!response.ok) throw new Error('Erreur lors de la récupération des pods');
            
            const data = await response.json();
            const pods = data.pods || [];
            
            // Filtre pour n'afficher que les pods dans les namespaces LabOnDemand
            const labPods = pods.filter(pod => 
                pod.namespace.startsWith('labondemand-') || 
                pod.namespace === 'default'
            );
            
            if (labPods.length === 0) {
                podsListEl.innerHTML = '<div class="no-items-message">Aucun pod trouvé</div>';
                return;
            }
            
            podsListEl.innerHTML = `
                <table class="k8s-table">
                    <thead>
                        <tr>
                            <th>Nom</th>
                            <th>Namespace</th>
                            <th>IP</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${labPods.map(pod => `
                            <tr>
                                <td><i class="fas fa-cube"></i> ${pod.name}</td>
                                <td>${pod.namespace}</td>
                                <td>${pod.ip || 'N/A'}</td>
                                <td class="action-cell">
                                    <button class="btn btn-danger btn-delete-pod" 
                                            data-name="${pod.name}" 
                                            data-namespace="${pod.namespace}">
                                        <i class="fas fa-trash-alt"></i>
                                    </button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
            
            // Ajouter des écouteurs pour les boutons de suppression
            document.querySelectorAll('.btn-delete-pod').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const name = e.currentTarget.getAttribute('data-name');
                    const namespace = e.currentTarget.getAttribute('data-namespace');
                    
                    if (confirm(`Êtes-vous sûr de vouloir supprimer le pod ${name} ?`)) {
                        try {
                            const response = await fetch(`${API_V1}/delete-pod/${namespace}/${name}`, {
                                method: 'DELETE'
                            });
                            
                            if (response.ok) {
                                alert(`Pod ${name} supprimé avec succès`);
                                fetchAndRenderPods(); // Rafraîchir la liste
                            } else {
                                const error = await response.json();
                                alert(`Erreur: ${error.detail || 'Échec de la suppression'}`);
                            }
                        } catch (error) {
                            console.error('Erreur:', error);
                            alert('Erreur réseau lors de la suppression du pod');
                        }
                    }
                });
            });
        } catch (error) {
            console.error('Erreur:', error);
            podsListEl.innerHTML = '<div class="error-message">Erreur lors du chargement des pods</div>';
        }
    }

    async function fetchAndRenderDeployments() {
        const deploymentsListEl = document.getElementById('deployments-list');
        
        try {
            // Utiliser le nouvel endpoint qui ne récupère que les déploiements LabOnDemand
            const response = await fetch(`${API_V1}/get-labondemand-deployments`);
            if (!response.ok) throw new Error('Erreur lors de la récupération des déploiements');
            
            const data = await response.json();
            const deployments = data.deployments || [];
            
            if (deployments.length === 0) {
                deploymentsListEl.innerHTML = '<div class="no-items-message">Aucun déploiement trouvé</div>';
                return;
            }
            
            deploymentsListEl.innerHTML = `
                <table class="k8s-table">
                    <thead>
                        <tr>
                            <th>Nom</th>
                            <th>Namespace</th>
                            <th>Type</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${deployments.map(dep => {
                            // Définir une icône basée sur le type de déploiement
                            let icon = "fa-layer-group";
                            let typeBadge = "";
                            
                            switch (dep.type) {
                                case "jupyter":
                                    icon = "fa-brands fa-python";
                                    typeBadge = '<span class="type-badge jupyter">Jupyter</span>';
                                    break;
                                case "vscode":
                                    icon = "fa-solid fa-code";
                                    typeBadge = '<span class="type-badge vscode">VSCode</span>';
                                    break;
                                case "custom":
                                    icon = "fa-solid fa-cube";
                                    typeBadge = '<span class="type-badge custom">Custom</span>';
                                    break;
                            }
                            
                            return `
                                <tr>
                                    <td><i class="fas ${icon}"></i> ${dep.name}</td>
                                    <td>${dep.namespace}</td>
                                    <td>${typeBadge}</td>
                                    <td class="action-cell">
                                        <button class="btn btn-secondary btn-view-deployment" 
                                                data-name="${dep.name}" 
                                                data-namespace="${dep.namespace}">
                                            <i class="fas fa-eye"></i>
                                        </button>
                                        <button class="btn btn-danger btn-delete-deployment" 
                                                data-name="${dep.name}" 
                                                data-namespace="${dep.namespace}">
                                            <i class="fas fa-trash-alt"></i>
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            `;
            
            // Écouteurs pour voir les détails d'un déploiement
            document.querySelectorAll('.btn-view-deployment').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const name = e.currentTarget.getAttribute('data-name');
                    const namespace = e.currentTarget.getAttribute('data-namespace');
                    showDeploymentDetails(namespace, name);
                });
            });
            
            // Écouteurs pour supprimer un déploiement
            document.querySelectorAll('.btn-delete-deployment').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const name = e.currentTarget.getAttribute('data-name');
                    const namespace = e.currentTarget.getAttribute('data-namespace');
                    
                    if (confirm(`Êtes-vous sûr de vouloir supprimer le déploiement ${name} ?`)) {
                        try {
                            const response = await fetch(`${API_V1}/delete-deployment/${namespace}/${name}?delete_service=true`, {
                                method: 'DELETE'
                            });
                            
                            if (response.ok) {
                                alert(`Déploiement ${name} supprimé avec succès`);
                                fetchAndRenderDeployments(); // Rafraîchir la liste
                                // Également mettre à jour les lab cards qui pourraient correspondre
                                refreshActiveLabs();
                            } else {
                                const error = await response.json();
                                alert(`Erreur: ${error.detail || 'Échec de la suppression'}`);
                            }
                        } catch (error) {
                            console.error('Erreur:', error);
                            alert('Erreur réseau lors de la suppression du déploiement');
                        }
                    }
                });
            });
        } catch (error) {
            console.error('Erreur:', error);
            deploymentsListEl.innerHTML = '<div class="error-message">Erreur lors du chargement des déploiements</div>';
        }
    }

    // Fonction pour montrer les détails d'un déploiement
    async function showDeploymentDetails(namespace, name) {
        const modal = document.getElementById('deployment-details-modal');
        const modalContent = document.getElementById('deployment-details-content');
        
        // Afficher le modal et son spinner de chargement
        modal.classList.add('show');
        modalContent.innerHTML = `
            <div class="loading-spinner">
                <i class="fas fa-spinner fa-spin"></i>
                <p>Chargement des détails...</p>
            </div>
        `;
        
        try {
            const response = await fetch(`${API_V1}/get-deployment-details/${namespace}/${name}`);
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Erreur lors de la récupération des détails');
            }
            
            const data = await response.json();
            
            // Formater les données pour l'affichage
            let accessUrlsHtml = '';
            if (data.access_urls && data.access_urls.length > 0) {
                accessUrlsHtml = `
                    <h4>URLs d'accès</h4>
                    <ul class="access-urls-list">
                        ${data.access_urls.map(url => `
                            <li>
                                <a href="${url.url}" target="_blank">
                                    <i class="fas fa-external-link-alt"></i> ${url.url}
                                </a> (Service: ${url.service}, NodePort: ${url.node_port})
                            </li>
                        `).join('')}
                    </ul>
                `;
            } else {
                accessUrlsHtml = `<p>Aucune URL d'accès disponible pour ce déploiement.</p>`;
            }
            
            // Construire le HTML des détails du déploiement
            modalContent.innerHTML = `
                <h3>Déploiement: ${data.deployment.name}</h3>
                <div class="deployment-details">
                    <div class="deployment-info">                        <h4>Informations générales</h4>
                        <ul>
                            <li><strong>Namespace:</strong> ${data.deployment.namespace}</li>
                            <li><strong>Image:</strong> ${data.deployment.image || 'N/A'}</li>
                            <li>
                                <strong>Réplicas:</strong> ${data.deployment.replicas} 
                                <span class="replica-status ${data.deployment.available_replicas > 0 ? 'ready' : 'pending'}">
                                    (${data.deployment.available_replicas || 0} disponible(s))
                                </span>
                            </li>
                        </ul>
                        
                        ${data.deployment.available_replicas > 0 ? `
                            <div class="app-availability ready">
                                <i class="fas fa-check-circle app-availability-icon"></i>
                                <span class="app-availability-text">L'application est prête à être utilisée</span>
                            </div>
                        ` : `
                            <div class="app-availability pending">
                                <i class="fas fa-hourglass-half app-availability-icon"></i>
                                <span class="app-availability-text">L'application est en cours d'initialisation</span>
                            </div>
                        `}
                    </div>
                    
                    <div class="access-section">
                        ${accessUrlsHtml}
                    </div>
                    
                    <div class="pods-section">
                        <h4>Pods (${data.pods.length})</h4>
                        ${data.pods.length > 0 ? `
                            <table class="k8s-table">
                                <thead>
                                    <tr>
                                        <th>Nom</th>
                                        <th>Node</th>
                                        <th>IP</th>
                                        <th>Statut</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${data.pods.map(pod => `
                                        <tr>
                                            <td>${pod.name}</td>
                                            <td>${pod.node_name || 'N/A'}</td>
                                            <td>${pod.pod_ip || 'N/A'}</td>
                                            <td>${pod.status || 'N/A'}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        ` : `<p>Aucun pod trouvé pour ce déploiement.</p>`}
                    </div>
                    
                    <div class="services-section">
                        <h4>Services (${data.services.length})</h4>
                        ${data.services.length > 0 ? `
                            <table class="k8s-table">
                                <thead>
                                    <tr>
                                        <th>Nom</th>
                                        <th>Type</th>
                                        <th>Cluster IP</th>
                                        <th>Ports</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${data.services.map(svc => `
                                        <tr>
                                            <td>${svc.name}</td>
                                            <td>${svc.type}</td>
                                            <td>${svc.cluster_ip || 'N/A'}</td>
                                            <td>
                                                ${svc.ports.map(port => {
                                                    let portInfo = `${port.port} → ${port.target_port}`;
                                                    if (port.node_port) {
                                                        portInfo += ` (NodePort: ${port.node_port})`;
                                                    }
                                                    return portInfo;
                                                }).join('<br>')}
                                            </td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        ` : `<p>Aucun service trouvé pour ce déploiement.</p>`}
                    </div>
                </div>
            `;
        } catch (error) {
            console.error('Erreur:', error);
            modalContent.innerHTML = `
                <div class="error-message">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Erreur lors du chargement des détails: ${error.message}</p>
                </div>
            `;
        }
    }

    // --- Navigation ---
    function showView(viewId) {
        views.forEach(view => {
            view.classList.remove('active-view');
        });
        
        const targetView = document.getElementById(viewId);
        if (targetView) {
            targetView.classList.add('active-view');
            
            // Si on montre la vue de configuration, s'assurer que le message d'erreur est effacé
            if (viewId === 'config-view') {
                const errorElement = document.querySelector('#config-form .error-message');
                if (errorElement) errorElement.remove();
            }
        }
    }

    if (showLaunchViewBtn) {
        showLaunchViewBtn.addEventListener('click', () => {
            showView('launch-view');
        });
    }

    backBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetViewId = btn.getAttribute('data-target');
            showView(targetViewId);
        });
    });

    // --- Service Selection ---
    serviceCards.forEach(card => {
        card.addEventListener('click', () => {
            const serviceName = card.getAttribute('data-service');
            const serviceIcon = card.getAttribute('data-icon');
            const deploymentType = card.getAttribute('data-deployment-type');
            
            configServiceName.textContent = serviceName;
            serviceTypeInput.value = serviceName;
            serviceIconInput.value = serviceIcon;
            deploymentTypeInput.value = deploymentType;

            // Définir un nom par défaut pour le déploiement
            const deploymentName = document.getElementById('deployment-name');
            deploymentName.value = `${serviceName.toLowerCase().replace(/\s+/g, '-')}-${Math.floor(Math.random() * 9000) + 1000}`;

            // Définir un namespace spécifique au type de service au lieu de "default"
            const namespaceInput = document.getElementById('namespace');
            switch(deploymentType) {
                case 'jupyter':
                    namespaceInput.value = 'labondemand-jupyter';
                    break;
                case 'vscode':
                    namespaceInput.value = 'labondemand-vscode';
                    break;
                case 'custom':
                    namespaceInput.value = 'labondemand-custom';
                    break;
                default:
                    namespaceInput.value = `labondemand-${serviceName.toLowerCase().replace(/\s+/g, '-')}`;
            }

            // Affichage des options selon le type de service
            jupyterOptions.style.display = (deploymentType === 'jupyter') ? 'block' : 'none';
            customDeploymentOptions.style.display = (deploymentType === 'custom') ? 'block' : 'none';

            // Reset form (optional)
            configForm.reset();

            // Rétablir le nom par défaut et le namespace
            document.getElementById('deployment-name').value = deploymentName.value;
            document.getElementById('namespace').value = namespaceInput.value;

            showView('config-view');
        });
    });

    // --- Form Submission (Real API Call) ---
    if (configForm) {
        configForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            // Récupérer les informations du formulaire
            const serviceName = serviceTypeInput.value;
            const serviceIcon = serviceIconInput.value;
            const deploymentType = deploymentTypeInput.value;
            const deploymentName = document.getElementById('deployment-name').value;
            const namespace = document.getElementById('namespace').value || 'labondemand-' + deploymentType; // Utiliser un namespace spécifique si non défini
            const cpu = document.getElementById('cpu').value;
            const ram = document.getElementById('ram').value;
            
            // Transformer les options CPU en valeurs réelles
            const cpuValues = {
                'very-low': { request: '100m', limit: '200m' },
                'low': { request: '250m', limit: '500m' },
                'medium': { request: '500m', limit: '1000m' },
                'high': { request: '1000m', limit: '2000m' },
                'very-high': { request: '2000m', limit: '4000m' }
            };
            
            // Transformer les options RAM en valeurs réelles
            const ramValues = {
                'very-low': { request: '128Mi', limit: '256Mi' },
                'low': { request: '256Mi', limit: '512Mi' },
                'medium': { request: '512Mi', limit: '1Gi' },
                'high': { request: '1Gi', limit: '2Gi' },
                'very-high': { request: '2Gi', limit: '4Gi' }
            };
            
            // Get service creation parameters for custom deployments
            let createService = false;
            let serviceType = 'ClusterIP';
            let servicePort = 80;
            let serviceTargetPort = 80;
            let image = 'nginx';
            let replicas = 1;
            
            if (deploymentType === 'custom') {
                createService = document.getElementById('create-service').checked;
                if (createService) {
                    serviceType = document.getElementById('service-type-select').value;
                    servicePort = parseInt(document.getElementById('service-port').value);
                    serviceTargetPort = parseInt(document.getElementById('service-target-port').value);
                }
                image = document.getElementById('deployment-image').value;
                replicas = parseInt(document.getElementById('deployment-replicas').value);
            } else if (deploymentType === 'jupyter') {
                // JupyterLab a des paramètres prédéfinis
                image = 'tutanka01/k8s:jupyter'; // Image prédéfinie côté serveur
                createService = true;
                serviceType = 'NodePort';
                servicePort = 8888;
                serviceTargetPort = 8888;
            } else if (deploymentType === 'vscode') {
                // VS Code a des paramètres prédéfinis
                image = 'tutanka01/k8s:vscode'; // Image prédéfinie côté serveur
                createService = true;
                serviceType = 'NodePort';
                servicePort = 8080;
                serviceTargetPort = 8080;
            }
            
            // Obtenir les valeurs réelles CPU/RAM
            const cpuRequest = cpuValues[cpu]?.request || '100m';
            const cpuLimit = cpuValues[cpu]?.limit || '500m';
            const memoryRequest = ramValues[ram]?.request || '128Mi';
            const memoryLimit = ramValues[ram]?.limit || '512Mi';
            
            // Get selected datasets (if Jupyter)
            let datasets = [];
            if (deploymentType === 'jupyter') {
                document.querySelectorAll('#jupyter-options input[type="checkbox"]:checked').forEach(cb => {
                    datasets.push(cb.value);
                });
            }

            // Afficher la vue de statut avec chargement
            showView('status-view');
            statusContent.innerHTML = `
                <i class="fas fa-spinner fa-spin status-icon loading"></i>
                <h2>Lancement de ${serviceName} en cours...</h2>
                <p>Votre environnement est en cours de préparation. Veuillez patienter.</p>
            `;
            statusActions.style.display = 'none'; // Cacher le bouton "Terminé" pendant le chargement

            try {
                // Construire les paramètres d'URL
                const params = new URLSearchParams({
                    name: deploymentName,
                    image: image,
                    replicas: replicas,
                    namespace: namespace,
                    create_service: createService,
                    service_port: servicePort,
                    service_target_port: serviceTargetPort,
                    service_type: serviceType,
                    deployment_type: deploymentType,
                    cpu_request: cpuRequest,
                    cpu_limit: cpuLimit,
                    memory_request: memoryRequest,
                    memory_limit: memoryLimit
                });
                
                // Appel API pour créer le déploiement
                const response = await fetch(`${API_V1}/create-deployment?${params.toString()}`, {
                    method: 'POST'
                });
                
                let data;
                // Vérifier le type de contenu avant de parser en JSON
                const contentType = response.headers.get("content-type");
                if (contentType && contentType.includes("application/json")) {
                    data = await response.json();
                } else {
                    // Si la réponse n'est pas JSON, obtenir le texte brut
                    const textResponse = await response.text();
                    throw new Error(`Réponse non-JSON reçue: ${textResponse}`);
                }
                
                if (!response.ok) {
                    throw new Error(data.detail || 'Erreur lors de la création du déploiement');
                }
                
                // Construire les infos du lab à ajouter au dashboard
                labCounter++;
                const labId = deploymentName;
                
                // Extraire l'URL d'accès des infos de retour (ou générer une URL factice en attendant de récupérer l'URL réelle)
                let accessUrl = '';
                let nodePort = '';
                
                // Parser la réponse pour extraire les informations d'accès
                if (data.message) {
                    // Essayer d'extraire un NodePort mentionné dans le message
                    const nodePortMatch = data.message.match(/NodePort: (\d+)/);
                    if (nodePortMatch && nodePortMatch[1]) {
                        nodePort = nodePortMatch[1];
                    }
                    
                    // Cherche une URL complète déjà formatée
                    const urlMatch = data.message.match(/(https?:\/\/[^\s"'<>]+)/);
                    if (urlMatch && urlMatch[1]) {
                        accessUrl = urlMatch[1];
                    }
                }
                
                if (!accessUrl && nodePort) {
                    // Si on n'a pas d'URL complète mais on a un NodePort, tenter de récupérer les détails
                    try {
                        const detailsResponse = await fetch(`${API_V1}/get-deployment-details/${namespace}/${deploymentName}`);
                        if (detailsResponse.ok) {
                            const detailsData = await detailsResponse.json();
                            if (detailsData.access_urls && detailsData.access_urls.length > 0) {
                                accessUrl = detailsData.access_urls[0].url;
                            }
                        }
                    } catch (error) {
                        console.error('Erreur lors de la récupération des détails:', error);
                    }
                    
                    // Fallback si on n'arrive pas à récupérer d'URL réelle
                    if (!accessUrl) {
                        accessUrl = `http://<IP_DU_NOEUD>:${nodePort}/`;
                    }
                } else if (!accessUrl) {
                    // URL générique selon le type de service
                    if (serviceType === 'NodePort' || serviceType === 'LoadBalancer') {
                        accessUrl = `http://<IP_EXTERNE>:${servicePort}/`;
                    } else {
                        accessUrl = `http://${deploymentName}-service:${servicePort}/`;
                    }
                }
                  // Ajouter le lab au dashboard avec l'état "en préparation"
                addLabCard({
                    id: labId,
                    name: serviceName,
                    icon: serviceIcon,
                    cpu: cpuValues[cpu]?.request || '100m',
                    ram: ramValues[ram]?.request || '128Mi',
                    datasets: datasets,
                    link: accessUrl,
                    namespace: namespace,
                    ready: false // Le déploiement commence toujours en état non prêt
                });

                // Mettre à jour la liste des déploiements
                fetchAndRenderDeployments();
                  // Afficher la réussite du déploiement initial (pas de l'application)
                statusContent.innerHTML = `
                    <i class="fas fa-circle-notch fa-spin status-icon"></i>
                    <h2>${serviceName} est en cours de préparation</h2>
                    <p>Votre environnement a été déployé avec succès, mais les conteneurs sont toujours en cours de démarrage.</p>
                    
                    <div class="app-availability pending">
                        <i class="fas fa-hourglass-half app-availability-icon"></i>
                        <span class="app-availability-text">L'application est en cours d'initialisation. Veuillez patienter...</span>
                    </div>
                    
                    <p>Vous serez notifié quand votre environnement sera prêt à être utilisé.</p>
                    <div class="api-response">${data.message}</div>
                    
                    ${accessUrl ? `
                        <p style="margin-top: 15px;">Une fois prêt, vous pourrez accéder à votre service via :</p>
                        <a class="access-link disabled">
                            <i class="fas fa-link"></i> ${accessUrl}
                            <span class="status-badge">En attente</span>
                        </a>
                    ` : ''}
                `;
                statusActions.style.display = 'block'; // Afficher le bouton "Terminé"
                
            } catch (error) {
                console.error('Erreur:', error);
                statusContent.innerHTML = `
                    <i class="fas fa-exclamation-triangle status-icon" style="color: var(--error-color);"></i>
                    <h2>Erreur lors du lancement</h2>
                    <p>Une erreur est survenue lors du déploiement de ${serviceName} :</p>
                    <div class="error-message">${error.message}</div>
                `;
                statusActions.style.display = 'block'; // Afficher le bouton "Terminé" même en cas d'erreur
            }
        });
    }

    // --- Manage Active Labs ---
    async function refreshActiveLabs() {
        try {
            // Récupérer la liste des déploiements LabOnDemand
            const response = await fetch(`${API_V1}/get-labondemand-deployments`);
            if (!response.ok) throw new Error('Erreur lors de la récupération des déploiements');
            
            const data = await response.json();
            const deployments = data.deployments || [];
            
            // Filtrer pour exclure les déploiements dans le namespace "default"
            const filteredDeployments = deployments.filter(dep => dep.namespace !== 'default');
            
            // Supprimer les labCards pour les déploiements qui n'existent plus
            const labCards = document.querySelectorAll('.lab-card');
            labCards.forEach(card => {
                const deploymentId = card.id;
                const deploymentNamespace = card.dataset.namespace;
                
                // Vérifier si le déploiement existe encore et n'est pas dans le namespace "default"
                const deploymentExists = filteredDeployments.some(d => 
                    d.name === deploymentId && d.namespace === deploymentNamespace
                );
                
                if (!deploymentExists) {
                    card.remove();
                }
            });
            
            // Vérifier si la liste est vide
            if (activeLabsList.children.length === 0 || 
                (activeLabsList.children.length === 1 && activeLabsList.children[0].classList.contains('no-labs-message'))) {
                if (noLabsMessage) noLabsMessage.style.display = 'block';
            } else {
                if (noLabsMessage) noLabsMessage.style.display = 'none';
            }
            
        } catch (error) {
            console.error('Erreur lors du rafraîchissement des labs actifs:', error);
        }
    }

    function addLabCard(labDetails) {
         if (noLabsMessage) {
             noLabsMessage.style.display = 'none'; // Hide "no labs" message
         }

        const card = document.createElement('div');
        card.classList.add('card', 'lab-card');
        // Ajouter une classe pour l'état initial (pending ou ready)
        card.classList.add(labDetails.ready ? 'lab-ready' : 'lab-pending');
        card.id = labDetails.id;
        card.dataset.namespace = labDetails.namespace;

        let datasetsHtml = '';
        if (labDetails.datasets && labDetails.datasets.length > 0) {
            datasetsHtml = `<li><i class="fas fa-database"></i> <span>Datasets: ${labDetails.datasets.join(', ')}</span></li>`;
        }

        // Déterminer l'indicateur d'état à afficher
        const statusIndicator = labDetails.ready 
            ? '<span class="status-indicator ready"><i class="fas fa-check-circle"></i> Prêt</span>'
            : '<span class="status-indicator pending"><i class="fas fa-spinner fa-spin"></i> En préparation...</span>';        card.innerHTML = `
            <h3><i class="${labDetails.icon}"></i> ${labDetails.name} ${statusIndicator}</h3>
            <ul class="lab-details">
                <li><i class="fas fa-tag"></i> <span>Nom: ${labDetails.id}</span></li>
                <li><i class="fas fa-project-diagram"></i> <span>Namespace: ${labDetails.namespace}</span></li>
                <li><i class="fas fa-microchip"></i> <span>CPU: ${labDetails.cpu}</span></li>
                <li><i class="fas fa-memory"></i> <span>RAM: ${labDetails.ram}</span></li>
                ${datasetsHtml}
            </ul>
            ${!labDetails.ready ? `
                <div class="app-availability pending" id="app-status-${labDetails.id}">
                    <i class="fas fa-hourglass-half app-availability-icon"></i>
                    <span class="app-availability-text">L'application est en cours d'initialisation</span>
                </div>
            ` : `
                <div class="app-availability ready" id="app-status-${labDetails.id}">
                    <i class="fas fa-check-circle app-availability-icon"></i>
                    <span class="app-availability-text">L'application est prête à être utilisée</span>
                </div>
            `}
            <div class="lab-actions">
                <a href="${labDetails.link}" target="_blank" class="btn btn-primary ${labDetails.ready ? '' : 'disabled'}" id="access-btn-${labDetails.id}">
                    <i class="fas fa-external-link-alt"></i> ${labDetails.ready ? 'Accéder' : 'En préparation...'}
                </a>
                <button class="btn btn-secondary btn-details" data-id="${labDetails.id}" data-namespace="${labDetails.namespace}">
                    <i class="fas fa-info-circle"></i> Détails
                </button>
                <button class="btn btn-danger stop-lab-btn" data-id="${labDetails.id}" data-namespace="${labDetails.namespace}">
                    <i class="fas fa-stop-circle"></i> Arrêter
                </button>
            </div>
        `;

        activeLabsList.appendChild(card);

        // Ajouter l'écouteur pour le bouton détails
        card.querySelector('.btn-details').addEventListener('click', (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            const namespace = e.currentTarget.getAttribute('data-namespace');
            showDeploymentDetails(namespace, id);
        });

        // Ajouter l'écouteur pour le bouton d'arrêt
        card.querySelector('.stop-lab-btn').addEventListener('click', (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            const namespace = e.currentTarget.getAttribute('data-namespace');
            stopLab(id, namespace);
        });
        
        // Si l'URL est incomplète/générique, on essaie de récupérer les détails pour avoir une URL réelle
        if (labDetails.link.includes('<IP_DU_NOEUD>') || labDetails.link.includes('<IP_EXTERNE>')) {
            fetchDeploymentAccessUrl(labDetails.namespace, labDetails.id);
        }
        
        // Si le déploiement n'est pas prêt, démarrer les vérifications périodiques
        if (!labDetails.ready) {
            checkDeploymentReadiness(labDetails.namespace, labDetails.id);
        }
    }
    
    // Fonction pour récupérer et mettre à jour l'URL d'accès à un déploiement
    async function fetchDeploymentAccessUrl(namespace, name) {
        try {
            const response = await fetch(`${API_V1}/get-deployment-details/${namespace}/${name}`);
            
            if (!response.ok) {
                throw new Error('Impossible de récupérer les détails du déploiement');
            }
            
            const data = await response.json();
            if (data.access_urls && data.access_urls.length > 0) {
                const accessUrl = data.access_urls[0].url;
                const accessBtn = document.getElementById(`access-btn-${name}`);
                if (accessBtn) {
                    accessBtn.href = accessUrl;
                }
            }
        } catch (error) {
            console.error(`Erreur lors de la récupération de l'URL d'accès pour ${name}:`, error);
        }
    }
    
    // Map pour stocker les timers de vérification des déploiements
    const deploymentCheckTimers = new Map();
    
    // Fonction pour vérifier périodiquement si un déploiement est prêt
    async function checkDeploymentReadiness(namespace, name, attempts = 0) {
        // Limiter à 60 tentatives (5 minutes si intervalle = 5s)
        const maxAttempts = 60;
        
        try {
            // Récupérer les détails du déploiement
            const response = await fetch(`${API_V1}/get-deployment-details/${namespace}/${name}`);
            if (!response.ok) {
                throw new Error('Impossible de récupérer les détails du déploiement');
            }
            
            const data = await response.json();
            const available = data.deployment.available_replicas > 0;
            const podsReady = data.pods.every(pod => pod.status === 'Running');
            
            console.log(`Vérification déploiement ${name}: available=${available}, podsReady=${podsReady}, tentative=${attempts+1}/${maxAttempts}`);
            
            // Si le déploiement est disponible et au moins un pod est prêt
            if (available && podsReady) {
                console.log(`Déploiement ${name} prêt !`);
                updateLabCardStatus(name, true, data);
                clearTimeout(deploymentCheckTimers.get(`${namespace}-${name}`));
                deploymentCheckTimers.delete(`${namespace}-${name}`);
                return;
            }
            
            // Continuer à vérifier sauf si max atteint
            if (attempts < maxAttempts) {
                const timerId = setTimeout(() => {
                    checkDeploymentReadiness(namespace, name, attempts + 1);
                }, 5000); // Vérifier toutes les 5 secondes
                
                deploymentCheckTimers.set(`${namespace}-${name}`, timerId);
            } else {
                console.log(`Nombre maximal de tentatives atteint pour ${name}`);
                // Informer l'utilisateur qu'il pourrait y avoir un problème
                updateLabCardStatus(name, false, data, true);
            }
        } catch (error) {
            console.error(`Erreur lors de la vérification du déploiement ${name}:`, error);
            // Continuer à vérifier sauf si max atteint
            if (attempts < maxAttempts) {
                const timerId = setTimeout(() => {
                    checkDeploymentReadiness(namespace, name, attempts + 1);
                }, 5000);
                deploymentCheckTimers.set(`${namespace}-${name}`, timerId);
            }
        }
    }
      // Fonction pour mettre à jour l'affichage d'un lab card en fonction de son état
    function updateLabCardStatus(deploymentId, isReady, deploymentData, timeout = false) {
        const card = document.getElementById(deploymentId);
        if (!card) return;
        
        // Mettre à jour les classes de la carte
        if (isReady) {
            card.classList.remove('lab-pending');
            card.classList.add('lab-ready');
            // Ajouter temporairement une classe pour mettre en évidence le changement
            card.classList.add('status-changed');
            setTimeout(() => card.classList.remove('status-changed'), 2000);
        } else if (timeout) {
            card.classList.remove('lab-pending');
            card.classList.add('lab-error');
        }
        
        // Récupérer et mettre à jour l'indicateur d'état
        const statusIndicator = card.querySelector('.status-indicator');
        if (statusIndicator) {
            if (isReady) {
                statusIndicator.className = 'status-indicator ready';
                statusIndicator.innerHTML = '<i class="fas fa-check-circle"></i> Prêt';
            } else if (timeout) {
                statusIndicator.className = 'status-indicator error';
                statusIndicator.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Problème de démarrage';
            }
        }
        
        // Mettre à jour l'indicateur de disponibilité de l'application
        const appStatus = document.getElementById(`app-status-${deploymentId}`);
        if (appStatus) {
            if (isReady) {
                appStatus.className = 'app-availability ready';
                appStatus.innerHTML = `
                    <i class="fas fa-check-circle app-availability-icon"></i>
                    <span class="app-availability-text">L'application est prête à être utilisée</span>
                `;
            } else if (timeout) {
                appStatus.className = 'app-availability error';
                appStatus.innerHTML = `
                    <i class="fas fa-exclamation-triangle app-availability-icon"></i>
                    <span class="app-availability-text">Problème de démarrage de l'application</span>
                `;
            }
        }
        
        // Mettre à jour le bouton d'accès
        const accessBtn = document.getElementById(`access-btn-${deploymentId}`);
        if (accessBtn) {
            if (isReady) {
                accessBtn.classList.remove('disabled');
                accessBtn.innerHTML = '<i class="fas fa-external-link-alt"></i> Accéder';
                
                // Si des URLs d'accès sont disponibles, mettre à jour l'URL du bouton
                if (deploymentData && deploymentData.access_urls && deploymentData.access_urls.length > 0) {
                    accessBtn.href = deploymentData.access_urls[0].url;
                }
            } else if (timeout) {
                accessBtn.innerHTML = '<i class="fas fa-exclamation-circle"></i> Vérifier les détails';
            }
        }
    }

    async function stopLab(labId, namespace) {
         // Demander confirmation
        if (confirm(`Êtes-vous sûr de vouloir arrêter le laboratoire "${labId}" ?`)) {
            try {
                // Appel API pour supprimer le déploiement
                const response = await fetch(`${API_V1}/delete-deployment/${namespace}/${labId}?delete_service=true`, {
                    method: 'DELETE'
                });
                
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Erreur lors de la suppression du déploiement');
                }
                
                // Supprimer la carte du tableau de bord
                const labCard = document.getElementById(labId);
                if (labCard) {
                    labCard.remove();
                    console.log(`Lab ${labId} arrêté avec succès.`);
                    
                    // Mettre à jour la liste des déploiements
                    fetchAndRenderDeployments();
                    
                    // Afficher le message "aucun lab" si nécessaire
                    if (activeLabsList.children.length === 0 || (activeLabsList.children.length === 1 && activeLabsList.children[0].classList.contains('no-labs-message'))) {
                        if (noLabsMessage) noLabsMessage.style.display = 'block';
                    }
                }
            } catch (error) {
                console.error('Erreur:', error);
                alert(`Erreur lors de l'arrêt du laboratoire: ${error.message}`);
            }
        }
    }

    // --- Modal Management ---
    document.querySelectorAll('.close-modal, .close-modal-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.modal.show').forEach(modal => {
                modal.classList.remove('show');
            });
        });
    });

    document.getElementById('cancel-delete').addEventListener('click', () => {
        document.getElementById('delete-modal').classList.remove('show');
    });

    // --- Initialisation ---
    async function init() {
        // Vérifier la connexion à l'API
        const apiConnected = await checkApiStatus();
        
        if (apiConnected) {
            // Charger les données K8s
            fetchAndRenderNamespaces();
            fetchAndRenderPods();
            fetchAndRenderDeployments();
            
            // Récupérer les déploiements existants pour les afficher comme labs actifs
            const response = await fetch(`${API_V1}/get-labondemand-deployments`);
            if (response.ok) {
                const data = await response.json();
                const deployments = data.deployments || [];
                
                // Filtrer pour exclure les déploiements dans le namespace "default"
                const filteredDeployments = deployments.filter(dep => dep.namespace !== 'default');
                
                // Pour chaque déploiement, récupérer les détails et créer une carte
                for (const deployment of filteredDeployments) {
                    try {
                        const detailsResponse = await fetch(`${API_V1}/get-deployment-details/${deployment.namespace}/${deployment.name}`);
                        if (detailsResponse.ok) {
                            const detailsData = await detailsResponse.json();
                            
                            // Déterminer l'icône et le nom du service selon le type
                            let serviceIcon = "fa-cube"; // Icône par défaut
                            let serviceName = "Application"; // Nom par défaut
                            
                            if (deployment.type === "jupyter") {
                                serviceIcon = "fa-brands fa-python";
                                serviceName = "Jupyter Notebook";
                            } else if (deployment.type === "vscode") {
                                serviceIcon = "fa-solid fa-code";
                                serviceName = "VS Code";
                            }
                            
                            // Déterminer l'URL d'accès
                            let accessUrl = '';
                            if (detailsData.access_urls && detailsData.access_urls.length > 0) {
                                accessUrl = detailsData.access_urls[0].url;
                            } else {
                                // URL générique fallback
                                accessUrl = `http://${deployment.name}-service`;
                            }
                            
                            // Vérifier si le déploiement est réellement prêt
                            const isReady = detailsData.deployment.available_replicas > 0 && 
                                          detailsData.pods.some(pod => pod.status === 'Running');
                            
                            // Ajouter la carte avec l'état de disponibilité correct
                            addLabCard({
                                id: deployment.name,
                                name: serviceName,
                                icon: serviceIcon,
                                cpu: 'N/A', // Ces informations ne sont pas directement disponibles
                                ram: 'N/A',
                                link: accessUrl,
                                namespace: deployment.namespace,
                                ready: isReady // Indiquer si le déploiement est prêt
                            });
                        }
                    } catch (error) {
                        console.error(`Erreur lors de la récupération des détails pour ${deployment.name}:`, error);
                    }
                }
            }
            
            // Ajouter des écouteurs pour les boutons de rafraîchissement
            if (refreshPodsBtn) {
                refreshPodsBtn.addEventListener('click', fetchAndRenderPods);
            }
            
            if (refreshDeploymentsBtn) {
                refreshDeploymentsBtn.addEventListener('click', fetchAndRenderDeployments);
            }
        } else {
            // Si l'API n'est pas accessible, afficher un message dans chaque section
            ['namespaces-list', 'pods-list', 'deployments-list'].forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.innerHTML = '<div class="error-message">API non disponible. Impossible de charger les données.</div>';
                }
            });
        }
        
        // Mise à jour de l'état initial pour la gestion des labs
        if (activeLabsList.children.length === 1 && activeLabsList.children[0].classList.contains('no-labs-message')) {
            // Gérer correctement l'état initial si le message "no-labs" est le seul enfant
        } else if (activeLabsList.children.length === 0) {
            if (noLabsMessage) noLabsMessage.style.display = 'block';
        } else {
            if (noLabsMessage) noLabsMessage.style.display = 'none';
        }
    }

    // Initialiser l'application
    init();

    // Afficher la vue dashboard au démarrage
    showView('dashboard-view');
});