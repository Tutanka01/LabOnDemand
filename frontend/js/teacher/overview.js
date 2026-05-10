/* Onglet "Vue d'ensemble" — grille classe × étudiant + auto-refresh */
window.TeacherOverview = (function () {
  const t = window.t || (k => k);
  let _refreshTimer = null;
  let _allStudents = [];

  function _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function _formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(window.i18nLang || 'fr', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  function _statusClass(status) {
    if (!status) return 'none';
    if (status === 'active') return 'active';
    if (status === 'paused') return 'paused';
    return 'error';
  }

  function _statusIcon(status) {
    if (!status) return 'fas fa-minus';
    if (status === 'active') return 'fas fa-play';
    if (status === 'paused') return 'fas fa-pause';
    return 'fas fa-exclamation';
  }

  function _renderGrid(students, filterStatus) {
    const grid = document.getElementById('overview-grid');
    const empty = document.getElementById('overview-empty');
    if (!grid) return;

    const filtered = filterStatus ? students.filter(s => {
      if (filterStatus === 'none') return !s.lab_status;
      return s.lab_status === filterStatus;
    }) : students;

    if (!filtered.length) {
      grid.style.display = 'none';
      if (empty) empty.style.display = 'flex';
      return;
    }

    if (empty) empty.style.display = 'none';
    grid.style.display = 'grid';
    grid.innerHTML = '';

    filtered.forEach(s => {
      const cls = _statusClass(s.lab_status);
      const cell = document.createElement('div');
      cell.className = `overview-cell overview-cell--${cls} tooltip-wrap`;
      cell.innerHTML = `
        <i class="${_statusIcon(s.lab_status)}" style="font-size:0.9rem;"></i>
        <span class="overview-cell__name">${_esc(s.username)}</span>
        <div class="tooltip-content">
          <strong>${_esc(s.username)}</strong><br>
          ${_esc(s.email)}<br>
          ${s.lab_name ? `Lab: ${_esc(s.lab_name)}<br>` : ''}
          ${s.lab_expires_at ? `Expire: ${_formatDate(s.lab_expires_at)}<br>` : ''}
          ${s.last_seen_at ? `Vu: ${_formatDate(s.last_seen_at)}` : t('overview.no_lab')}
        </div>
      `;
      grid.appendChild(cell);
    });
  }

  async function _loadClassStudents(cid) {
    try {
      return await window.TeacherAPI.listStudents(cid);
    } catch {
      return [];
    }
  }

  async function render() {
    const loading = document.getElementById('overview-loading');
    const grid = document.getElementById('overview-grid');
    const empty = document.getElementById('overview-empty');
    const classSel = document.getElementById('overview-class-select');
    const statusSel = document.getElementById('overview-status-select');

    const selectedCid = classSel?.value || null;
    const selectedStatus = statusSel?.value || null;

    if (loading) loading.style.display = 'grid';
    if (grid) grid.style.display = 'none';
    if (empty) empty.style.display = 'none';

    try {
      const classrooms = window.TeacherState.getClassrooms();
      let toLoad = selectedCid ? [parseInt(selectedCid, 10)] : classrooms.map(c => c.id);

      const results = await Promise.all(toLoad.map(cid => _loadClassStudents(cid)));
      _allStudents = results.flat();

      if (loading) loading.style.display = 'none';
      _renderGrid(_allStudents, selectedStatus);
    } catch (err) {
      if (loading) loading.style.display = 'none';
      if (empty) empty.style.display = 'flex';
    }
  }

  function _startAutoRefresh() {
    _stopAutoRefresh();
    _refreshTimer = setInterval(render, 30000);
  }

  function _stopAutoRefresh() {
    if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
  }

  function init() {
    document.getElementById('overview-class-select')?.addEventListener('change', render);
    document.getElementById('overview-status-select')?.addEventListener('change', () => {
      const statusSel = document.getElementById('overview-status-select');
      _renderGrid(_allStudents, statusSel?.value || null);
    });
    document.getElementById('overview-refresh-btn')?.addEventListener('click', render);
  }

  return { init, render, startAutoRefresh: _startAutoRefresh, stopAutoRefresh: _stopAutoRefresh };
})();
