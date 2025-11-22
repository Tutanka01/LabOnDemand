import { escapeHtml } from './utils.js';

export function createDeploymentsModule({
    API_V1,
    state,
    elements,
    novnc,
    statusView,
    resources,
}) {
    const {
        activeLabsList,
        noLabsMessage,
        deploymentDetailsModal,
        deploymentDetailsContent,
    } = elements;
    const {
        registerNovncEndpoint,
        bindNovncButtons,
        updateNovncButtonsAvailability,
        extractNovncInfoFromDetails,
    } = novnc;
    const {
        updateStatusViewForDeployment,
    } = statusView;
    const {
        refreshPvcs,
        populatePvcSelect,
    } = resources;

    function formatLifecycleBadge(lifecycle) {
        if (!lifecycle) {
            return '<span class="lifecycle-badge unknown"><i class="fas fa-question-circle"></i> Inconnu</span>';
        }
        const stateValue = (lifecycle.state || 'unknown').toLowerCase();
        const mapping = {
            paused: { label: 'En pause', icon: 'fa-circle-pause', css: 'paused' },
            running: { label: 'Actif', icon: 'fa-circle-check', css: 'running' },
            mixed: { label: 'Relance en cours', icon: 'fa-rotate', css: 'starting' },
            starting: { label: 'Initialisation', icon: 'fa-rotate', css: 'starting' },
            unknown: { label: 'Inconnu', icon: 'fa-question-circle', css: 'unknown' },
        };
        const meta = mapping[stateValue] || mapping.unknown;
        return `<span class="lifecycle-badge ${meta.css}"><i class="fas ${meta.icon}"></i> ${meta.label}</span>`;
    }

    function pushLifecycleFeedback(message, tone = 'info') {
        const feedbackEl = document.getElementById('pause-feedback');
        if (!feedbackEl) {
            console.info('pause-mode:', message);
            return;
        }
        feedbackEl.textContent = message;
        feedbackEl.dataset.tone = tone;
    }

    async function toggleDeploymentLifecycleRequest(namespace, name, action) {
        const endpoint = `${API_V1}/k8s/deployments/${namespace}/${name}/${action}`;
        const response = await fetch(endpoint, { method: 'POST' });
        let payload = {};
        try {
            payload = await response.json();
        } catch (error) {
            payload = {};
        }
        if (!response.ok) {
            throw new Error(payload.detail || payload.message || 'Impossible d\'appliquer cette action.');
        }
        return payload;
    }

    async function refreshDeploymentLifecycle(namespace, name, options = {}) {
        const { silent = false } = options;
        try {
            const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/details`);
            if (!response.ok) {
                throw new Error('Impossible d\'obtenir l\'état actuel');
            }
            const data = await response.json();
            if (data.lifecycle) {
                applyLifecycleStateToLabCard(name, data.lifecycle);
            }
            return data.lifecycle;
        } catch (error) {
            if (!silent) {
                console.warn('refreshDeploymentLifecycle', error);
            }
            return null;
        }
    }

    function bindPauseButtons(root = document) {
        const scope = root || document;
        scope.querySelectorAll('.btn-toggle-pause').forEach(btn => {
            if (btn.dataset.bound === 'true') {
                return;
            }
            btn.dataset.bound = 'true';
            btn.addEventListener('click', onTogglePauseClick);
        });
    }

    async function onTogglePauseClick(event) {
        const btn = event.currentTarget;
        const namespace = btn.getAttribute('data-namespace');
        const name = btn.getAttribute('data-name');
        const action = btn.getAttribute('data-action');
        if (!namespace || !name || !action) {
            return;
        }

        if (action === 'pause') {
            const confirmed = confirm(`Mettre l'application "${name}" en pause ? Cela libèrera les pods mais conservera vos données.`);
            if (!confirmed) {
                return;
            }
        }

        btn.disabled = true;
        btn.classList.add('loading');

        try {
            const payload = await toggleDeploymentLifecycleRequest(namespace, name, action);
            pushLifecycleFeedback(payload.message || (action === 'pause' ? 'Application mise en pause.' : 'Application relancée.'), 'success');
            await fetchAndRenderDeployments();
            const lifecycle = await refreshDeploymentLifecycle(namespace, name, { silent: true });
            if (action === 'resume') {
                checkDeploymentReadiness(namespace, name);
            }
            return lifecycle;
        } catch (error) {
            console.error('pause/resume error', error);
            pushLifecycleFeedback(error.message || 'Action impossible.', 'error');
            alert(`Erreur: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.classList.remove('loading');
        }
    }

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

    async function fetchAndRenderPods() {
        const podsListEl = document.getElementById('pods-list');
        if (!podsListEl) return;
        try {
            const response = await fetch(`${API_V1}/k8s/pods`);
            if (!response.ok) throw new Error('Erreur lors de la récupération des pods');
            const data = await response.json();
            const pods = data.pods || [];
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

            document.querySelectorAll('.btn-delete-pod').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const name = e.currentTarget.getAttribute('data-name');
                    const namespace = e.currentTarget.getAttribute('data-namespace');

                    if (confirm(`Êtes-vous sûr de vouloir supprimer le pod ${name} ?`)) {
                        try {
                            const deleteResponse = await fetch(`${API_V1}/k8s/pods/${namespace}/${name}`, {
                                method: 'DELETE'
                            });

                            if (deleteResponse.ok) {
                                alert(`Pod ${name} supprimé avec succès`);
                                fetchAndRenderPods();
                            } else {
                                const error = await deleteResponse.json();
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
        if (!deploymentsListEl) return;
        try {
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
            }
            window.__myAppsUsageIndex = usageIndex;

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
                            <th>État</th>
                            <th>CPU</th>
                            <th>Mémoire</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${deployments.map(dep => {
                            let icon = 'fa-layer-group';
                            let typeBadge = '';
                            switch (dep.type) {
                                case 'jupyter':
                                    icon = 'fa-brands fa-python';
                                    typeBadge = '<span class="type-badge jupyter">Jupyter</span>';
                                    break;
                                case 'vscode':
                                    icon = 'fa-solid fa-code';
                                    typeBadge = '<span class="type-badge vscode">VSCode</span>';
                                    break;
                                case 'custom':
                                    icon = 'fa-solid fa-cube';
                                    typeBadge = '<span class="type-badge custom">Custom</span>';
                                    break;
                            }

                            const usage = (window.__myAppsUsageIndex || {})[`$${dep.namespace}::$${dep.name}`] || null;
                            const cpuDisplay = usage ? `${usage.cpu_m} m` : 'N/A';
                            const memDisplay = usage ? `${usage.mem_mi} Mi` : 'N/A';
                            const srcBadge = usage ? `<span class="usage-source ${usage.source === 'live' ? 'live' : 'requests'}" title="${usage.source === 'live' ? 'Mesures live (metrics-server)' : 'Estimation par requests'}">${usage.source === 'live' ? 'Live' : 'Req'}</span>` : '';
                            const lifecycle = dep.lifecycle || dep.lifecycle_summary || null;
                            const lifecycleBadge = formatLifecycleBadge(lifecycle);
                            const isPaused = lifecycle?.state === 'paused' || lifecycle?.paused;
                            const pauseAction = isPaused ? 'resume' : 'pause';
                            const pauseIcon = isPaused ? 'fa-circle-play' : 'fa-circle-pause';

                            return `
                                <tr>
                                    <td><i class="fas ${icon}"></i> ${dep.name}</td>
                                    <td>${dep.namespace}</td>
                                    <td>${typeBadge}</td>
                                    <td>${lifecycleBadge}</td>
                                    <td>${cpuDisplay} ${srcBadge}</td>
                                    <td>${memDisplay}</td>
                                    <td class="action-cell">
                                        <button class="btn btn-secondary btn-view-deployment" 
                                                data-name="${dep.name}" 
                                                data-namespace="${dep.namespace}">
                                            <i class="fas fa-eye"></i>
                                        </button>
                                        <button class="btn btn-warning btn-toggle-pause" 
                                                data-name="${dep.name}" 
                                                data-namespace="${dep.namespace}"
                                                data-action="${pauseAction}"
                                                data-variant="icon"
                                                title="${isPaused ? 'Relancer cette application' : 'Mettre temporairement en pause'}">
                                            <i class="fas ${pauseIcon}"></i>
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

            document.querySelectorAll('.btn-view-deployment').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const name = e.currentTarget.getAttribute('data-name');
                    const namespace = e.currentTarget.getAttribute('data-namespace');
                    showDeploymentDetails(namespace, name);
                });
            });

            document.querySelectorAll('.btn-delete-deployment').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const name = e.currentTarget.getAttribute('data-name');
                    const namespace = e.currentTarget.getAttribute('data-namespace');

                    if (confirm(`Êtes-vous sûr de vouloir supprimer le déploiement ${name} ?`)) {
                        try {
                            const deleteResp = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}?delete_service=true`, {
                                method: 'DELETE'
                            });

                            if (deleteResp.ok) {
                                alert(`Déploiement ${name} supprimé avec succès`);
                                fetchAndRenderDeployments();
                                refreshActiveLabs();
                            } else {
                                const error = await deleteResp.json();
                                alert(`Erreur: ${error.detail || 'Échec de la suppression'}`);
                            }
                        } catch (error) {
                            console.error('Erreur:', error);
                            alert('Erreur réseau lors de la suppression du déploiement');
                        }
                    }
                });
            });

            bindPauseButtons(deploymentsListEl);
        } catch (error) {
            console.error('Erreur:', error);
            deploymentsListEl.innerHTML = '<div class="error-message">Erreur lors du chargement des déploiements</div>';
        }
    }

    async function showDeploymentDetails(namespace, name) {
        const modal = deploymentDetailsModal || document.getElementById('deployment-details-modal');
        const modalContent = deploymentDetailsContent || document.getElementById('deployment-details-content');
        if (!modal || !modalContent) return;

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
            const lifecycle = data.lifecycle || {};
            const lifecycleState = (lifecycle.state || 'unknown').toLowerCase();
            const lifecycleLabelMap = {
                paused: 'En pause',
                running: 'Actif',
                mixed: 'Redémarrage',
                starting: 'Initialisation',
                unknown: 'Inconnu',
            };
            const lifecycleLabel = lifecycleLabelMap[lifecycleState] || lifecycleLabelMap.unknown;
            const isPaused = lifecycleState === 'paused' || lifecycle.paused === true;
            const pauseAction = isPaused ? 'resume' : 'pause';
            const pauseIcon = isPaused ? 'fa-circle-play' : 'fa-circle-pause';
            const pausedSince = lifecycle.paused_at
                ? new Date(lifecycle.paused_at).toLocaleString('fr-FR', { hour12: false })
                : null;
            const pausedBy = lifecycle.paused_by || null;

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
                accessUrlsHtml = '<p>Aucune URL d\'accès disponible pour ce déploiement.</p>';
            }

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
                            <li><strong>État:</strong> ${lifecycleLabel}${isPaused && pausedSince ? ` – en pause depuis ${pausedSince}` : ''}</li>
                            <li>
                                <strong>Réplicas:</strong> ${data.deployment.replicas} 
                                <span class="replica-status ${data.deployment.available_replicas > 0 ? 'ready' : 'pending'}">
                                    (${data.deployment.available_replicas || 0} disponible(s))
                                </span>
                            </li>
                        </ul>

                        ${isPaused ? `
                            <div class="app-availability paused">
                                <i class="fas fa-circle-pause app-availability-icon"></i>
                                <span class="app-availability-text">Application en pause. Vos volumes et secrets sont conservés.</span>
                            </div>
                        ` : data.deployment.available_replicas > 0 ? `
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
                                <div class="energy-panel">
                                    <h4><i class="fas fa-leaf"></i> Mode économie de ressources</h4>
                                    <p class="muted">Mettez votre application en pause pour libérer immédiatement CPU et mémoire tout en conservant vos données persistantes.</p>
                                    <ul class="pause-benefits">
                                        <li><i class="fas fa-clock"></i> Reprise en quelques secondes</li>
                                        <li><i class="fas fa-shield-alt"></i> Volumes et secrets intacts</li>
                                    </ul>
                                    <div class="pause-actions">
                                        <button class="btn btn-warning btn-toggle-pause" data-name="${name}" data-namespace="${namespace}" data-action="${pauseAction}" data-variant="text">
                                            <i class="fas ${pauseIcon}"></i> ${isPaused ? 'Reprendre l\'application' : 'Mettre en pause'}
                                        </button>
                                        <a class="btn btn-ghost" href="documentation/README.md#mode-pause" target="_blank">
                                            <i class="fas fa-book-open"></i> Comprendre cette fonctionnalité
                                        </a>
                                    </div>
                                    <p class="pause-note">${isPaused ? `En pause${pausedSince ? ` depuis ${pausedSince}` : ''}${pausedBy ? ` (initiée par ${pausedBy})` : ''}.` : 'Conseil : mettez vos TP en veille au lieu de les supprimer lorsque vous faites une pause.'}</p>
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
                        ` : '<p>Aucun pod trouvé pour ce déploiement.</p>'}
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
                        ` : '<p>Aucun point d\'exposition (Service Kubernetes) trouvé pour ce déploiement.</p>'}
                    </div>
                </div>
            `;

            bindPauseButtons(modalContent);

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

            const loadBtn = modalContent.querySelector('#load-credentials');
            const credContent = modalContent.querySelector('#credentials-content');
            const podSelect = modalContent.querySelector('#terminal-pod-select');
            const openTermBtn = modalContent.querySelector('#open-terminal');
            const closeTermBtn = modalContent.querySelector('#close-terminal');
            const termWrapper = modalContent.querySelector('#terminal-wrapper');
            let term = null, fitAddon = null, ws = null;

            try {
                const r = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/details`);
                if (r.ok) {
                    const d = await r.json();
                    const pods = d.pods || [];
                    if (podSelect) {
                        podSelect.innerHTML = pods.map(p => `<option value="${p.name}">${p.name} (${p.status})</option>`).join('');
                    }
                }
            } catch (err) {}

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
                        rendererType: 'webgl'
                    });
                    const FitCtor = (typeof window !== 'undefined' && window.FitAddon && (window.FitAddon.FitAddon || window.FitAddon))
                        ? (window.FitAddon.FitAddon || window.FitAddon)
                        : null;
                    if (FitCtor) {
                        fitAddon = new FitCtor();
                        term.loadAddon(fitAddon);
                    }
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

            function loadXtermIfNeeded() {
                return new Promise((resolve, reject) => {
                    if (typeof window !== 'undefined' && window.Terminal) return resolve();
                    const sources = [
                        { xterm: 'https://cdn.jsdelivr.net/npm/xterm/lib/xterm.min.js', fit: 'https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.min.js', attach: 'https://cdn.jsdelivr.net/npm/xterm-addon-attach/lib/xterm-addon-attach.min.js', webgl: 'https://cdn.jsdelivr.net/npm/xterm-addon-webgl/lib/xterm-addon-webgl.min.js' },
                        { xterm: 'https://unpkg.com/xterm/lib/xterm.min.js', fit: 'https://unpkg.com/xterm-addon-fit/lib/xterm-addon-fit.min.js', attach: 'https://unpkg.com/xterm-addon-attach/lib/xterm-addon-attach.min.js', webgl: 'https://unpkg.com/xterm-addon-webgl/lib/xterm-addon-webgl.min.js' },
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
                    try { closeTerminal(); } catch {}
                    ensureTerminal();
                    termWrapper.style.display = 'block';
                    openTermBtn.style.display = 'none';
                    closeTermBtn.style.display = '';
                    ws = new WebSocket(wsUrl);
                    ws.binaryType = 'arraybuffer';
                    ws.onopen = () => {
                        try { fitAddon && fitAddon.fit(); } catch {}
                        const cols = term.cols || 80, rows = term.rows || 24;
                        try { ws.send(JSON.stringify({ type: 'resize', cols, rows })); } catch {}
                        ws.__kalive = setInterval(() => { try { ws.send('\u0000'); } catch {} }, 25000);
                        try {
                            const AttachCtor = (window.AttachAddon && (window.AttachAddon.AttachAddon || window.AttachAddon)) ? (window.AttachAddon.AttachAddon || window.AttachAddon) : null;
                            if (AttachCtor) {
                                const attach = new AttachCtor(ws, { bidirectional: true, useUtf8: true });
                                term.loadAddon(attach);
                            } else {
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
            if (deploymentDetailsContent) {
                deploymentDetailsContent.innerHTML = `
                    <div class="error-message">
                        <i class="fas fa-exclamation-triangle"></i>
                        <p>Erreur lors du chargement des détails: ${error.message}</p>
                    </div>
                `;
            }
        }
    }

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

    function applyLifecycleStateToLabCard(deploymentId, lifecycle) {
        const card = document.getElementById(deploymentId);
        if (!card) {
            return;
        }
        const stateValue = (lifecycle && lifecycle.state) || 'unknown';
        card.dataset.lifecycleState = stateValue;
        const statusIndicator = card.querySelector('.status-indicator');
        const availabilityBlock = document.getElementById(`app-status-${deploymentId}`);
        const accessBtn = document.getElementById(`access-btn-${deploymentId}`);
        const pauseBtn = card.querySelector(`.btn-toggle-pause[data-name="${deploymentId}"]`);

        if (stateValue === 'paused') {
            card.classList.add('lab-paused');
            card.classList.remove('lab-ready', 'lab-pending', 'lab-error');
            if (statusIndicator) {
                statusIndicator.className = 'status-indicator paused';
                statusIndicator.innerHTML = '<i class="fas fa-circle-pause"></i> En pause';
            }
            if (availabilityBlock) {
                availabilityBlock.className = 'app-availability paused';
                availabilityBlock.innerHTML = `
                    <i class="fas fa-circle-pause app-availability-icon"></i>
                    <span class="app-availability-text">Application en pause. Cliquez sur "Reprendre" pour la relancer.</span>
                `;
            }
            if (accessBtn) {
                accessBtn.classList.add('disabled');
                accessBtn.innerHTML = '<i class="fas fa-circle-pause"></i> En pause';
            }
            if (pauseBtn) {
                pauseBtn.setAttribute('data-action', 'resume');
                if (pauseBtn.dataset.variant === 'text') {
                    pauseBtn.innerHTML = '<i class="fas fa-circle-play"></i> Reprendre';
                } else {
                    pauseBtn.innerHTML = '<i class="fas fa-circle-play"></i>';
                }
            }
        } else {
            card.classList.remove('lab-paused');
            if (statusIndicator && statusIndicator.classList.contains('paused')) {
                statusIndicator.className = 'status-indicator pending';
                statusIndicator.innerHTML = '<i class="fas fa-spinner fa-spin"></i> En préparation...';
            }
            if (availabilityBlock && availabilityBlock.classList.contains('paused')) {
                availabilityBlock.className = 'app-availability pending';
                availabilityBlock.innerHTML = `
                    <i class="fas fa-hourglass-half app-availability-icon"></i>
                    <span class="app-availability-text">L'application redémarre...</span>
                `;
            }
            if (accessBtn && accessBtn.classList.contains('disabled')) {
                accessBtn.classList.remove('disabled');
                accessBtn.innerHTML = '<i class="fas fa-external-link-alt"></i> Accéder';
            }
            if (pauseBtn) {
                pauseBtn.setAttribute('data-action', 'pause');
                if (pauseBtn.dataset.variant === 'text') {
                    pauseBtn.innerHTML = '<i class="fas fa-circle-pause"></i> Pause';
                } else {
                    pauseBtn.innerHTML = '<i class="fas fa-circle-pause"></i>';
                }
            }
        }
    }

    function addLabCard(labDetails) {
        if (noLabsMessage) {
            noLabsMessage.style.display = 'none';
        }

        const card = document.createElement('div');
        card.classList.add('card', 'lab-card');
        const lifecycleState = (labDetails.lifecycle && labDetails.lifecycle.state) || null;
        const isPaused = lifecycleState === 'paused' || labDetails.isPaused;
        if (isPaused) {
            card.classList.add('lab-paused');
        } else {
            card.classList.add(labDetails.ready ? 'lab-ready' : 'lab-pending');
        }
        card.id = labDetails.id;
        card.dataset.namespace = labDetails.namespace;
        card.dataset.deploymentType = labDetails.deploymentType || '';
        card.dataset.serviceName = labDetails.name || labDetails.id;

        let datasetsHtml = '';
        if (labDetails.datasets && labDetails.datasets.length > 0) {
            datasetsHtml = `<div class="lab-datasets"><i class="fas fa-database"></i><span>Datasets: ${labDetails.datasets.join(', ')}</span></div>`;
        }

        const isNetbeans = labDetails.deploymentType === 'netbeans';
        const embedButtonHtml = isNetbeans ? `
                <button type="button" class="btn btn-secondary embed-novnc-btn ${labDetails.ready ? '' : 'disabled'}" data-novnc-target="${labDetails.id}" data-namespace="${labDetails.namespace}" ${labDetails.ready ? '' : 'disabled'}>
                    <i class="fas fa-desktop"></i> ${labDetails.ready ? 'Ouvrir dans la page' : 'En attente NoVNC...'}
                </button>
        ` : '';

        let statusIndicator = '<span class="status-indicator pending"><i class="fas fa-spinner fa-spin"></i> En préparation...</span>';
        if (isPaused) {
            statusIndicator = '<span class="status-indicator paused"><i class="fas fa-circle-pause"></i> En pause</span>';
        } else if (labDetails.ready) {
            statusIndicator = '<span class="status-indicator ready"><i class="fas fa-check-circle"></i> Prêt</span>';
        }

        const availabilityHtml = isPaused ? `
            <div class="app-availability paused" id="app-status-${labDetails.id}">
                <i class="fas fa-circle-pause app-availability-icon"></i>
                <span class="app-availability-text">L'application est en pause, aucune ressource n'est consommée.</span>
            </div>
        ` : labDetails.ready ? `
            <div class="app-availability ready" id="app-status-${labDetails.id}">
                <i class="fas fa-check-circle app-availability-icon"></i>
                <span class="app-availability-text">L'application est prête à être utilisée</span>
            </div>
        ` : `
            <div class="app-availability pending" id="app-status-${labDetails.id}">
                <i class="fas fa-hourglass-half app-availability-icon"></i>
                <span class="app-availability-text">L'application est en cours d'initialisation</span>
            </div>
        `;

        const pauseButtonHtml = `
            <button class="btn btn-warning btn-toggle-pause" data-name="${labDetails.id}" data-namespace="${labDetails.namespace}" data-action="${isPaused ? 'resume' : 'pause'}" data-variant="text">
                <i class="fas ${isPaused ? 'fa-circle-play' : 'fa-circle-pause'}"></i> ${isPaused ? 'Reprendre' : 'Pause'}
            </button>
        `;

        card.innerHTML = `
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
            ${availabilityHtml}
            <div class="lab-actions">
                <a href="${labDetails.link}" target="_blank" class="btn btn-primary ${labDetails.ready ? '' : 'disabled'}" id="access-btn-${labDetails.id}">
                    <i class="fas fa-external-link-alt"></i> ${labDetails.ready ? 'Accéder' : 'En préparation...'}
                </a>
                ${embedButtonHtml}
                <button class="btn btn-secondary btn-details" data-id="${labDetails.id}" data-namespace="${labDetails.namespace}">
                    <i class="fas fa-info-circle"></i> Détails
                </button>
                ${pauseButtonHtml}
                <button class="btn btn-danger stop-lab-btn" data-id="${labDetails.id}" data-namespace="${labDetails.namespace}">
                    <i class="fas fa-stop-circle"></i> Arrêter
                </button>
            </div>
        `;

        activeLabsList.appendChild(card);
        bindPauseButtons(card);

        if (isNetbeans) {
            registerNovncEndpoint(labDetails.id, labDetails.namespace, {
                nodePort: labDetails.nodePort,
                urlTemplate: labDetails.urlTemplate,
                url: labDetails.link && !labDetails.link.includes('IP_DU_NOEUD') && !labDetails.link.includes('NODE_PORT') ? labDetails.link : undefined,
                protocol: labDetails.protocol,
                secure: labDetails.secure,
                credentials: labDetails.credentials,
            });
        }

        bindNovncButtons(card);
        if (isNetbeans) {
            updateNovncButtonsAvailability(labDetails.id);
        }

        if (labDetails.lifecycle) {
            applyLifecycleStateToLabCard(labDetails.id, labDetails.lifecycle);
        } else if (isPaused) {
            applyLifecycleStateToLabCard(labDetails.id, { state: 'paused' });
        }

        card.querySelector('.btn-details').addEventListener('click', (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            const namespace = e.currentTarget.getAttribute('data-namespace');
            showDeploymentDetails(namespace, id);
        });

        card.querySelector('.stop-lab-btn').addEventListener('click', (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            const namespace = e.currentTarget.getAttribute('data-namespace');
            stopLab(id, namespace);
        });

        if (labDetails.link.includes('<IP_DU_NOEUD>') || labDetails.link.includes('<IP_EXTERNE>')) {
            fetchDeploymentAccessUrl(labDetails.namespace, labDetails.id);
        }

        if (!labDetails.ready && !isPaused) {
            checkDeploymentReadiness(labDetails.namespace, labDetails.id);
        }
    }

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
                }
                if (state.currentStatusDeployment && state.currentStatusDeployment.id === name) {
                    const currentState = state.currentStatusDeployment.state || 'pending';
                    updateStatusViewForDeployment(name, currentState, { accessUrl });
                }
            }
        } catch (error) {
            console.error(`Erreur lors de la récupération de l'URL d'accès pour ${name}:`, error);
        }
    }

    function refreshActiveLabs() {
        fetch(`${API_V1}/k8s/deployments/labondemand`).then(resp => resp.json()).then(data => {
            const deployments = data.deployments || [];
            const labCards = document.querySelectorAll('.lab-card');
            labCards.forEach(card => {
                const deploymentId = card.id;
                const deploymentNamespace = card.dataset.namespace;
                const deploymentExists = deployments.some(d =>
                    d.name === deploymentId && d.namespace === deploymentNamespace
                );
                if (!deploymentExists) {
                    const timerKey = `${deploymentNamespace}-${deploymentId}`;
                    if (state.deploymentCheckTimers.has(timerKey)) {
                        clearTimeout(state.deploymentCheckTimers.get(timerKey));
                        state.deploymentCheckTimers.delete(timerKey);
                    }
                    card.remove();
                }
            });
            if (activeLabsList.children.length === 0 ||
                (activeLabsList.children.length === 1 && activeLabsList.children[0].classList.contains('no-labs-message'))) {
                if (noLabsMessage) noLabsMessage.style.display = 'block';
            } else if (noLabsMessage) {
                noLabsMessage.style.display = 'none';
            }
        }).catch(error => {
            console.error('Erreur lors du rafraîchissement des labs actifs:', error);
        });
    }

    async function checkDeploymentReadiness(namespace, name, attempts = 0) {
        const maxAttempts = 60;
        try {
            const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${name}/details`);
            if (response.status === 404) {
                const timerKey = `${namespace}-${name}`;
                clearTimeout(state.deploymentCheckTimers.get(timerKey));
                state.deploymentCheckTimers.delete(timerKey);
                const card = document.getElementById(name);
                const serviceName = card?.dataset?.serviceName || name;
                updateStatusViewForDeployment(name, 'deleted', { serviceName });
                if (card) {
                    card.remove();
                }
                if (noLabsMessage && activeLabsList.children.length === 0) {
                    noLabsMessage.style.display = 'block';
                }
                return;
            }
            if (response.status === 500 && attempts >= 5) {
                clearTimeout(state.deploymentCheckTimers.get(`${namespace}-${name}`));
                state.deploymentCheckTimers.delete(`${namespace}-${name}`);
                updateLabCardStatus(name, false, null, true);
                return;
            }
            if (!response.ok) {
                throw new Error(`Erreur ${response.status}: ${response.statusText}`);
            }
            const data = await response.json();
            if (data.lifecycle) {
                applyLifecycleStateToLabCard(name, data.lifecycle);
                if (data.lifecycle.state === 'paused') {
                    const pausedKey = `${namespace}-${name}`;
                    if (state.deploymentCheckTimers.has(pausedKey)) {
                        clearTimeout(state.deploymentCheckTimers.get(pausedKey));
                        state.deploymentCheckTimers.delete(pausedKey);
                    }
                    return;
                }
            }
            const available = (data.deployment && (data.deployment.available_replicas || 0) > 0);
            const podsReady = Array.isArray(data.pods) && data.pods.length > 0 && data.pods.every(pod => pod.status === 'Running');
            if (available && podsReady) {
                updateLabCardStatus(name, true, data);
                clearTimeout(state.deploymentCheckTimers.get(`${namespace}-${name}`));
                state.deploymentCheckTimers.delete(`${namespace}-${name}`);
                return;
            }
            if (attempts < maxAttempts) {
                const timerId = setTimeout(() => {
                    checkDeploymentReadiness(namespace, name, attempts + 1);
                }, 5000);
                state.deploymentCheckTimers.set(`${namespace}-${name}`, timerId);
            } else {
                updateLabCardStatus(name, false, data, true);
                clearTimeout(state.deploymentCheckTimers.get(`${namespace}-${name}`));
                state.deploymentCheckTimers.delete(`${namespace}-${name}`);
            }
        } catch (error) {
            console.error(`Erreur lors de la vérification du déploiement ${name}:`, error);
            if (attempts < maxAttempts && !error.message.includes('404')) {
                const timerId = setTimeout(() => {
                    checkDeploymentReadiness(namespace, name, attempts + 1);
                }, 5000);
                state.deploymentCheckTimers.set(`${namespace}-${name}`, timerId);
            } else {
                clearTimeout(state.deploymentCheckTimers.get(`${namespace}-${name}`));
                state.deploymentCheckTimers.delete(`${namespace}-${name}`);
            }
        }
    }

    function updateLabCardStatus(deploymentId, isReady, deploymentData, timeout = false) {
        const card = document.getElementById(deploymentId);
        if (!card) return;
        if (card.dataset.lifecycleState === 'paused' && !isReady && !timeout) {
            return;
        }
        const serviceName = card.dataset.serviceName || deploymentId;
        let resolvedAccessUrl = '';
        if (isReady) {
            card.classList.remove('lab-pending');
            card.classList.add('lab-ready');
            card.classList.add('status-changed');
            setTimeout(() => card.classList.remove('status-changed'), 2000);
        } else if (timeout) {
            card.classList.remove('lab-pending');
            card.classList.add('lab-error');
        }
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
        const accessBtn = document.getElementById(`access-btn-${deploymentId}`);
        if (accessBtn) {
            if (isReady) {
                accessBtn.classList.remove('disabled');
                accessBtn.innerHTML = '<i class="fas fa-external-link-alt"></i> Accéder';
                if (deploymentData && Array.isArray(deploymentData.access_urls) && deploymentData.access_urls.length > 0) {
                    const accessUrl = deploymentData.access_urls[0].url;
                    accessBtn.href = accessUrl;
                    resolvedAccessUrl = accessUrl;
                } else if (accessBtn.href) {
                    resolvedAccessUrl = accessBtn.href;
                }
            } else if (timeout) {
                accessBtn.innerHTML = '<i class="fas fa-exclamation-circle"></i> Vérifier les détails';
            }
        }
        if (card.dataset.deploymentType === 'netbeans') {
            if (isReady && deploymentData) {
                const novncInfo = extractNovncInfoFromDetails(deploymentData);
                registerNovncEndpoint(deploymentId, card.dataset.namespace, {
                    nodePort: novncInfo.nodePort,
                    url: novncInfo.url,
                    hostname: novncInfo.hostname,
                    protocol: novncInfo.protocol,
                    secure: novncInfo.secure,
                });
            }
            updateNovncButtonsAvailability(deploymentId);
        }
        if (isReady) {
            const overrides = { serviceName };
            if (resolvedAccessUrl) {
                overrides.accessUrl = resolvedAccessUrl;
            }
            updateStatusViewForDeployment(deploymentId, 'ready', overrides);
        } else if (timeout) {
            updateStatusViewForDeployment(deploymentId, 'timeout', { serviceName });
        }
    }

    async function stopLab(labId, namespace) {
        if (!confirm(`Êtes-vous sûr de vouloir arrêter l'application "${labId}" ?`)) {
            return;
        }
        try {
            const response = await fetch(`${API_V1}/k8s/deployments/${namespace}/${labId}?delete_service=true`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Erreur lors de la suppression du déploiement');
            }

            const labCard = document.getElementById(labId);
            if (labCard) {
                labCard.remove();
                fetchAndRenderDeployments();
                try {
                    await refreshPvcs({ render: true, force: true });
                    populatePvcSelect();
                } catch (error) {
                    console.warn('Impossible de rafraîchir les PVC après arrêt:', error);
                }
                if (activeLabsList.children.length === 0 || (activeLabsList.children.length === 1 && activeLabsList.children[0].classList.contains('no-labs-message'))) {
                    if (noLabsMessage) noLabsMessage.style.display = 'block';
                }
            }
        } catch (error) {
            console.error('Erreur:', error);
            alert(`Erreur lors de l'arrêt de l'application: ${error.message}`);
        }
    }

    function clearAllDeploymentTimers() {
        for (const [key, timerId] of state.deploymentCheckTimers.entries()) {
            clearTimeout(timerId);
        }
        state.deploymentCheckTimers.clear();
    }

    return {
        fetchAndRenderNamespaces,
        fetchAndRenderPods,
        fetchAndRenderDeployments,
        showDeploymentDetails,
        addLabCard,
        refreshActiveLabs,
        checkDeploymentReadiness,
        updateLabCardStatus,
        fetchDeploymentAccessUrl,
        stopLab,
        applyLifecycleStateToLabCard,
        clearAllDeploymentTimers,
    };
}
