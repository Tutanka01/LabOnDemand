/* Point d'entrée du dashboard enseignant */
(function () {
  'use strict';

  // ── Auth check ─────────────────────────────────────────────────────────────
  async function checkAuth() {
    try {
      const r = await fetch('/api/v1/auth/check-role', { credentials: 'include' });
      if (!r.ok) throw new Error('unauthenticated');
      const data = await r.json();

      const role = data.role;

      // Redirect non-teacher/admin roles
      if (!data.can_manage_classrooms) {
        window.location.href = 'index.html';
        return false;
      }

      // Show admin nav items
      if (role === 'admin') {
        document.querySelectorAll('.admin-only').forEach(el => el.style.removeProperty('display'));
      }

      // Update user display
      const usernameEl = document.getElementById('current-username');
      const roleEl = document.getElementById('user-role');
      if (usernameEl) {
        // Fetch actual username from session
        const meR = await fetch('/api/v1/auth/me', { credentials: 'include' }).catch(() => null);
        if (meR && meR.ok) {
          const me = await meR.json();
          usernameEl.textContent = me.username || '';
          if (roleEl) roleEl.innerHTML = `<span class="role-badge">${me.role}</span>`;
        }
      }

      return true;
    } catch {
      window.location.href = 'login.html';
      return false;
    }
  }

  // ── Tab system ─────────────────────────────────────────────────────────────
  const VALID_TABS = ['classrooms', 'students', 'assignments', 'overview'];

  window.TeacherTabs = {
    activate(tabId) {
      if (!VALID_TABS.includes(tabId)) return;
      document.querySelectorAll('.tab-btn').forEach(btn => {
        const active = btn.dataset.tab === tabId;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', active);
      });
      document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === 'tab-' + tabId);
      });
      history.replaceState(null, '', '#' + tabId);

      if (tabId === 'overview') {
        window.TeacherOverview.render();
        window.TeacherOverview.startAutoRefresh();
      } else {
        window.TeacherOverview.stopAutoRefresh();
      }
    },
  };

  // ── Sync class selects ─────────────────────────────────────────────────────
  function _syncClassSelects() {
    ['students-class-select', 'assignments-class-select'].forEach(id => {
      const sel = document.getElementById(id);
      sel?.addEventListener('change', e => {
        window.TeacherState.setSelectedId(e.target.value);
      });
    });
  }

  // ── Logout ─────────────────────────────────────────────────────────────────
  function _initLogout() {
    document.getElementById('logout-btn')?.addEventListener('click', async () => {
      await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {});
      window.location.href = 'login.html';
    });
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  async function init() {
    const ok = await checkAuth();
    if (!ok) return;

    // Wire tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => window.TeacherTabs.activate(btn.dataset.tab));
    });

    // Check if i18n is already loaded
    const startModules = () => {
      window.TeacherClassrooms.init();
      window.TeacherStudents.init();
      window.TeacherAssignments.init();
      window.TeacherOverview.init();
      _syncClassSelects();
      _initLogout();

      // Deep-link via hash
      const hash = location.hash.replace('#', '');
      if (VALID_TABS.includes(hash)) {
        window.TeacherTabs.activate(hash);
      }
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', startModules);
    } else {
      startModules();
    }
  }

  // Wait for i18n to be ready, then boot
  document.addEventListener('i18n-loaded', init, { once: true });
  // Fallback if i18n already fired
  if (window._i18nLoaded) init();
})();
