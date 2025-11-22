// Importation du gestionnaire d'authentification et des modules du tableau de bord
import authManager from './js/auth.js';
import { createDashboardState } from './js/dashboard/state.js';
import { createNovncModule } from './js/dashboard/novnc.js';
import { createStatusView } from './js/dashboard/statusView.js';
import { createResourceModule } from './js/dashboard/resources.js';
import { createDeploymentsModule } from './js/dashboard/deployments.js';
import { escapeHtml } from './js/dashboard/utils.js';

function createDashboardApp() {
    const API_V1 = '/api/v1';
    const state = createDashboardState();

    async function init() {
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
        const serviceGuidanceBox = document.getElementById('service-guidance');
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
        const novncModal = document.getElementById('novnc-modal');
        const novncModalTitle = document.getElementById('novnc-modal-title');
        const novncFrame = document.getElementById('novnc-frame');
        const novncStatusBanner = document.getElementById('novnc-status');
        const novncCredentialsBox = document.getElementById('novnc-credentials');
        const pvcListContainer = document.getElementById('pvc-list');
        const refreshPvcsBtn = document.getElementById('refresh-pvcs');
        const pvcSelectGroup = document.getElementById('persistent-volume-group');
        const existingPvcSelect = document.getElementById('existing-pvc-select');
        const refreshDashboardBtn = document.getElementById('refresh-dashboard');
        const statActiveAppsEl = document.getElementById('stat-active-apps');
        const statReadyAppsEl = document.getElementById('stat-ready-apps');
        const statPvcsEl = document.getElementById('stat-persistent-volumes');
        const statQuotaAppsEl = document.getElementById('stat-quota-apps');
        const adminPvcsPanel = document.getElementById('admin-pvc-panel');
        const adminPvcsList = document.getElementById('admin-pvcs-list');
        const refreshAdminPvcsBtn = document.getElementById('refresh-admin-pvcs');
        const pvcSectionToggle = document.getElementById('pvc-section-toggle');
        const pvcResources = document.getElementById('pvc-resources');
        const showPvcPanelBtn = document.getElementById('show-pvc-panel-btn');
        const pvcStatTotal = document.getElementById('pvc-stat-total');
        const pvcStatBound = document.getElementById('pvc-stat-bound');
        const deploymentDetailsModal = document.getElementById('deployment-details-modal');
        const deploymentDetailsContent = document.getElementById('deployment-details-content');

        const novncModule = createNovncModule({
            API_V1,
            state,
            elements: {
                novncModal,
                novncModalTitle,
                novncFrame,
                novncStatusBanner,
                novncCredentialsBox,
            },
        });

        const statusViewModule = createStatusView({
            state,
            elements: { statusContent, statusActions },
            novnc: novncModule,
        });

        const resourcesModule = createResourceModule({
            API_V1,
            state,
            elements: {
                quotasContent,
                statActiveAppsEl,
                statReadyAppsEl,
                statPvcsEl,
                statQuotaAppsEl,
                pvcStatTotal,
                pvcStatBound,
                pvcListContainer,
                existingPvcSelect,
                pvcSelectGroup,
                adminPvcsList,
            },
        });

        const deploymentsModule = createDeploymentsModule({
            API_V1,
            state,
            elements: {
                activeLabsList,
                noLabsMessage,
                deploymentDetailsModal,
                deploymentDetailsContent,
            },
            novnc: novncModule,
            statusView: statusViewModule,
            resources: resourcesModule,
        });

        const {
            fetchAndRenderNamespaces,
            fetchAndRenderPods,
            fetchAndRenderDeployments,
            showDeploymentDetails,
            addLabCard,
            refreshActiveLabs,
            clearAllDeploymentTimers,
        } = deploymentsModule;

        const { renderStatusView, renderServicePortsSummary, renderConnectionHints } = statusViewModule;

        const { fetchMyQuotas, refreshQuotas, refreshPvcs, populatePvcSelect, refreshAdminPvcs } = resourcesModule;

        const { registerNovncEndpoint, resetNovncModal, extractNovncInfoFromDetails } = novncModule;

        function bindCollapsibleToggle(trigger, content) {
            if (!trigger || !content) {
                return;
            }
            trigger.addEventListener('click', () => {
                const isActive = !trigger.classList.contains('active');
                trigger.classList.toggle('active', isActive);
                trigger.setAttribute('aria-expanded', String(isActive));
                content.classList.toggle('active', isActive);
            });
        }

        async function refreshDashboardData() {
            const jobs = [
                fetchAndRenderDeployments(),
                refreshPvcs({ render: true, force: true }),
            ];
            if (quotasContent) {
                jobs.push(refreshQuotas());
            }
            if (authManager.isAdmin() || authManager.isTeacher()) {
                jobs.push(refreshAdminPvcs({ force: true }));
            }
            const outcomes = await Promise.allSettled(jobs);
            outcomes.forEach(result => {
                if (result.status === 'rejected') {
                    console.warn('Dashboard refresh error', result.reason);
                }
            });
        }

        function bindDashboardActions() {
            if (refreshQuotasBtn && !refreshQuotasBtn.dataset.bound) {
                refreshQuotasBtn.dataset.bound = '1';
                refreshQuotasBtn.addEventListener('click', async () => {
                    refreshQuotasBtn.disabled = true;
                    try {
                        await refreshQuotas();
                    } catch (error) {
                        console.error('Erreur lors du rafraîchissement des quotas', error);
                    } finally {
                        refreshQuotasBtn.disabled = false;
                    }
                });
            }

            if (refreshPvcsBtn && !refreshPvcsBtn.dataset.bound) {
                refreshPvcsBtn.dataset.bound = '1';
                refreshPvcsBtn.addEventListener('click', async () => {
                    refreshPvcsBtn.disabled = true;
                    try {
                        await refreshPvcs({ render: true, force: true });
                    } catch (error) {
                        console.error('Erreur lors du rafraîchissement des PVC', error);
                    } finally {
                        refreshPvcsBtn.disabled = false;
                    }
                });
            }

            if (refreshAdminPvcsBtn && !refreshAdminPvcsBtn.dataset.bound) {
                refreshAdminPvcsBtn.dataset.bound = '1';
                refreshAdminPvcsBtn.addEventListener('click', async () => {
                    refreshAdminPvcsBtn.disabled = true;
                    try {
                        await refreshAdminPvcs({ force: true });
                    } catch (error) {
                        console.error('Erreur lors du rafraîchissement des PVC administrateur', error);
                    } finally {
                        refreshAdminPvcsBtn.disabled = false;
                    }
                });
            }

            if (refreshDashboardBtn && !refreshDashboardBtn.dataset.bound) {
                refreshDashboardBtn.dataset.bound = '1';
                refreshDashboardBtn.addEventListener('click', async () => {
                    refreshDashboardBtn.disabled = true;
                    refreshDashboardBtn.setAttribute('aria-busy', 'true');
                    try {
                        await refreshDashboardData();
                    } finally {
                        refreshDashboardBtn.disabled = false;
                        refreshDashboardBtn.removeAttribute('aria-busy');
                    }
                });
            }

            if (showPvcPanelBtn && !showPvcPanelBtn.dataset.bound) {
                showPvcPanelBtn.dataset.bound = '1';
                showPvcPanelBtn.addEventListener('click', () => {
                    if (pvcSectionToggle && pvcResources) {
                        pvcSectionToggle.classList.add('active');
                        pvcResources.classList.add('active');
                        pvcResources.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                });
            }

            bindCollapsibleToggle(pvcSectionToggle, pvcResources);
            bindCollapsibleToggle(k8sSectionToggle, k8sResources);
        }

        function initUserInfo() {
            const displayName = escapeHtml(authManager.getUserDisplayName() || 'Utilisateur');
            const role = authManager.getUserRole();
            const roleLabels = { admin: 'Administrateur', teacher: 'Enseignant', student: 'Étudiant' };
            if (userGreeting) {
                const roleLabel = roleLabels[role] ? ` · ${roleLabels[role]}` : '';
                userGreeting.innerHTML = `Bonjour, ${displayName}${roleLabel}`;
            }
            if (logoutBtn && !logoutBtn.dataset.bound) {
                logoutBtn.dataset.bound = '1';
                logoutBtn.addEventListener('click', async () => {
                    await authManager.logout();
                });
            }
        }

        async function checkApiStatus() {
            if (apiStatusEl) {
                apiStatusEl.textContent = 'Vérification...';
                apiStatusEl.dataset.status = 'loading';
            }
            const status = { api: false, k8s: false };
            try {
                const apiResp = await fetch(`${API_V1}/status`, { credentials: 'include' });
                status.api = apiResp.ok;
            } catch (error) {
                status.api = false;
            }
            try {
                const k8sResp = await fetch(`${API_V1}/k8s/deployments/labondemand`, { credentials: 'include' });
                status.k8s = k8sResp.ok;
            } catch (error) {
                status.k8s = false;
            }
            if (apiStatusEl) {
                if (status.api && status.k8s) {
                    apiStatusEl.textContent = 'API et Kubernetes opérationnels';
                    apiStatusEl.dataset.status = 'ok';
                } else if (status.api) {
                    apiStatusEl.textContent = 'API OK – Kubernetes indisponible';
                    apiStatusEl.dataset.status = 'partial';
                } else {
                    apiStatusEl.textContent = 'API indisponible';
                    apiStatusEl.dataset.status = 'error';
                }
            }
            return status;
        }

        bindDashboardActions();

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
            } else if (serviceGuidanceBox) {
                serviceGuidanceBox.innerHTML = '';
                serviceGuidanceBox.classList.remove('active');
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
    function updateServiceGuidance(deploymentType) {
        if (!serviceGuidanceBox) {
            return;
        }
        const guidanceMap = {
            jupyter: {
                title: 'Jupyter Notebook',
                icon: 'fa-brands fa-python',
                description: 'Idéal pour les TP data science. Le volume persistant apparaît dans /home/jovyan.',
                tips: [
                    'Sélectionnez les datasets voulus avant le lancement.',
                    'Conservez le token affiché dans le panneau de statut.',
                ],
            },
            vscode: {
                title: 'VS Code Browser',
                icon: 'fa-solid fa-code',
                description: 'Bureau VS Code prêt à l’emploi avec extensions essentielles.',
                tips: [
                    'Réutilisez vos volumes existants pour retrouver vos projets.',
                    'Le mode pause libère les ressources sans perdre vos fichiers.',
                ],
            },
            netbeans: {
                title: 'NetBeans via NoVNC',
                icon: 'fa-solid fa-desktop',
                description: 'NetBeans complet accessible dans le navigateur (flux NoVNC).',
                tips: [
                    'Le bouton "Bureau intégré" apparaît quand le service est prêt.',
                    'Utilisez pause/reprise pour conserver vos réglages.',
                ],
            },
            custom: {
                title: 'Déploiement personnalisé',
                icon: 'fa-solid fa-cube',
                description: 'Spécifiez votre image Docker et les ports à exposer.',
                tips: [
                    'Vérifiez que vos ports cibles correspondent au service Kubernetes.',
                    'Ajoutez un PVC si votre conteneur doit persister des données.',
                ],
            },
        };
        const info = guidanceMap[deploymentType];
        if (!info) {
            serviceGuidanceBox.classList.remove('active');
            serviceGuidanceBox.innerHTML = '';
            return;
        }
        const tipsHtml = info.tips.map(tip => `<li><i class="fas fa-check"></i> ${tip}</li>`).join('');
        serviceGuidanceBox.innerHTML = `
            <h4><i class="fas ${info.icon}"></i> ${info.title}</h4>
            <p>${info.description}</p>
            <ul>${tipsHtml}</ul>
        `;
        serviceGuidanceBox.classList.add('active');
    }

    function bindServiceCard(card) {
        card.addEventListener('click', async () => {
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
            if (existingPvcSelect) {
                existingPvcSelect.value = '';
            }

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
            } else if (deploymentType === 'vscode') {
                const cpuSelect = document.getElementById('cpu');
                if (cpuSelect) cpuSelect.value = 'low';
            } else if (deploymentType === 'netbeans') {
                const cpuSelect = document.getElementById('cpu');
                const ramSelect = document.getElementById('ram');
                if (cpuSelect) cpuSelect.value = 'medium';
                if (ramSelect) ramSelect.value = 'high';
            }

            // Rétablir le nom par défaut (après reset)
            document.getElementById('deployment-name').value = deploymentName.value;

            try {
                if (['vscode', 'jupyter'].includes(deploymentType)) {
                    await refreshPvcs({ render: true });
                }
            } catch (error) {
                console.warn('Impossible de rafraîchir les PVC avant configuration:', error);
            }
            populatePvcSelect(deploymentType);
            updateServiceGuidance(deploymentType);

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
                const studentCpuPreset = deploymentType === 'vscode' ? 'low' : 'medium';
                // Étudiants: pas de choix CPU/RAM ni de replicas; valeurs imposées et clamp backend
                if (cpuSelect) {
                    cpuSelect.value = studentCpuPreset;
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
            } else if (deploymentType === 'netbeans') {
                image = 'tutanka01/labondemand:netbeansjava';
                createService = true;
                serviceType = 'NodePort';
                servicePort = 6901;
                serviceTargetPort = 6901;
            } else if (deploymentType === 'wordpress') {
                // WordPress: l'image sera ignorée côté serveur (bitnamilegacy/wordpress), mais on garde NodePort 8080
                image = 'bitnamilegacy/wordpress:6.8.2-debian-12-r5';
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
            state.currentStatusDeployment = null;
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

                if ((deploymentType === 'vscode' || deploymentType === 'jupyter') && existingPvcSelect && existingPvcSelect.value) {
                    params.append('existing_pvc_name', existingPvcSelect.value);
                }
                
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
                
                const serviceInfo = data.service_info || {};
                const portsDetails = Array.isArray(serviceInfo.ports_detail) ? serviceInfo.ports_detail : [];
                const connectionHints = data.connection_hints || null;

                // Construire les infos du lab à ajouter au dashboard
                state.labCounter++;
                const labId = deploymentName;
                const effectiveNamespace = data.namespace || 'labondemand-user';

                if (deploymentType === 'netbeans') {
                    state.lastLaunchedDeployment = { id: labId, namespace: effectiveNamespace };
                } else {
                    state.lastLaunchedDeployment = null;
                }

                // Extraire l'URL d'accès des infos de retour (ou générer une URL factice en attendant de récupérer l'URL réelle)
                let accessUrl = '';
                let nodePort = serviceInfo.node_port ?? '';
                if (nodePort && typeof nodePort !== 'string') nodePort = String(nodePort);

                if (portsDetails.length) {
                    const firstWithNode = portsDetails.find(detail => detail && detail.node_port);
                    if (!nodePort && firstWithNode && firstWithNode.node_port) {
                        nodePort = String(firstWithNode.node_port);
                    }
                }

                const prefersHttps = (() => {
                    if (connectionHints?.novnc) {
                        const hintProtocol = (connectionHints.novnc.protocol || '').toLowerCase();
                        if (hintProtocol === 'https') return true;
                        if (hintProtocol === 'http') return false;
                        if (connectionHints.novnc.secure === true) return true;
                    }
                    return false;
                })();

                if (connectionHints?.novnc) {
                    const hint = connectionHints.novnc;
                    if (!nodePort && hint.node_port) {
                        nodePort = String(hint.node_port);
                    }
                    if (hint.url_template) {
                        accessUrl = hint.node_port
                            ? hint.url_template.replace('<NODE_PORT>', hint.node_port)
                            : hint.url_template;
                    } else if (hint.node_port) {
                        const hintProtocol = (hint.protocol || (hint.secure ? 'https' : null) || (prefersHttps ? 'https' : 'http')).toLowerCase();
                        const scheme = hintProtocol === 'http' ? 'http' : 'https';
                        accessUrl = `${scheme}://<IP_DU_NOEUD>:${hint.node_port}/`;
                    }
                }

                // Parser la réponse pour extraire des informations supplémentaires
                if (data.message) {
                    const nodePortMatch = data.message.match(/NodePort: (\d+)/);
                    if (!nodePort && nodePortMatch && nodePortMatch[1]) {
                        nodePort = nodePortMatch[1];
                    }
                    const urlMatch = data.message.match(/(https?:\/\/[^\s"'<>]+)/);
                    if (!accessUrl && urlMatch && urlMatch[1]) {
                        accessUrl = urlMatch[1];
                    }
                }

                if (!accessUrl && nodePort) {
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

                    if (!accessUrl) {
                        const fallbackScheme = prefersHttps ? 'https' : 'http';
                        accessUrl = nodePort ? `${fallbackScheme}://<IP_DU_NOEUD>:${nodePort}/` : '';
                    }
                } else if (!accessUrl) {
                    const scheme = prefersHttps ? 'https' : 'http';
                    if (serviceType === 'NodePort' || serviceType === 'LoadBalancer') {
                        accessUrl = `${scheme}://<IP_EXTERNE>:${servicePort}/`;
                    } else {
                        accessUrl = `${scheme}://${deploymentName}-service:${servicePort}/`;
                    }
                }

                if (accessUrl && accessUrl.includes('<')) {
                    accessUrl = accessUrl
                        .replace(/<IP_DU_NOEUD>/g, 'IP_DU_NOEUD')
                        .replace(/<IP_EXTERNE>/g, 'IP_EXTERNE')
                        .replace(/<NODE_PORT>/g, nodePort || 'NODE_PORT');
                }

                if (deploymentType === 'netbeans') {
                    const novncCredentials = connectionHints?.novnc ? {
                        username: connectionHints.novnc.username,
                        password: connectionHints.novnc.password,
                    } : undefined;
                    registerNovncEndpoint(labId, effectiveNamespace, {
                        nodePort: nodePort ? Number(nodePort) : undefined,
                        urlTemplate: connectionHints?.novnc?.url_template,
                        url: accessUrl && !accessUrl.includes('<') ? accessUrl : undefined,
                        protocol: connectionHints?.novnc?.protocol || 'http',
                        secure: connectionHints?.novnc?.secure ?? false,
                        credentials: novncCredentials,
                    });
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
                    ready: false,
                    lifecycle: { state: 'starting', paused: false },
                    deploymentType,
                    nodePort: nodePort ? Number(nodePort) : undefined,
                    urlTemplate: connectionHints?.novnc?.url_template,
                    protocol: connectionHints?.novnc?.protocol || (prefersHttps ? 'https' : 'http'),
                    secure: connectionHints?.novnc?.secure ?? prefersHttps,
                    credentials: connectionHints?.novnc ? {
                        username: connectionHints.novnc.username,
                        password: connectionHints.novnc.password,
                    } : undefined
                });

                try {
                    await refreshPvcs({ render: true, force: true });
                } catch (error) {
                    console.warn('Impossible de rafraîchir les PVC après création:', error);
                }

                // Mettre à jour la liste des déploiements
                fetchAndRenderDeployments();

                const portsSummaryHtml = renderServicePortsSummary(portsDetails, serviceInfo.type);
                const connectionHintsHtml = renderConnectionHints(connectionHints);
                const escapedMessage = escapeHtml(data.message || '');

                const inlineNovncBlock = deploymentType === 'netbeans' ? `
                    <div class="novnc-inline-card">
                        <h4><i class="fas fa-desktop"></i> Bureau intégré NoVNC</h4>
                        <p id="inline-novnc-hint">La session NoVNC sera disponible dès que le service sera prêt.</p>
                        <button type="button" class="btn btn-primary embed-novnc-btn disabled" data-novnc-target="${labId}" data-namespace="${effectiveNamespace}" disabled>
                            <i class="fas fa-desktop"></i> Ouvrir dans la page
                        </button>
                    </div>
                ` : '';

                state.currentStatusDeployment = {
                    id: labId,
                    namespace: effectiveNamespace,
                    serviceName,
                    message: escapedMessage,
                    portsSummaryHtml,
                    connectionHintsHtml,
                    inlineNovncBlock,
                    accessUrl,
                    deploymentType,
                };

                renderStatusView('pending');
                
            } catch (error) {
                console.error('Erreur:', error);
                statusContent.innerHTML = `
                    <i class="fas fa-exclamation-triangle status-icon" style="color: var(--error-color);"></i>
                    <h2>Erreur lors du lancement</h2>
                    <p>Une erreur est survenue lors du déploiement de ${serviceName} :</p>
                    <div class="error-message">${error.message}</div>
                `;
                statusActions.style.display = 'block'; // Afficher le bouton "Terminé" même en cas d'erreur
                state.currentStatusDeployment = null;
            }
        });
    }


    // --- Modal Management ---
    document.querySelectorAll('.close-modal, .close-modal-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.modal.show').forEach(modal => {
                if (modal.id === 'novnc-modal') {
                    resetNovncModal();
                }
                modal.classList.remove('show');
            });
        });
    });

    document.getElementById('cancel-delete').addEventListener('click', () => {
        document.getElementById('delete-modal').classList.remove('show');
    });

    if (novncModal) {
        novncModal.addEventListener('click', (event) => {
            if (event.target === novncModal) {
                resetNovncModal();
                novncModal.classList.remove('show');
            }
        });
    }

    // --- Initialisation ---
    async function init() {
        // Nettoyer tous les timers existants au démarrage
        clearAllDeploymentTimers();
        
    initUserInfo();
    if (quotasContent) { refreshQuotas(); }
    try {
        await refreshPvcs({ render: true, force: true });
    } catch (error) {
        console.warn('Impossible de charger les PVC au démarrage:', error);
    }
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
                    if (adminPvcsPanel) {
                        refreshAdminPvcs({ force: true }).catch(err => {
                            console.warn('Chargement des PVC admin impossible au démarrage', err);
                        });
                    }
                } else {
                    // Afficher un message clair dans les panneaux K8s
                    ['namespaces-list', 'pods-list', 'deployments-list'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) {
                            el.innerHTML = '<div class="error-message">Kubernetes indisponible. Réessayez plus tard.</div>';
                        }
                    });
                    if (adminPvcsList) {
                        adminPvcsList.innerHTML = '<div class="error-message"><i class="fas fa-exclamation-triangle"></i> Kubernetes indisponible pour lister les volumes.</div>';
                    }
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
                            } else if (deployment.type === "netbeans") {
                                serviceIcon = "fa-solid fa-desktop";
                                serviceName = "NetBeans Desktop (NoVNC)";
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

                            let novncInfo = {};
                            if (deployment.type === 'netbeans') {
                                novncInfo = extractNovncInfoFromDetails(detailsData);
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
                                ready: isReady,
                                lifecycle: detailsData.lifecycle,
                                isPaused: deployment.is_paused,
                                deploymentType: deployment.type,
                                nodePort: novncInfo.nodePort,
                                urlTemplate: undefined,
                                protocol: novncInfo.protocol,
                                secure: novncInfo.secure,
                                credentials: deployment.type === 'netbeans' ? { username: 'kasm_user', password: 'password' } : undefined
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
            clearAllDeploymentTimers();
        });

        // Initialiser l'application
        init();

        // Afficher la vue dashboard au démarrage
        showView('dashboard-view');
    }

    return { init };
}

document.addEventListener('DOMContentLoaded', () => {
    const app = createDashboardApp();
    app.init().catch(error => {
        console.error('Erreur lors de l\'initialisation du dashboard', error);
    });
});