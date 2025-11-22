import { escapeHtml, mapPhaseToClass, formatIsoDateShort, pct, barClass } from './utils.js';

export function createResourceModule({ API_V1, state, elements }) {
    const {
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
    } = elements;

    async function fetchMyQuotas() {
        const resp = await fetch(`${API_V1}/quotas/me`, { credentials: 'include' });
        if (!resp.ok) throw new Error('Quotas indisponibles');
        return resp.json();
    }

    function updateDashboardStats() {
        if (statActiveAppsEl) {
            const total = document.querySelectorAll('.lab-card').length;
            statActiveAppsEl.textContent = String(total);
        }
        if (statReadyAppsEl) {
            const ready = document.querySelectorAll('.lab-card.lab-ready').length;
            statReadyAppsEl.textContent = String(ready);
        }
        if (statPvcsEl) {
            statPvcsEl.textContent = String(state.cachedPvcs.length);
        }
        if (statQuotaAppsEl) {
            const remaining = state.lastQuotaData && state.lastQuotaData.remaining ? state.lastQuotaData.remaining.apps : null;
            statQuotaAppsEl.textContent = typeof remaining === 'number' ? String(Math.max(remaining, 0)) : '—';
        }
        if (pvcStatTotal) {
            pvcStatTotal.textContent = String(state.cachedPvcs.length);
        }
        if (pvcStatBound) {
            const boundCount = state.cachedPvcs.filter(pvc => pvc.bound || (pvc.phase && pvc.phase.toLowerCase() === 'bound')).length;
            pvcStatBound.textContent = String(boundCount);
        }
    }

    function renderQuotasCard(data) {
        if (!quotasContent) return;
        state.lastQuotaData = data;
        const { limits, usage } = data || {};
        if (!limits || !usage) {
            quotasContent.innerHTML = `<div class="error-message"><i class="fas fa-exclamation-triangle"></i> Quotas indisponibles</div>`;
            updateDashboardStats();
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
        updateDashboardStats();
    }

    async function refreshQuotas() {
        if (!quotasContent) return;
        quotasContent.innerHTML = 'Chargement...';
        try {
            renderQuotasCard(await fetchMyQuotas());
        }
        catch (e) {
            quotasContent.innerHTML = `<div class="error-message"><i class=\"fas fa-exclamation-triangle\"></i> ${e.message || 'Erreur quotas'}</div>`;
            state.lastQuotaData = null;
            updateDashboardStats();
        }
    }

    async function fetchUserPvcs() {
        const resp = await fetch(`${API_V1}/k8s/pvcs`, { credentials: 'include' });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            const detail = err.detail || 'Impossible de récupérer les volumes persistants';
            throw new Error(detail);
        }
        return resp.json();
    }

    function handlePvcDelete(pvc) {
        const encodedName = encodeURIComponent(pvc.name);
        const boundMessage = pvc.bound ? '\nLe volume est encore attaché. Supprimer quand même ?' : '';
        if (!confirm(`Supprimer le volume "${pvc.name}" ?${boundMessage}`)) return;
        const forceParam = pvc.bound ? '?force=true' : '';
        fetch(`${API_V1}/k8s/pvcs/${encodedName}${forceParam}`, {
            method: 'DELETE',
            credentials: 'include'
        }).then(resp => {
            if (!resp.ok) {
                return resp.json().catch(() => ({})).then(err => { throw new Error(err.detail || 'Suppression impossible'); });
            }
            return refreshPvcs({ render: true, force: true }).then(() => {
                populatePvcSelect();
            });
        }).catch(error => {
            alert(`Erreur lors de la suppression du volume: ${error.message}`);
        });
    }

    function renderPvcList(items) {
        if (!pvcListContainer) return;
        if (!Array.isArray(items) || items.length === 0) {
            pvcListContainer.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-database"></i> Aucun volume persistant. Lancez VS Code ou Jupyter pour en créer un.
                </div>`;
            return;
        }

        const rows = items.map(pvc => {
            const phase = pvc.phase || 'Inconnu';
            const phaseClass = mapPhaseToClass(phase);
            const storage = pvc.storage || 'Taille inconnue';
            const access = (pvc.access_modes && pvc.access_modes.length) ? pvc.access_modes.join(', ') : 'Mode non précisé';
            const lastApp = pvc.last_bound_app || pvc.app_type || '—';
            const createdAt = formatIsoDateShort(pvc.created_at);
            const phaseBadgeClass = phaseClass ? ` status-${phaseClass}` : '';
            return `
                <tr data-pvc-name="${escapeHtml(pvc.name)}">
                    <td>
                        <div class="cell-main" title="${escapeHtml(pvc.name)}">${escapeHtml(pvc.name)}</div>
                        <div class="cell-meta">
                            <span class="badge-soft${phaseBadgeClass}">${escapeHtml(phase)}</span>
                            <span class="badge-soft muted"><i class="fas fa-share-alt"></i> ${escapeHtml(access)}</span>
                        </div>
                    </td>
                    <td>${escapeHtml(storage)}</td>
                    <td>${escapeHtml(lastApp)}</td>
                    <td>${escapeHtml(createdAt)}</td>
                    <td class="cell-actions">
                        <button type="button" class="btn btn-danger btn-icon pvc-delete-btn" data-name="${escapeHtml(pvc.name)}" title="Supprimer ce volume">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        pvcListContainer.innerHTML = `
            <div class="pvc-table-wrapper">
                <table class="pvc-table">
                    <thead>
                        <tr>
                            <th>Volume</th>
                            <th>Capacité</th>
                            <th>Dernière application</th>
                            <th>Créé le</th>
                            <th class="text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;

        pvcListContainer.querySelectorAll('.pvc-delete-btn').forEach(btn => {
            const name = btn.getAttribute('data-name');
            const pvc = items.find(item => item.name === name);
            if (pvc) {
                btn.addEventListener('click', () => handlePvcDelete(pvc));
            }
        });
    }

    async function refreshPvcs(options = {}) {
        const { render = true, force = false } = options;
        if (!force && state.cachedPvcs.length && Date.now() - state.pvcsLastFetched < 60000) {
            if (render) renderPvcList(state.cachedPvcs);
            return state.cachedPvcs;
        }

        if (pvcListContainer && render) {
            pvcListContainer.innerHTML = '<div class="loading-spinner"><i class="fas fa-spinner fa-spin"></i> Chargement...</div>';
        }

        try {
            const data = await fetchUserPvcs();
            state.cachedPvcs = data.items || [];
            state.pvcsLastFetched = Date.now();
            if (render) renderPvcList(state.cachedPvcs);
            updateDashboardStats();
            return state.cachedPvcs;
        } catch (error) {
            if (pvcListContainer && render) {
                pvcListContainer.innerHTML = `<div class="error-message"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(error.message)}</div>`;
            }
            updateDashboardStats();
            throw error;
        }
    }

    let lastDeploymentType = '';

    function populatePvcSelect(deploymentType = lastDeploymentType) {
        if (!pvcSelectGroup || !existingPvcSelect) return;
        if (deploymentType) {
            lastDeploymentType = deploymentType;
        }
        const supported = ['vscode', 'jupyter'];
        if (!supported.includes(lastDeploymentType)) {
            pvcSelectGroup.style.display = 'none';
            existingPvcSelect.value = '';
            return;
        }

        pvcSelectGroup.style.display = 'block';
        existingPvcSelect.innerHTML = '';
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Créer un nouveau volume';
        existingPvcSelect.appendChild(defaultOption);

        state.cachedPvcs.forEach(pvc => {
            const option = document.createElement('option');
            option.value = pvc.name;
            const storage = pvc.storage || 'taille inconnue';
            const suffix = pvc.bound ? ' (attaché)' : '';
            option.textContent = `${pvc.name} - ${storage}${suffix}`;
            existingPvcSelect.appendChild(option);
        });
    }

    async function fetchAllManagedPvcs() {
        const resp = await fetch(`${API_V1}/k8s/pvcs/all`, { credentials: 'include' });
        if (!resp.ok) {
            if (resp.status === 403) {
                throw new Error('ACCESS_DENIED');
            }
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || 'Impossible de récupérer les volumes globaux');
        }
        return resp.json();
    }

    function renderAdminPvcList(items) {
        if (!adminPvcsList) return;
        if (!Array.isArray(items) || items.length === 0) {
            adminPvcsList.innerHTML = '<div class="empty-state"><i class="fas fa-hdd"></i> Aucun volume LabOnDemand trouvé.</div>';
            return;
        }

        const rows = items.map(pvc => {
            const phase = pvc.phase || 'Inconnu';
            const phaseClass = mapPhaseToClass(phase);
            const storage = pvc.storage || 'n/a';
            const lastApp = pvc.last_bound_app || pvc.app_type || 'n/a';
            const owner = pvc.labels && pvc.labels['user-id'] ? `Utilisateur #${escapeHtml(String(pvc.labels['user-id']))}` : 'n/a';
            const created = formatIsoDateShort(pvc.created_at);
            const phaseBadgeClass = phaseClass ? ` status-${phaseClass}` : '';
            const namespaceBadge = `<span class="badge-soft">${escapeHtml(pvc.namespace)}</span>`;
            const phaseBadge = `<span class="badge-soft${phaseBadgeClass}">${escapeHtml(phase)}</span>`;
            return `
                <tr>
                    <td>
                        <div class="cell-main" title="${escapeHtml(pvc.name)}">${escapeHtml(pvc.name)}</div>
                        <span class="cell-sub">${namespaceBadge}</span>
                    </td>
                    <td>${escapeHtml(storage)}</td>
                    <td>${phaseBadge}</td>
                    <td>${escapeHtml(lastApp)}</td>
                    <td>${owner}</td>
                    <td>${escapeHtml(created)}</td>
                </tr>
            `;
        }).join('');

        adminPvcsList.innerHTML = `
            <div class="table-wrapper">
                <table class="k8s-table compact-table">
                    <thead>
                        <tr>
                            <th>Volume</th>
                            <th>Capacité</th>
                            <th>Phase</th>
                            <th>Dernière application</th>
                            <th>Propriétaire</th>
                            <th>Créé le</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    async function refreshAdminPvcs(options = {}) {
        if (!adminPvcsList) return [];
        const { force = false } = options;
        if (!force && state.cachedAdminPvcs.length && Date.now() - state.adminPvcsLastFetched < 60000) {
            renderAdminPvcList(state.cachedAdminPvcs);
            return state.cachedAdminPvcs;
        }

        adminPvcsList.innerHTML = '<div class="loading-spinner"><i class="fas fa-spinner fa-spin"></i> Chargement...</div>';
        try {
            const data = await fetchAllManagedPvcs();
            state.cachedAdminPvcs = data.items || [];
            state.adminPvcsLastFetched = Date.now();
            renderAdminPvcList(state.cachedAdminPvcs);
            return state.cachedAdminPvcs;
        } catch (error) {
            if (error.message === 'ACCESS_DENIED') {
                adminPvcsList.innerHTML = '<div class="empty-state"><i class="fas fa-lock"></i> Accès réservé aux rôles enseignant ou admin.</div>';
                return [];
            }
            adminPvcsList.innerHTML = `<div class="error-message"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(error.message)}</div>`;
            throw error;
        }
    }

    return {
        fetchMyQuotas,
        renderQuotasCard,
        refreshQuotas,
        refreshPvcs,
        populatePvcSelect,
        refreshAdminPvcs,
        updateDashboardStats,
    };
}
