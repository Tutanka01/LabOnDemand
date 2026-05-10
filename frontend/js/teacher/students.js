/* Onglet "Étudiants" — list + CSV import */
window.TeacherStudents = (function () {
  const t = window.t || (k => k);

  function _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function _formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString(window.i18nLang || 'fr', { day: '2-digit', month: 'short' });
  }

  function _statusBadge(status) {
    if (!status) return `<span class="student-status-badge student-status-badge--none"><i class="fas fa-minus"></i> ${t('students.lab_none')}</span>`;
    const map = {
      active: ['running', 'fas fa-circle', t('students.lab_running')],
      paused: ['paused', 'fas fa-pause', t('students.lab_paused')],
      expired: ['expired', 'fas fa-clock', t('students.lab_expired')],
    };
    const [cls, icon, label] = map[status] || ['none', 'fas fa-minus', status];
    return `<span class="student-status-badge student-status-badge--${cls}"><i class="${icon}"></i> ${label}</span>`;
  }

  function _notify(type, msg) {
    const el = document.getElementById(type === 'error' ? 'error-message' : 'success-message');
    const txt = document.getElementById(type === 'error' ? 'error-text' : 'success-text');
    if (!el || !txt) return;
    txt.textContent = msg;
    el.style.display = 'flex';
    setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  async function render(classroomId) {
    const loading = document.getElementById('students-loading');
    const empty = document.getElementById('students-empty');
    const wrap = document.getElementById('students-table-wrap');
    const tbody = document.getElementById('students-tbody');
    const importBtn = document.getElementById('import-students-csv-btn');

    const addBtn = document.getElementById('add-student-btn');
    if (!classroomId) {
      if (loading) loading.style.display = 'none';
      if (empty) empty.style.display = 'none';
      if (wrap) wrap.style.display = 'none';
      if (importBtn) importBtn.disabled = true;
      if (addBtn) addBtn.disabled = true;
      return;
    }

    if (importBtn) importBtn.disabled = false;
    if (addBtn) addBtn.disabled = false;
    if (loading) loading.style.display = 'block';
    if (empty) empty.style.display = 'none';
    if (wrap) wrap.style.display = 'none';

    try {
      const students = await window.TeacherAPI.listStudents(classroomId);
      if (loading) loading.style.display = 'none';

      if (!students.length) {
        if (empty) empty.style.display = 'flex';
        return;
      }

      if (tbody) {
        tbody.innerHTML = '';
        students.forEach(s => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><strong>${_esc(s.username)}</strong></td>
            <td>${_esc(s.email)}</td>
            <td>${_statusBadge(s.lab_status)}</td>
            <td>${_formatDate(s.last_seen_at)}</td>
            <td>
              <button class="action-btn action-btn--danger btn-sm btn-unenroll" data-uid="${s.user_id}" data-name="${_esc(s.username)}" title="${t('students.unenroll')}">
                <i class="fas fa-user-minus"></i>
              </button>
            </td>
          `;
          tr.querySelector('.btn-unenroll')?.addEventListener('click', async (e) => {
            const btn = e.currentTarget;
            if (!confirm(`Désinscrire ${btn.dataset.name} ?`)) return;
            try {
              await window.TeacherAPI.unenrollStudent(classroomId, btn.dataset.uid);
              _notify('success', `${btn.dataset.name} désinscrit(e)`);
              render(classroomId);
            } catch (err) {
              _notify('error', err.message);
            }
          });
          tbody.appendChild(tr);
        });
      }
      if (wrap) wrap.style.display = 'block';
    } catch (err) {
      if (loading) loading.style.display = 'none';
      _notify('error', err.message);
    }
  }

  function _openCsvModal() {
    const modal = document.getElementById('csv-import-modal');
    const result = document.getElementById('csv-import-result');
    const file = document.getElementById('csv-import-file');
    if (modal) { modal.style.display = 'flex'; }
    if (result) result.style.display = 'none';
    if (file) file.value = '';
  }

  function _closeCsvModal() {
    const modal = document.getElementById('csv-import-modal');
    if (modal) modal.style.display = 'none';
  }

  async function _submitCsv() {
    const cid = document.getElementById('students-class-select').value;
    if (!cid) return;
    const file = document.getElementById('csv-import-file').files[0];
    if (!file) { _notify('error', 'Sélectionner un fichier CSV'); return; }

    try {
      const result = await window.TeacherAPI.importStudentsCSV(cid, file);
      const s = result.summary;
      const resEl = document.getElementById('csv-import-result');
      if (resEl) {
        resEl.style.display = 'block';
        resEl.innerHTML = `<div class="deploy-report">
          ${result.results.map(r => `
            <div class="deploy-report-item deploy-report-item--${r.status === 'enrolled' || r.status === 're-enrolled' ? 'ok' : r.status === 'skipped' ? 'skip' : 'error'}">
              <i class="fas fa-${r.status === 'enrolled' || r.status === 're-enrolled' ? 'check' : r.status === 'skipped' ? 'minus' : 'times'}"></i>
              ${_esc(r.username)} — ${_esc(r.status)}${r.detail ? ' : ' + _esc(r.detail) : ''}
            </div>
          `).join('')}
        </div>
        <p style="font-size:0.82rem;margin-top:8px;color:var(--text-secondary,#6b7280);">
          ${s.enrolled} inscrits · ${s.skipped} ignorés · ${s.errors} erreurs
        </p>`;
      }
      _notify('success', `Import : ${s.enrolled} inscrits`);
      render(cid);
    } catch (err) {
      _notify('error', err.message);
    }
  }

  // ── Modal : Ajouter un étudiant manuellement ──────────────────────────────

  let _selectedUserId = null;
  let _searchTimer = null;

  function _openAddModal() {
    const modal = document.getElementById('add-student-modal');
    if (!modal) return;
    _selectedUserId = null;
    document.getElementById('add-student-search').value = '';
    document.getElementById('add-student-results').innerHTML = '';
    document.getElementById('add-student-selected').style.display = 'none';
    document.getElementById('add-student-submit').disabled = true;
    modal.style.display = 'flex';
    document.getElementById('add-student-search').focus();
  }

  function _closeAddModal() {
    const modal = document.getElementById('add-student-modal');
    if (modal) modal.style.display = 'none';
  }

  function _selectUser(user) {
    _selectedUserId = user.user_id;
    document.getElementById('add-student-selected').style.display = 'block';
    document.getElementById('add-student-selected-name').textContent = `${user.username} (${user.email})`;
    document.getElementById('add-student-submit').disabled = false;
    document.getElementById('add-student-results').innerHTML = '';
    document.getElementById('add-student-search').value = user.username;
  }

  async function _runSearch(q) {
    const resultsEl = document.getElementById('add-student-results');
    if (!q.trim()) { resultsEl.innerHTML = ''; return; }
    resultsEl.innerHTML = '<div style="padding:8px;color:var(--text-secondary,#6b7280);font-size:0.85rem;">Recherche...</div>';
    try {
      const users = await window.TeacherAPI.searchUsers(q);
      if (!users.length) {
        resultsEl.innerHTML = '<div style="padding:8px;color:var(--text-secondary,#6b7280);font-size:0.85rem;">Aucun étudiant trouvé</div>';
        return;
      }
      resultsEl.innerHTML = '';
      users.forEach(u => {
        const row = document.createElement('div');
        row.style.cssText = 'padding:8px 12px;cursor:pointer;border-radius:6px;display:flex;align-items:center;gap:10px;font-size:0.9rem;';
        row.innerHTML = `<i class="fas fa-user-graduate" style="color:var(--primary,#6366f1);width:16px;"></i>
          <span><strong>${_esc(u.username)}</strong> <span style="color:var(--text-secondary,#6b7280);">${_esc(u.email)}</span></span>`;
        row.addEventListener('mouseenter', () => row.style.background = 'var(--bg-secondary,#f3f4f6)');
        row.addEventListener('mouseleave', () => row.style.background = '');
        row.addEventListener('click', () => _selectUser(u));
        resultsEl.appendChild(row);
      });
    } catch (err) {
      resultsEl.innerHTML = `<div style="padding:8px;color:#ef4444;font-size:0.85rem;">${_esc(err.message)}</div>`;
    }
  }

  async function _submitAddStudent() {
    const cid = document.getElementById('students-class-select').value;
    if (!cid || !_selectedUserId) return;
    const btn = document.getElementById('add-student-submit');
    btn.disabled = true;
    try {
      await window.TeacherAPI.enrollStudents(cid, [_selectedUserId]);
      const name = document.getElementById('add-student-selected-name').textContent;
      _notify('success', `Étudiant inscrit : ${name}`);
      _closeAddModal();
      render(cid);
    } catch (err) {
      _notify('error', err.message);
      btn.disabled = false;
    }
  }

  function init() {
    document.getElementById('students-class-select')?.addEventListener('change', e => {
      const cid = e.target.value || null;
      const addBtn = document.getElementById('add-student-btn');
      if (addBtn) addBtn.disabled = !cid;
      render(cid);
    });

    // Bouton ajouter manuellement
    document.getElementById('add-student-btn')?.addEventListener('click', _openAddModal);
    document.getElementById('add-student-cancel')?.addEventListener('click', _closeAddModal);
    document.getElementById('add-student-submit')?.addEventListener('click', _submitAddStudent);
    document.querySelectorAll('#add-student-modal .modal-close').forEach(btn => btn.addEventListener('click', _closeAddModal));
    document.getElementById('add-student-modal')?.addEventListener('click', e => {
      if (e.target === document.getElementById('add-student-modal')) _closeAddModal();
    });
    document.getElementById('add-student-search')?.addEventListener('input', e => {
      _selectedUserId = null;
      document.getElementById('add-student-selected').style.display = 'none';
      document.getElementById('add-student-submit').disabled = true;
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(() => _runSearch(e.target.value), 300);
    });

    document.getElementById('import-students-csv-btn')?.addEventListener('click', _openCsvModal);
    document.getElementById('csv-import-cancel')?.addEventListener('click', _closeCsvModal);
    document.getElementById('csv-import-submit')?.addEventListener('click', _submitCsv);
    document.querySelectorAll('#csv-import-modal .modal-close').forEach(btn => btn.addEventListener('click', _closeCsvModal));
    document.getElementById('csv-import-modal')?.addEventListener('click', e => {
      if (e.target === document.getElementById('csv-import-modal')) _closeCsvModal();
    });
  }

  return { init, render };
})();
