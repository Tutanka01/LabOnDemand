/**
 * audit-logs.js — Logs d'Audit
 *
 * Dépend de api.js (window.api) chargé avant ce script.
 * S'initialise au premier clic sur l'onglet "audit" (événement custom)
 * ou immédiatement si l'onglet est déjà actif au chargement (hash #audit).
 *
 * Fonctionnalités :
 *  - KPI cards (total, par catégorie, alertes)
 *  - Mini sparkbar d'activité sur 7 jours
 *  - Tableau paginé (50 entrées/page)
 *  - Filtres : recherche texte, catégorie, événement, niveau, utilisateur, plage de dates
 *  - Modal de détail d'une entrée (tous les champs JSON)
 *  - Export JSON
 *  - Debounce sur les inputs texte
 *  - Deep-link via hash #audit
 */
(function () {
    'use strict';

    // ── État ──────────────────────────────────────────────────────────────────
    let initialized    = false;
    let currentPage    = 1;
    let totalPages     = 1;
    let totalEntries   = 0;
    const PAGE_SIZE    = 50;

    // Filtres courants
    const filters = {
        search:   '',
        category: '',
        event:    '',
        level:    '',
        username: '',
        dateFrom: '',
        dateTo:   '',
    };

    // ── Éléments DOM ─────────────────────────────────────────────────────────
    const tableBody      = document.getElementById('audit-table-body');
    const searchInput    = document.getElementById('audit-search');
    const categoryFilter = document.getElementById('audit-category-filter');
    const eventFilter    = document.getElementById('audit-event-filter');
    const levelFilter    = document.getElementById('audit-level-filter');
    const usernameFilter = document.getElementById('audit-username-filter');
    const dateFromInput  = document.getElementById('audit-date-from');
    const dateToInput    = document.getElementById('audit-date-to');
    const resetBtn       = document.getElementById('audit-reset-filters');
    const refreshBtn     = document.getElementById('audit-refresh-btn');
    const exportBtn      = document.getElementById('audit-export-btn');
    const countLabel     = document.getElementById('audit-count');
    const prevBtn        = document.getElementById('audit-prev-page');
    const nextBtn        = document.getElementById('audit-next-page');
    const pageInfo       = document.getElementById('audit-page-info');
    const sparkbar       = document.getElementById('audit-sparkbar');

    // KPI
    const kpiTotal  = document.getElementById('audit-kpi-total');
    const kpiAuth   = document.getElementById('audit-kpi-auth');
    const kpiUsers  = document.getElementById('audit-kpi-users');
    const kpiDeploy = document.getElementById('audit-kpi-deploy');
    const kpiWarn   = document.getElementById('audit-kpi-warn');

    if (!tableBody) return; // page non concernée

    // ── Bootstrap ─────────────────────────────────────────────────────────────
    function init() {
        if (initialized) return;
        initialized = true;
        loadStats();
        loadLogs();
    }

    if (document.getElementById('tab-audit')?.classList.contains('active')) {
        init();
    }
    document.addEventListener('audit-tab-opened', init);

    // ── Listeners ─────────────────────────────────────────────────────────────
    if (refreshBtn) refreshBtn.addEventListener('click', () => {
        loadStats();
        loadLogs();
    });

    if (exportBtn) exportBtn.addEventListener('click', exportJson);

    if (resetBtn) resetBtn.addEventListener('click', resetFilters);

    if (prevBtn) prevBtn.addEventListener('click', () => {
        if (currentPage > 1) { currentPage--; loadLogs(); }
    });

    if (nextBtn) nextBtn.addEventListener('click', () => {
        if (currentPage < totalPages) { currentPage++; loadLogs(); }
    });

    // Filtres avec debounce pour les champs texte
    const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

    if (searchInput)    searchInput   .addEventListener('input', debounce(() => { currentPage = 1; filters.search   = searchInput.value.trim();    loadLogs(); }, 350));
    if (usernameFilter) usernameFilter.addEventListener('input', debounce(() => { currentPage = 1; filters.username = usernameFilter.value.trim(); loadLogs(); }, 350));

    if (categoryFilter) categoryFilter.addEventListener('change', () => {
        currentPage = 1;
        filters.category = categoryFilter.value;
        // Réinitialiser l'event filter quand on change de catégorie
        filters.event = '';
        if (eventFilter) eventFilter.value = '';
        loadLogs();
    });

    if (eventFilter) eventFilter.addEventListener('change', () => {
        currentPage = 1;
        filters.event = eventFilter.value;
        loadLogs();
    });

    if (levelFilter) levelFilter.addEventListener('change', () => {
        currentPage = 1;
        filters.level = levelFilter.value;
        loadLogs();
    });

    if (dateFromInput) dateFromInput.addEventListener('change', () => {
        currentPage = 1;
        filters.dateFrom = dateFromInput.value;
        loadLogs();
    });

    if (dateToInput) dateToInput.addEventListener('change', () => {
        currentPage = 1;
        filters.dateTo = dateToInput.value;
        loadLogs();
    });

    // ── Chargement des stats ──────────────────────────────────────────────────
    async function loadStats() {
        try {
            const stats = await window.api('/api/v1/audit-logs/stats');
            renderKpis(stats);
            renderSparkbar(stats.activity_7d || []);
            populateEventFilter(stats.available_events || []);
        } catch (err) {
            // Stats non bloquantes
            console.warn('Audit stats error:', err.message);
        }
    }

    function renderKpis(stats) {
        if (kpiTotal)  kpiTotal.textContent  = stats.total ?? '—';
        if (kpiAuth)   kpiAuth.textContent   = stats.by_category?.auth ?? 0;
        if (kpiUsers)  kpiUsers.textContent  = stats.by_category?.users ?? 0;
        if (kpiDeploy) kpiDeploy.textContent = stats.by_category?.deployments ?? 0;
        if (kpiWarn)   kpiWarn.textContent   = (stats.by_level?.WARNING ?? 0) + (stats.by_level?.ERROR ?? 0);
    }

    function renderSparkbar(activity) {
        if (!sparkbar || !activity.length) return;

        const max = Math.max(...activity.map(d => d.count), 1);

        sparkbar.innerHTML = activity.map(d => {
            const pct    = Math.round((d.count / max) * 100);
            const height = Math.max(pct, d.count > 0 ? 4 : 1);
            const date   = new Date(d.date + 'T12:00:00').toLocaleDateString('fr-FR', {
                weekday: 'short', day: 'numeric', month: 'short'
            });
            return `
            <div class="sparkbar-col" title="${date} : ${d.count} event${d.count !== 1 ? 's' : ''}">
                <div class="sparkbar-bar" style="height:${height}%"></div>
                <div class="sparkbar-label">${new Date(d.date + 'T12:00:00').toLocaleDateString('fr-FR', { weekday: 'short' })}</div>
            </div>`;
        }).join('');
    }

    function populateEventFilter(events) {
        if (!eventFilter) return;
        const EVENT_LABELS = {
            login_success:      'Connexion',
            login_failed:       'Échec connexion',
            logout:             'Déconnexion',
            user_registered:    'Création utilisateur',
            user_updated:       'Modification utilisateur',
            user_deleted:       'Suppression utilisateur',
            user_self_update:   'Mise à jour profil',
            password_changed:   'Changement mot de passe',
            quota_override_set: 'Dérogation quota',
            users_imported_csv: 'Import CSV',
            deployment_created: 'Déploiement créé',
            deployment_deleted: 'Déploiement supprimé',
            deployment_paused:  'Déploiement en pause',
            deployment_resumed: 'Déploiement repris',
        };

        // Préserver la valeur sélectionnée
        const current = eventFilter.value;
        // Vider sauf l'option "Tous"
        while (eventFilter.options.length > 1) eventFilter.remove(1);

        events.forEach(ev => {
            const opt = document.createElement('option');
            opt.value       = ev;
            opt.textContent = EVENT_LABELS[ev] || ev;
            eventFilter.appendChild(opt);
        });

        eventFilter.value = current;
    }

    // ── Chargement des logs paginés ───────────────────────────────────────────
    async function loadLogs() {
        setTableLoading();
        updatePagination(currentPage, 1, 0);

        const params = new URLSearchParams();
        params.set('page',      currentPage);
        params.set('page_size', PAGE_SIZE);
        if (filters.search)   params.set('search',    filters.search);
        if (filters.category) params.set('category',  filters.category);
        if (filters.event)    params.set('event',     filters.event);
        if (filters.level)    params.set('level',     filters.level);
        if (filters.username) params.set('username',  filters.username);
        if (filters.dateFrom) params.set('date_from', filters.dateFrom + 'T00:00:00');
        if (filters.dateTo)   params.set('date_to',   filters.dateTo   + 'T23:59:59');

        try {
            const data = await window.api(`/api/v1/audit-logs?${params.toString()}`);
            totalEntries = data.total  ?? 0;
            totalPages   = data.pages  ?? 1;

            if (countLabel) {
                countLabel.textContent = `${totalEntries} entrée${totalEntries !== 1 ? 's' : ''}`;
            }

            renderTable(data.entries || []);
            updatePagination(data.page, data.pages, data.total);
        } catch (err) {
            setTableError(err.message);
        }
    }

    // ── Rendu du tableau ──────────────────────────────────────────────────────
    function renderTable(entries) {
        if (!tableBody) return;

        if (!entries.length) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="table-loading">
                        <i class="fas fa-search"></i> Aucun log ne correspond aux filtres.
                    </td>
                </tr>`;
            return;
        }

        tableBody.innerHTML = entries.map((e, idx) => {
            const ts       = formatTimestamp(e.timestamp);
            const levelHtml= renderLevelBadge(e.level);
            const eventHtml= renderEventBadge(e.message, e.event_label);
            const details  = buildDetailsSummary(e);
            const username = e.username || e.target_username || e.target_user_id || '—';
            const ip       = e.client_ip || '—';

            return `
            <tr class="audit-row" data-idx="${idx}" style="cursor:pointer" title="Cliquer pour voir tous les détails">
                <td class="audit-ts">${ts}</td>
                <td>${levelHtml}</td>
                <td>${eventHtml}</td>
                <td class="audit-details">${details}</td>
                <td class="audit-username">${escHtml(String(username))}</td>
                <td class="audit-ip"><code>${escHtml(String(ip))}</code></td>
            </tr>`;
        }).join('');

        // Attacher le modal de détail
        tableBody.querySelectorAll('.audit-row').forEach((row, idx) => {
            row.addEventListener('click', () => openDetailModal(entries[idx]));
        });
    }

    // ── Formatage des données ─────────────────────────────────────────────────

    function formatTimestamp(raw) {
        if (!raw) return '<span class="audit-ts--unknown">—</span>';
        try {
            const d = new Date(raw.replace('Z', '+00:00'));
            const date = d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
            const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            return `<span class="audit-ts-date">${date}</span><br><span class="audit-ts-time">${time}</span>`;
        } catch {
            return escHtml(raw);
        }
    }

    function renderLevelBadge(level) {
        const map = {
            INFO:    ['audit-level--info',    'INFO'],
            WARNING: ['audit-level--warning', 'WARN'],
            ERROR:   ['audit-level--error',   'ERR'],
        };
        const [cls, label] = map[(level || '').toUpperCase()] || ['audit-level--info', level || '?'];
        return `<span class="audit-level-badge ${cls}">${label}</span>`;
    }

    function renderEventBadge(event, label) {
        const catMap = {
            login_success:      'cat-auth',
            login_failed:       'cat-danger',
            logout:             'cat-auth',
            user_registered:    'cat-users',
            user_updated:       'cat-users',
            user_deleted:       'cat-danger',
            user_self_update:   'cat-users',
            password_changed:   'cat-users',
            quota_override_set: 'cat-quota',
            users_imported_csv: 'cat-users',
            deployment_created: 'cat-deploy',
            deployment_deleted: 'cat-danger',
            deployment_paused:  'cat-deploy',
            deployment_resumed: 'cat-deploy',
        };
        const iconMap = {
            login_success:      'fa-right-to-bracket',
            login_failed:       'fa-circle-xmark',
            logout:             'fa-right-from-bracket',
            user_registered:    'fa-user-plus',
            user_updated:       'fa-user-pen',
            user_deleted:       'fa-user-minus',
            user_self_update:   'fa-user-gear',
            password_changed:   'fa-key',
            quota_override_set: 'fa-tachometer-alt',
            users_imported_csv: 'fa-file-csv',
            deployment_created: 'fa-rocket',
            deployment_deleted: 'fa-trash',
            deployment_paused:  'fa-pause',
            deployment_resumed: 'fa-play',
        };
        const cat  = catMap[event]  || 'cat-other';
        const icon = iconMap[event] || 'fa-circle-info';
        const lbl  = label || event || '—';
        return `<span class="audit-event-badge ${cat}"><i class="fas ${icon}"></i> ${escHtml(lbl)}</span>`;
    }

    /**
     * Résumé lisible des champs métier de l'entrée.
     * On exclut les champs "infrastructure" déjà affichés ailleurs.
     */
    const SKIP_FIELDS = new Set([
        'timestamp', 'level', 'logger', 'message', 'request_id',
        'event_label', 'client_ip', 'username', '_raw',
    ]);

    function buildDetailsSummary(e) {
        const parts = [];
        for (const [k, v] of Object.entries(e)) {
            if (SKIP_FIELDS.has(k)) continue;
            if (v === null || v === undefined || v === '') continue;
            const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
            parts.push(`<span class="detail-chip"><strong>${escHtml(k)}</strong> ${escHtml(val.length > 60 ? val.slice(0, 60) + '…' : val)}</span>`);
        }
        return parts.length ? parts.join('') : '<span class="audit-no-details">—</span>';
    }

    // ── Pagination ────────────────────────────────────────────────────────────
    function updatePagination(page, pages, total) {
        currentPage = page;
        totalPages  = pages;
        if (pageInfo) pageInfo.textContent = `Page ${page} sur ${pages}`;
        if (prevBtn)  prevBtn.disabled = page <= 1;
        if (nextBtn)  nextBtn.disabled = page >= pages;
    }

    // ── Modal de détail ───────────────────────────────────────────────────────
    let detailModal = null;

    function openDetailModal(entry) {
        // Créer le modal à la volée s'il n'existe pas encore
        if (!detailModal) {
            detailModal = document.createElement('div');
            detailModal.id = 'audit-detail-modal';
            detailModal.className = 'modal';
            detailModal.innerHTML = `
                <div class="modal-content" style="max-width:720px">
                    <div class="modal-header">
                        <h2 id="audit-modal-title"><i class="fas fa-magnifying-glass"></i> Détail de l'événement</h2>
                        <button id="audit-modal-close" class="close-modal"><i class="fas fa-times"></i></button>
                    </div>
                    <div class="modal-body" id="audit-modal-body" style="padding:0"></div>
                </div>`;
            document.body.appendChild(detailModal);

            detailModal.querySelector('#audit-modal-close').addEventListener('click', closeDetailModal);
            detailModal.addEventListener('click', e => { if (e.target === detailModal) closeDetailModal(); });
            document.addEventListener('keydown', e => {
                if (e.key === 'Escape' && detailModal?.classList.contains('show')) closeDetailModal();
            });
        }

        // Remplir le contenu
        const body   = detailModal.querySelector('#audit-modal-body');
        const title  = detailModal.querySelector('#audit-modal-title');
        const level  = (entry.level || '').toUpperCase();
        const event  = entry.message || '—';
        const label  = entry.event_label || event;

        title.innerHTML = `<i class="fas fa-magnifying-glass"></i> ${escHtml(label)}`;

        // Section en-tête
        const tsStr = (() => {
            try {
                const d = new Date(entry.timestamp.replace('Z', '+00:00'));
                return d.toLocaleString('fr-FR', {
                    day: '2-digit', month: 'long', year: 'numeric',
                    hour: '2-digit', minute: '2-digit', second: '2-digit',
                    timeZoneName: 'short',
                });
            } catch { return entry.timestamp || '—'; }
        })();

        const rows = Object.entries(entry)
            .filter(([k]) => k !== 'event_label')
            .map(([k, v]) => {
                const val = v === null || v === undefined ? '<em class="audit-null">null</em>'
                    : typeof v === 'object'
                        ? `<code class="audit-json">${escHtml(JSON.stringify(v, null, 2))}</code>`
                        : `<span class="audit-val">${escHtml(String(v))}</span>`;
                return `<tr>
                    <td class="audit-detail-key">${escHtml(k)}</td>
                    <td class="audit-detail-val">${val}</td>
                </tr>`;
            }).join('');

        body.innerHTML = `
            <div class="audit-detail-header">
                <div class="audit-detail-meta">
                    ${renderLevelBadge(level)}
                    ${renderEventBadge(event, label)}
                </div>
                <div class="audit-detail-ts">
                    <i class="fas fa-clock"></i> ${escHtml(tsStr)}
                </div>
            </div>
            <div class="audit-detail-table-wrap">
                <table class="audit-detail-table">
                    <thead>
                        <tr>
                            <th>Champ</th>
                            <th>Valeur</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;

        detailModal.classList.add('show');
    }

    function closeDetailModal() {
        detailModal?.classList.remove('show');
    }

    // ── Export JSON ───────────────────────────────────────────────────────────
    async function exportJson() {
        if (exportBtn) {
            exportBtn.disabled = true;
            exportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Export…';
        }
        try {
            const params = new URLSearchParams();
            params.set('page',      1);
            params.set('page_size', 500);
            params.set('export',    'json');
            if (filters.search)   params.set('search',    filters.search);
            if (filters.category) params.set('category',  filters.category);
            if (filters.event)    params.set('event',     filters.event);
            if (filters.level)    params.set('level',     filters.level);
            if (filters.username) params.set('username',  filters.username);
            if (filters.dateFrom) params.set('date_from', filters.dateFrom + 'T00:00:00');
            if (filters.dateTo)   params.set('date_to',   filters.dateTo   + 'T23:59:59');

            const resp = await fetch(`/api/v1/audit-logs?${params.toString()}`, {
                credentials: 'include',
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const blob = await resp.blob();
            const url  = URL.createObjectURL(blob);
            const a    = document.createElement('a');
            a.href     = url;

            // Récupère le nom du fichier depuis le header Content-Disposition
            const cd   = resp.headers.get('Content-Disposition') || '';
            const match = cd.match(/filename="([^"]+)"/);
            a.download  = match ? match[1] : 'audit-export.json';

            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (err) {
            alert('Erreur lors de l\'export : ' + err.message);
        } finally {
            if (exportBtn) {
                exportBtn.disabled = false;
                exportBtn.innerHTML = '<i class="fas fa-download"></i> Exporter JSON';
            }
        }
    }

    // ── Réinitialisation des filtres ─────────────────────────────────────────
    function resetFilters() {
        filters.search   = '';
        filters.category = '';
        filters.event    = '';
        filters.level    = '';
        filters.username = '';
        filters.dateFrom = '';
        filters.dateTo   = '';

        if (searchInput)    searchInput.value    = '';
        if (categoryFilter) categoryFilter.value = '';
        if (eventFilter)    eventFilter.value    = '';
        if (levelFilter)    levelFilter.value    = '';
        if (usernameFilter) usernameFilter.value = '';
        if (dateFromInput)  dateFromInput.value  = '';
        if (dateToInput)    dateToInput.value    = '';

        currentPage = 1;
        loadLogs();
    }

    // ── Helpers UI ─────────────────────────────────────────────────────────────
    function setTableLoading() {
        if (tableBody) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="table-loading">
                        <i class="fas fa-spinner fa-spin"></i> Chargement des logs d'audit…
                    </td>
                </tr>`;
        }
    }

    function setTableError(msg) {
        if (tableBody) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="table-loading" style="color:var(--red)">
                        <i class="fas fa-exclamation-circle"></i> ${escHtml(msg)}
                    </td>
                </tr>`;
        }
    }

    function escHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

})();
