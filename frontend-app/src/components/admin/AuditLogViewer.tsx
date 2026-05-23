import { useQuery } from "@tanstack/react-query";
import { Download, Eye, RefreshCw, Search } from "lucide-react";
import { useState } from "react";
import type { AuditLogEntry } from "../../types/api";
import { exportAuditLogs, getAuditLogs, getAuditLogStats } from "../../lib/api";
import { fullDate } from "../../lib/format";
import { Button, EmptyState, ErrorState, LoadingState, MetricCard, Pagination, SearchBox, StatusBadge, showToast } from "../ui";

export function AuditLogViewer() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [username, setUsername] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selectedEntry, setSelectedEntry] = useState<AuditLogEntry | null>(null);

  const pageSize = 50;

  const stats = useQuery({
    queryKey: ["audit-stats"],
    queryFn: getAuditLogStats,
    staleTime: 60_000,
  });

  const logs = useQuery({
    queryKey: ["audit-logs", { page, pageSize, search, category, level, username, dateFrom, dateTo }],
    queryFn: () =>
      getAuditLogs({
        page,
        page_size: pageSize,
        search: search || undefined,
        category: category || undefined,
        level: level || undefined,
        username: username || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      }),
  });

  const totalPages = logs.data?.total ? Math.ceil(logs.data.total / pageSize) : 1;

  const handleExport = async () => {
    try {
      const data = await exportAuditLogs({
        search: search || undefined,
        category: category || undefined,
        level: level || undefined,
        username: username || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("Export termine", "success");
    } catch {
      showToast("Erreur d'export", "error");
    }
  };

  const levelBadge = (l?: string) => {
    if (l === "ERROR" || l === "error") return <span className="badge red">{l}</span>;
    if (l === "WARNING" || l === "warning") return <span className="badge amber">{l}</span>;
    if (l === "INFO" || l === "info") return <span className="badge blue">{l}</span>;
    return <span className="badge">{l}</span>;
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      {stats.data ? (
        <section className="metric-grid">
          <MetricCard label="Total" value={stats.data.total || 0} icon={<Eye size={18} />} />
          <MetricCard
            label="7 derniers jours"
            value={stats.data.last_7_days ? Object.values(stats.data.last_7_days).reduce((a, b) => a + b, 0) : 0}
            icon={<Eye size={18} />}
          />
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <h2>Filtres</h2>
          <Button onClick={handleExport}><Download size={16} /> Export JSON</Button>
        </div>
        <div className="actions-row" style={{ flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
          <SearchBox placeholder="Recherche texte..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <input
            placeholder="Categorie"
            value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(1); }}
            style={{ minHeight: 38, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8, width: 140 }}
          />
          <select value={level} onChange={(e) => { setLevel(e.target.value); setPage(1); }} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }}>
            <option value="">Tous niveaux</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <input
            placeholder="Utilisateur"
            value={username}
            onChange={(e) => { setUsername(e.target.value); setPage(1); }}
            style={{ minHeight: 38, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8, width: 140 }}
          />
          <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }} />
          <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }} />
          <Button onClick={() => { setSearch(""); setCategory(""); setLevel(""); setUsername(""); setDateFrom(""); setDateTo(""); setPage(1); }}>
            <RefreshCw size={16} />
          </Button>
        </div>

        {logs.isLoading ? <LoadingState /> : null}
        {logs.error ? <ErrorState>Impossible de charger les logs.</ErrorState> : null}

        {(logs.data?.items || []).length ? (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Niveau</th>
                    <th>Evenement</th>
                    <th>Categorie</th>
                    <th>Utilisateur</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(logs.data?.items || []).map((entry, i) => (
                    <tr key={entry.id || i}>
                      <td>{fullDate(entry.timestamp)}</td>
                      <td>{levelBadge(entry.level)}</td>
                      <td>{entry.event}</td>
                      <td>{entry.category}</td>
                      <td>{entry.username || "N/A"}</td>
                      <td>
                        <Button onClick={() => setSelectedEntry(entry)}>
                          <Eye size={14} />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} totalPages={totalPages} onChange={setPage} />
          </>
        ) : null}
      </section>

      {selectedEntry ? (
        <section className="panel">
          <div className="section-head">
            <h2>Detail: {selectedEntry.event}</h2>
            <Button onClick={() => setSelectedEntry(null)}>Fermer</Button>
          </div>
          <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: "0.85rem" }}>
            {JSON.stringify(selectedEntry, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}
