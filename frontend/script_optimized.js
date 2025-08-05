// Importation du gestionnaire d'authentification
import authManager from './js/auth.js';

document.addEventListener('DOMContentLoaded', async () => {
    // Vérifier l'authentification avant de continuer
    const isAuthenticated = await authManager.init();
    if (!isAuthenticated) return;
    
    // --- Éléments DOM et variables globales ---
    const views = document.querySelectorAll('.view');
    const showLaunchViewBtn = document.getElementById('show-launch-view-btn');
    const serviceCards = document.querySelectorAll('.service-card:not(.disabled)');
    const backBtns = document.querySelectorAll('.back-btn');
    const configForm = document.getElementById('config-form');
    const activeLabsList = document.getElementById('active-labs-list');
    const noLabsMessage = document.querySelector('.no-labs-message');
    const statusContent = document.getElementById('status-content');
    const statusActions = document.querySelector('.status-actions');
    const refreshPodsBtn = document.getElementById('refresh-pods');
    const refreshDeploymentsBtn = document.getElementById('refresh-deployments');
    const apiStatusEl = document.getElementById('api-status');
    const k8sSectionToggle = document.getElementById('k8s-section-toggle');
    const k8sResources = document.getElementById('k8s-resources');
    const userGreeting = document.getElementById('user-greeting');
    const logoutBtn = document.getElementById('logout-btn');

    // URL de base de l'API
    const API_BASE_URL = '';
    const API_V1 = `${API_BASE_URL}/api/v1`;
    
    let labCounter = 0;
    const deploymentCheckTimers = new Map();

    // --- Section collapsible pour Kubernetes ---
    if (k8sSectionToggle) {
        k8sSectionToggle.addEventListener('click', () => {
            k8sSectionToggle.classList.toggle('active');
            k8sResources.classList.toggle('active');
        });
    }

    // --- Initialiser les informations utilisateur ---
    function initUserInfo() {
        const userInfo = authManager.getUserInfo();
        if (userGreeting && userInfo) {
            userGreeting.textContent = `Bonjour, ${userInfo.username}`;
        }
        
        if (logoutBtn) {
            logoutBtn.addEventListener('click', async () => {
                await authManager.logout();
            });
        }
        
        // Ajuster l'interface selon le rôle
        if (authManager.isAdmin() || authManager.isTeacher()) {
            const k8sSection = document.querySelector('.collapsible-section');
            if (k8sSection) k8sSection.style.display = 'block';
        } else {
            const k8sSection = document.querySelector('.collapsible-section');
            if (k8sSection) k8sSection.style.display = 'none';
        }
    }

    // --- API et utilitaires ---
    async function checkApiStatus() {
        try {
            const response = await fetch(`${API_V1}/status`);
            if (response.ok) {
                const data = await response.json();
                apiStatusEl.textContent = `API v${data.version} connectée`;
                apiStatusEl.classList.add('online');
                apiStatusEl.classList.remove('offline');
                return true;
            }
            throw new Error('Réponse API non OK');
        } catch (error) {
            console.error('Erreur de connexion à l\'API:', error);
            apiStatusEl.textContent = 'API non disponible';
            apiStatusEl.classList.add('offline');
            apiStatusEl.classList.remove('online');
            return false;
        }
    }

    // Fonction générique pour les appels API
    async function apiCall(endpoint, options = {}) {
        try {
            const response = await fetch(`${API_V1}${endpoint}`, {
                credentials: 'include',
                ...options
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Erreur HTTP ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error(`Erreur API [${endpoint}]:`, error);
            throw error;
        }
    }

    // --- Fonctions de rendu K8s consolidées ---
    async function renderK8sList(endpoint, elementId, transformer, filterFn = null) {
        const element = document.getElementById(elementId);
        if (!element) return;
        
        try {
            const data = await apiCall(endpoint);
            const items = data[Object.keys(data)[0]] || [];
            const filteredItems = filterFn ? items.filter(filterFn) : items;
            
            if (filteredItems.length === 0) {
                element.innerHTML = '<div class="no-items-message">Aucun élément trouvé</div>';
                return;
            }
            
            element.innerHTML = transformer(filteredItems);
        } catch (error) {
            element.innerHTML = '<div class="error-message">Erreur lors du chargement</div>';
        }
    }

    // Transformers pour les différents types d'éléments
    const namespaceTransformer = (namespaces) => {
        const listItems = namespaces.map(ns => {
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
            
            return `<div class="list-group-item"><i class="fas ${icon}"></i> ${ns} ${typeLabel}</div>`;
        }).join('');
        
        return `<div class="list-group">${listItems}</div>`;
    };

    const podsTransformer = (pods) => {
        return `
            <table class="k8s-table">
                <thead>
                    <tr><th>Nom</th><th>Namespace</th><th>IP</th><th>Actions</th></tr>
                </thead>
                <tbody>
                    ${pods.map(pod => `
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
    };

    const deploymentsTransformer = (deployments) => {
        return `
            <table class="k8s-table">
                <thead>
                    <tr><th>Nom</th><th>Namespace</th><th>Type</th><th>Actions</th></tr>
                </thead>
                <tbody>
                    ${deployments.map(dep => {
                        const type = dep.namespace.includes('jupyter') ? 'Jupyter' : 
                                   dep.namespace.includes('vscode') ? 'VSCode' : 'Custom';
                        return `
                            <tr>
                                <td><i class="fas fa-cube"></i> ${dep.name}</td>
                                <td>${dep.namespace}</td>
                                <td><span class="type-badge ${type.toLowerCase()}">${type}</span></td>
                                <td class="action-cell">
                                    <button class="btn btn-primary btn-view-deployment" 
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
    };

    // Fonctions de rendu simplifiées
    const fetchAndRenderNamespaces = () => renderK8sList(
        '/get-namespaces', 
        'namespaces-list', 
        namespaceTransformer,
        ns => ns.startsWith('labondemand-') || ns === 'default'
    );

    const fetchAndRenderPods = () => renderK8sList(
        '/get-pods',
        'pods-list',
        podsTransformer,
        pod => pod.namespace.startsWith('labondemand-') || pod.namespace === 'default'
    );

    const fetchAndRenderDeployments = () => renderK8sList(
        '/get-labondemand-deployments',
        'deployments-list',
        deploymentsTransformer
    );

    // --- Navigation ---
    function showView(viewId) {
        views.forEach(view => view.classList.remove('active'));
        const targetView = document.getElementById(viewId);
        if (targetView) {
            targetView.classList.add('active');
        }
    }

    // --- Gestion des labs ---
    function addLabCard(labDetails) {
        if (noLabsMessage) noLabsMessage.style.display = 'none';

        const card = document.createElement('div');
        card.classList.add('card', 'lab-card', labDetails.ready ? 'lab-ready' : 'lab-pending');
        card.id = labDetails.id;
        card.dataset.namespace = labDetails.namespace;

        const statusIndicator = labDetails.ready 
            ? '<span class="status-indicator ready"><i class="fas fa-check-circle"></i> Prêt</span>'
            : '<span class="status-indicator pending"><i class="fas fa-spinner fa-spin"></i> En préparation...</span>';

        card.innerHTML = `
            <h3><i class="${labDetails.icon}"></i> ${labDetails.name} ${statusIndicator}</h3>
            <ul class="lab-details">
                <li><i class="fas fa-tag"></i> <span>Nom: ${labDetails.id}</span></li>
                <li><i class="fas fa-project-diagram"></i> <span>Namespace: ${labDetails.namespace}</span></li>
                <li><i class="fas fa-microchip"></i> <span>CPU: ${labDetails.cpu}</span></li>
                <li><i class="fas fa-memory"></i> <span>RAM: ${labDetails.ram}</span></li>
            </ul>
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

        // Événements
        card.querySelector('.btn-details').addEventListener('click', (e) => {
            showDeploymentDetails(e.currentTarget.getAttribute('data-namespace'), e.currentTarget.getAttribute('data-id'));
        });

        card.querySelector('.stop-lab-btn').addEventListener('click', (e) => {
            stopLab(e.currentTarget.getAttribute('data-id'), e.currentTarget.getAttribute('data-namespace'));
        });

        // Démarrer la vérification si nécessaire
        if (!labDetails.ready) {
            checkDeploymentReadiness(labDetails.namespace, labDetails.id);
        }
    }

    // --- Event listeners consolidés ---
    function setupEventListeners() {
        // Navigation
        if (showLaunchViewBtn) {
            showLaunchViewBtn.addEventListener('click', () => showView('launch-view'));
        }

        backBtns.forEach(btn => {
            btn.addEventListener('click', () => showView('dashboard-view'));
        });

        // Services
        serviceCards.forEach(card => {
            card.addEventListener('click', (e) => {
                const serviceType = e.currentTarget.dataset.service;
                selectService(serviceType);
            });
        });

        // Refresh buttons
        if (refreshPodsBtn) refreshPodsBtn.addEventListener('click', fetchAndRenderPods);
        if (refreshDeploymentsBtn) refreshDeploymentsBtn.addEventListener('click', fetchAndRenderDeployments);

        // Formulaire de configuration
        if (configForm) {
            configForm.addEventListener('submit', handleFormSubmit);
        }

        // Event delegation pour les boutons dynamiques
        document.addEventListener('click', handleDynamicButtons);
    }

    // Gestionnaire d'événements délégués
    function handleDynamicButtons(e) {
        if (e.target.closest('.btn-delete-pod')) {
            const btn = e.target.closest('.btn-delete-pod');
            deletePod(btn.dataset.name, btn.dataset.namespace);
        }
        
        if (e.target.closest('.btn-delete-deployment')) {
            const btn = e.target.closest('.btn-delete-deployment');
            deleteDeployment(btn.dataset.name, btn.dataset.namespace);
        }
        
        if (e.target.closest('.btn-view-deployment')) {
            const btn = e.target.closest('.btn-view-deployment');
            showDeploymentDetails(btn.dataset.namespace, btn.dataset.name);
        }
    }

    // --- Fonctions utilitaires réduites ---
    async function deletePod(name, namespace) {
        if (confirm(`Supprimer le pod ${name} ?`)) {
            try {
                await apiCall(`/delete-pod/${namespace}/${name}`, { method: 'DELETE' });
                fetchAndRenderPods();
            } catch (error) {
                alert(`Erreur: ${error.message}`);
            }
        }
    }

    async function deleteDeployment(name, namespace) {
        if (confirm(`Supprimer le déploiement ${name} ?`)) {
            try {
                await apiCall(`/delete-deployment/${namespace}/${name}?delete_service=true`, { method: 'DELETE' });
                fetchAndRenderDeployments();
            } catch (error) {
                alert(`Erreur: ${error.message}`);
            }
        }
    }

    async function stopLab(labId, namespace) {
        if (confirm(`Arrêter le laboratoire "${labId}" ?`)) {
            try {
                await apiCall(`/delete-deployment/${namespace}/${labId}?delete_service=true`, { method: 'DELETE' });
                
                const labCard = document.getElementById(labId);
                if (labCard) labCard.remove();
                
                fetchAndRenderDeployments();
                
                if (activeLabsList.children.length === 0 && noLabsMessage) {
                    noLabsMessage.style.display = 'block';
                }
            } catch (error) {
                alert(`Erreur: ${error.message}`);
            }
        }
    }

    // --- Placeholder pour les fonctions spécialisées (à implémenter selon les besoins) ---
    function selectService(serviceType) { /* TODO */ }
    function handleFormSubmit(e) { /* TODO */ }
    function showDeploymentDetails(namespace, name) { /* TODO */ }
    function checkDeploymentReadiness(namespace, name) { /* TODO */ }

    // --- Initialisation ---
    async function init() {
        initUserInfo();
        setupEventListeners();
        
        const apiConnected = await checkApiStatus();
        if (apiConnected) {
            await Promise.all([
                fetchAndRenderNamespaces(),
                fetchAndRenderPods(), 
                fetchAndRenderDeployments()
            ]);
        }
        
        // Afficher la vue dashboard
        showView('dashboard-view');
    }

    // Lancer l'application
    init();
});
