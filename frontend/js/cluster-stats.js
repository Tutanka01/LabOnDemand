// UI des statistiques du cluster (admin)

document.addEventListener('DOMContentLoaded', () => {
  const clusterStatsEl = document.getElementById('cluster-stats');
  const nodesStatsEl = document.getElementById('nodes-stats');
  const refreshBtn = document.getElementById('refresh-stats-btn');

  if (!clusterStatsEl || !nodesStatsEl) return; // autre page

  async function fetchStats() {
    try {
      const res = await fetch('/api/v1/k8s/stats/cluster', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include'
      });
      if (!res.ok) {
        throw new Error('Impossible de charger les statistiques du cluster');
      }
      const data = await res.json();
      renderCluster(data);
      renderNodes(data);
    } catch (e) {
      clusterStatsEl.innerHTML = `<div class="notification error" style="display:block"><i class="fas fa-exclamation-circle"></i> ${e.message}</div>`;
      nodesStatsEl.innerHTML = '';
    }
  }

  function renderCluster(data) {
    const c = data.cluster || {};
    clusterStatsEl.innerHTML = `
      <table class="users-table">
        <thead>
          <tr>
            <th><i class="fas fa-server"></i> Nœuds</th>
            <th><i class="fas fa-layer-group"></i> Déploiements</th>
            <th><i class="fas fa-check-circle"></i> Déploiements prêts</th>
            <th><i class="fas fa-cubes"></i> Apps LabOnDemand</th>
            <th><i class="fas fa-cube"></i> Pods</th>
            <th><i class="fas fa-sitemap"></i> Namespaces</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>${c.nodes ?? '-'}</td>
            <td>${c.deployments ?? '-'}</td>
            <td>${c.deployments_ready ?? '-'}</td>
            <td>${c.lab_apps ?? '-'}</td>
            <td>${c.pods ?? '-'}</td>
            <td>${c.namespaces ?? '-'}</td>
          </tr>
        </tbody>
      </table>
    `;
  }

  function pctBar(percent) {
    const p = Math.max(0, Math.min(100, Number(percent) || 0));
    const color = p < 70 ? '#10b981' : p < 90 ? '#f59e0b' : '#ef4444';
    return `
      <div style="background:#f1f5f9;border-radius:6px;overflow:hidden;height:10px;width:120px;">
        <div style="width:${p}%;height:100%;background:${color};"></div>
      </div>
      <div style="font-size:0.85rem;color:#475569;margin-top:4px;">${p}%</div>
    `;
  }

  function renderNodes(data) {
    const nodes = data.nodes || [];
    if (!nodes.length) {
      nodesStatsEl.innerHTML = `<div class="notification" style="display:block"><i class="fas fa-info-circle"></i> Aucune information de nœud disponible.</div>`;
      return;
    }

    const rows = nodes.map(n => `
      <tr>
        <td>
          <div style="font-weight:600;color:#0f172a">${n.name}</div>
          <div style="font-size:0.8rem;color:${n.ready ? '#16a34a' : '#b91c1c'}">
            ${n.ready ? '<i class="fas fa-circle" style="font-size:8px"></i> Ready' : '<i class="fas fa-circle" style="font-size:8px"></i> NotReady'}
          </div>
        </td>
        <td>${(n.roles || []).join(', ')}</td>
        <td>${n.kubelet_version || '-'}</td>
        <td>${n.pods}</td>
        <td>
          <div><strong>${n.cpu.usage_m}</strong> m / ${n.cpu.allocatable_m} m</div>
          ${pctBar(n.cpu.usage_pct)}
        </td>
        <td>
          <div><strong>${n.memory.usage_mi}</strong> Mi / ${n.memory.allocatable_mi} Mi</div>
          ${pctBar(n.memory.usage_pct)}
        </td>
      </tr>
    `).join('');

    nodesStatsEl.innerHTML = `
      <table class="users-table">
        <thead>
          <tr>
            <th>Nœud</th>
            <th>Rôles</th>
            <th>Kubelet</th>
            <th>Pods</th>
            <th>CPU</th>
            <th>Mémoire</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    `;
  }

  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => fetchStats());
  }

  // Chargement initial
  fetchStats();
  // Auto-refresh léger toutes les 30s
  setInterval(fetchStats, 30000);
});
