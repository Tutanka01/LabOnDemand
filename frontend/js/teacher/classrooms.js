/* Onglet "Mes Classes" — CRUD + modal */
window.TeacherClassrooms = (function () {
  const t = window.t || (k => k);

  /* Color palette — indexed by classroom id % length */
  const ACCENT_COLORS = [
    '#2563EB', /* blue   */
    '#7C3AED', /* violet */
    '#0891B2', /* cyan   */
    '#16A34A', /* green  */
    '#D97706', /* amber  */
    '#DC2626', /* red    */
    '#0D9488', /* teal   */
    '#EA580C', /* orange */
  ];

  let _editId = null;

  function _formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString(window.i18nLang || 'fr', { day: '2-digit', month: 'short', year: 'numeric' });
  }

  function _notify(type, msg) {
    const el = document.getElementById(type === 'error' ? 'error-message' : 'success-message');
    const txt = document.getElementById(type === 'error' ? 'error-text' : 'success-text');
    if (!el || !txt) return;
    txt.textContent = msg;
    el.style.display = 'flex';
    setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  function _renderCard(cls) {
    const accent = ACCENT_COLORS[cls.id % ACCENT_COLORS.length];
    const card = document.createElement('div');
    card.className = 'classroom-card' + (cls.archived ? ' classroom-card--archived' : '');
    card.dataset.id = cls.id;
    card.style.setProperty('--classroom-accent', accent);

    card.innerHTML = `
      <div class="classroom-card__accent"></div>
      <div class="classroom-card__body">
        <div class="classroom-card__header">
          <h3 class="classroom-card__name">${_esc(cls.name)}</h3>
          ${cls.archived ? `<span class="classroom-card__badge classroom-card__badge--archived">${t('classroom.archived')}</span>` : ''}
        </div>
        ${cls.description ? `<p class="classroom-card__desc">${_esc(cls.description)}</p>` : ''}
        <div class="classroom-card__stats">
          <span class="classroom-card__stat">
            <i class="fas fa-users"></i>
            ${cls.student_count ?? 0} ${t('classroom.students')}
          </span>
          <span class="classroom-card__stat">
            <i class="fas fa-tasks"></i>
            ${cls.active_assignment_count ?? 0} ${t('classroom.assignments')}
          </span>
          <span class="classroom-card__stat">
            <i class="fas fa-calendar-alt"></i>
            ${_formatDate(cls.created_at)}
          </span>
        </div>
        <div class="classroom-card__actions">
          <button class="action-btn action-btn--secondary btn-students" data-id="${cls.id}" title="${t('students.title')}">
            <i class="fas fa-users"></i> <span class="hide-sm">${t('students.title')}</span>
          </button>
          <button class="action-btn action-btn--secondary btn-assignments" data-id="${cls.id}" title="${t('assignment.title')}">
            <i class="fas fa-tasks"></i> <span class="hide-sm">${t('assignment.title')}</span>
          </button>
          ${!cls.archived ? `
          <button class="action-btn action-btn--secondary btn-edit" data-id="${cls.id}" title="${t('classroom.edit')}" style="margin-left:auto;">
            <i class="fas fa-pen"></i>
          </button>
          <button class="action-btn action-btn--danger btn-archive" data-id="${cls.id}" title="${t('classroom.archive')}">
            <i class="fas fa-archive"></i>
          </button>` : ''}
        </div>
      </div>
    `;
    return card;
  }

  function _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function render() {
    const loading = document.getElementById('classrooms-loading');
    const grid = document.getElementById('classrooms-grid');
    const empty = document.getElementById('classrooms-empty');

    if (loading) loading.style.display = 'grid';
    if (grid) grid.style.display = 'none';
    if (empty) empty.style.display = 'none';

    try {
      const classrooms = await window.TeacherAPI.listClassrooms();
      window.TeacherState.setClassrooms(classrooms);
      _populateClassSelects(classrooms);

      if (loading) loading.style.display = 'none';

      if (!classrooms.length) {
        if (empty) empty.style.display = 'flex';
        return;
      }

      if (grid) {
        grid.style.display = 'grid';
        grid.innerHTML = '';
        classrooms.forEach(cls => {
          const card = _renderCard(cls);
          card.querySelector('.btn-students')?.addEventListener('click', () => {
            window.TeacherTabs.activate('students');
            document.getElementById('students-class-select').value = cls.id;
            document.getElementById('students-class-select').dispatchEvent(new Event('change'));
          });
          card.querySelector('.btn-assignments')?.addEventListener('click', () => {
            window.TeacherTabs.activate('assignments');
            document.getElementById('assignments-class-select').value = cls.id;
            document.getElementById('assignments-class-select').dispatchEvent(new Event('change'));
          });
          card.querySelector('.btn-edit')?.addEventListener('click', () => _openModal(cls));
          card.querySelector('.btn-archive')?.addEventListener('click', () => _archiveClassroom(cls.id, cls.name));
          grid.appendChild(card);
        });
      }
    } catch (err) {
      if (loading) loading.style.display = 'none';
      _notify('error', err.message);
    }
  }

  function _populateClassSelects(classrooms) {
    const selects = ['students-class-select', 'assignments-class-select', 'overview-class-select'];
    selects.forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const current = sel.value;
      const first = sel.options[0];
      sel.innerHTML = '';
      sel.appendChild(first);
      classrooms.forEach(cls => {
        const opt = document.createElement('option');
        opt.value = cls.id;
        opt.textContent = cls.name;
        sel.appendChild(opt);
      });
      if (current) sel.value = current;
    });
  }

  async function _archiveClassroom(id, name) {
    if (!confirm(`Archiver la classe "${name}" ?`)) return;
    try {
      await window.TeacherAPI.archiveClassroom(id);
      _notify('success', `Classe "${name}" archivée.`);
      render();
    } catch (err) {
      _notify('error', err.message);
    }
  }

  // ── Modal ─────────────────────────────────────────────────────────────────

  let _step = 1;
  let _createdId = null;

  function _openModal(editData) {
    const modal = document.getElementById('classroom-modal');
    if (!modal) return;
    _step = 1;
    _createdId = null;
    _editId = editData?.id || null;

    document.getElementById('classroom-name-input').value = editData?.name || '';
    document.getElementById('classroom-desc-input').value = editData?.description || '';
    document.getElementById('classroom-import-toggle').checked = false;

    /* Hide CSV step option when editing */
    const importToggleGroup = document.getElementById('classroom-import-toggle')?.closest('.form-group');
    if (importToggleGroup) importToggleGroup.style.display = _editId ? 'none' : '';

    document.getElementById('step-classroom-info').classList.add('active');
    document.getElementById('step-csv-import').classList.remove('active');
    document.getElementById('classroom-modal-back').style.display = 'none';

    const title = document.getElementById('classroom-modal-title');
    if (title) title.textContent = _editId ? t('classroom.edit') : t('classroom.create_title');

    const submitSpan = document.getElementById('classroom-modal-submit').querySelector('span');
    if (submitSpan) submitSpan.textContent = _editId ? t('common.save') : t('classroom.save');

    modal.style.display = 'flex';
    document.getElementById('classroom-name-input').focus();
  }

  function _closeModal() {
    const modal = document.getElementById('classroom-modal');
    if (modal) modal.style.display = 'none';
    _editId = null;
  }

  async function _submitModal() {
    const name = document.getElementById('classroom-name-input').value.trim();
    if (!name) { _notify('error', 'Le nom de la classe est requis'); return; }
    const desc = document.getElementById('classroom-desc-input').value.trim();

    if (_editId) {
      /* ── Edit mode ── */
      try {
        await window.TeacherAPI.updateClassroom(_editId, { name, description: desc || null });
        _notify('success', `Classe "${name}" modifiée.`);
        _closeModal();
        render();
      } catch (err) {
        _notify('error', err.message);
      }
      return;
    }

    /* ── Create mode ── */
    if (_step === 1) {
      const wantsCSV = document.getElementById('classroom-import-toggle').checked;
      try {
        const cls = await window.TeacherAPI.createClassroom({ name, description: desc || null });
        _createdId = cls.id;
        _notify('success', `Classe "${name}" créée !`);

        if (wantsCSV) {
          _step = 2;
          document.getElementById('step-classroom-info').classList.remove('active');
          document.getElementById('step-csv-import').classList.add('active');
          document.getElementById('classroom-modal-back').style.display = 'inline-flex';
          const submitSpan = document.getElementById('classroom-modal-submit').querySelector('span');
          if (submitSpan) submitSpan.textContent = t('common.import') || 'Importer';
          return;
        }
        _closeModal();
        render();
      } catch (err) {
        _notify('error', err.message);
      }
    } else if (_step === 2 && _createdId) {
      const file = document.getElementById('classroom-csv-input').files[0];
      if (!file) { _closeModal(); render(); return; }
      try {
        const result = await window.TeacherAPI.importStudentsCSV(_createdId, file);
        const s = result.summary;
        _notify('success', `Import : ${s.enrolled} inscrits, ${s.errors} erreurs`);
      } catch (err) {
        _notify('error', err.message);
      }
      _closeModal();
      render();
    }
  }

  function init() {
    document.getElementById('new-classroom-btn')?.addEventListener('click', () => _openModal(null));
    document.getElementById('classroom-modal-cancel')?.addEventListener('click', _closeModal);
    document.getElementById('classroom-modal-back')?.addEventListener('click', () => {
      _step = 1;
      document.getElementById('step-classroom-info').classList.add('active');
      document.getElementById('step-csv-import').classList.remove('active');
      document.getElementById('classroom-modal-back').style.display = 'none';
    });
    document.getElementById('classroom-modal-submit')?.addEventListener('click', _submitModal);
    document.querySelectorAll('#classroom-modal .modal-close').forEach(btn => btn.addEventListener('click', _closeModal));

    document.getElementById('classroom-modal')?.addEventListener('click', e => {
      if (e.target === document.getElementById('classroom-modal')) _closeModal();
    });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') _closeModal();
    });

    render();
  }

  return { init, render };
})();
