/* Onglet "Devoirs" — CRUD + bulk-spawn modal */
window.TeacherAssignments = (function () {
  const t = window.t || (k => k);
  let _deployTargetCid = null;
  let _deployTargetAid = null;

  function _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function _formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(window.i18nLang || 'fr', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  function _notify(type, msg) {
    const el = document.getElementById(type === 'error' ? 'error-message' : 'success-message');
    const txt = document.getElementById(type === 'error' ? 'error-text' : 'success-text');
    if (!el || !txt) return;
    txt.textContent = msg;
    el.style.display = 'flex';
    setTimeout(() => { el.style.display = 'none'; }, 5000);
  }

  function _renderCard(asgn, cid) {
    const card = document.createElement('div');
    card.className = 'assignment-card';
    const templates = window.TeacherState.getTemplates();
    const tpl = templates.find(t => t.key === asgn.template_key);
    card.innerHTML = `
      <div class="assignment-card__info">
        <h3 class="assignment-card__title">${_esc(asgn.title)}</h3>
        <div class="assignment-card__meta">
          ${tpl ? `<span><i class="fas fa-cube"></i> ${_esc(tpl.name)}</span>` : ''}
          ${asgn.due_at ? `<span><i class="fas fa-clock"></i> ${t('assignment.due')} ${_formatDate(asgn.due_at)}</span>` : ''}
          <span><i class="fas fa-microchip"></i> CPU: ${asgn.cpu_preset || 'low'}</span>
          <span><i class="fas fa-memory"></i> RAM: ${asgn.ram_preset || 'low'}</span>
        </div>
      </div>
      <div class="assignment-card__actions">
        <button class="action-btn btn-deploy" data-aid="${asgn.id}" title="${t('assignment.distribute')}">
          <i class="fas fa-rocket"></i> <span class="hide-sm">${t('assignment.distribute')}</span>
        </button>
        <button class="action-btn action-btn--danger btn-archive-assignment" data-aid="${asgn.id}" title="${t('assignment.archive')}">
          <i class="fas fa-archive"></i>
        </button>
      </div>
    `;
    card.querySelector('.btn-deploy')?.addEventListener('click', () => _openDeployModal(cid, asgn));
    card.querySelector('.btn-archive-assignment')?.addEventListener('click', () => _archiveAssignment(cid, asgn.id, asgn.title));
    return card;
  }

  async function render(classroomId) {
    const loading = document.getElementById('assignments-loading');
    const empty = document.getElementById('assignments-empty');
    const unselected = document.getElementById('assignments-unselected');
    const list = document.getElementById('assignments-list');
    const newBtn = document.getElementById('new-assignment-btn');

    if (newBtn) newBtn.disabled = !classroomId;

    if (!classroomId) {
      if (loading) loading.style.display = 'none';
      if (empty) empty.style.display = 'none';
      if (unselected) unselected.style.display = 'flex';
      if (list) list.innerHTML = '';
      return;
    }

    if (unselected) unselected.style.display = 'none';
    if (loading) loading.style.display = 'block';
    if (empty) empty.style.display = 'none';
    if (list) list.innerHTML = '';

    try {
      const assignments = await window.TeacherAPI.listAssignments(classroomId);
      if (loading) loading.style.display = 'none';

      if (!assignments.length) {
        if (empty) empty.style.display = 'flex';
        return;
      }
      assignments.forEach(a => {
        list.appendChild(_renderCard(a, classroomId));
      });
    } catch (err) {
      if (loading) loading.style.display = 'none';
      _notify('error', err.message);
    }
  }

  async function _archiveAssignment(cid, aid, title) {
    if (!confirm(`Archiver le devoir "${title}" ?`)) return;
    try {
      await window.TeacherAPI.archiveAssignment(cid, aid);
      _notify('success', `Devoir "${title}" archivé`);
      render(cid);
    } catch (err) {
      _notify('error', err.message);
    }
  }

  // ── Assignment creation modal ─────────────────────────────────────────────

  function _openAssignmentModal() {
    const cid = document.getElementById('assignments-class-select').value;
    if (!cid) return;
    const modal = document.getElementById('assignment-modal');
    if (!modal) return;
    document.getElementById('assignment-title-input').value = '';
    document.getElementById('assignment-template-select').value = '';
    document.getElementById('assignment-cpu-select').value = 'low';
    document.getElementById('assignment-ram-select').value = 'low';
    document.getElementById('assignment-due-input').value = '';
    document.getElementById('assignment-instructions-input').value = '';
    modal.style.display = 'flex';
    document.getElementById('assignment-title-input').focus();
  }

  function _closeAssignmentModal() {
    const modal = document.getElementById('assignment-modal');
    if (modal) modal.style.display = 'none';
  }

  async function _submitAssignment() {
    const cid = document.getElementById('assignments-class-select').value;
    if (!cid) return;
    const title = document.getElementById('assignment-title-input').value.trim();
    if (!title) { _notify('error', 'Le titre est requis'); return; }

    const data = {
      title,
      template_key: document.getElementById('assignment-template-select').value || null,
      cpu_preset: document.getElementById('assignment-cpu-select').value,
      ram_preset: document.getElementById('assignment-ram-select').value,
      instructions: document.getElementById('assignment-instructions-input').value.trim() || null,
      due_at: document.getElementById('assignment-due-input').value || null,
    };

    try {
      await window.TeacherAPI.createAssignment(cid, data);
      _notify('success', `Devoir "${title}" créé !`);
      _closeAssignmentModal();
      render(cid);
    } catch (err) {
      _notify('error', err.message);
    }
  }

  // ── Deploy modal ──────────────────────────────────────────────────────────

  function _openDeployModal(cid, asgn) {
    _deployTargetCid = cid;
    _deployTargetAid = asgn.id;
    const modal = document.getElementById('deploy-modal');
    if (!modal) return;

    const classroom = window.TeacherState.getClassrooms().find(c => c.id == cid);
    const count = classroom?.student_count ?? '?';

    const confirmText = document.getElementById('deploy-confirm-text');
    if (confirmText) {
      confirmText.textContent = `"${asgn.title}" — ${t('assignment.confirm_deploy_body').replace('{count}', count)}`;
    }
    document.getElementById('deploy-progress-wrap').style.display = 'none';
    document.getElementById('deploy-report').style.display = 'none';
    document.getElementById('deploy-confirm-btn').style.display = 'inline-flex';
    document.getElementById('deploy-cancel-btn').textContent = t('common.close');
    document.getElementById('deploy-progress-bar').style.width = '0%';

    modal.style.display = 'flex';
  }

  function _closeDeployModal() {
    const modal = document.getElementById('deploy-modal');
    if (modal) modal.style.display = 'none';
  }

  async function _confirmDeploy() {
    const cid = _deployTargetCid;
    const aid = _deployTargetAid;
    if (!cid || !aid) return;

    const confirmBtn = document.getElementById('deploy-confirm-btn');
    const progressWrap = document.getElementById('deploy-progress-wrap');
    const progressBar = document.getElementById('deploy-progress-bar');
    const reportEl = document.getElementById('deploy-report');

    if (confirmBtn) confirmBtn.style.display = 'none';
    if (progressWrap) progressWrap.style.display = 'block';

    // Animate bar while waiting
    let pct = 10;
    const ticker = setInterval(() => {
      pct = Math.min(pct + 5, 85);
      if (progressBar) progressBar.style.width = pct + '%';
    }, 400);

    try {
      const report = await window.TeacherAPI.deployAssignment(cid, aid);
      clearInterval(ticker);
      if (progressBar) progressBar.style.width = '100%';

      const msg = t('assignment.deploy_done')
        .replace('{ok}', report.ok)
        .replace('{errors}', report.errors)
        .replace('{skipped}', report.skipped);
      _notify('success', msg);

      if (reportEl) {
        reportEl.style.display = 'block';
        reportEl.innerHTML = report.results.map(r => `
          <div class="deploy-report-item deploy-report-item--${r.status === 'ok' ? 'ok' : r.status === 'skipped' ? 'skip' : 'error'}">
            <i class="fas fa-${r.status === 'ok' ? 'check' : r.status === 'skipped' ? 'minus' : 'times'}"></i>
            ${_esc(r.username)}
            ${r.status === 'error' && r.error ? ` — <span style="font-size:0.78rem;">${_esc(r.error)}</span>` : ''}
            ${r.deployment_name ? ` <code style="font-size:0.72rem;">${_esc(r.deployment_name)}</code>` : ''}
          </div>
        `).join('');
      }
    } catch (err) {
      clearInterval(ticker);
      if (progressBar) progressBar.style.width = '0%';
      if (progressWrap) progressWrap.style.display = 'none';
      _notify('error', err.message);
    }
  }

  function _loadTemplatesIntoSelect() {
    window.TeacherAPI.listTemplates()
      .then(templates => {
        window.TeacherState.setTemplates(templates || []);
        const sel = document.getElementById('assignment-template-select');
        if (!sel) return;
        const first = sel.options[0];
        sel.innerHTML = '';
        sel.appendChild(first);
        (templates || []).forEach(tpl => {
          const opt = document.createElement('option');
          opt.value = tpl.key;
          opt.textContent = tpl.name;
          sel.appendChild(opt);
        });
      })
      .catch(() => {});
  }

  function init() {
    document.getElementById('assignments-class-select')?.addEventListener('change', e => {
      render(e.target.value || null);
    });
    document.getElementById('new-assignment-btn')?.addEventListener('click', _openAssignmentModal);
    document.getElementById('assignment-modal-cancel')?.addEventListener('click', _closeAssignmentModal);
    document.getElementById('assignment-modal-submit')?.addEventListener('click', _submitAssignment);
    document.querySelectorAll('#assignment-modal .modal-close').forEach(btn => btn.addEventListener('click', _closeAssignmentModal));
    document.getElementById('assignment-modal')?.addEventListener('click', e => {
      if (e.target === document.getElementById('assignment-modal')) _closeAssignmentModal();
    });

    document.getElementById('deploy-cancel-btn')?.addEventListener('click', _closeDeployModal);
    document.getElementById('deploy-confirm-btn')?.addEventListener('click', _confirmDeploy);
    document.querySelectorAll('#deploy-modal .modal-close').forEach(btn => btn.addEventListener('click', _closeDeployModal));
    document.getElementById('deploy-modal')?.addEventListener('click', e => {
      if (e.target === document.getElementById('deploy-modal')) _closeDeployModal();
    });

    _loadTemplatesIntoSelect();
  }

  return { init, render };
})();
