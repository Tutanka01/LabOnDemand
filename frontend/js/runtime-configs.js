// Gestion des Runtime Configs (CRUD) + toggle "Accessible aux étudiants"
(function() {
  const listEl = document.getElementById('runtime-configs-list');
  const addBtn = document.getElementById('add-rc-btn');
  if (!listEl || !addBtn) return;

  // Modal dynamique (créé à la volée)
  let modal; let form; let titleEl;

  function ensureModal() {
    if (modal) return;
    modal = document.createElement('div');
    modal.id = 'rc-modal';
    modal.className = 'modal';
    modal.innerHTML = `
      <div class="modal-content">
        <div class="modal-header">
          <h2 id="rc-modal-title"><i class="fas fa-cogs"></i> Nouveau runtime</h2>
          <button class="close-rc-modal"><i class="fas fa-times"></i></button>
        </div>
        <div class="modal-body">
          <form id="rc-form">
            <input type="hidden" id="rc-id">
            <div class="form-row">
              <div class="form-group">
                <label for="rc-key"><i class="fas fa-key"></i> Clé</label>
                <input type="text" id="rc-key" required minlength="2" maxlength="50" placeholder="vscode">
                <small>Identifiant unique (ex: vscode, jupyter)</small>
              </div>
              <div class="form-group">
                <label for="rc-image"><i class="fas fa-box"></i> Image par défaut</label>
                <input type="text" id="rc-image" maxlength="200" placeholder="ex: tutanka01/k8s:vscode">
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="rc-target-port"><i class="fas fa-plug"></i> Port cible</label>
                <input type="number" id="rc-target-port" min="1" max="65535" placeholder="ex: 8080">
              </div>
              <div class="form-group">
                <label for="rc-service-type"><i class="fas fa-network-wired"></i> Mode d’accès</label>
                <select id="rc-service-type">
                  <option value="ClusterIP">ClusterIP</option>
                  <option value="NodePort" selected>NodePort</option>
                  <option value="LoadBalancer">LoadBalancer</option>
                </select>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="rc-min-cpu-req"><i class="fas fa-microchip"></i> CPU request min</label>
                <input type="text" id="rc-min-cpu-req" placeholder="ex: 250m">
              </div>
              <div class="form-group">
                <label for="rc-min-mem-req"><i class="fas fa-memory"></i> RAM request min</label>
                <input type="text" id="rc-min-mem-req" placeholder="ex: 512Mi">
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="rc-min-cpu-limit"><i class="fas fa-gauge-high"></i> CPU limit min</label>
                <input type="text" id="rc-min-cpu-limit" placeholder="ex: 500m">
              </div>
              <div class="form-group">
                <label for="rc-min-mem-limit"><i class="fas fa-hard-drive"></i> RAM limit min</label>
                <input type="text" id="rc-min-mem-limit" placeholder="ex: 1Gi">
              </div>
            </div>
            <div class="form-row">
              <div class="form-group checkbox-group">
                <input type="checkbox" id="rc-allowed" checked>
                <label for="rc-allowed">Accessible aux étudiants</label>
              </div>
              <div class="form-group checkbox-group">
                <input type="checkbox" id="rc-active" checked>
                <label for="rc-active">Actif</label>
              </div>
            </div>
            <div class="form-actions">
              <button type="button" class="btn-cancel close-rc-modal">Annuler</button>
              <button type="submit" class="btn-save">Enregistrer</button>
            </div>
          </form>
        </div>
      </div>`;
    document.body.appendChild(modal);
    form = modal.querySelector('#rc-form');
    titleEl = modal.querySelector('#rc-modal-title');
    modal.querySelectorAll('.close-rc-modal').forEach(btn => btn.addEventListener('click', closeModal));
  }

  function openModal(editing = false, data = null) {
    ensureModal();
    form.reset();
    titleEl.innerHTML = editing ? '<i class="fas fa-pen"></i> Modifier le runtime' : '<i class="fas fa-cogs"></i> Nouveau runtime';
    modal.classList.add('show');
    const idEl = document.getElementById('rc-id');
    const keyEl = document.getElementById('rc-key');
    keyEl.disabled = editing;
    if (editing && data) {
      idEl.value = data.id;
      keyEl.value = data.key;
      document.getElementById('rc-image').value = data.default_image || '';
      document.getElementById('rc-target-port').value = data.target_port ?? '';
      document.getElementById('rc-service-type').value = data.default_service_type || 'NodePort';
      document.getElementById('rc-min-cpu-req').value = data.min_cpu_request || '';
      document.getElementById('rc-min-mem-req').value = data.min_memory_request || '';
      document.getElementById('rc-min-cpu-limit').value = data.min_cpu_limit || '';
      document.getElementById('rc-min-mem-limit').value = data.min_memory_limit || '';
      document.getElementById('rc-allowed').checked = !!data.allowed_for_students;
      document.getElementById('rc-active').checked = !!data.active;
    } else {
      idEl.value = '';
      keyEl.value = '';
    }
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

  function rowActions(rc) {
    return `
      <button class="edit-rc" data-id="${rc.id}"><i class="fas fa-edit"></i></button>
      <button class="del-rc" data-id="${rc.id}"><i class="fas fa-trash-alt"></i></button>
      <label class="toggle">
        <input type="checkbox" class="toggle-allowed" data-id="${rc.id}" ${rc.allowed_for_students ? 'checked' : ''}>
        <span>Étudiants</span>
      </label>
    `;
  }

  async function refreshRCs() {
    try {
      const rows = await api('/api/v1/k8s/runtime-configs');
      listEl.innerHTML = `
        <table class="users-table">
          <thead>
            <tr>
              <th>ID</th><th>Clé</th><th>Image</th><th>Port cible</th><th>Accès</th><th>Min CPU</th><th>Min RAM</th><th>Min CPU Lim</th><th>Min RAM Lim</th><th>Actif</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(rc => `
              <tr>
                <td>${rc.id}</td>
                <td>${rc.key}</td>
                <td>${rc.default_image || '-'}</td>
                <td>${rc.target_port ?? '-'}</td>
                <td>${rc.default_service_type || '-'}</td>
                <td>${rc.min_cpu_request || '-'}</td>
                <td>${rc.min_memory_request || '-'}</td>
                <td>${rc.min_cpu_limit || '-'}</td>
                <td>${rc.min_memory_limit || '-'}</td>
                <td><span class="status-badge ${rc.active ? 'active' : 'inactive'}">${rc.active ? 'Actif' : 'Inactif'}</span></td>
                <td class="action-icons">${rowActions(rc)}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;

      // Bind edits
      listEl.querySelectorAll('.edit-rc').forEach(btn => btn.addEventListener('click', () => {
        const id = parseInt(btn.getAttribute('data-id'), 10);
        const row = btn.closest('tr').children;
        const rc = {
          id,
          key: row[1].textContent,
          default_image: row[2].textContent === '-' ? '' : row[2].textContent,
          target_port: row[3].textContent === '-' ? null : parseInt(row[3].textContent, 10),
          default_service_type: row[4].textContent,
          min_cpu_request: row[5].textContent === '-' ? '' : row[5].textContent,
          min_memory_request: row[6].textContent === '-' ? '' : row[6].textContent,
          min_cpu_limit: row[7].textContent === '-' ? '' : row[7].textContent,
          min_memory_limit: row[8].textContent === '-' ? '' : row[8].textContent,
          active: row[9].querySelector('.status-badge').classList.contains('active'),
          // allowed_for_students est géré via le toggle; on le récupère depuis l'attribut du checkbox si présent
          allowed_for_students: row[10]?.querySelector?.('.toggle-allowed')?.checked ?? true
        };
        openModal(true, rc);
      }));

      listEl.querySelectorAll('.del-rc').forEach(btn => btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!confirm('Supprimer ce runtime ?')) return;
        await api(`/api/v1/k8s/runtime-configs/${id}`, { method: 'DELETE' });
        await refreshRCs();
      }));

      listEl.querySelectorAll('.toggle-allowed').forEach(cb => cb.addEventListener('change', async (e) => {
        const id = e.currentTarget.getAttribute('data-id');
        const allowed = e.currentTarget.checked;
        try {
          await api(`/api/v1/k8s/runtime-configs/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ allowed_for_students: allowed })
          });
        } catch (err) {
          alert('Erreur: ' + err.message);
          e.currentTarget.checked = !allowed; // revert
        }
      }));
    } catch (e) {
      listEl.innerHTML = `<div class="notification error" style="display:flex"><i class="fas fa-exclamation-circle"></i> ${e.message}</div>`;
    }
  }

  addBtn.addEventListener('click', () => openModal(false));

  document.addEventListener('click', (e) => {
    if (e.target.closest && e.target.closest('.close-rc-modal')) closeModal();
  });

  document.addEventListener('submit', async (e) => {
    if (e.target && e.target.id === 'rc-form') {
      e.preventDefault();
      const id = document.getElementById('rc-id').value || null;
      const body = {
        key: document.getElementById('rc-key').value.trim(),
        default_image: document.getElementById('rc-image').value.trim() || null,
        target_port: document.getElementById('rc-target-port').value ? parseInt(document.getElementById('rc-target-port').value, 10) : null,
        default_service_type: document.getElementById('rc-service-type').value,
        min_cpu_request: document.getElementById('rc-min-cpu-req').value.trim() || null,
        min_memory_request: document.getElementById('rc-min-mem-req').value.trim() || null,
        min_cpu_limit: document.getElementById('rc-min-cpu-limit').value.trim() || null,
        min_memory_limit: document.getElementById('rc-min-mem-limit').value.trim() || null,
        allowed_for_students: document.getElementById('rc-allowed').checked,
        active: document.getElementById('rc-active').checked
      };

      try {
        if (id) {
          // Update: on ne peut pas changer la clé
          const payload = { ...body };
          delete payload.key;
          await api(`/api/v1/k8s/runtime-configs/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        } else {
          await api('/api/v1/k8s/runtime-configs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
          });
        }
        closeModal();
        await refreshRCs();
      } catch (err) {
        alert('Erreur: ' + err.message);
      }
    }
  });

  // Initial load
  refreshRCs();
})();
