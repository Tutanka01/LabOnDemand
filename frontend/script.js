// Importation du gestionnaire d'authentification
import authManager from './js/auth.js';

document.addEventListener('DOMContentLoaded', async () => {
    // Vérifier l'authentification avant de continuer
    const isAuthenticated = await authManager.init();
    if (!isAuthenticated) return; // L'utilisateur sera redirigé vers la page de connexion
    
    // --- Éléments DOM et variables globales ---
    const views = document.querySelectorAll('.view');
    const showLaunchViewBtn = document.getElementById('show-launch-view-btn');
    const serviceCatalog = document.getElementById('service-catalog');
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
    const catalogSearch = document.getElementById('catalog-search');
    const tagFiltersEl = document.getElementById('tag-filters');
    const quotasContent = document.getElementById('quotas-content');
    const refreshQuotasBtn = document.getElementById('refresh-quotas');

    // URL de base de l'API (à adapter selon votre configuration)
    const API_BASE_URL = ''; // Vide pour les requêtes relatives
    const API_V1 = `${API_BASE_URL}/api/v1`;
    
    console.log('LabOnDemand Script - Corrections de filtrage des déploiements et gestion d\'erreurs améliorée');

    // Compteur pour les labs (utilisé pour les demos uniquement)
    let labCounter = 0;

    // --- UI: Toggle section Kubernetes ---
    if (k8sSectionToggle && k8sResources) {
        k8sSectionToggle.addEventListener('click', () => {
            k8sSectionToggle.classList.toggle('active');
            k8sResources.classList.toggle('active');
        });
    }

    // --- Auth UI: infos utilisateur + bouton logout ---
    function initUserInfo() {
        // Message de bienvenue
        if (userGreeting) {
            const name = authManager.getUserDisplayName();
            let roleIcon = '<i class="fas fa-user"></i>';
            const role = authManager.getUserRole();
            if (role === 'admin') roleIcon = '<i class="fas fa-user-shield"></i>';
            else if (role === 'teacher') roleIcon = '<i class="fas fa-chalkboard-teacher"></i>';
            else if (role === 'student') roleIcon = '<i class="fas fa-user-graduate"></i>';

            userGreeting.innerHTML = `Bonjour, ${name} ${roleIcon}`;
        }

        // Déconnexion
        if (logoutBtn) {
            // éviter de dupliquer les listeners si le script est rechargé
            logoutBtn.onclick = async () => {
                await authManager.logout();
            };
        }

        // Adapter l'UI selon le rôle: masquer la section K8s pour les étudiants
        const k8sSection = document.querySelector('.collapsible-section');
        if (k8sSection) {
            if (authManager.isAdmin() || authManager.isTeacher()) {
                k8sSection.style.display = 'block';
            } else {
                k8sSection.style.display = 'none';
            }
        }
    }

    // --- API: statut ---
    async function checkApiStatus() {
        try {
            const resp = await fetch(`${API_V1}/status`);
            if (!resp.ok) throw new Error('Statut API non OK');
            const data = await resp.json();
            if (apiStatusEl) {
                apiStatusEl.textContent = `API v${data.version} connectée`;
                apiStatusEl.classList.add('online');
                apiStatusEl.classList.remove('offline');
            }
            // Ping rapide de l'API Kubernetes pour savoir si on peut afficher la section K8s
            try {
                const ping = await fetch(`${API_V1}/k8s/ping`);
                if (!ping.ok) throw new Error('K8s KO');
                return { api: true, k8s: true };
            } catch (e) {
                console.warn('Kubernetes indisponible:', e.message || e);
                return { api: true, k8s: false };
            }
        } catch (err) {
            console.error("Erreur de connexion à l'API:", err);
            if (apiStatusEl) {
                apiStatusEl.textContent = 'API non disponible';
                apiStatusEl.classList.add('offline');
                apiStatusEl.classList.remove('online');
            }
            return { api: false, k8s: false };
        }
    }

    // --- Quotas: fetch + rendu ---
    async function fetchMyQuotas() {
        const resp = await fetch(`${API_V1}/quotas/me`, { credentials: 'include' });
        if (!resp.ok) throw new Error('Quotas indisponibles');
        return await resp.json();
    }
    function pct(part, whole) { return whole ? Math.min(100, Math.round((part / whole) * 100)) : 0; }
    function barClass(p) { return p < 70 ? 'pb-green' : (p < 90 ? 'pb-amber' : 'pb-red'); }
    function renderQuotasCard(data) {
        if (!quotasContent) return;
        const { limits, usage } = data || {};
        if (!limits || !usage) {
            quotasContent.innerHTML = `<div class="error-message"><i class="fas fa-exclamation-triangle"></i> Quotas indisponibles</div>`;
            return;
        }
        const rows = [
            { title: 'Applications', icon: 'fa-layer-group', used: usage.apps_used, max: limits.max_apps, unit: '' },
            { title: 'CPU', icon: 'fa-microchip', used: usage.cpu_m_used, max: limits.max_requests_cpu_m, unit: 'm' },
            { title: 'Mémoire', icon: 'fa-memory', used: usage.mem_mi_used, max: limits.max_requests_mem_mi, unit: 'Mi' },
        ];
        quotasContent.innerHTML = rows.map(r => {
            const p = pct(r.used, r.max);
            return `
            <div class="quota-item">
              <h4><i class="fas ${r.icon}"></i> ${r.title}</h4>
              <div class="quota-metric"><i class="fas fa-chart-bar"></i> ${r.used} / ${r.max} ${r.unit}</div>
              <div class="progress"><div class="progress-bar ${barClass(p)}" style="width:${p}%"></div></div>
              <div class="quota-legend">Reste: ${Math.max(r.max - r.used, 0)} ${r.unit}</div>
            </div>`;
        }).join('');
    }
    async function refreshQuotas() {
        if (!quotasContent) return;
        quotasContent.innerHTML = 'Chargement...';
        try { renderQuotasCard(await fetchMyQuotas()); }
        catch (e) { quotasContent.innerHTML = `<div class="error-message"><i class=\"fas fa-exclamation-triangle\"></i> ${e.message || 'Erreur quotas'}</div>`; }
    }
    if (refreshQuotasBtn) {
        refreshQuotasBtn.addEventListener('click', refreshQuotas);
        setInterval(() => { refreshQuotas(); }, 45000);
    }

    // --- Rendu des namespaces (admin/teacher) ---
    async function fetchAndRenderNamespaces() {
        const listEl = document.getElementById('namespaces-list');
        if (!listEl) return;
        try {
            const resp = await fetch(`${API_V1}/k8s/namespaces`);
            if (!resp.ok) throw new Error('Erreur lors de la récupération des namespaces');
            const data = await resp.json();
            const namespaces = (data.namespaces || []).filter(ns => ns.startsWith('labondemand-') || ns === 'default');
            if (namespaces.length === 0) {
                listEl.innerHTML = '<div class="no-items-message">Aucun namespace trouvé</div>';
                return;
            }
            const html = `
                <div class="list-group">
                    ${namespaces.map(ns => {
                        let icon = 'fa-project-diagram';
                        let badge = '';
                        if (ns.includes('jupyter')) { icon = 'fa-brands fa-python'; badge = '<span class="namespace-type jupyter">Jupyter</span>'; }
                        else if (ns.includes('vscode')) { icon = 'fa-solid fa-code'; badge = '<span class="namespace-type vscode">VSCode</span>'; }
                        else if (ns.includes('custom')) { icon = 'fa-solid fa-cube'; badge = '<span class="namespace-type custom">Custom</span>'; }
                        return `<div class="list-group-item"><i class="fas ${icon}"></i> ${ns} ${badge}</div>`;
                    }).join('')}
                </div>`;
            listEl.innerHTML = html;
        } catch (e) {
            console.error(e);
            listEl.innerHTML = '<div class="error-message">Erreur lors du chargement des namespaces</div>';
        }
    }

    // --- Fonctions de Rendu des listes K8s ---

    async function fetchAndRenderPods() {
        const podsListEl = document.getElementById('pods-list');
        
        try {
            const response = await fetch(`${API_V1}/k8s/pods`);
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
                            const response = await fetch(`${API_V1}/k8s/pods/${namespace}/${name}`, {
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
            // 1) Récupérer les métriques d’usage par application (facultatif)
            let usageIndex = {};
            try {
                const usageResp = await fetch(`${API_V1}/k8s/usage/my-apps`);
                if (usageResp.ok) {
                    const usageData = await usageResp.json();
                    (usageData.items || []).forEach(it => {
                        const key = `$${it.namespace}::$${it.name}`;
                        usageIndex[key] = it;
                    });
                }
            } catch (e) {
                // Ne pas bloquer si indisponible
            }
            window.__myAppsUsageIndex = usageIndex;

            // Utiliser l'endpoint spécialisé qui ne récupère que les déploiements LabOnDemand
            const response = await fetch(`${API_V1}/k8s/deployments/labondemand`);
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
                            <th>CPU</th>
                            <th>Mémoire</th>
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
                            
                            // Chercher les métriques d’usage pour cette app
                            const u = (window.__myAppsUsageIndex || {})[`$${dep.namespace}::$${dep.name}`] || null;
                            const cpuDisplay = u ? `${u.cpu_m} m` : 'N/A';
                            const memDisplay = u ? `${u.mem_mi} Mi` : 'N/A';
                            const srcBadge = u ? `<span class="usage-source ${u.source === 'live' ? 'live' : 'requests'}" title="${u.source === 'live' ? 'Mesures live (metrics-server)' : 'Estimation par requests'}">${u.source === 'live' ? 'Live' : 'Req'}</span>` : '';

                            return `
                                <tr>
                                    <td><i class="fas ${icon}"></i> ${dep.name}</td>
                                    <td>${dep.namespace}</td>
                                    <td>${typeBadge}</td>
                                    <td>${cpuDisplay} ${srcBadge}</td>
                                    <td>${memDisplay}</td>
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
                            const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}?delete_service=true`, {
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
            const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/details`);
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Erreur lors de la récupération des détails');
            }
            
            const data = await response.json();
            
            // Formater les données pour l'affichage
            let accessUrlsHtml = '';
            if (data.access_urls && data.access_urls.length > 0) {
                accessUrlsHtml = `
                    <h4>Accès à l'application</h4>
                    <ul class="access-urls-list">
                        ${data.access_urls.map(url => `
                            <li>
                                <a href="${url.url}" target="_blank">
                                    <i class="fas fa-external-link-alt"></i> ${url.label ? `${url.label} – ` : ''}${url.url}
                                </a> (exposé par: ${url.service}, NodePort: ${url.node_port})
                            </li>
                        `).join('')}
                    </ul>
                `;
            } else {
                accessUrlsHtml = `<p>Aucune URL d'accès disponible pour ce déploiement.</p>`;
            }
            
            // Construire le HTML des détails du déploiement avec un onglet Options
            modalContent.innerHTML = `
                <h3>Application: ${data.deployment.name}</h3>
                <div class="deployment-details">
                    <div class="deployment-info">
                        <div class="details-tabs">
                            <button class="tab-btn active" data-tab="infos"><i class="fas fa-info-circle"></i> Infos</button>
                            <button class="tab-btn" data-tab="options"><i class="fas fa-sliders-h"></i> Options</button>
                        </div>
                        <div class="tab-content" id="tab-infos">
                        <h4>Informations générales</h4>
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
                        <div class="tab-content" id="tab-options" style="display:none;">
                            <div class="options-panel">
                                <h4><i class="fas fa-key"></i> Identifiants & paramètres</h4>
                                <p class="muted">Retrouvez ici les identifiants générés pour votre application. Ne partagez pas ces informations.</p>
                                <div id="credentials-container" class="credentials-container">
                                    <button class="btn btn-secondary" id="load-credentials">
                                        <i class="fas fa-unlock"></i> Afficher les identifiants
                                    </button>
                                    <div id="credentials-content" class="credentials-content" style="display:none;"></div>
                                </div>
                                <hr>
                                <h4><i class="fas fa-terminal"></i> Console intégrée (beta)</h4>
                                <p class="muted">Terminal web directement dans votre pod (sans SSH). Accès limité à vos ressources LabOnDemand.</p>
                                <div class="terminal-controls">
                                   <label>Sélection du pod:
                                        <select id="terminal-pod-select"></select>
                                   </label>
                                   <button class="btn btn-secondary" id="open-terminal"><i class="fas fa-terminal"></i> Ouvrir</button>
                                   <button class="btn" id="close-terminal" style="display:none;"><i class="fas fa-times"></i> Fermer</button>
                                </div>
                                <div id="terminal-wrapper" style="display:none; border:1px solid var(--border-color); border-radius:8px; margin-top:10px;">
                                   <div id="xterm" style="height:320px; width:100%; background:#111;"></div>
                                </div>
                            </div>
                        </div>
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
                        <h4>Points d'exposition (${data.services.length})</h4>
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
                        ` : `<p>Aucun point d'exposition (Service Kubernetes) trouvé pour ce déploiement.</p>`}
                    </div>
                </div>
            `;

            // Gestion des tabs
            const tabBtns = modalContent.querySelectorAll('.tab-btn');
            const tabInfos = modalContent.querySelector('#tab-infos');
            const tabOptions = modalContent.querySelector('#tab-options');
            tabBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    tabBtns.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    const t = btn.dataset.tab;
                    tabInfos.style.display = (t === 'infos') ? 'block' : 'none';
                    tabOptions.style.display = (t === 'options') ? 'block' : 'none';
                });
            });

            // Bouton pour charger les credentials
            const loadBtn = modalContent.querySelector('#load-credentials');
            const credContent = modalContent.querySelector('#credentials-content');
            const podSelect = modalContent.querySelector('#terminal-pod-select');
            const openTermBtn = modalContent.querySelector('#open-terminal');
            const closeTermBtn = modalContent.querySelector('#close-terminal');
            const termWrapper = modalContent.querySelector('#terminal-wrapper');
            let term = null, fitAddon = null, ws = null;

            // Pré-remplir la liste des pods dans le select
            try {
                const r = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/details`);
                if (r.ok) {
                    const d = await r.json();
                    const pods = d.pods || [];
                    if (podSelect) {
                        podSelect.innerHTML = pods.map(p => `<option value="${p.name}">${p.name} (${p.status})</option>`).join('');
                    }
                }
            } catch {}
            if (loadBtn) {
                loadBtn.addEventListener('click', async () => {
                    loadBtn.disabled = true;
                    loadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Chargement...';
                    try {
                        const r = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/credentials`);
                        if (!r.ok) {
                            const err = await r.json().catch(() => ({}));
                            throw new Error(err.detail || 'Impossible de récupérer les identifiants');
                        }
                        const creds = await r.json();
                        credContent.style.display = 'block';
                        credContent.innerHTML = renderCredentials(creds);
                        // Bind boutons copier
                        credContent.querySelectorAll('.copy-btn').forEach(btn => {
                            btn.addEventListener('click', () => {
                                const target = btn.getAttribute('data-target');
                                const el = credContent.querySelector(`#${target}`);
                                if (el) {
                                    navigator.clipboard.writeText(el.textContent || '').then(() => {
                                        btn.classList.add('copied');
                                        setTimeout(() => btn.classList.remove('copied'), 1000);
                                    });
                                }
                            });
                        });
                    } catch (e) {
                        credContent.style.display = 'block';
                        credContent.innerHTML = `<div class="error-message"><i class="fas fa-exclamation-triangle"></i> ${e.message}</div>`;
                    } finally {
                        loadBtn.disabled = false;
                        loadBtn.innerHTML = '<i class="fas fa-unlock"></i> Afficher les identifiants';
                    }
                });
            }

            function ensureTerminal() {
                if (!term) {
                    // Utiliser la classe globale fournie par le CDN (window.Terminal)
                    const TerminalCtor = (typeof window !== 'undefined' && window.Terminal) ? window.Terminal : null;
                    if (!TerminalCtor) {
                        alert('Le composant terminal n\'est pas chargé. Rechargez la page (Ctrl+F5).');
                        throw new Error('xterm.js non chargé');
                    }
                    term = new TerminalCtor({
                        cursorBlink: true,
                        convertEol: true,
                        fontFamily: 'Consolas, Menlo, monospace',
                        fontSize: 13,
                        theme: { background: '#111111' },
                        rendererType: 'webgl' // préférer WebGL si dispo
                    });
                    // Fit addon (UMD): peut être exposé comme window.FitAddon.FitAddon ou window.FitAddon
                    const FitCtor = (typeof window !== 'undefined' && window.FitAddon && (window.FitAddon.FitAddon || window.FitAddon))
                        ? (window.FitAddon.FitAddon || window.FitAddon)
                        : null;
                    if (FitCtor) {
                        fitAddon = new FitCtor();
                        term.loadAddon(fitAddon);
                    }
                    // Activer WebGL si dispo
                    try {
                        const WebglCtor = (window.WebglAddon && (window.WebglAddon.WebglAddon || window.WebglAddon)) ? (window.WebglAddon.WebglAddon || window.WebglAddon) : null;
                        if (WebglCtor) {
                            const webglAddon = new WebglCtor();
                            term.loadAddon(webglAddon);
                        }
                    } catch {}
                    term.open(modalContent.querySelector('#xterm'));
                    setTimeout(() => { try { fitAddon && fitAddon.fit(); } catch {} }, 50);
                }
                return term;
            }

            function closeTerminal() {
                if (ws) { try { ws.close(); } catch {} ws = null; }
                if (term) { try { term.dispose(); } catch {} term = null; }
                termWrapper.style.display = 'none';
                openTermBtn.style.display = '';
                closeTermBtn.style.display = 'none';
            }

            // Charge dynamiquement xterm.js si nécessaire
            function loadXtermIfNeeded() {
                return new Promise((resolve, reject) => {
                    if (typeof window !== 'undefined' && window.Terminal) return resolve();
                    // Charger xterm puis l'addon fit
                    const sources = [
                        // Priorité: URLs sans version (conseillées par vous)
                        { xterm: 'https://cdn.jsdelivr.net/npm/xterm/lib/xterm.min.js', fit: 'https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.min.js', attach: 'https://cdn.jsdelivr.net/npm/xterm-addon-attach/lib/xterm-addon-attach.min.js', webgl: 'https://cdn.jsdelivr.net/npm/xterm-addon-webgl/lib/xterm-addon-webgl.min.js' },
                        { xterm: 'https://unpkg.com/xterm/lib/xterm.min.js', fit: 'https://unpkg.com/xterm-addon-fit/lib/xterm-addon-fit.min.js', attach: 'https://unpkg.com/xterm-addon-attach/lib/xterm-addon-attach.min.js', webgl: 'https://unpkg.com/xterm-addon-webgl/lib/xterm-addon-webgl.min.js' },
                        // Fallbacks versionnés
                        { xterm: 'https://cdn.jsdelivr.net/npm/xterm@5.5.0/lib/xterm.min.js', fit: 'https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js', attach: 'https://cdn.jsdelivr.net/npm/xterm-addon-attach@0.7.0/lib/xterm-addon-attach.min.js', webgl: 'https://cdn.jsdelivr.net/npm/xterm-addon-webgl@0.15.0/lib/xterm-addon-webgl.min.js' },
                        { xterm: 'https://unpkg.com/xterm@5.5.0/lib/xterm.min.js', fit: 'https://unpkg.com/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js', attach: 'https://unpkg.com/xterm-addon-attach@0.7.0/lib/xterm-addon-attach.min.js', webgl: 'https://unpkg.com/xterm-addon-webgl@0.15.0/lib/xterm-addon-webgl.min.js' }
                    ];

                    function loadScript(src) {
                        return new Promise((res, rej) => {
                            const s = document.createElement('script');
                            s.src = src;
                            s.async = true;
                            s.onload = () => res();
                            s.onerror = () => rej(new Error('Failed to load ' + src));
                            document.head.appendChild(s);
                        });
                    }

                    (async () => {
                        let lastErr = null;
                        for (const cdn of sources) {
                            try {
                                await loadScript(cdn.xterm);
                                // xterm peut mettre un petit délai à init le global
                                await new Promise(r => setTimeout(r, 30));
                                if (!window.Terminal) throw new Error('Terminal global missing');
                                try { await loadScript(cdn.fit); } catch {}
                                try { await loadScript(cdn.attach); } catch {}
                                try { await loadScript(cdn.webgl); } catch {}
                                return resolve();
                            } catch (e) {
                                lastErr = e;
                                continue;
                            }
                        }
                        reject(lastErr || new Error('Impossible de charger xterm.js'));
                    })();
                });
            }

            if (openTermBtn) {
                openTermBtn.addEventListener('click', async () => {
                    try {
                        await loadXtermIfNeeded();
                    } catch (e) {
                        alert("Impossible de charger le composant terminal (xterm.js).\nVérifiez votre connexion réseau puis réessayez.");
                        return;
                    }
                    const podName = podSelect?.value;
                    if (!podName) { alert('Aucun pod disponible'); return; }
                    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
                    const base = `${proto}://${window.location.host}`;
                    const wsUrl = `${base}/api/v1/k8s/terminal/${encodeURIComponent(namespace)}/${encodeURIComponent(podName)}`;
                    // Ouvrir socket
                    try { closeTerminal(); } catch {}
                    ensureTerminal();
                    termWrapper.style.display = 'block';
                    openTermBtn.style.display = 'none';
                    closeTermBtn.style.display = '';
                    ws = new WebSocket(wsUrl);
                    ws.binaryType = 'arraybuffer';
                    ws.onopen = () => {
                        try { fitAddon && fitAddon.fit(); } catch {}
                        // Envoyer immédiatement les dimensions pour un prompt correct
                        const cols = term.cols || 80, rows = term.rows || 24;
                        try { ws.send(JSON.stringify({ type: 'resize', cols, rows })); } catch {}
                        // Keepalive
                        ws.__kalive = setInterval(() => { try { ws.send('\u0000'); } catch {} }, 25000);
                        // Utiliser AttachAddon pour un écho sans perte
                        try {
                            const AttachCtor = (window.AttachAddon && (window.AttachAddon.AttachAddon || window.AttachAddon)) ? (window.AttachAddon.AttachAddon || window.AttachAddon) : null;
                            if (AttachCtor) {
                                const attach = new AttachCtor(ws, { bidirectional: true, useUtf8: true });
                                term.loadAddon(attach);
                            } else {
                                // Fallback manuel
                                ws.onmessage = (ev) => { term.write(typeof ev.data === 'string' ? ev.data : new TextDecoder().decode(ev.data)); };
                                term.onData((data) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(data); });
                            }
                        } catch {}
                    };
                    ws.onclose = () => {
                        term.write('\r\n[connexion fermée]\r\n');
                        if (ws.__kalive) try { clearInterval(ws.__kalive); } catch {}
                        closeTermBtn.style.display = 'none';
                        openTermBtn.style.display = '';
                    };
                    ws.onerror = () => {
                        term.write('\r\n[erreur websocket]\r\n');
                    };
                    // term.onData est géré par AttachAddon si dispo (fallback ci-dessus)
                    // Ajuster la taille du TTY côté pod
                    function sendResize() {
                        if (!ws || ws.readyState !== WebSocket.OPEN) return;
                        const cols = term.cols || 80, rows = term.rows || 24;
                        try { ws.send(JSON.stringify({ type: 'resize', cols, rows })); } catch {}
                    }
                    setTimeout(sendResize, 150);
                    window.addEventListener('resize', () => { try { fitAddon && fitAddon.fit(); sendResize(); } catch {} });
                });
            }
            if (closeTermBtn) {
                closeTermBtn.addEventListener('click', closeTerminal);
            }
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

    // Rendu HTML des credentials
    function renderCredentials(creds) {
        if (!creds) return '<p class="muted">Aucun identifiant disponible.</p>';
        if (creds.type === 'wordpress') {
            return `
                <div class="credentials-grid">
                    <div class="cred-card">
                        <h5><i class="fab fa-wordpress"></i> Admin WordPress</h5>
                        <div class="cred-row"><span>Utilisateur</span><code id="wp-user">${creds.wordpress?.username || ''}</code><button class="copy-btn" data-target="wp-user"><i class="fas fa-copy"></i></button></div>
                        <div class="cred-row"><span>Mot de passe</span><code id="wp-pass">${creds.wordpress?.password || ''}</code><button class="copy-btn" data-target="wp-pass"><i class="fas fa-copy"></i></button></div>
                        ${creds.wordpress?.email ? `<div class="cred-row"><span>Email</span><code id="wp-mail">${creds.wordpress.email}</code><button class="copy-btn" data-target="wp-mail"><i class="fas fa-copy"></i></button></div>` : ''}
                    </div>
                    <div class="cred-card">
                        <h5><i class="fas fa-database"></i> Base de données</h5>
                        <div class="cred-row"><span>Hôte</span><code id="db-host">${creds.database?.host || ''}</code><button class="copy-btn" data-target="db-host"><i class="fas fa-copy"></i></button></div>
                        <div class="cred-row"><span>Port</span><code id="db-port">${creds.database?.port || ''}</code><button class="copy-btn" data-target="db-port"><i class="fas fa-copy"></i></button></div>
                        <div class="cred-row"><span>Utilisateur</span><code id="db-user">${creds.database?.username || ''}</code><button class="copy-btn" data-target="db-user"><i class="fas fa-copy"></i></button></div>
                        <div class="cred-row"><span>Mot de passe</span><code id="db-pass">${creds.database?.password || ''}</code><button class="copy-btn" data-target="db-pass"><i class="fas fa-copy"></i></button></div>
                        <div class="cred-row"><span>Base</span><code id="db-name">${creds.database?.database || ''}</code><button class="copy-btn" data-target="db-name"><i class="fas fa-copy"></i></button></div>
                    </div>
                </div>
            `;
        }
        // Générique
        const entries = Object.entries(creds.secrets || {});
        if (!entries.length) return '<p class="muted">Aucun identifiant trouvé.</p>';
        return `
            <div class="credentials-grid">
                ${entries.map(([k,v],i)=>`
                    <div class="cred-card">
                        <h5><i class="fas fa-key"></i> ${k}</h5>
                        <div class="cred-row"><span>Valeur</span><code id="gen-${i}">${v || ''}</code><button class="copy-btn" data-target="gen-${i}"><i class="fas fa-copy"></i></button></div>
                    </div>
                `).join('')}
            </div>
        `;
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

    // --- Service Selection (dynamique) ---
    function bindServiceCard(card) {
        card.addEventListener('click', () => {
            const serviceName = card.getAttribute('data-service');
            const serviceIcon = card.getAttribute('data-icon');
            const deploymentType = card.getAttribute('data-deployment-type');
            const defaultImage = card.getAttribute('data-default-image');
            const defaultPort = card.getAttribute('data-default-port');
            const defaultServiceType = card.getAttribute('data-default-service-type') || 'NodePort';

            configServiceName.textContent = serviceName;
            serviceTypeInput.value = serviceName;
            serviceIconInput.value = serviceIcon;
            deploymentTypeInput.value = deploymentType;

            // Définir un nom par défaut pour le déploiement
            const deploymentName = document.getElementById('deployment-name');
            deploymentName.value = `${serviceName.toLowerCase().replace(/\s+/g, '-')}-${Math.floor(Math.random() * 9000) + 1000}`;

            // Reset form (optional)
            configForm.reset();

            // Affichage des options selon le type de service
            jupyterOptions.style.display = (deploymentType === 'jupyter') ? 'block' : 'none';
            customDeploymentOptions.style.display = (deploymentType === 'custom') ? 'block' : 'none';

            // Pré-remplir pour custom si le template fournit image/port
            if (deploymentType === 'custom') {
                if (defaultImage) document.getElementById('deployment-image').value = defaultImage;
                if (defaultPort) {
                    document.getElementById('service-port').value = defaultPort;
                    document.getElementById('service-target-port').value = defaultPort;
                }
                document.getElementById('service-type-select').value = defaultServiceType;
            }

            // Rétablir le nom par défaut (après reset)
            document.getElementById('deployment-name').value = deploymentName.value;

            showView('config-view');

            // Prévalidation quotas côté client
            const warnElId = 'quota-warning';
            function ensureWarn() {
                let w = document.getElementById(warnElId);
                if (!w) { w = document.createElement('div'); w.id = warnElId; w.className = 'error-message'; configForm.prepend(w); }
                return w;
            }
            function toMillicores(cpu) { return cpu.endsWith('m') ? parseInt(cpu) : Math.round(parseFloat(cpu) * 1000); }
            function toMi(mem) { if (mem.endsWith('Mi')) return parseInt(mem); if (mem.endsWith('Gi')) return parseInt(mem)*1024; if (mem.endsWith('Ki')) return Math.round(parseInt(mem)/1024); return parseInt(mem); }
            async function prevalidateQuotas() {
                const w = ensureWarn();
                try {
                    const q = await fetchMyQuotas();
                    const cpuMap = { 'very-low':'100m','low':'250m','medium':'500m','high':'1000m','very-high':'2000m' };
                    const ramMap = { 'very-low':'128Mi','low':'256Mi','medium':'512Mi','high':'1Gi','very-high':'2Gi' };
                    const cpuReq = cpuMap[document.getElementById('cpu').value] || '100m';
                    const memReq = ramMap[document.getElementById('ram').value] || '128Mi';
                    const replicas = (deploymentType === 'custom') ? parseInt(document.getElementById('deployment-replicas').value || '1', 10) : 1;
                    let plannedApps = 1, plannedPods = replicas, plannedCpuM = toMillicores(cpuReq) * replicas, plannedMemMi = toMi(memReq) * replicas;
                    if (deploymentType === 'wordpress') { plannedPods = 2; plannedCpuM = toMillicores('250m') + toMillicores('250m'); plannedMemMi = toMi('256Mi') + toMi('512Mi'); }
                    if (deploymentType === 'mysql') { plannedPods = 2; plannedCpuM = toMillicores('250m') + toMillicores('150m'); plannedMemMi = toMi('256Mi') + toMi('128Mi'); }
                    const over = [];
                    if (q.usage.apps_used + plannedApps > q.limits.max_apps) over.push('Applications');
                    if (q.usage.cpu_m_used + plannedCpuM > q.limits.max_requests_cpu_m) over.push('CPU');
                    if (q.usage.mem_mi_used + plannedMemMi > q.limits.max_requests_mem_mi) over.push('Mémoire');
                    const btn = configForm.querySelector('.btn-launch');
                    if (over.length) { w.innerHTML = `<i class=\"fas fa-ban\"></i> Lancement impossible: dépassement ${over.join(', ')}.`; w.style.display = 'block'; if (btn) btn.disabled = true; }
                    else { w.style.display = 'none'; if (btn) btn.disabled = false; }
                } catch { const btn = configForm.querySelector('.btn-launch'); const w = ensureWarn(); w.textContent = 'Quotas indisponibles. Réessayez plus tard.'; w.style.display = 'block'; if (btn) btn.disabled = true; }
            }
            prevalidateQuotas();
            ['cpu','ram','deployment-replicas'].forEach(id => { const el = document.getElementById(id); if (el) el.addEventListener('change', prevalidateQuotas); });

            // Appliquer la politique ressources par rôle (UI):
            const cpuSelect = document.getElementById('cpu');
            const ramSelect = document.getElementById('ram');
            const replicasInput = document.getElementById('deployment-replicas');
            const isStudent = authManager.isStudent();
            const isTeacher = authManager.isTeacher();
            const isAdmin = authManager.isAdmin();

            // Ajouter/mettre à jour une note de politique sous les champs
            function ensurePolicyNote(targetEl, text) {
                if (!targetEl) return;
                const group = targetEl.closest('.form-group');
                if (!group) return;
                let note = group.querySelector('.policy-note');
                if (!note) {
                    note = document.createElement('small');
                    note.className = 'policy-note';
                    group.appendChild(note);
                }
                note.textContent = text;
            }

            if (isStudent) {
                // Étudiants: pas de choix CPU/RAM ni de replicas; valeurs imposées et clamp backend
                if (cpuSelect) {
                    cpuSelect.value = 'medium';
                    cpuSelect.disabled = true;
                    ensurePolicyNote(cpuSelect, 'Les ressources sont fixées par la politique étudiante.');
                    cpuSelect.title = 'Ressources fixées par la politique';
                }
                if (ramSelect) {
                    ramSelect.value = 'medium';
                    ramSelect.disabled = true;
                    ensurePolicyNote(ramSelect, 'Les ressources sont fixées par la politique étudiante.');
                    ramSelect.title = 'Ressources fixées par la politique';
                }
                if (replicasInput) {
                    replicasInput.value = 1;
                    replicasInput.disabled = true;
                    ensurePolicyNote(replicasInput, 'Un seul replica autorisé pour les étudiants.');
                    replicasInput.title = 'Limité à 1';
                }
            } else {
                // Enseignants/Admins: choix permis, avec maxima indiqués
                if (cpuSelect) cpuSelect.disabled = false;
                if (ramSelect) ramSelect.disabled = false;
                if (replicasInput) {
                    replicasInput.disabled = false;
                    if (isTeacher) {
                        replicasInput.max = 2;
                        ensurePolicyNote(replicasInput, 'Jusqu’à 2 réplicas autorisés pour les enseignants.');
                        replicasInput.title = 'Max 2';
                        if (parseInt(replicasInput.value || '1', 10) > 2) replicasInput.value = 2;
                    } else if (isAdmin) {
                        replicasInput.max = 5;
                        ensurePolicyNote(replicasInput, 'Jusqu’à 5 réplicas autorisés pour les administrateurs.');
                        replicasInput.title = 'Max 5';
                        if (parseInt(replicasInput.value || '1', 10) > 5) replicasInput.value = 5;
                    }
                }
            }

            // Toggle options réseau avancées
            const advToggle = document.getElementById('advanced-options-toggle');
            const svcOptions = document.getElementById('service-options');
            if (advToggle && svcOptions) {
                advToggle.onclick = (ev) => {
                    ev.preventDefault();
                    const show = svcOptions.style.display === 'none' || svcOptions.style.display === '';
                    svcOptions.style.display = show ? 'block' : 'none';
                    advToggle.textContent = show ? 'Masquer les options réseau avancées' : 'Options réseau avancées';
                };
                // Par défaut replié
                svcOptions.style.display = 'none';
                advToggle.textContent = 'Options réseau avancées';
            }
        });
    }

    async function loadTemplates() {
        try {
            const resp = await fetch(`${API_V1}/k8s/templates`);
            if (!resp.ok) throw new Error('Erreur de chargement des templates');
            const data = await resp.json();
            const templates = data.templates || [];
            // Laisser le backend décider des apps visibles selon RuntimeConfig.allowed_for_students
            const filteredTemplates = templates;
            if (!serviceCatalog) return;
            if (filteredTemplates.length === 0) {
                serviceCatalog.innerHTML = '<div class="no-items-message">Aucune application disponible</div>';
                return;
            }

            // Construire la liste de tags uniques à partir des templates
            const tagSet = new Set();
            filteredTemplates.forEach(t => (t.tags || []).forEach(tag => tagSet.add(tag)));
            const allTags = Array.from(tagSet).sort();

            // Rendu des filtres de tags
            if (tagFiltersEl) {
                tagFiltersEl.innerHTML = allTags.map(tag => `<span class="tag-chip" data-tag="${tag}"><i class="fas fa-tag"></i> ${tag}</span>`).join('');
            }

            // Fonction de rendu en appliquant recherche + tags actifs
            function renderCatalog() {
                const q = (catalogSearch?.value || '').toLowerCase();
                const activeTags = Array.from(tagFiltersEl?.querySelectorAll('.tag-chip.active') || []).map(el => el.getAttribute('data-tag'));
                const matches = filteredTemplates.filter(t => {
                    const title = (t.name || t.id || '').toLowerCase();
                    const desc = (t.description || '').toLowerCase();
                    const textOk = !q || title.includes(q) || desc.includes(q);
                    const tags = t.tags || [];
                    const tagsOk = activeTags.length === 0 || activeTags.every(tag => tags.includes(tag));
                    return textOk && tagsOk;
                });

                serviceCatalog.innerHTML = matches.map(t => {
                    const rawIcon = (t.icon || '').trim();
                    const isFA = rawIcon.includes('fa-');
                    const faClass = isFA ? rawIcon : 'fa-solid fa-cube';
                    const iconHtml = isFA
                        ? `<i class="${faClass} service-icon" aria-hidden="true"></i>`
                        : (rawIcon
                            ? `<span class="emoji-icon service-icon" role="img" aria-label="icône">${rawIcon}</span>`
                            : `<i class="fa-solid fa-cube service-icon" aria-hidden="true"></i>`);
                    const title = t.name || t.id;
                    const desc = t.description || '';
                    const deploymentType = t.deployment_type || (t.id === 'custom' ? 'custom' : t.id);
                    const tagsHtml = (t.tags || []).map(tag => `<span class="tag-chip" role="listitem">${tag}</span>`).join(' ');
                    return `
                        <div class="card service-card" 
                            data-service="${title}"
                            data-icon="${rawIcon}"
                            data-deployment-type="${deploymentType}"
                            data-default-image="${t.default_image || ''}"
                            data-default-port="${t.default_port || ''}"
                            data-default-service-type="${t.default_service_type || 'NodePort'}">
                            ${iconHtml}
                            <h3>${title}</h3>
                            <p>${desc}</p>
                            ${tagsHtml ? `<div class=\"card-tags\" role=\"list\">${tagsHtml}</div>` : ''}
                        </div>
                    `;
                }).join('');
                document.querySelectorAll('.service-card').forEach(bindServiceCard);
            }

            // Bind des filtres
            if (tagFiltersEl) {
                tagFiltersEl.addEventListener('click', (e) => {
                    const chip = e.target.closest('.tag-chip');
                    if (!chip) return;
                    chip.classList.toggle('active');
                    renderCatalog();
                });
            }
            if (catalogSearch) {
                catalogSearch.addEventListener('input', () => renderCatalog());
            }

            // Premier rendu
            renderCatalog();
        } catch (e) {
            console.error(e);
            // Fallback minimal si l'API échoue
            if (serviceCatalog) {
                const isElevated = authManager.isAdmin() || authManager.isTeacher();
                // Pour étudiants: proposer uniquement Jupyter et VS Code en fallback
                serviceCatalog.innerHTML = isElevated ? `
                    <div class=\"card service-card\" data-service=\"Custom\" data-icon=\"fa-solid fa-cube\" data-deployment-type=\"custom\">
                        <i class=\"fas fa-cube service-icon\"></i>
                        <h3>Personnalisé</h3>
                        <p>Déploiement d'image Docker personnalisée.</p>
                    </div>` : `
                    <div class=\"card service-card\" data-service=\"Jupyter Notebook\" data-icon=\"fa-brands fa-python\" data-deployment-type=\"jupyter\" data-default-image=\"tutanka01/k8s:jupyter\" data-default-port=\"8888\" data-default-service-type=\"NodePort\">
                        <i class=\"fa-brands fa-python service-icon\"></i>
                        <h3>Jupyter Notebook</h3>
                        <p>Environnement interactif pour Python et data science.</p>
                    </div>
                    <div class=\"card service-card\" data-service=\"VS Code\" data-icon=\"fa-solid fa-code\" data-deployment-type=\"vscode\" data-default-image=\"tutanka01/k8s:vscode\" data-default-port=\"8080\" data-default-service-type=\"NodePort\">
                        <i class=\"fa-solid fa-code service-icon\"></i>
                        <h3>VS Code</h3>
                        <p>Éditeur de code accessible via le navigateur.</p>
                    </div>`;
                document.querySelectorAll('.service-card').forEach(bindServiceCard);
            }
        }
    }

    // --- Form Submission (Real API Call) ---
    if (configForm) {
        configForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            // Double check quotas côté client
            try { await (async ()=>{ await fetchMyQuotas(); })(); } catch { return; }
            
            // Récupérer les informations du formulaire
            const serviceName = serviceTypeInput.value;
            const serviceIcon = serviceIconInput.value;
            const deploymentType = deploymentTypeInput.value;
            const deploymentName = document.getElementById('deployment-name').value;
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
            } else if (deploymentType === 'wordpress') {
                // WordPress: l'image sera ignorée côté serveur (bitnami/wordpress), mais on garde NodePort 8080
                image = 'bitnami/wordpress:latest';
                createService = true;
                serviceType = 'NodePort';
                servicePort = 8080;
                serviceTargetPort = 8080;
            } else if (deploymentType === 'lamp') {
                // LAMP: Web exposé sur 8080 (->80), phpMyAdmin exposé séparément (->80 via 8081)
                image = 'php:8.2-apache';
                createService = true;
                serviceType = 'NodePort';
                servicePort = 8080;        // Web principal
                serviceTargetPort = 80;    // Apache écoute sur 80
            } else if (deploymentType === 'mysql') {
                // MySQL + phpMyAdmin: seule l'UI phpMyAdmin est exposée côté serveur
                // L'image côté client n'est pas utilisée mais on fixe les ports d'accès
                image = 'phpmyadmin:latest';
                createService = true;
                serviceType = 'NodePort';
                servicePort = 8080;        // accessible depuis l'extérieur
                serviceTargetPort = 80;    // phpMyAdmin écoute sur 80
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
                <h2>Lancement de l'application ${serviceName} en cours...</h2>
                <p>Votre application est en cours de préparation. Veuillez patienter.</p>
            `;
            statusActions.style.display = 'none'; // Cacher le bouton "Terminé" pendant le chargement

            try {
                // Construire les paramètres d'URL pour l'endpoint POST
                const params = new URLSearchParams({
                    name: deploymentName,
                    image: image,
                    replicas: replicas,
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
                const response = await fetch(`${API_V1}/k8s/deployments?${params.toString()}`, {
                    method: 'POST',
                    credentials: 'include'
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
                    // Gestion d'erreur améliorée
                    let errorMessage = 'Erreur lors de la création du déploiement';
                    
                    if (data && data.detail) {
                        if (typeof data.detail === 'string') {
                            errorMessage = data.detail;
                        } else if (Array.isArray(data.detail)) {
                            // Si c'est un tableau d'erreurs de validation
                            errorMessage = data.detail.map(err => {
                                if (typeof err === 'string') return err;
                                if (err.msg) return `${err.loc ? err.loc.join('.') + ': ' : ''}${err.msg}`;
                                return JSON.stringify(err);
                            }).join(', ');
                        } else {
                            // Si c'est un objet complexe
                            errorMessage = JSON.stringify(data.detail);
                        }
                    }
                    
                    throw new Error(errorMessage);
                }
                
                // Construire les infos du lab à ajouter au dashboard
                labCounter++;
                const labId = deploymentName;
                const effectiveNamespace = data.namespace || 'labondemand-user';
                
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
                        const detailsResponse = await fetch(`${API_V1}/k8s/deployments/${effectiveNamespace}/${deploymentName}/details`);
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
                    namespace: effectiveNamespace,
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
            // Récupérer la liste des déploiements LabOnDemand uniquement
            const response = await fetch(`${API_V1}/k8s/deployments/labondemand`);
            if (!response.ok) throw new Error('Erreur lors de la récupération des déploiements');
            
            const data = await response.json();
            const deployments = data.deployments || [];
            
            // Plus besoin de filtrer puisque l'endpoint ne retourne que les déploiements LabOnDemand
            const filteredDeployments = deployments;
            
            // Supprimer les labCards pour les déploiements qui n'existent plus
            const labCards = document.querySelectorAll('.lab-card');
            labCards.forEach(card => {
                const deploymentId = card.id;
                const deploymentNamespace = card.dataset.namespace;
                
                // Vérifier si le déploiement existe encore
                const deploymentExists = filteredDeployments.some(d => 
                    d.name === deploymentId && d.namespace === deploymentNamespace
                );
                
                if (!deploymentExists) {
                    console.log(`Suppression de la carte obsolète: ${deploymentId} (namespace: ${deploymentNamespace})`);
                    
                    // Arrêter les timers de vérification s'ils existent
                    const timerKey = `${deploymentNamespace}-${deploymentId}`;
                    if (deploymentCheckTimers.has(timerKey)) {
                        clearTimeout(deploymentCheckTimers.get(timerKey));
                        deploymentCheckTimers.delete(timerKey);
                        console.log(`Timer de vérification arrêté pour ${deploymentId}`);
                    }
                    
                    card.remove();
                }
            });
            
            // Vérifier si la liste est vide
            const noLabsMessage = document.querySelector('.no-labs-message');
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
            datasetsHtml = `<div class="lab-datasets"><i class="fas fa-database"></i><span>Datasets: ${labDetails.datasets.join(', ')}</span></div>`;
        }

        // Déterminer l'indicateur d'état à afficher
        const statusIndicator = labDetails.ready 
            ? '<span class="status-indicator ready"><i class="fas fa-check-circle"></i> Prêt</span>'
            : '<span class="status-indicator pending"><i class="fas fa-spinner fa-spin"></i> En préparation...</span>';        card.innerHTML = `
            <h3><i class="${labDetails.icon}"></i> ${labDetails.name} ${statusIndicator}</h3>
            <div class="lab-subtitle">
                <span class="id-badge"><i class="fas fa-tag"></i>${labDetails.id}</span>
            </div>
            <div class="lab-meta">
                <span class="meta-item"><i class="fas fa-microchip"></i>${labDetails.cpu}</span>
                <span class="sep">•</span>
                <span class="meta-item"><i class="fas fa-memory"></i>${labDetails.ram}</span>
            </div>
            ${datasetsHtml}
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
            const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/details`);
            
            if (!response.ok) {
                throw new Error('Impossible de récupérer les détails du déploiement');
            }
            
            const data = await response.json();
            if (data.access_urls && data.access_urls.length > 0) {
                const accessUrl = data.access_urls[0].url;
                const accessBtn = document.getElementById(`access-btn-${name}`);
                if (accessBtn) {
                    accessBtn.href = accessUrl;
                    console.log(`URL d'accès récupérée pour ${name}: ${accessUrl}`);
                }
            } else {
                console.warn(`Aucune URL d'accès disponible pour ${name}`);
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
            const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/details`);
            
            // Si le déploiement n'existe pas (404), arrêter les vérifications et supprimer la carte
            if (response.status === 404) {
                console.warn(`Déploiement ${name} non trouvé (404). Suppression de la carte et arrêt des vérifications.`);
                
                // Nettoyer le timer
                clearTimeout(deploymentCheckTimers.get(`${namespace}-${name}`));
                deploymentCheckTimers.delete(`${namespace}-${name}`);
                
                // Supprimer la carte de l'application
                const card = document.getElementById(name);
                if (card) {
                    card.remove();
                    console.log(`Carte d'application ${name} supprimée car le déploiement n'existe plus.`);
                }
                
                // Vérifier si la liste est maintenant vide
                const noLabsMessage = document.querySelector('.no-labs-message');
                if (activeLabsList.children.length === 0) {
                    if (noLabsMessage) noLabsMessage.style.display = 'block';
                }
                
                return;
            }
            
            // Si erreur 500, arrêter aussi les vérifications après quelques tentatives
            if (response.status === 500) {
                console.error(`Erreur serveur 500 pour le déploiement ${name}. Tentative ${attempts+1}/${maxAttempts}`);
                
                if (attempts >= 5) { // Arrêter après 5 tentatives pour les erreurs 500
                    console.error(`Arrêt des vérifications pour ${name} après erreurs 500 répétées`);
                    clearTimeout(deploymentCheckTimers.get(`${namespace}-${name}`));
                    deploymentCheckTimers.delete(`${namespace}-${name}`);
                    updateLabCardStatus(name, false, null, true);
                    return;
                }
            }
            
            if (!response.ok) {
                throw new Error(`Erreur ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            const available = (data.deployment && (data.deployment.available_replicas || 0) > 0);
            // Ne pas considérer "pods prêts" si la liste est vide (every([]) === true -> piège)
            const podsReady = Array.isArray(data.pods) && data.pods.length > 0 && data.pods.every(pod => pod.status === 'Running');
            
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
                clearTimeout(deploymentCheckTimers.get(`${namespace}-${name}`));
                deploymentCheckTimers.delete(`${namespace}-${name}`);
            }
        } catch (error) {
            console.error(`Erreur lors de la vérification du déploiement ${name}:`, error);
            // Continuer à vérifier sauf si max atteint ET si ce n'est pas une erreur 404
            if (attempts < maxAttempts && !error.message.includes('404')) {
                const timerId = setTimeout(() => {
                    checkDeploymentReadiness(namespace, name, attempts + 1);
                }, 5000);
                deploymentCheckTimers.set(`${namespace}-${name}`, timerId);
            } else {
                // Arrêter les vérifications en cas d'erreur persistante
                console.error(`Arrêt des vérifications pour ${name} après ${attempts} tentatives`);
                clearTimeout(deploymentCheckTimers.get(`${namespace}-${name}`));
                deploymentCheckTimers.delete(`${namespace}-${name}`);
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
                    const accessUrl = deploymentData.access_urls[0].url;
                    accessBtn.href = accessUrl;
                    console.log(`URL d'accès mise à jour pour ${deploymentId}: ${accessUrl}`);
                } else {
                    console.warn(`Aucune URL d'accès trouvée pour ${deploymentId}`);
                }
            } else if (timeout) {
                accessBtn.innerHTML = '<i class="fas fa-exclamation-circle"></i> Vérifier les détails';
            }
        }
    }

    async function stopLab(labId, namespace) {
         // Demander confirmation
    if (confirm(`Êtes-vous sûr de vouloir arrêter l'application "${labId}" ?`)) {
            try {
                // Appel API pour supprimer le déploiement
                const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${labId}?delete_service=true`, {
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
                alert(`Erreur lors de l'arrêt de l'application: ${error.message}`);
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

    // --- Fonction pour nettoyer tous les timers ---
    function clearAllDeploymentTimers() {
        console.log('Nettoyage de tous les timers de vérification des déploiements');
        for (const [key, timerId] of deploymentCheckTimers.entries()) {
            clearTimeout(timerId);
            console.log(`Timer nettoyé pour: ${key}`);
        }
        deploymentCheckTimers.clear();
    }

    // --- Initialisation ---
    async function init() {
        // Nettoyer tous les timers existants au démarrage
        clearAllDeploymentTimers();
        
    initUserInfo();
    if (quotasContent) { refreshQuotas(); }
    // Charger le catalogue dynamiquement
    await loadTemplates();
        // Vérifier la connexion à l'API
        const status = await checkApiStatus();
        const apiConnected = !!status.api;
        const k8sConnected = !!status.k8s;

        if (apiConnected) {
            // Charger les données K8s seulement pour admin/teacher
            const isElevated = authManager.isAdmin() || authManager.isTeacher();
            if (isElevated) {
                if (k8sConnected) {
                    fetchAndRenderNamespaces();
                    fetchAndRenderPods();
                    fetchAndRenderDeployments();
                } else {
                    // Afficher un message clair dans les panneaux K8s
                    ['namespaces-list', 'pods-list', 'deployments-list'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) {
                            el.innerHTML = '<div class="error-message">Kubernetes indisponible. Réessayez plus tard.</div>';
                        }
                    });
                }
            } else {
                // Étudiants: n'appellent pas les endpoints /namespaces et /pods
                fetchAndRenderDeployments();
            }
            
            
            // Récupérer les déploiements existants pour les afficher comme labs actifs
            const response = await fetch(`${API_V1}/k8s/deployments/labondemand`);
            if (response.ok) {
                const data = await response.json();
                const deployments = data.deployments || [];
                
                console.log(`Trouvé ${deployments.length} déploiements LabOnDemand`);
                console.log(`Déploiements:`, deployments);
                
                // Pour chaque déploiement, récupérer les détails et créer une carte
                for (const deployment of deployments) {
                    // Vérifier si une carte existe déjà pour ce déploiement
                    const existingCard = document.getElementById(deployment.name);
                    if (existingCard) {
                        console.log(`Carte existante trouvée pour ${deployment.name}, ignorée.`);
                        continue;
                    }
                    console.log(`Traitement du déploiement:`, {
                        name: deployment.name,
                        namespace: deployment.namespace,
                        type: deployment.type,
                        labels: deployment.labels
                    });
                    
                    // Protection supplémentaire contre les namespaces système
                    if (deployment.namespace.includes('system') || 
                        deployment.namespace === 'kube-public' || 
                        deployment.namespace === 'kube-node-lease') {
                        console.log(`Ignoré déploiement système ${deployment.name}`);
                        continue;
                    }
                    
                    // Vérifier que nous avons un déploiement valide avec un nom et un type
                    if (!deployment.name || !deployment.type) {
                        console.error(`Déploiement invalide:`, deployment);
                        continue;
                    }
                    
                    try {
                        console.log(`Récupération des détails pour ${deployment.namespace}/${deployment.name}`);
                        const detailsResponse = await fetch(`${API_V1}/k8s/deployments/${deployment.namespace}/${deployment.name}/details`);
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
                            } else if (deployment.type === "lamp") {
                                serviceIcon = "fa-solid fa-server";
                                serviceName = "Stack LAMP";
                            } else if (deployment.type === "wordpress") {
                                serviceIcon = "fa-brands fa-wordpress";
                                serviceName = "WordPress";
                            } else if (deployment.type === "mysql") {
                                serviceIcon = "fa-solid fa-database";
                                serviceName = "MySQL + phpMyAdmin";
                            }
                            
                            // Déterminer l'URL d'accès
                            let accessUrl = '';
                            if (detailsData.access_urls && detailsData.access_urls.length > 0) {
                                // Pour LAMP, préférer l'URL Web si disponible
                                if (deployment.type === 'lamp') {
                                    const web = detailsData.access_urls.find(u => (u.label||'').toLowerCase().includes('web'));
                                    accessUrl = (web && web.url) || detailsData.access_urls[0].url;
                                } else {
                                    accessUrl = detailsData.access_urls[0].url;
                                }
                            } else {
                                // URL générique fallback
                                accessUrl = `http://${deployment.name}-service`;
                            }
                            
                            // Vérifier si le déploiement est réellement prêt
                            const isReady = detailsData.deployment.available_replicas > 0 && 
                                          detailsData.pods.some(pod => pod.status === 'Running');
                            
                            // Ajouter la carte avec l'état de disponibilité correct
                            console.log(`Ajout de la carte pour ${deployment.name}`, {
                                serviceName, serviceIcon, accessUrl, isReady
                            });
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
                        } else {
                            console.error(`Erreur lors de la récupération des détails pour ${deployment.name}:`, detailsResponse.status);
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
            
            // Mettre en place un nettoyage périodique des cartes obsolètes (toutes les 30 secondes)
            setInterval(refreshActiveLabs, 30000);
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

    // Nettoyer les timers lors du déchargement de la page
    window.addEventListener('beforeunload', () => {
        console.log('Nettoyage des timers de vérification...');
        deploymentCheckTimers.forEach((timerId, key) => {
            clearTimeout(timerId);
            console.log(`Timer nettoyé pour ${key}`);
        });
        deploymentCheckTimers.clear();
    });

    // Initialiser l'application
    init();

    // Afficher la vue dashboard au démarrage
    showView('dashboard-view');
});