/**
 * admin-labs.js — Parc des Labs
 *
 * Dépend de api.js (window.api) chargé avant ce script.
 * S'initialise au premier clic sur l'onglet "labs" (événement custom)
 * ou immédiatement si l'onglet est déjà actif au chargement (hash #labs).
 */
(function () {
    'use strict';

    // ── État ──────────────────────────────────────────────────────────────────
    let allLabs      = [];
    let filteredLabs = [];
    let initialized  = false;

    // ── Éléments DOM ─────────────────────────────────────────────────────────
    const tableBody    = document.getElementById('labs-table-body');
    const searchInput  = document.getElementById('labs-search');
    const statusFilter = document.getElementById('labs-status-filter');
    const typeFilter   = document.getElementById('labs-type-filter');
    const refreshBtn   = document.getElementById('refresh-labs-btn');
    const labsCount    = document.getElementById('labs-count');

    // Stat cards
    const statActive  = document.getElementById('stat-active');
    const statPaused  = document.getElementById('stat-paused');
    const statExpired = document.getElementById('stat-expired');
    const statTotal   = document.getElementById('stat-total');

    // Modale de confirmation d'action admin
    const labActionModal   = document.getElementById('lab-action-modal');
    const labActionTitle   = document.getElementById('lab-action-modal-title');
    const labActionBody    = document.getElementById('lab-action-modal-body');
    const labActionWarning = document.getElementById('lab-action-modal-warning');
    const labActionConfirm = document.getElementById('lab-action-confirm-btn');

    if (!tableBody) return; // page non concernée

    // ── Bootstrap : chargement différé à l'ouverture de l'onglet ─────────────
    function init() {
        if (initialized) return;
        initialized = true;
        loadLabs();
    }

    // Si l'onglet labs est déjà actif (hash #labs) ou activé plus tard
    if (document.getElementById('tab-labs')?.classList.contains('active')) {
        init();
    }
    document.addEventListener('labs-tab-opened', init);

    // ── Listeners ─────────────────────────────────────────────────────────────
    if (refreshBtn) refreshBtn.addEventListener('click', loadLabs);
    if (searchInput) searchInput.addEventListener('input', applyFilters);
    if (statusFilter) statusFilter.addEventListener('change', applyFilters);
    if (typeFilter) typeFilter.addEventListener('change', applyFilters);

    // Fermeture modale
    document.querySelectorAll('.close-lab-modal').forEach(btn =>
        btn.addEventListener('click', closeLabActionModal)
    );
    if (labActionModal) {
        labActionModal.addEventListener('click', e => {
            if (e.target === labActionModal) closeLabActionModal();
        });
    }
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && labActionModal?.classList.contains('show')) {
            closeLabActionModal();
        }
    });

    // ── Chargement ────────────────────────────────────────────────────────────
    async function loadLabs() {
        setTableLoading();
        resetStatCards();
        try {
            const data = await window.api('/api/v1/k8s/deployments/all');
            allLabs = data.deployments || [];
            updateStatCards(allLabs);
            applyFilters();
        } catch (err) {
            setTableError(err.message);
        }
    }

    // ── Stat cards ────────────────────────────────────────────────────────────
    function updateStatCards(labs) {
        const counts = { active: 0, paused: 0, expired: 0 };
        labs.forEach(l => {
            if (counts[l.status] !== undefined) counts[l.status]++;
        });
        if (statActive)  statActive.textContent  = counts.active;
        if (statPaused)  statPaused.textContent  = counts.paused;
        if (statExpired) statExpired.textContent = counts.expired;
        if (statTotal)   statTotal.textContent   = labs.length;
    }

    function resetStatCards() {
        [statActive, statPaused, statExpired, statTotal].forEach(el => {
            if (el) el.textContent = '—';
        });
    }

    // ── Filtres ───────────────────────────────────────────────────────────────
    function applyFilters() {
        const search = searchInput  ? searchInput.value.toLowerCase()  : '';
        const status = statusFilter ? statusFilter.value : 'all';
        const type   = typeFilter   ? typeFilter.value   : 'all';

        filteredLabs = allLabs.filter(lab => {
            const owner = lab.owner || {};
            const matchSearch =
                lab.name.toLowerCase().includes(search) ||
                (owner.username  || '').toLowerCase().includes(search) ||
                (owner.full_name || '').toLowerCase().includes(search) ||
                (owner.email     || '').toLowerCase().includes(search) ||
                (lab.namespace   || '').toLowerCase().includes(search);

            const matchStatus = status === 'all' || lab.status === status;
            const matchType   = type   === 'all' || lab.deployment_type === type;

            return matchSearch && matchStatus && matchType;
        });

        if (labsCount) {
            labsCount.textContent = filteredLabs.length < allLabs.length
                ? `${filteredLabs.length} / ${allLabs.length} labs`
                : `${allLabs.length} lab${allLabs.length !== 1 ? 's' : ''}`;
        }

        renderTable();
    }

    // ── Rendu du tableau ──────────────────────────────────────────────────────
    function renderTable() {
        if (!tableBody) return;

        if (filteredLabs.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="7" class="table-loading">
                        Aucun lab ne correspond aux filtres.
                    </td>
                </tr>`;
            return;
        }

        tableBody.innerHTML = filteredLabs.map(lab => {
            const owner      = lab.owner || {};
            const expiryHtml = formatExpiry(lab.expires_at);
            const statusHtml = renderStatusBadge(lab.status);
            const typeBadge  = renderTypeBadge(lab.deployment_type);
            const createdAt  = lab.created_at
                ? new Date(lab.created_at).toLocaleDateString('fr-FR', {
                    day: '2-digit', month: 'short', year: 'numeric'
                  })
                : '—';

            const isPausable  = lab.status === 'active';
            const isResumable = lab.status === 'paused';
            const isDeletable = lab.status !== 'deleted';

            return `
            <tr>
                <td>
                    <strong class="lab-name">${escHtml(lab.name)}</strong>
                    ${lab.namespace ? `<br><code class="lab-ns">${escHtml(lab.namespace)}</code>` : ''}
                </td>
                <td>
                    <span class="owner-name">${escHtml(owner.full_name || owner.username || '?')}</span>
                    <br><span class="owner-email">${escHtml(owner.email || '')}</span>
                </td>
                <td>${typeBadge}</td>
                <td>${statusHtml}</td>
                <td>${expiryHtml}</td>
                <td class="cell-date">${createdAt}</td>
                <td class="action-icons">
                    ${isPausable
                        ? `<button class="pause-lab-btn"
                                data-name="${escAttr(lab.name)}"
                                data-namespace="${escAttr(lab.namespace)}"
                                data-owner="${escAttr(owner.username || '?')}"
                                title="Mettre en pause">
                                <i class="fas fa-pause"></i>
                           </button>`
                        : ''}
                    ${isResumable
                        ? `<button class="resume-lab-btn"
                                data-name="${escAttr(lab.name)}"
                                data-namespace="${escAttr(lab.namespace)}"
                                data-owner="${escAttr(owner.username || '?')}"
                                title="Reprendre">
                                <i class="fas fa-play"></i>
                           </button>`
                        : ''}
                    ${isDeletable
                        ? `<button class="delete-lab-btn"
                                data-name="${escAttr(lab.name)}"
                                data-namespace="${escAttr(lab.namespace)}"
                                data-owner="${escAttr(owner.username || '?')}"
                                title="Supprimer le lab">
                                <i class="fas fa-trash-alt"></i>
                           </button>`
                        : ''}
                </td>
            </tr>`;
        }).join('');

        attachLabActionListeners();
    }

    // ── Listeners boutons du tableau ──────────────────────────────────────────
    function attachLabActionListeners() {
        tableBody.querySelectorAll('.pause-lab-btn').forEach(btn => {
            btn.addEventListener('click', () => openLabActionModal({
                type: 'pause',
                name: btn.dataset.name,
                namespace: btn.dataset.namespace,
                owner: btn.dataset.owner,
            }));
        });

        tableBody.querySelectorAll('.resume-lab-btn').forEach(btn => {
            btn.addEventListener('click', () => openLabActionModal({
                type: 'resume',
                name: btn.dataset.name,
                namespace: btn.dataset.namespace,
                owner: btn.dataset.owner,
            }));
        });

        tableBody.querySelectorAll('.delete-lab-btn').forEach(btn => {
            btn.addEventListener('click', () => openLabActionModal({
                type: 'delete',
                name: btn.dataset.name,
                namespace: btn.dataset.namespace,
                owner: btn.dataset.owner,
            }));
        });
    }

    // ── Modale de confirmation ────────────────────────────────────────────────
    let pendingAction = null;

    function openLabActionModal({ type, name, namespace, owner }) {
        pendingAction = { type, name, namespace };

        if (type === 'pause') {
            labActionTitle.innerHTML  = '<i class="fas fa-pause"></i> Mettre en pause';
            labActionBody.textContent = `Mettre en pause le lab « ${name} » (propriétaire : ${owner}) ?`;
            labActionWarning.textContent = 'Le lab sera suspendu mais les données seront conservées.';
            labActionConfirm.className = 'btn-save';
            labActionConfirm.innerHTML = '<i class="fas fa-pause"></i> Mettre en pause';
        } else if (type === 'resume') {
            labActionTitle.innerHTML  = '<i class="fas fa-play"></i> Reprendre le lab';
            labActionBody.textContent = `Reprendre le lab « ${name} » (propriétaire : ${owner}) ?`;
            labActionWarning.textContent = '';
            labActionConfirm.className = 'btn-save';
            labActionConfirm.innerHTML = '<i class="fas fa-play"></i> Reprendre';
        } else {
            labActionTitle.innerHTML  = '<i class="fas fa-trash-alt"></i> Supprimer le lab';
            labActionBody.textContent = `Supprimer définitivement le lab « ${name} » (propriétaire : ${owner}) ?`;
            labActionWarning.textContent = 'Cette action est irréversible. Les données K8s seront supprimées.';
            labActionConfirm.className = 'btn-delete';
            labActionConfirm.innerHTML = '<i class="fas fa-trash-alt"></i> Supprimer';
        }

        labActionModal.classList.add('show');
    }

    function closeLabActionModal() {
        if (labActionModal) labActionModal.classList.remove('show');
        pendingAction = null;
    }

    if (labActionConfirm) {
        labActionConfirm.addEventListener('click', async () => {
            if (!pendingAction) return;
            const { type, name, namespace } = pendingAction;

            labActionConfirm.disabled = true;
            labActionConfirm.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

            try {
                if (type === 'pause') {
                    await window.api(`/api/v1/k8s/deployments/${namespace}/${name}/pause`, { method: 'POST' });
                    showGlobalSuccess(`Lab « ${name} » mis en pause.`);
                } else if (type === 'resume') {
                    await window.api(`/api/v1/k8s/deployments/${namespace}/${name}/resume`, { method: 'POST' });
                    showGlobalSuccess(`Lab « ${name} » repris.`);
                } else {
                    await window.api(`/api/v1/k8s/deployments/${namespace}/${name}`, { method: 'DELETE' });
                    showGlobalSuccess(`Lab « ${name} » supprimé.`);
                }
                closeLabActionModal();
                loadLabs();
            } catch (err) {
                showGlobalError(err.message);
                closeLabActionModal();
            } finally {
                labActionConfirm.disabled = false;
            }
        });
    }

    // ── Helpers visuels ───────────────────────────────────────────────────────
    function setTableLoading() {
        if (tableBody) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="7" class="table-loading">
                        <i class="fas fa-spinner fa-spin"></i> Chargement du parc des labs…
                    </td>
                </tr>`;
        }
    }

    function setTableError(msg) {
        if (tableBody) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="7" class="table-loading" style="color:var(--red)">
                        <i class="fas fa-exclamation-circle"></i> ${escHtml(msg)}
                    </td>
                </tr>`;
        }
    }

    function renderStatusBadge(status) {
        const map = {
            active:  ['active',  'Actif'],
            paused:  ['paused',  'En pause'],
            expired: ['expired', 'Expiré'],
            deleted: ['deleted', 'Supprimé'],
        };
        const [cls, label] = map[status] || ['inactive', status];
        return `<span class="status-badge ${cls}">${label}</span>`;
    }

    function renderTypeBadge(type) {
        const icons = {
            vscode:    'fa-code',
            jupyter:   'fa-book',
            wordpress: 'fa-wordpress',
            lamp:      'fa-server',
            mysql:     'fa-database',
            custom:    'fa-cube',
        };
        const icon = icons[type] || 'fa-cube';
        return `<span class="type-badge"><i class="fas ${icon}"></i> ${escHtml(type || '—')}</span>`;
    }

    function formatExpiry(isoStr) {
        if (!isoStr) return '<span class="expiry-none">—</span>';
        const d      = new Date(isoStr);
        const now    = new Date();
        const diffMs = d - now;
        const diffH  = diffMs / 3600000;
        const str    = d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });

        if (diffMs < 0)  return `<span class="expiry-past"  title="${isoStr}"><i class="fas fa-exclamation-circle"></i> ${str}</span>`;
        if (diffH < 24)  return `<span class="expiry-soon"  title="${isoStr}"><i class="fas fa-clock"></i> ${str}</span>`;
        return `<span title="${isoStr}">${str}</span>`;
    }

    function escHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function escAttr(str) {
        return String(str ?? '').replace(/"/g, '&quot;');
    }

    // ── Pont vers les notifications admin.js ──────────────────────────────────
    function showGlobalSuccess(msg) {
        const el  = document.getElementById('success-message');
        const txt = document.getElementById('success-text');
        if (el && txt) {
            txt.textContent = msg;
            el.style.display = 'flex';
            setTimeout(() => { el.style.display = 'none'; }, 5000);
        }
    }

    function showGlobalError(msg) {
        const el  = document.getElementById('error-message');
        const txt = document.getElementById('error-text');
        if (el && txt) {
            txt.textContent = msg;
            el.style.display = 'flex';
            setTimeout(() => { el.style.display = 'none'; }, 5000);
        }
    }

})();
