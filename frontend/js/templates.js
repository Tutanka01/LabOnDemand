// Gestion des templates (CRUD) avec formulaire modale

(function() {
  const listEl = document.getElementById('templates-list');
  const addBtn = document.getElementById('add-template-btn');
  const modal = document.getElementById('template-modal');
  const closeBtns = modal ? modal.querySelectorAll('.close-template-modal') : [];
  const form = document.getElementById('template-form');
  const titleEl = document.getElementById('template-modal-title');

  const idEl = document.getElementById('template-id');
  const keyEl = document.getElementById('tpl-key');
  const nameEl = document.getElementById('tpl-name');
  const descEl = document.getElementById('tpl-description');
  const iconEl = document.getElementById('tpl-icon');
  const typeEl = document.getElementById('tpl-type');
  const imageEl = document.getElementById('tpl-image');
  const portEl = document.getElementById('tpl-port');
  const svcTypeEl = document.getElementById('tpl-service-type');
  const tagsEl = document.getElementById('tpl-tags');
  const activeEl = document.getElementById('tpl-active');

  if (!listEl || !addBtn) return; // ne pas exécuter si pas sur la page

  async function populateRuntimes() {
    try {
      const resp = await fetch('/api/v1/k8s/runtime-configs', { credentials: 'include' });
      const ct = resp.headers.get('content-type') || '';
      const rows = ct.includes('application/json') ? await resp.json() : [];
      if (Array.isArray(rows)) {
        const opts = [
          '<option value="custom">Custom</option>',
          ...rows.filter(rc => rc.active).map(rc => `<option value="${rc.key}">${rc.key}</option>`)
        ];
        typeEl.innerHTML = opts.join('');
      }
    } catch (e) {
      // ignorer: laisser les options statiques si l'appel échoue
    }
  }

  function openModal(editing = false, data = null) {
    titleEl.innerHTML = editing ? '<i class="fas fa-pen"></i> Modifier le template' : '<i class="fas fa-th-large"></i> Nouveau template';
    form.reset();
    idEl.value = '';
    keyEl.disabled = editing; // clé non modifiable en édition

    // Peupler dynamiquement les runtimes disponibles à chaque ouverture
    populateRuntimes();

    if (editing && data) {
      idEl.value = data.id;
      keyEl.value = data.key;
      nameEl.value = data.name;
      descEl.value = data.description || '';
      iconEl.value = data.icon || '';
      typeEl.value = data.deployment_type || 'custom';
      imageEl.value = data.default_image || '';
      portEl.value = data.default_port || '';
      svcTypeEl.value = data.default_service_type || 'NodePort';
      if (tagsEl) tagsEl.value = Array.isArray(data.tags) ? data.tags.join(', ') : '';
      activeEl.checked = !!data.active;
    }

    modal.classList.add('show');
  }

  function closeModal() {
    modal.classList.remove('show');
  }

  async function api(path, options = {}) {
    const resp = await fetch(path, { credentials: 'include', ...options });
    let payload = null;
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('application/json')) payload = await resp.json();
    if (!resp.ok) {
      const msg = (payload && (payload.detail || payload.message)) || `HTTP ${resp.status}`;
      throw new Error(msg);
    }
    return payload;
  }

  async function refreshTemplates() {
    try {
      const templates = await api('/api/v1/k8s/templates/all');
      listEl.innerHTML = `
        <table class="users-table">
          <thead>
            <tr>
              <th>ID</th><th>Clé</th><th>Nom</th><th>Runtime</th><th>Image</th><th>Port</th><th>Accès</th><th>Tags</th><th>Actif</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${templates.map(t => `
              <tr>
                <td>${t.id}</td>
                <td>${t.key}</td>
                <td>${t.name}</td>
                <td>${t.deployment_type}</td>
                <td>${t.default_image || '-'}</td>
                <td>${t.default_port ?? '-'}</td>
                <td>${t.default_service_type || '-'}</td>
                <td>${Array.isArray(t.tags) && t.tags.length ? t.tags.join(', ') : '-'}</td>
                <td><span class="status-badge ${t.active ? 'active' : 'inactive'}">${t.active ? 'Actif' : 'Inactif'}</span></td>
                <td class="action-icons">
                  <button class="edit-tpl" data-id="${t.id}"><i class="fas fa-edit"></i></button>
                  <button class="del-tpl" data-id="${t.id}"><i class="fas fa-trash-alt"></i></button>
                </td>
              </tr>`).join('')}
          </tbody>
        </table>`;

      // Bind actions
      listEl.querySelectorAll('.edit-tpl').forEach(btn => btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        const row = btn.closest('tr').children;
        const current = {
          id,
          key: row[1].textContent,
          name: row[2].textContent,
          deployment_type: row[3].textContent,
          default_image: row[4].textContent === '-' ? '' : row[4].textContent,
          default_port: row[5].textContent === '-' ? '' : parseInt(row[5].textContent),
          default_service_type: row[6].textContent,
          tags: row[7].textContent === '-' ? [] : row[7].textContent.split(',').map(s => s.trim()),
          active: row[8].querySelector('.status-badge').classList.contains('active')
        };
        openModal(true, current);
      }));

      listEl.querySelectorAll('.del-tpl').forEach(btn => btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!confirm('Supprimer ce template ?')) return;
        try {
          await api(`/api/v1/k8s/templates/${id}`, { method: 'DELETE' });
          await refreshTemplates();
        } catch (e) {
          showInlineError(e.message);
        }
      }));
    } catch (e) {
      showInlineError(e.message);
    }
  }

  function showInlineError(message) {
    listEl.innerHTML = `<div class="notification error" style="display:flex"><i class="fas fa-exclamation-circle"></i> ${message}</div>`;
  }

  addBtn.addEventListener('click', () => openModal(false));
  closeBtns.forEach(btn => btn.addEventListener('click', closeModal));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = idEl.value || null;
    const body = {
      key: keyEl.value.trim(),
      name: nameEl.value.trim(),
      description: descEl.value.trim() || null,
      icon: iconEl.value.trim() || null,
      deployment_type: typeEl.value,
      default_image: imageEl.value.trim() || null,
      default_port: portEl.value ? parseInt(portEl.value, 10) : null,
      default_service_type: svcTypeEl.value,
      tags: tagsEl && tagsEl.value ? tagsEl.value.split(',').map(s => s.trim()).filter(Boolean) : [],
      active: activeEl.checked
    };

    try {
      if (id) {
        // Update (clé non modifiable)
        const payload = { ...body };
        delete payload.key;
        await api(`/api/v1/k8s/templates/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        await api('/api/v1/k8s/templates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
      }
      closeModal();
      await refreshTemplates();
    } catch (e) {
      // Afficher une erreur utilisateur dans le formulaire
      const err = document.createElement('div');
      err.className = 'notification error';
      err.style.display = 'flex';
      err.innerHTML = `<i class="fas fa-exclamation-circle"></i> <span>${e.message}</span>`;
      form.prepend(err);
      setTimeout(() => err.remove(), 5000);
    }
  });

  // Initial load
  refreshTemplates();
})();
